import asyncio
from dataclasses import replace

import httpx
import pytest

from xflog.app import create_app
from xflog.collector import DEFAULT_SELECTION, Collector
from xflog.config import Config
from xflog.demo import demo_history
from xflog.events import EVENT_TYPES, parse_event
from xflog.storage import Store
from xflog.transport import ProviderError, check_response, subscription_result


def envelope(kind="follow.follow", identity="-123456789", **overrides):
    return {
        "data": {
            "event_uuid": identity,
            "event_type": kind,
            "created_at": "2026-10-26T10:12:00Z",
            "payload": {
                "source": {"data": {"id": "222", "name": "Maya Chen", "username": "maya"}},
                "target": {"data": {"id": "111"}},
            },
            **overrides,
        }
    }


@pytest.mark.parametrize("kind", EVENT_TYPES)
@pytest.mark.parametrize("wrapped", [True, False])
def test_official_event_shapes_and_subjects(kind, wrapped):
    raw = envelope(kind)
    if not wrapped:
        raw = raw["data"]
        raw["payload"] = {key: value["data"] for key, value in raw["payload"].items()}
    result = parse_event(raw, "111")
    assert (result.kind, result.account_id, result.actor_id, result.handle) == (
        kind,
        "111",
        "222",
        "maya",
    )
    assert result.event_id == "-123456789"
    assert result.provider_at == "2026-10-26T10:12:00+00:00"


def test_only_incoming_activity_is_accepted():
    raw = envelope()
    assert parse_event(raw, "222") is None
    assert parse_event(raw, "333") is None
    raw["data"]["payload"]["source"]["data"]["id"] = "111"
    assert parse_event(raw, "111") is None


def test_missing_timestamp_is_unknown_and_unsafe_handles_never_become_links():
    raw = envelope(created_at=None)
    raw["data"]["payload"]["source"]["data"].update(
        {"username": "javascript:alert(1)", "name": '<img src=x onerror="alert(1)">'}
    )
    event = parse_event(raw, "111")
    assert event.provider_at is None
    assert event.received_at
    assert event.public()["profile_url"] is None
    assert "<img" in event.name  # Rendering, not storage, owns escaping of display names.


@pytest.mark.parametrize(
    "change",
    [
        {"event_uuid": None},
        {"created_at": "no date"},
        {"created_at": "2026-10-26T10:00:00"},
        {"payload": {}},
        {"payload": {"source": []}},
    ],
)
def test_malformed_known_event_cannot_silently_enter_history(change):
    with pytest.raises((ValueError, TypeError)):
        parse_event(envelope(**change), "111")


def test_unrequested_events_are_ignored():
    assert parse_event(envelope("like.create"), "111") is None
    assert parse_event({"connection_id": "stream-keepalive"}, "111") is None


async def test_dedup_cycles_delayed_events_and_restart(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = Store(path)
    await store.open()
    first = parse_event(envelope(), "111")
    assert await store.insert(first)
    assert not await store.insert(first)
    second = parse_event(envelope("follow.unfollow", "second"), "111")
    third = parse_event(
        envelope("follow.follow", "third", created_at="2026-10-20T09:00:00Z"), "111"
    )
    assert await store.insert(second)
    assert await store.insert(third)
    # An event's snapshot preserves the name at receipt; it isn't a current follower roster.
    renamed = replace(third, event_id="fourth", handle="new_maya", name="Maya New")
    await store.insert(renamed)
    await store.close()
    reopened = Store(path)
    await reopened.open()
    try:
        history = await reopened.history("111", {"limit": 2})
        assert [event["event_id"] for event in history["events"]] == ["fourth", "third"]
        older = await reopened.history("111", {"limit": 2, "before": history["next"]})
        assert [event["event_id"] for event in older["events"]] == ["second", "-123456789"]
        assert older["next"] is None
        assert (await reopened.summary("111"))["follow.follow"] == 3
        assert not (await reopened.history("different-account", {}))["events"]
    finally:
        await reopened.close()


async def test_subject_filters_and_gaps_persist_separately(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    try:
        for index, kind in enumerate(EVENT_TYPES):
            await store.insert(parse_event(envelope(kind, str(index)), "111"))
        follower = await store.history("111", {"kind": "lost"})
        paid = await store.history("111", {"subject": "subscriptions", "kind": "lost"})
        assert [event["kind"] for event in follower["events"]] == ["follow.unfollow"]
        assert [event["kind"] for event in paid["events"]] == ["subscriptions.unsubscribe"]
        await store.gap("111", "network lost")
        await store.gap("111", "retry")
        assert len(await store.gaps("111")) == 1
        await store.end_gap("111")
        assert (await store.gaps("111"))[0]["ended_at"] is not None
    finally:
        await store.close()


@pytest.mark.parametrize(
    "data",
    [
        {"subscription": {"subscription_id": "one"}},
        {"subscription_id": "one"},
        [{"subscription_id": "one"}],
    ],
)
def test_documented_subscription_success_variants(data):
    assert subscription_result({"data": data})["subscription_id"] == "one"


def test_rate_limit_uses_provider_wait():
    response = httpx.Response(429, headers={"retry-after": "73"})
    with pytest.raises(ProviderError) as error:
        check_response(response)
    assert error.value.delay == 73


def test_demo_totals_are_derived_and_subjects_never_mix():
    follower = demo_history({"limit": 50})
    next_page = demo_history({"limit": 50, "before": follower["next"]})
    events = follower["events"] + next_page["events"]
    assert len(events) == 66
    assert (
        sum(event["kind"] == "follow.follow" for event in events)
        == follower["counts"]["follow.follow"]
    )
    assert all(event["kind"].startswith("follow.") for event in events)
    assert all(
        event["kind"].startswith("subscriptions.")
        for event in demo_history({"subject": "subscriptions"})["events"]
    )
    assert DEFAULT_SELECTION["followers"] and not DEFAULT_SELECTION["subscriptions"]


async def test_demo_never_touches_real_history_or_x(tmp_path):
    def forbidden(request):
        raise AssertionError("Mock UI browsing must not call X")

    app = create_app(
        Config(tmp_path / "history.sqlite3"),
        transport=httpx.MockTransport(forbidden),
        mount_ui=False,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:7860"
        ) as browser,
    ):
        await browser.get("/")
        assert (await browser.get("/api/demo")).json()["events"]
        assert not (await browser.get("/api/events")).json()["events"]
        status = (await browser.get("/api/status")).json()
        assert not status["tracking"] and not status["connected"]
        assert (
            await browser.post(
                "/api/start",
                json={"accepted_costs": False},
                headers={"origin": "http://127.0.0.1:7860", "x-xflog-csrf": status["csrf"]},
            )
        ).status_code == 422


async def test_multiple_tabs_start_one_collector(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()

    class ConfiguredClient:
        config = Config(tmp_path / "history.sqlite3", app_bearer="fake", user_id="111")

    collector = Collector(store, ConfiguredClient())
    collector.connected = True
    entered = asyncio.Event()
    calls = []

    async def run():
        calls.append(1)
        entered.set()
        await asyncio.Event().wait()

    collector.run = run
    await store.save_setting("account", {"id": "111"})
    try:
        await asyncio.gather(*(collector.start() for _ in range(15)))
        await entered.wait()
        assert len(calls) == 1
        assert await store.setting("tracking")
    finally:
        await collector.shutdown()
        await store.close()


async def test_database_error_is_not_disguised_as_success(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    await store.db.execute("PRAGMA query_only=ON")
    try:
        import sqlite3

        with pytest.raises(sqlite3.OperationalError):
            await store.insert(parse_event(envelope(), "111"))
    finally:
        await store.close()


async def test_restart_resumes_only_previously_authorized_collection(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()

    class Client:
        config = Config(tmp_path / "history.sqlite3", app_bearer="fake-app", user_id="111")

    called = asyncio.Event()

    async def waiting():
        called.set()
        await asyncio.Event().wait()

    await store.save_setting("account", {"id": "111"})
    collector = Collector(store, Client())
    collector.run = waiting
    try:
        await collector.initialize()
        assert collector.task is None
        await store.save_setting("tracking", True)
        await collector.initialize()
        await called.wait()
        assert (await store.gaps("111"))[0]["ended_at"] is None
    finally:
        await collector.shutdown()
        await store.close()


async def test_reconnect_rate_limit_records_gap_without_duplicate_tasks(tmp_path, monkeypatch):
    import xflog.collector as module

    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    await store.save_setting("account", {"id": "111"})
    collector = Collector(store, None)
    waiting = asyncio.Event()
    delays = []
    calls = []

    async def reconcile(account, kinds):
        calls.append(1)
        raise ProviderError(429, 73)

    async def sleep(delay):
        delays.append(delay)
        waiting.set()
        await asyncio.Event().wait()

    collector.reconcile = reconcile
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    await store.save_setting("tracking", True)
    collector.task = asyncio.create_task(collector.run())
    try:
        await waiting.wait()
        assert collector.state == "reconnecting"
        assert len(calls) == 1 and 73 <= delays[0] <= 73.5
        assert len(await store.gaps("111")) == 1
    finally:
        await collector.cancel_task()
        await store.close()
