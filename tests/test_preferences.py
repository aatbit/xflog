import asyncio
import json
import sqlite3
from dataclasses import replace

import httpx
import pytest

from xflog.app import create_app
from xflog.collector import DEFAULT_SELECTION, Collector
from xflog.config import Config
from xflog.errors import SetupError
from xflog.storage import Store
from xflog.transport import XClient


class ActivityStream(httpx.AsyncByteStream):
    def __init__(self):
        self.queue = asyncio.Queue()
        self.opened = asyncio.Event()
        self.closed = 0

    async def __aiter__(self):
        self.opened.set()
        while True:
            chunk = await self.queue.get()
            try:
                yield chunk
            finally:
                self.queue.task_done()

    async def aclose(self):
        self.closed += 1

    async def send(self, kind, identity):
        event = {
            "event_type": kind,
            "event_uuid": identity,
            "payload": {"source": {"id": "222"}, "target": {"id": "111"}},
        }
        await self.queue.put(json.dumps(event).encode() + b"\n")
        await asyncio.wait_for(self.queue.join(), timeout=2)


class ActivityProvider:
    def __init__(self):
        self.body = ActivityStream()
        self.streams = 0
        self.requests = []
        self.remote = {}
        self.reject_paid = False
        self.block_kind = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.reject_blocked = False
        self.lost_delete_reply = False

    async def __call__(self, request):
        if request.url.path.endswith("/stream"):
            self.streams += 1
            return httpx.Response(200, stream=self.body)
        self.requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"data": list(self.remote.values())})
        if request.method == "POST":
            data = json.loads(request.content)
            if self.reject_paid and data["event_type"].startswith("subscriptions."):
                return httpx.Response(403)
            identity = data["event_type"].replace(".", "-")
            self.remote[identity] = {"subscription_id": identity, **data}
            if data["event_type"] == self.block_kind:
                self.entered.set()
                await self.release.wait()
                if self.reject_blocked:
                    return httpx.Response(401)
            return httpx.Response(200, json={"data": self.remote[identity]})
        if request.method == "DELETE":
            item = self.remote.pop(request.url.path.rsplit("/", 1)[-1], None)
            if item is None:
                return httpx.Response(404)
            if self.lost_delete_reply:
                self.lost_delete_reply = False
                return httpx.Response(500)
            return httpx.Response(200, json={"data": {"deleted": True}})
        raise AssertionError("Unexpected mocked request")


@pytest.fixture
async def listener(tmp_path):
    config = Config(
        tmp_path / "history.sqlite3",
        app_bearer="fake-app-secret",
        user_id="111",
        user_token="fake-user-secret",
    )
    provider = ActivityProvider()
    store = Store(config.database)
    await store.open()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        collector = Collector(store, XClient(config, http))
        await collector.initialize()
        await collector.start()
        await asyncio.wait_for(provider.body.opened.wait(), timeout=2)
        try:
            yield collector, provider
        finally:
            await collector.shutdown()
            await store.close()


async def test_notification_save_keeps_same_stream_and_receives_next_event(listener):
    collector, provider = listener
    task = collector.task
    requests = list(provider.requests)
    await collector.save_preferences({**DEFAULT_SELECTION, "notifications": True})
    await provider.body.send("follow.follow", "after-save")
    assert collector.task is task and not task.done()
    assert provider.streams == 1 and provider.body.closed == 0
    assert provider.requests == requests
    assert await collector.store.setting("tracking")
    assert not await collector.store.restart_blocked()
    assert collector.notifications == 1


async def test_live_category_changes_reconcile_without_reconnecting_and_filter_new_choices(
    listener,
):
    collector, provider = listener
    task = collector.task
    await provider.body.send("follow.follow", "before")
    selection = {**DEFAULT_SELECTION, "followers": False, "subscriptions": True}
    result = await collector.save_preferences(selection)
    assert "continues" in result["message"]
    assert collector.task is task and provider.streams == 1
    assert set(provider.remote) == {"subscriptions-subscribe", "subscriptions-unsubscribe"}
    assert [method for method, _ in provider.requests[-4:]] == ["POST", "POST", "DELETE", "DELETE"]
    await provider.body.send("follow.follow", "disabled")
    await provider.body.send("subscriptions.subscribe", "enabled")
    rows = await collector.store.db.execute_fetchall(
        "SELECT event_id FROM events ORDER BY sequence"
    )
    assert [row["event_id"] for row in rows] == ["before", "enabled"]
    assert not await collector.store.gaps("111")


async def test_failed_provider_update_keeps_listener_and_reports_saved_pending_choices(listener):
    collector, provider = listener
    task = collector.task
    provider.reject_paid = True
    selection = {**DEFAULT_SELECTION, "subscriptions": True}
    result = await collector.save_preferences(selection)
    assert result["saved"] and "saved locally" in result["message"]
    assert collector.preference_warning
    assert await collector.store.setting("selection") == selection
    await provider.body.send("follow.follow", "still-listening")
    assert collector.task is task and provider.streams == 1 and collector.notifications == 1
    provider.reject_paid = False
    await collector.save_preferences(selection)
    assert not collector.preference_warning
    assert len(provider.remote) == 4


async def test_retry_recovers_a_delete_that_succeeded_remotely_without_its_reply(listener):
    collector, provider = listener
    provider.lost_delete_reply = True
    selection = {**DEFAULT_SELECTION, "followers": False, "subscriptions": True}
    await collector.save_preferences(selection)
    assert collector.preference_warning
    await collector.save_preferences(selection)
    assert not collector.preference_warning
    assert set(provider.remote) == {"subscriptions-subscribe", "subscriptions-unsubscribe"}
    assert {item["kind"] for item in await collector.store.subscriptions()} == {
        "subscriptions.subscribe",
        "subscriptions.unsubscribe",
    }
    assert provider.streams == 1


async def test_active_all_off_is_rejected_without_changing_or_pausing_listener(listener):
    collector, provider = listener
    requests = list(provider.requests)
    with pytest.raises(SetupError, match="Pause tracking first"):
        await collector.save_preferences({**DEFAULT_SELECTION, "followers": False})
    assert provider.requests == requests
    assert await collector.store.setting("selection", DEFAULT_SELECTION) == DEFAULT_SELECTION
    assert await collector.store.setting("tracking")


async def test_failed_settings_write_does_not_change_provider_or_stop_stream(listener, monkeypatch):
    collector, provider = listener
    requests = list(provider.requests)
    original = collector.store.save_setting

    async def fail_selection(key, value):
        if key == "selection":
            raise sqlite3.OperationalError("test disk failure")
        await original(key, value)

    monkeypatch.setattr(collector.store, "save_setting", fail_selection)
    with pytest.raises(sqlite3.Error):
        await collector.save_preferences({**DEFAULT_SELECTION, "subscriptions": True})
    assert provider.requests == requests
    await provider.body.send("follow.follow", "after-failed-write")
    assert collector.notifications == 1
    assert await collector.store.setting("tracking")


async def test_active_paid_selection_requires_token_before_any_mutation(listener):
    collector, provider = listener
    collector.client.config = replace(collector.client.config, user_token="")
    requests = list(provider.requests)
    with pytest.raises(SetupError, match="X_USER_ACCESS_TOKEN"):
        await collector.save_preferences({**DEFAULT_SELECTION, "subscriptions": True})
    assert provider.requests == requests
    assert await collector.store.setting("selection", DEFAULT_SELECTION) == DEFAULT_SELECTION
    assert not collector.task.done()


async def test_events_keep_arriving_while_save_waits_for_x(listener):
    collector, provider = listener
    task = collector.task
    provider.block_kind = "subscriptions.subscribe"
    saving = asyncio.create_task(
        collector.save_preferences({**DEFAULT_SELECTION, "subscriptions": True})
    )
    try:
        await asyncio.wait_for(provider.entered.wait(), timeout=2)
        assert not saving.done()
        await provider.body.send("follow.follow", "during-save")
        assert collector.notifications == 1 and collector.task is task
        provider.release.set()
        assert "continues" in (await asyncio.wait_for(saving, timeout=2))["message"]
    finally:
        provider.release.set()
        await asyncio.gather(saving, return_exceptions=True)


async def test_pause_interrupts_save_api_and_cleans_accepted_subscription(tmp_path):
    config = Config(
        tmp_path / "api.sqlite3", app_bearer="fake-app", user_id="111", user_token="fake-user"
    )
    provider = ActivityProvider()
    app = create_app(config, transport=httpx.MockTransport(provider), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=config.origin
        ) as browser,
    ):
        await browser.get("/")
        status = (await browser.get("/api/status")).json()
        headers = {"origin": config.origin, "x-xflog-csrf": status["csrf"]}
        assert (
            await browser.post("/api/start", json={"accepted_costs": True}, headers=headers)
        ).status_code == 200
        await asyncio.wait_for(provider.body.opened.wait(), timeout=2)
        provider.block_kind = "subscriptions.subscribe"
        saving = asyncio.create_task(
            browser.post(
                "/api/preferences",
                json={**DEFAULT_SELECTION, "subscriptions": True},
                headers=headers,
            )
        )
        try:
            await asyncio.wait_for(provider.entered.wait(), timeout=2)
            paused = await asyncio.wait_for(
                browser.post("/api/stop", json={}, headers=headers), timeout=2
            )
            assert paused.status_code == 200
            response = await asyncio.wait_for(saving, timeout=2)
            assert response.status_code == 200 and "stopped" in response.json()["message"]
            assert not provider.remote
            assert provider.body.closed == 1
            assert not await app.state.store.setting("tracking")
            assert await app.state.store.restart_blocked()
        finally:
            provider.release.set()
            await asyncio.gather(saving, return_exceptions=True)


async def test_listener_failure_during_save_never_claims_tracking_continues(tmp_path, monkeypatch):
    config = Config(
        tmp_path / "race.sqlite3", app_bearer="fake-app", user_id="111", user_token="fake-user"
    )
    provider = ActivityProvider()
    provider.block_kind = "follow.follow"
    provider.reject_blocked = True
    store = Store(config.database)
    await store.open()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        collector = Collector(store, XClient(config, http))
        committed = asyncio.Event()
        save_setting = store.save_setting

        async def observed(key, value):
            await save_setting(key, value)
            if key == "selection":
                committed.set()

        monkeypatch.setattr(store, "save_setting", observed)
        await collector.initialize()
        await collector.start()
        await asyncio.wait_for(provider.entered.wait(), timeout=2)
        saving = asyncio.create_task(
            collector.save_preferences({**DEFAULT_SELECTION, "subscriptions": True})
        )
        try:
            await asyncio.wait_for(committed.wait(), timeout=2)
            provider.release.set()
            response = await asyncio.wait_for(saving, timeout=2)
            assert response["saved"]
            assert "stopped" in response["message"]
            assert not await store.setting("tracking")
            assert not any(
                item["event_type"].startswith("subscriptions.") for item in provider.remote.values()
            )
        finally:
            provider.release.set()
            await collector.shutdown()
            await asyncio.gather(saving, return_exceptions=True)
            await store.close()


async def test_disconnected_save_browser_does_not_orphan_update_and_pause_can_cancel_it(listener):
    collector, provider = listener
    provider.block_kind = "subscriptions.subscribe"
    saving = asyncio.create_task(
        collector.save_preferences({**DEFAULT_SELECTION, "subscriptions": True})
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=2)
    saving.cancel()
    await asyncio.gather(saving, return_exceptions=True)
    assert collector.preference_task is not None and not collector.preference_task.done()
    await asyncio.wait_for(collector.stop(), timeout=2)
    assert not provider.remote and collector.preference_task is None
    assert not await collector.store.setting("tracking")


async def test_disconnect_at_selection_commit_does_not_lose_provider_update(listener, monkeypatch):
    collector, provider = listener
    committed = asyncio.Event()
    release = asyncio.Event()
    original = collector.store.save_setting

    async def commit_then_wait(key, value):
        await original(key, value)
        if key == "selection":
            committed.set()
            await release.wait()

    monkeypatch.setattr(collector.store, "save_setting", commit_then_wait)
    selection = {**DEFAULT_SELECTION, "subscriptions": True}
    saving = asyncio.create_task(collector.save_preferences(selection))
    try:
        await asyncio.wait_for(committed.wait(), timeout=2)
        saving.cancel()
        await asyncio.wait_for(asyncio.gather(saving, return_exceptions=True), timeout=2)
        update = collector.preference_task
        assert update is not None and not update.done()
        release.set()
        await asyncio.wait_for(update, timeout=2)
        monkeypatch.setattr(collector.store, "save_setting", original)
        await collector.save_preferences(selection)
        assert len(provider.remote) == 4
        assert not collector.preference_warning and collector.is_running()
    finally:
        release.set()
        await asyncio.gather(saving, return_exceptions=True)


async def test_pause_before_persistence_does_not_claim_unsaved_choices_are_saved(
    listener, monkeypatch
):
    collector, _ = listener
    entered = asyncio.Event()

    async def not_yet_saved(selection):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(collector, "apply_preferences", not_yet_saved)
    saving = asyncio.create_task(
        collector.save_preferences({**DEFAULT_SELECTION, "subscriptions": True})
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    await asyncio.wait_for(collector.stop(), timeout=2)
    result = await asyncio.wait_for(saving, timeout=2)
    assert not result["saved"]
    assert await collector.store.setting("selection", DEFAULT_SELECTION) == DEFAULT_SELECTION


async def test_paused_save_stays_paused_and_missing_keys_are_names_only(tmp_path):
    config = Config(tmp_path / "history.sqlite3", environment_file="/host/xflog/.env")
    app = create_app(
        config, transport=httpx.MockTransport(lambda _: pytest.fail("No X call")), mount_ui=False
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=config.origin
        ) as browser,
    ):
        await browser.get("/")
        status = (await browser.get("/api/status")).json()
        assert status["missing_settings"] == ["X_APP_BEARER_TOKEN", "X_USER_ID"]
        assert status["environment_file"] == "/host/xflog/.env"
        assert "/host/xflog/.env" in status["setup_message"]
        response = await browser.post(
            "/api/preferences",
            json={**DEFAULT_SELECTION, "subscriptions": True},
            headers={"origin": config.origin, "x-xflog-csrf": status["csrf"]},
        )
        assert response.status_code == 200
        assert "stopped" in response.json()["message"]
        status = (await browser.get("/api/status")).json()
        assert status["missing_settings"] == [
            "X_APP_BEARER_TOKEN",
            "X_USER_ID",
            "X_USER_ACCESS_TOKEN",
        ]
        assert "X_USER_ACCESS_TOKEN" in status["setup_message"]
        assert not status["tracking"] and app.state.collector.task is None


@pytest.mark.parametrize("paid", [False, True])
def test_missing_settings_do_not_expose_configured_secret_values(tmp_path, paid):
    config = Config(tmp_path / "test.sqlite3", app_bearer="fake-secret-app", user_id="111")
    assert config.missing_settings({"subscriptions": paid}) == (
        ["X_USER_ACCESS_TOKEN"] if paid else []
    )
    assert "fake-secret-app" not in config.setup_message({"subscriptions": paid})
