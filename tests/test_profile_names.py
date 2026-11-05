import asyncio
import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest
from test_interactions import envelope, post
from test_interactions import instance as shared_instance
from test_timeline import only_interactions

from xflog.errors import SetupError
from xflog.profile_names import ProfileNames
from xflog.tracking.events import Event, utc_now
from xflog.tracking.transport import ProviderError, XClient

instance = shared_instance


async def enable_names(browser):
    response = await browser.post("/api/preferences", json={"profile_names": True})
    assert response.status_code == 200


async def test_names_are_opt_in_once_cached_and_reused_after_restart(instance, monkeypatch):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    lookup = AsyncMock(return_value=[{"id": "222", "name": "Maya Chen", "username": "maya"}])
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    assert (await browser.get("/api/timeline")).json()["events"][0]["handle"] is None
    lookup.assert_not_awaited()
    await enable_names(browser)
    first = (await browser.get("/api/timeline")).json()["events"][0]
    assert (first["name"], first["handle"], first["profile_url"]) == (
        "Maya Chen",
        "maya",
        "https://x.com/maya",
    )
    await browser.get("/api/timeline")
    await app.state.interactions.ingest(envelope(event_uuid="another"), selection)
    await browser.get("/api/timeline")
    await app.state.store.close()
    await app.state.store.open()
    await ProfileNames(app.state.store, app.state.client).ensure(
        [{**first, "handle": None, "name": "Account 222"}]
    )
    restored = (await browser.get("/api/timeline")).json()["events"][0]
    assert (restored["name"], restored["handle"]) == ("Maya Chen", "maya")
    lookup.assert_awaited_once_with(["222"])


async def test_concurrent_readers_share_one_paid_lookup(instance, monkeypatch):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    await enable_names(browser)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(identities):
        entered.set()
        await release.wait()
        return [{"id": "222", "name": "Maya", "username": "maya"}]

    lookup = AsyncMock(side_effect=delayed)
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    first = asyncio.create_task(browser.get("/api/timeline"))
    await entered.wait()
    second = asyncio.create_task(browser.get("/api/timeline"))
    release.set()
    responses = await asyncio.gather(first, second)
    assert all(response.json()["events"][0]["handle"] == "maya" for response in responses)
    lookup.assert_awaited_once_with(["222"])


async def test_partial_results_are_not_polled_again_and_retry_only_unresolved(
    instance, monkeypatch
):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    await app.state.interactions.ingest(
        envelope(event_uuid="other", payload=post("901", "333")), selection
    )
    await enable_names(browser)
    lookup = AsyncMock(
        side_effect=[
            [{"id": "222", "name": "Maya", "username": "maya"}],
            [{"id": "333", "name": "Sofia", "username": "sofia"}],
        ]
    )
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    await browser.get("/api/timeline")
    await browser.get("/api/timeline")
    assert lookup.await_count == 1
    assert (await browser.get("/api/status")).json()["profile_warning"]
    await browser.post("/api/preferences", json={"profile_names": False})
    assert not (await browser.get("/api/status")).json()["profile_warning"]
    await enable_names(browser)
    final = (await browser.get("/api/timeline")).json()["events"]
    assert {event["handle"] for event in final} == {"maya", "sofia"}
    assert lookup.await_args_list[0].args == (["222", "333"],)
    assert lookup.await_args_list[1].args == (["333"],)


async def test_lookup_failure_keeps_history_and_does_not_repeat(instance, monkeypatch):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    await enable_names(browser)
    lookup = AsyncMock(side_effect=ProviderError(402))
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    result = (await browser.get("/api/timeline")).json()
    assert len(result["events"]) == 1
    await browser.get("/api/timeline")
    lookup.assert_awaited_once()
    assert (await browser.get("/api/status")).json()["profile_warning"]


async def test_event_supplied_identity_is_shared_without_profile_requests(instance, monkeypatch):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    await app.state.interactions.ingest(
        envelope(
            event_uuid="named",
            includes={"users": [{"id": "222", "name": "Maya", "username": "maya"}]},
        ),
        selection,
    )
    await enable_names(browser)
    lookup = AsyncMock()
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    result = (await browser.get("/api/timeline")).json()["events"]
    assert all(event["name"] == "Maya" and event["handle"] == "maya" for event in result)
    lookup.assert_not_awaited()


async def test_old_saved_profile_metadata_is_reused_on_upgrade(instance, monkeypatch):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(
        envelope(includes={"users": [{"id": "222", "name": "Maya", "username": "maya"}]}), selection
    )
    await app.state.interactions.ingest(envelope(event_uuid="later-id-only"), selection)
    await app.state.store.db.execute("DROP TABLE known_profiles")
    await app.state.store.db.execute("DELETE FROM settings WHERE key='profile_cache_backfilled'")
    await app.state.store.db.commit()
    await app.state.store.close()
    await app.state.store.open()
    await enable_names(browser)
    lookup = AsyncMock()
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    events = (await browser.get("/api/timeline")).json()["events"]
    assert all(event["name"] == "Maya" and event["handle"] == "maya" for event in events)
    lookup.assert_not_awaited()


async def test_batch_lookup_uses_only_identity_fields(instance):
    app, _, _ = instance
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "222", "name": "Maya", "username": "maya", "secret": "discard"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        result = await XClient(app.state.client.config, http).lookup_users(["222", "222"])
    assert result == [{"id": "222", "name": "Maya", "username": "maya"}]
    assert calls[0].url.params["ids"] == "222"
    assert calls[0].url.params["user.fields"] == "id,name,username"
    assert calls[0].headers["authorization"] == "Bearer fake-app"


@pytest.mark.parametrize("data", [[{"id": "999"}], [{"id": "222"}, {"id": "222"}], "bad"])
async def test_invalid_batch_response_is_not_trusted(instance, data):
    app, _, _ = instance
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": data}))
    ) as http:
        with pytest.raises(SetupError):
            await XClient(app.state.client.config, http).lookup_users(["222", "333"])


async def test_profile_cache_write_failure_rolls_back_record(instance, monkeypatch):
    app, _, _ = instance
    import xflog.history.store as store_module

    async def fail(*args):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store_module, "remember_profile", fail)
    with pytest.raises(sqlite3.Error):
        await app.state.store.insert(
            Event("rollback", "follow.follow", "111", "333", "sofia", "Sofia", None, utc_now())
        )
    await app.state.store.save_setting("unrelated", True)
    assert await app.state.store.event_actor("111", "rollback") is None


async def test_profile_cache_is_scoped_and_disabled_queued_reads_do_not_lookup(
    instance, monkeypatch
):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    await app.state.store.db.execute(
        "INSERT INTO known_profiles VALUES ('999','222','Wrong account','wrong','2026-11-04T00:00:00+00:00')"
    )
    await app.state.store.db.commit()
    await enable_names(browser)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(ids):
        entered.set()
        await release.wait()
        return [{"id": "222", "name": "Maya", "username": "maya"}]

    lookup = AsyncMock(side_effect=delayed)
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    first = asyncio.create_task(browser.get("/api/timeline"))
    await entered.wait()
    await app.state.interactions.ingest(
        envelope(event_uuid="new-person", payload=post("902", "333")), selection
    )
    second = asyncio.create_task(browser.get("/api/timeline"))
    await browser.post("/api/preferences", json={"profile_names": False})
    release.set()
    results = await asyncio.gather(first, second)
    assert all(
        event["name"] != "Wrong account" for result in results for event in result.json()["events"]
    )
    lookup.assert_awaited_once_with(["222"])
