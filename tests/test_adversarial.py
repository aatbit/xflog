"""Independent mocked boundary checks; no live X authorization or requests."""

import asyncio
import sqlite3

import httpx
import pytest

from xflog.app import create_app
from xflog.collector import Collector
from xflog.config import Config
from xflog.errors import SetupError
from xflog.storage import Store
from xflog.transport import XClient


class SparseStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"data":{"event_uuid":"one"}}\n'
        await asyncio.Event().wait()


@pytest.fixture
async def opened_store(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    await store.save_setting("account", {"id": "111", "name": "Test", "username": "test"})
    try:
        yield store
    finally:
        await store.close()


async def test_sparse_stream_delivers_event_without_waiting_for_8kb(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SparseStream()))
    async with httpx.AsyncClient(transport=transport) as http:
        client = XClient(Config(tmp_path / "test.sqlite3", app_bearer="fake-app"), http)
        stream = client.stream()
        assert await anext(stream) is None
        try:
            event = await asyncio.wait_for(anext(stream), timeout=0.1)
            assert event == {"data": {"event_uuid": "one"}}
        finally:
            await stream.aclose()


async def test_stop_discovers_subscription_created_before_lost_response(opened_store, tmp_path):
    await opened_store.save_setting("tag", "xflog-test")
    removed = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "subscription_id": "remote-only",
                            "event_type": "follow.follow",
                            "filter": {"user_id": "111"},
                            "tag": "xflog-test",
                        }
                    ]
                },
            )
        if request.method == "DELETE":
            removed.append(request.url.path)
            return httpx.Response(200, json={"data": {"deleted": True}})
        raise AssertionError("Unexpected mocked request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = XClient(Config(tmp_path / "test.sqlite3", app_bearer="fake-app"), http)

        collector = Collector(opened_store, client)
        collector.connected = True
        await collector.stop()
    assert removed == ["/2/activity/subscriptions/remote-only"]


async def test_stop_cancels_stream_even_when_settings_write_fails(opened_store, monkeypatch):
    collector = Collector(opened_store, None)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def pending_stream():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def fail_write(key, value):
        raise sqlite3.OperationalError("disk full")

    stream_task = asyncio.create_task(pending_stream())
    collector.task = stream_task
    await entered.wait()
    monkeypatch.setattr(opened_store, "save_setting", fail_write)
    try:
        with pytest.raises(sqlite3.Error):
            await collector.stop()
        assert cancelled.is_set(), "A failed SQLite write must not keep the billable stream alive"
    finally:
        stream_task.cancel()
        await asyncio.gather(stream_task, return_exceptions=True)


async def test_local_mutations_require_origin_and_csrf(tmp_path):
    app = create_app(Config(tmp_path / "test.sqlite3"), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:7860"
        ) as browser,
    ):
        assert (await browser.get("/api/status")).status_code == 401
        await browser.get("/")
        status = (await browser.get("/api/status")).json()
        missing = await browser.post("/api/preferences", json={"subscriptions": True})
        hostile = await browser.post(
            "/api/preferences",
            json={"subscriptions": True},
            headers={"origin": "https://evil.invalid", "x-xflog-csrf": status["csrf"]},
        )
        valid = await browser.post(
            "/api/preferences",
            json={"subscriptions": True},
            headers={"origin": "http://127.0.0.1:7860", "x-xflog-csrf": status["csrf"]},
        )
        assert missing.status_code == hostile.status_code == 403
        assert valid.status_code == 200


async def test_same_site_other_port_cannot_read_status(tmp_path):
    app = create_app(
        Config(tmp_path / "test.sqlite3"),
        mount_ui=False,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:7860"
        ) as browser,
    ):
        await browser.get("/")
        response = await browser.get(
            "/api/status",
            headers={
                "sec-fetch-site": "same-site",
                "referer": "http://127.0.0.1:8888/untrusted-page",
            },
        )
        assert response.status_code == 403


async def test_stop_attempts_remote_cleanup_when_tracking_write_fails(opened_store, monkeypatch):
    removed = []

    class CleanupClient:
        async def delete_subscription(self, identity):
            removed.append(identity)

    await opened_store.save_subscription(
        {
            "id": "known-subscription",
            "kind": "follow.follow",
            "account_id": "111",
            "expires_at": None,
            "tag": "xflog-test",
        }
    )
    original_save = opened_store.save_setting

    async def fail_tracking_write(key, value):
        if key == "tracking":
            raise sqlite3.OperationalError("disk full")
        await original_save(key, value)

    monkeypatch.setattr(opened_store, "save_setting", fail_tracking_write)
    collector = Collector(opened_store, CleanupClient())
    with pytest.raises(sqlite3.Error):
        await collector.stop()
    assert removed == ["known-subscription"]


def test_subscription_creation_requires_nonempty_identity():
    from xflog.transport import subscription_result

    with pytest.raises(SetupError):
        subscription_result({"data": {"subscription_id": ""}})


async def test_completed_failed_task_does_not_prevent_remote_cleanup(opened_store):
    removed = []

    class CleanupClient:
        async def delete_subscription(self, identity):
            removed.append(identity)

    await opened_store.save_subscription(
        {
            "id": "known-subscription",
            "kind": "follow.follow",
            "account_id": "111",
            "expires_at": None,
            "tag": "xflog-test",
        }
    )
    collector = Collector(opened_store, CleanupClient())

    async def failed_task():
        raise RuntimeError("unexpected transport adapter failure")

    task = asyncio.create_task(failed_task())
    await asyncio.gather(task, return_exceptions=True)
    collector.task = task
    await collector.stop()
    assert removed == ["known-subscription"]
    assert collector.task is None


async def test_stop_during_accepted_create_discovers_and_deletes_remote(opened_store, tmp_path):
    accepted = asyncio.Event()
    deleted = []
    remote = []

    async def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": remote})
        if request.method == "POST":
            import json

            body = json.loads(request.content)
            remote.append({"subscription_id": "accepted-before-cancel", **body})
            accepted.set()
            await asyncio.Event().wait()
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(200, json={"data": {"deleted": True}})
        raise AssertionError("Unexpected request")

    config = Config(tmp_path / "test.sqlite3", app_bearer="fake-app")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = XClient(config, http)

        collector = Collector(opened_store, client)
        collector.connected = True
        await collector.start()
        await asyncio.wait_for(accepted.wait(), timeout=1)
        await collector.stop()
        assert deleted == ["/2/activity/subscriptions/accepted-before-cancel"]
        assert not await opened_store.subscriptions()
        assert collector.task is None


async def test_ndjson_chunks_split_unicode_and_coalesced_heartbeats(tmp_path):
    class FragmentedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in [b'\n{"name":"caf\xc3', b'\xa9"}\r\n\n{"event":"two"}\n']:
                yield chunk

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=FragmentedStream()))
    async with httpx.AsyncClient(transport=transport) as http:
        stream = XClient(Config(tmp_path / "test.sqlite3", app_bearer="fake-app"), http).stream()
        assert [event async for event in stream] == [None, {"name": "café"}, {"event": "two"}]
