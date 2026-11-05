import asyncio
import json

import httpx
import pytest

from xflog.app import create_app
from xflog.config import Config
from xflog.interactions import TYPES, parse_interaction, selected, subscription_filter
from xflog.tracking.collector import selected_kinds
from xflog.tracking.events import Event, utc_now


def post(identity="900", author="222", conversation="800", text="Hello <script>no</script>"):
    return {
        "id": identity,
        "author_id": author,
        "conversation_id": conversation,
        "text": text,
        "created_at": "2026-11-04T10:00:00Z",
    }


def envelope(kind="post.reply.create", payload=None, **extra):
    return {
        "data": {
            "event_uuid": "interaction-1",
            "event_type": kind,
            "filter": {"user_id": "111"},
            "created_at": "2026-11-04T12:00:00Z",
            "payload": post() if payload is None else payload,
            **extra,
        }
    }


def requested_post(request, source):
    if not isinstance(source, dict):
        return source
    fields = {"id", "text", "edit_history_tweet_ids"} | set(
        request.url.params.get("tweet.fields", request.url.params.get("post.fields", "")).split(",")
    )
    return {key: value for key, value in source.items() if key in fields}


class Provider:
    def __init__(self):
        self.calls = []
        self.page = {
            "data": [post("800", "111"), post()],
            "meta": {"result_count": 2, "next_token": "older"},
        }
        self.failure = 0
        self.owner = "111"
        self.owned = []
        self.lease = 0

    async def __call__(self, request):
        self.calls.append(request)
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": self.owner}})
        if request.url.path == "/2/activity/subscriptions":
            if request.method == "GET":
                return httpx.Response(200, json={"data": self.owned})
            self.lease += 1
            return httpx.Response(200, json={"data": {"subscription_id": str(self.lease)}})
        if request.method == "DELETE":
            return httpx.Response(200, json={"data": {"deleted": True}})
        if self.failure:
            return httpx.Response(self.failure)
        if request.url.path == "/2/tweets/search/all":
            page = dict(self.page)
            if isinstance(page.get("data"), list):
                page["data"] = [requested_post(request, item) for item in page["data"]]
            return httpx.Response(200, json=page)
        return httpx.Response(
            200, json={"data": requested_post(request, post(request.url.path.rsplit("/", 1)[-1]))}
        )

    @property
    def searches(self):
        return [call for call in self.calls if call.url.path == "/2/tweets/search/all"]


@pytest.fixture
async def instance(tmp_path):
    provider = Provider()
    config = Config(
        tmp_path / "history.sqlite3", user_id="111", app_bearer="fake-app", user_token="fake-user"
    )
    app = create_app(config, transport=httpx.MockTransport(provider), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=config.origin
        ) as browser,
    ):
        await browser.get("/")
        status = (await browser.get("/api/status")).json()
        browser.headers.update({"Origin": config.origin, "X-XFlog-CSRF": status["csrf"]})
        await app.state.store.insert(
            Event("person", "follow.follow", "111", "222", "maya", "Maya", None, utc_now())
        )
        yield app, browser, provider


async def enable(app, browser, choices=None):
    result = await browser.post(
        "/api/preferences", json={"interactions": choices or {"replies": True}}
    )
    assert result.status_code == 200, result.text
    await app.state.interactions.ingest(envelope(), await app.state.store.setting("selection"))


def target(action="open", **extra):
    return {"event_id": "person", "sequence": 1, "action": action, "accepted_costs": True, **extra}


async def test_off_by_default_and_details_are_local(instance):
    app, browser, provider = instance
    status = (await browser.get("/api/status")).json()
    assert not status["selection"].get("interactions")
    assert len(status["interaction_types"]) == 7
    await app.state.interactions.ingest(envelope(), status["selection"])
    assert (await browser.get("/api/interactions", params={"event_id": "person"})).json()[
        "interactions"
    ] == []
    assert not provider.calls


async def test_capture_is_separate_persistent_and_idempotent(instance):
    app, browser, provider = instance
    await enable(app, browser)
    await app.state.interactions.ingest(envelope(), {"interactions": {"replies": True}})
    history = (await browser.get("/api/interactions", params={"event_id": "person"})).json()
    assert len(history["interactions"]) == 1
    assert history["interactions"][0]["text"].startswith("Hello")
    assert (await app.state.store.summary("111"))["follow.follow"] == 1
    assert not provider.calls
    assert await app.state.store.setting("tracking", False) is False


async def test_missing_and_wrong_account_no_billable_requests(instance):
    app, browser, provider = instance
    await enable(app, browser)
    await app.state.store.insert(
        Event("other", "follow.follow", "999", "222", None, None, None, utc_now())
    )
    for body in (
        target(event_id="missing"),
        target(event_id="other"),
        target(sequence=999),
        target(demo=True),
    ):
        assert (await browser.post("/api/interactions/thread", json=body)).status_code == 409
    provider.owner = "999"
    assert (await browser.post("/api/interactions/thread", json=target())).status_code == 409
    assert not provider.searches


async def test_explicit_load_cache_more_refresh_and_failure(instance):
    app, browser, provider = instance
    await enable(app, browser)
    assert (
        await browser.post("/api/interactions/thread", json=target(accepted_costs=False))
    ).status_code == 409
    first = (await browser.post("/api/interactions/thread", json=target())).json()
    assert first["fetched"] and first["total"] == 2
    assert (
        provider.searches[0].url.params["tweet.fields"]
        == "id,author_id,conversation_id,created_at,text"
    )
    assert provider.searches[0].url.params["max_results"] == "100"
    for _ in range(3):
        result = (
            await browser.post("/api/interactions/thread", json=target(accepted_costs=False))
        ).json()
        assert not result["fetched"]
    assert len(provider.searches) == 1
    provider.page = {"data": [post("700")], "meta": {"result_count": 1}}
    more = (
        await browser.post(
            "/api/interactions/thread", json=target("more", checked_at=first["checked_at"])
        )
    ).json()
    assert more["total"] == 3 and not more["more_available"]
    assert provider.searches[-1].url.params["next_token"] == "older"
    provider.failure = 403
    assert (
        await browser.post(
            "/api/interactions/thread", json=target("refresh", checked_at=more["checked_at"])
        )
    ).status_code == 409
    cached = (await browser.post("/api/interactions/thread", json=target())).json()
    assert cached["total"] == 3 and cached["checked_at"] == more["checked_at"]
    await browser.post("/api/preferences", json={"interactions": {}})
    assert (await browser.post("/api/interactions/thread", json=target())).json()["total"] == 3
    assert (
        await browser.post(
            "/api/interactions/thread", json=target("refresh", checked_at=more["checked_at"])
        )
    ).status_code == 409


async def test_thread_author_ids_survive_fetch_and_cached_read(instance):
    app, browser, provider = instance
    await enable(app, browser)
    provider.page = {
        "data": [post("700", "333"), post("800", "111"), post()],
        "meta": {"result_count": 3},
    }
    fetched = (await browser.post("/api/interactions/thread", json=target())).json()
    cached = (
        await browser.post("/api/interactions/thread", json=target(accepted_costs=False))
    ).json()
    expected = [("700", "333"), ("800", "111"), ("900", "222")]
    assert [
        [(item["id"], item["author_id"]) for item in result["posts"]]
        for result in (fetched, cached)
    ] == [expected, expected]
    assert [call.url.path for call in provider.calls] == ["/2/users/me", "/2/tweets/search/all"]
    assert "expansions" not in provider.searches[0].url.params


async def test_resolved_post_author_is_saved(instance):
    app, _, _ = instance
    await app.state.interactions.resolve_post("777")
    async with app.state.store.db.execute(
        "SELECT author_id FROM interaction_posts WHERE account_id=? AND id=?", ("111", "777")
    ) as cursor:
        saved = await cursor.fetchone()
    assert saved["author_id"] == "222"


async def test_concurrent_opens_fetch_once_and_old_clients_preserve_choice(instance):
    app, browser, provider = instance
    await enable(app, browser)
    await browser.post("/api/preferences", json={"notifications": True})
    assert (await app.state.store.setting("selection"))["interactions"]["replies"]
    responses = await asyncio.gather(
        *(browser.post("/api/interactions/thread", json=target()) for _ in range(4))
    )
    assert all(response.status_code == 200 for response in responses)
    assert len(provider.searches) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"data": [post(conversation="999")], "meta": {"result_count": 1}},
        {"data": [post()], "meta": {"result_count": 0}},
        {"data": [post()], "meta": {"result_count": True}},
        {"data": [post()], "meta": {"result_count": 1, "next_token": 4}},
        {"data": [post()], "meta": {"result_count": 1}, "errors": [{"detail": "partial"}]},
    ],
)
async def test_bad_pages_do_not_corrupt_cached_thread(instance, bad):
    app, browser, provider = instance
    await enable(app, browser)
    first = (await browser.post("/api/interactions/thread", json=target())).json()
    provider.page = bad
    assert (
        await browser.post(
            "/api/interactions/thread", json=target("refresh", checked_at=first["checked_at"])
        )
    ).status_code == 409
    assert (await browser.post("/api/interactions/thread", json=target())).json()["total"] == 2


async def test_stream_posts_extend_only_existing_saved_thread(instance):
    app, browser, provider = instance
    await enable(app, browser)
    first = (await browser.post("/api/interactions/thread", json=target())).json()
    raw = envelope(payload=post("950"))
    raw["data"]["event_uuid"] = "interaction-2"
    await app.state.interactions.ingest(raw, {"interactions": {"replies": True}})
    cached = (await browser.post("/api/interactions/thread", json=target())).json()
    assert cached["total"] == 3
    assert cached["checked_at"] == first["checked_at"]
    assert len(provider.searches) == 1


def test_parse_aliases_missing_references_and_like_time():
    raw = envelope(
        "post.create",
        {**post(author="111"), "referenced_posts": [{"type": "quoted", "id": "777"}]},
        includes={"posts": [post("777", "222")]},
    )
    assert parse_interaction(raw, "111")["people"] == {"222"}
    raw["data"]["includes"] = {}
    assert parse_interaction(raw, "111")["people"] == set()
    like = envelope(
        "like.create",
        {
            "liking_user_id": "222",
            "liked_tweet_author_id": "111",
            "liked_tweet_id": "900",
            "created_at": "2020-01-01T00:00:00Z",
        },
    )
    result = parse_interaction(like, "111")
    assert result["key"] == "likes_received" and result["provider_at"].startswith("2026-11-04")
    like["data"]["payload"].update(liking_user_id="111", liked_tweet_author_id="222")
    assert parse_interaction(like, "111")["key"] == "likes_given"
    raw["data"]["filter"]["user_id"] = "999"
    assert parse_interaction(raw, "111") is None


async def test_like_without_context_looks_up_only_when_clicked(instance):
    app, browser, provider = instance
    await enable(app, browser, {"likes_received": True})
    await app.state.interactions.ingest(
        envelope(
            "like.create",
            {"liking_user_id": "222", "liked_tweet_author_id": "111", "liked_tweet_id": "900"},
        ),
        {"interactions": {"likes_received": True}},
    )
    assert not provider.calls
    assert (await browser.post("/api/interactions/thread", json=target())).status_code == 200
    assert sum(call.url.path == "/2/tweets/900" for call in provider.calls) == 1
    await browser.post("/api/interactions/thread", json=target())
    assert sum(call.url.path == "/2/tweets/900" for call in provider.calls) == 1


async def test_subscription_filters_routing_and_like_replacement(instance):
    app, _, provider = instance
    selection = {
        "followers": True,
        "subscriptions": False,
        "interactions": {key: True for key in TYPES},
    }
    kinds = selected_kinds(selection)
    assert selected(selection).count("like.create:both") == 1
    assert subscription_filter("like.create:both", "111") == {"user_id": "111"}
    await app.state.collector.reconcile({"id": "111"}, kinds)
    creations = [call for call in provider.calls if call.method == "POST"]
    for call in creations:
        body = json.loads(call.content)
        if body["event_type"].startswith("post."):
            assert "qualifiers" not in body["filter"]
        if body["event_type"] in {"post.reply.create", "like.create"}:
            assert call.headers["Authorization"] == "Bearer fake-user"
    provider.calls.clear()
    await app.state.collector.reconcile({"id": "111"}, ("follow.follow", "like.create:inbound"))
    like_delete = next(i for i, call in enumerate(provider.calls) if call.method == "DELETE")
    like_create = next(
        i
        for i, call in enumerate(provider.calls)
        if call.method == "POST" and json.loads(call.content)["event_type"] == "like.create"
    )
    assert like_delete < like_create


async def test_disabled_malformed_type_is_ignored_but_selected_type_is_strict(instance):
    app, _, provider = instance
    selection = {"interactions": {"replies": True}}
    assert not await app.state.interactions.ingest(envelope("like.create", {}), selection)
    with pytest.raises(ValueError, match="Missing post ID"):
        await app.state.interactions.ingest(envelope(payload={}), selection)
    assert not provider.calls


async def test_existing_database_migrates_and_thread_survives_reopen(tmp_path):
    import sqlite3

    from xflog.history.store import SCHEMA, Store
    from xflog.interactions.store import InteractionStore

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as database:
        database.executescript(SCHEMA)
        database.execute("INSERT INTO settings VALUES (?,?)", ("selection", '{"followers":true}'))
    store = Store(path)
    await store.open()
    records = InteractionStore(store)
    try:
        await records.insert("111", parse_interaction(envelope(), "111"))
        await store.save_setting(
            "selection", {"followers": True, "interactions": {"replies": True}}
        )
        await records.save_thread(
            "111", {"conversation": "800", "posts": [post("800")], "next_token": "next"}
        )
    finally:
        await store.close()
    await store.open()
    try:
        assert (await records.history("111", {"person": "222", "before": 0}))["interactions"][0][
            "post_id"
        ] == "900"
        assert (await records.thread("111", {"conversation": "800"}))["total"] == 2
        assert (await records.snapshot("111", "800"))["next_token"] == "next"
        assert (await store.setting("selection"))["interactions"]["replies"]
        assert not (await records.thread("999", {"conversation": "800"}))["posts"]
    finally:
        await store.close()


async def test_thread_transaction_rollback_keeps_previous_snapshot(instance, monkeypatch):
    import sqlite3

    app, browser, _ = instance
    await enable(app, browser)
    first = (await browser.post("/api/interactions/thread", json=target())).json()
    records = app.state.interactions.records
    save = records.save_posts

    async def fail_after_posts(account, posts):
        await save(account, posts)
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(records, "save_posts", fail_after_posts)
    with pytest.raises(sqlite3.OperationalError):
        await records.save_thread(
            "111", {"conversation": "800", "posts": [post("999")], "next_token": None}
        )
    cached = (await browser.post("/api/interactions/thread", json=target())).json()
    assert cached["checked_at"] == first["checked_at"]
    assert cached["total"] == first["total"]


@pytest.mark.parametrize("boundary", ["delete", "create"])
async def test_like_replacement_failure_does_not_claim_new_coverage(
    instance, monkeypatch, boundary
):
    from xflog.tracking.transport import ProviderError

    app, _, provider = instance
    collector = app.state.collector
    await collector.reconcile({"id": "111"}, ("follow.follow", "like.create:inbound"))
    provider.calls.clear()
    original_delete = app.state.client.delete_subscription
    original_request = app.state.client.request

    async def fail_delete(identity):
        raise ProviderError(403)

    async def fail_create(method, path, **kwargs):
        if method == "POST" and kwargs["json"]["event_type"] == "like.create":
            raise ProviderError(403)
        return await original_request(method, path, **kwargs)

    monkeypatch.setattr(
        app.state.client,
        "delete_subscription",
        fail_delete if boundary == "delete" else original_delete,
    )
    monkeypatch.setattr(
        app.state.client, "request", fail_create if boundary == "create" else original_request
    )
    with pytest.raises(ProviderError):
        await collector.reconcile({"id": "111"}, ("follow.follow", "like.create:outbound"))
    saved = await app.state.store.subscriptions()
    assert any(item["kind"] == "follow.follow" for item in saved)
    assert not any(item["kind"] == "like.create:outbound" for item in saved)
    assert not any(
        call.method == "POST" and json.loads(call.content)["event_type"] == "like.create"
        for call in provider.calls
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", True),
        ("sequence", "1"),
        ("offset", -1),
        ("accepted_costs", "true"),
        ("action", "background"),
    ],
)
async def test_thread_request_rejects_malformed_types_before_x(instance, field, value):
    _, browser, provider = instance
    assert (
        await browser.post("/api/interactions/thread", json=target(**{field: value}))
    ).status_code == 422
    assert not provider.calls


async def test_refresh_stale_version_does_not_charge_twice(instance):
    app, browser, provider = instance
    await enable(app, browser)
    first = (await browser.post("/api/interactions/thread", json=target())).json()
    response = await asyncio.gather(
        *(
            browser.post(
                "/api/interactions/thread", json=target("refresh", checked_at=first["checked_at"])
            )
            for _ in range(3)
        )
    )
    assert all(item.status_code == 200 for item in response)
    assert len(provider.searches) == 2


async def test_large_saved_thread_pages_locally_and_reports_cache(instance):
    app, browser, provider = instance
    await enable(app, browser)
    records = app.state.interactions.records
    await records.save_thread(
        "111",
        {
            "conversation": "800",
            "posts": [post(str(1000 + index)) for index in range(150)],
            "next_token": None,
        },
    )
    history = (await browser.get("/api/interactions", params={"event_id": "person"})).json()
    assert history["interactions"][0]["thread_saved"]
    first = (
        await browser.post("/api/interactions/thread", json=target(accepted_costs=False))
    ).json()
    second = (
        await browser.post(
            "/api/interactions/thread", json=target("cached", offset=100, accepted_costs=False)
        )
    ).json()
    assert len(first["posts"]) == 100 and first["more_saved"]
    assert len(second["posts"]) == 51 and not second["more_saved"]
    assert len({item["id"] for item in first["posts"] + second["posts"]}) == 151
    assert not provider.calls


async def test_interaction_from_other_person_cannot_be_used_as_thread_target(instance):
    app, browser, provider = instance
    await enable(app, browser)
    await app.state.store.insert(
        Event("other-person", "follow.follow", "111", "333", None, None, None, utc_now())
    )
    assert (
        await browser.post("/api/interactions/thread", json=target(event_id="other-person"))
    ).status_code == 409
    assert not provider.calls


@pytest.mark.parametrize(
    "enabled,liker,author", [("likes_given", "222", "111"), ("likes_received", "111", "222")]
)
async def test_disabled_like_direction_ignores_unreadable_optional_context(
    instance, enabled, liker, author
):
    app, _, provider = instance
    raw = envelope(
        "like.create",
        {"liking_user_id": liker, "liked_tweet_author_id": author, "liked_tweet_id": "900"},
        includes={"posts": "unreadable"},
    )
    assert not await app.state.interactions.ingest(raw, {"interactions": {enabled: True}})
    opposite = "likes_received" if enabled == "likes_given" else "likes_given"
    with pytest.raises(ValueError, match="Invalid related posts"):
        await app.state.interactions.ingest(raw, {"interactions": {opposite: True}})
    assert not provider.calls
