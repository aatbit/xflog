import asyncio
import sqlite3

import httpx
import pytest
from test_history import envelope
from test_preferences import ActivityProvider

from xflog import audience_groups as groups
from xflog.app import create_app
from xflog.config import Config
from xflog.events import parse_event
from xflog.storage import SCHEMA, Store


def test_defaults_and_explicit_module_registration(monkeypatch):
    monkeypatch.setattr(groups, "MODULES", dict(groups.MODULES))
    assert groups.preferences() == {"account-size": False, "activity": True}
    assert groups.preferences({"account-size": "true", "activity": False}) == {
        "account-size": False,
        "activity": False,
    }
    module = groups.AudienceGroup(
        "sample",
        "Sample",
        "Event-only test module",
        (groups.Bucket("unknown", "Unknown"),),
        lambda event: "unknown",
    )
    groups.register(module)
    assert groups.catalog()[-1]["key"] == "sample"
    assert groups.decorate({}, {"sample": True})["audience_groups"]["sample"] == "unknown"
    with pytest.raises(ValueError, match="unique"):
        groups.register(module)


@pytest.mark.parametrize(
    "count,bucket",
    [
        (0, "under-100"),
        (99, "under-100"),
        (100, "100-999"),
        (999, "100-999"),
        (1000, "1k-9999"),
        (9999, "1k-9999"),
        (10000, "10k-plus"),
        (2**53 - 1, "10k-plus"),
        (None, "unknown"),
        (True, "unknown"),
        (-1, "unknown"),
        ("12", "unknown"),
        (1.5, "unknown"),
        (2**53, "unknown"),
    ],
)
def test_source_snapshot_and_bucket_boundaries(count, bucket):
    raw = envelope()
    raw["data"]["payload"]["source"]["data"]["public_metrics"] = {"followers_count": count}
    raw["data"]["payload"]["target"]["data"]["public_metrics"] = {"followers_count": 100000}
    enabled = {"account-size": True}
    event = parse_event(raw, "111", enabled)
    assert groups.decorate(event.public(), enabled)["audience_groups"]["account-size"] == bucket
    assert groups.decorate(event.public())["audience_groups"] == {"activity": "follow.follow"}
    if bucket == "unknown":
        assert event.group_data == {}
    else:
        assert event.group_data == {"account-size": {"followers_count": count}}


def test_disabled_capture_is_not_called_and_target_metrics_are_never_used(monkeypatch):
    original = groups.MODULES["account-size"]
    from dataclasses import replace

    def forbidden(source):
        raise AssertionError("Disabled module must not execute its capture")

    monkeypatch.setitem(groups.MODULES, "account-size", replace(original, capture=forbidden))
    assert parse_event(envelope(), "111").group_data == {}
    monkeypatch.setitem(groups.MODULES, "account-size", original)
    raw = envelope()
    raw["data"]["payload"]["target"]["data"]["public_metrics"] = {"followers_count": 900}
    assert parse_event(raw, "111", {"account-size": True}).group_data == {}


async def test_existing_database_migrates_without_losing_history_or_fabricating_counts(tmp_path):
    path = tmp_path / "old.sqlite3"
    event = parse_event(envelope(), "111")
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO events (event_id,kind,account_id,actor_id,handle,name,provider_at,received_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            tuple(value for key, value in vars(event).items() if key != "group_data"),
        )
    for _ in range(2):
        store = Store(path)
        await store.open()
        try:
            history = await store.history("111", {})
            assert len(history["events"]) == 1
            old = history["events"][0]
            assert old["event_id"] == event.event_id and old["group_data"] == {}
            assert (
                groups.decorate(old, {"account-size": True})["audience_groups"]["account-size"]
                == "unknown"
            )
            assert not await store.insert(event)
            assert not (await store.history("333", {}))["events"]
        finally:
            await store.close()


async def test_group_settings_are_protected_and_do_not_restart_or_call_x(tmp_path):
    import json

    provider = ActivityProvider()
    config = Config(tmp_path / "history.sqlite3", app_bearer="fake", user_id="111")
    app = create_app(config, transport=httpx.MockTransport(provider), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=config.origin,
        ) as browser,
    ):
        await browser.get("/")
        status = (await browser.get("/api/status")).json()
        headers = {"origin": config.origin, "x-xflog-csrf": status["csrf"]}
        assert [item["key"] for item in status["audience_groups"] if item["enabled"]] == [
            "activity"
        ]
        assert (await browser.post("/api/audience-groups", json={"enabled": {}})).status_code == 403
        for enabled in ({"account-size": "true"}, {"untrusted.module": True}):
            response = await browser.post(
                "/api/audience-groups", json={"enabled": enabled}, headers=headers
            )
            assert response.status_code == 422
        collector = app.state.collector
        await collector.start()
        await asyncio.wait_for(provider.body.opened.wait(), timeout=2)
        task, requests = collector.task, list(provider.requests)
        responses = await asyncio.gather(
            *(
                browser.post("/api/audience-groups", json={"enabled": enabled}, headers=headers)
                for enabled in ({"activity": False}, {"account-size": True})
            )
        )
        assert all(response.status_code == 200 for response in responses)
        assert await collector.store.setting("audience_groups") == {
            "activity": False,
            "account-size": True,
        }
        raw = envelope(identity="captured")
        raw["data"]["payload"]["source"]["data"]["public_metrics"] = {"followers_count": 0}
        await provider.body.queue.put(json.dumps(raw).encode() + b"\n")
        await asyncio.wait_for(provider.body.queue.join(), timeout=2)
        history = (await browser.get("/api/events")).json()["events"]
        assert history[0]["audience_groups"] == {"account-size": "under-100"}
        assert history[0]["group_data"] == {"account-size": {"followers_count": 0}}
        await browser.post(
            "/api/audience-groups", json={"enabled": {"account-size": False}}, headers=headers
        )
        raw["data"]["event_uuid"] = "not-captured"
        await provider.body.queue.put(json.dumps(raw).encode() + b"\n")
        await asyncio.wait_for(provider.body.queue.join(), timeout=2)
        rows = (await browser.get("/api/events")).json()["events"]
        assert rows[0]["group_data"] == {} and rows[0]["audience_groups"] == {}
        assert rows[1]["group_data"] == {"account-size": {"followers_count": 0}}
        assert collector.task is task and not task.done()
        assert provider.requests == requests and provider.streams == 1
        assert await collector.store.setting("tracking")
