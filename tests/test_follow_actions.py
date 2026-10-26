import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from xflog.app import create_app
from xflog.config import Config
from xflog.errors import SetupError
from xflog.events import Event, utc_now


class FollowProvider:
    """Fake user-context API with observable reads and writes; never contacts X."""

    def __init__(self):
        self.requests = []
        self.owner = "111"
        self.connections = []
        self.lookup_data = None
        self.write_data = None
        self.write_status = 200
        self.write_started = asyncio.Event()
        self.write_release = None

    async def __call__(self, request):
        self.requests.append(request)
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": self.owner}})
        if request.method == "GET":
            data = self.lookup_data
            if data is None:
                data = {
                    "id": request.url.path.rsplit("/", 1)[-1],
                    "connection_status": self.connections,
                }
            return httpx.Response(200, json={"data": data})
        self.write_started.set()
        if self.write_release:
            await self.write_release.wait()
        if self.write_status != 200:
            return httpx.Response(self.write_status)
        following = request.method == "POST"
        data = self.write_data
        if data is None:
            self.connections = ["following"] if following else []
            data = {"following": following, "pending_follow": False}
        return httpx.Response(200, json={"data": data})

    @property
    def writes(self):
        return [request for request in self.requests if request.method != "GET"]


async def record(store, event_id="recorded", actor="222", account="111"):
    await store.insert(
        Event(event_id, "follow.follow", account, actor, "maya", "Maya", None, utc_now())
    )


@pytest.fixture
async def following(tmp_path):
    config = Config(
        tmp_path / "history.sqlite3", user_id="111", app_bearer="fake-app", user_token="fake-user"
    )
    provider = FollowProvider()
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
        await record(app.state.store)
        yield app, browser, provider


async def enable(browser):
    response = await browser.post("/api/preferences", json={"follow_actions": True})
    assert response.status_code == 200, response.text


async def test_default_off_and_status_make_no_provider_requests(following):
    app, browser, provider = following
    status = (await browser.get("/api/status")).json()
    assert status["follow_actions"] == {"enabled": False, "available": True, "reason": ""}
    for path, body in (
        ("/api/follow-actions/relationship", {"event_id": "recorded"}),
        ("/api/follow-actions", {"event_id": "recorded", "following": True}),
    ):
        assert (await browser.post(path, json=body)).status_code == 409
    await enable(browser)
    for _ in range(3):
        await browser.get("/api/status")
    assert not provider.requests
    assert not await app.state.store.setting("tracking", False)
    assert await app.state.store.setting("selection") == {
        "followers": True,
        "subscriptions": False,
        "notifications": False,
    }


async def test_older_preference_clients_do_not_disable_opt_in(following):
    app, browser, _ = following
    await enable(browser)
    await browser.post("/api/preferences", json={"notifications": True})
    assert await app.state.store.setting("follow_actions") is True


@pytest.mark.parametrize("changes", [{"user_token": ""}, {"user_id": ""}])
async def test_missing_credentials_cannot_enable_or_call_x(tmp_path, changes):
    config = replace(
        Config(tmp_path / "history.sqlite3", user_id="111", user_token="fake"), **changes
    )
    provider = FollowProvider()
    app = create_app(config, transport=httpx.MockTransport(provider), mount_ui=False)
    async with app.router.lifespan_context(app):
        assert not (await app.state.follow_actions.status())["available"]
        with pytest.raises(SetupError, match="Requires X_USER_ID"):
            await app.state.follow_actions.configure(True)
        assert not provider.requests


@pytest.mark.parametrize("actor", ["111", "../222", "٢٢٢", "2" * 20])
async def test_invalid_or_self_actor_never_reaches_provider(following, actor):
    app, browser, provider = following
    await record(app.state.store, "invalid", actor)
    await enable(browser)
    response = await browser.post("/api/follow-actions/relationship", json={"event_id": "invalid"})
    assert response.status_code == 409
    assert not provider.requests


async def test_demo_unknown_and_other_accounts_events_never_reach_provider(following):
    app, browser, provider = following
    await record(app.state.store, "other-account", account="333")
    await enable(browser)
    for body in (
        {"event_id": "recorded", "demo": True},
        {"event_id": "missing"},
        {"event_id": "other-account"},
    ):
        assert (
            await browser.post("/api/follow-actions/relationship", json=body)
        ).status_code == 409
        assert (
            await browser.post("/api/follow-actions", json={**body, "following": True})
        ).status_code == 409
    assert not provider.requests


async def test_token_owner_must_match_configured_and_stored_account(following):
    app, browser, provider = following
    await enable(browser)
    provider.owner = "999"
    response = await browser.post(
        "/api/follow-actions", json={"event_id": "recorded", "following": True}
    )
    assert response.status_code == 409 and "must belong" in response.json()["detail"]
    assert [r.url.path for r in provider.requests] == ["/2/users/me"]
    assert provider.requests[0].headers["authorization"] == "Bearer fake-user"
    provider.requests.clear()
    await app.state.store.save_setting("account", {"id": "333"})
    response = await browser.post("/api/follow-actions/relationship", json={"event_id": "recorded"})
    assert response.status_code == 409 and not provider.requests


@pytest.mark.parametrize(
    "connections,expected",
    [
        ([], (False, False, False)),
        (["followed_by"], (False, False, False)),
        (["following", "muting"], (True, False, False)),
        (["follow_request_sent"], (False, True, False)),
        (["blocking"], (False, False, True)),
    ],
)
async def test_relationship_is_outgoing_and_uses_user_context(following, connections, expected):
    _, browser, provider = following
    provider.connections = connections
    await enable(browser)
    response = await browser.post("/api/follow-actions/relationship", json={"event_id": "recorded"})
    assert response.status_code == 200
    assert tuple(response.json().values()) == expected
    assert provider.requests[-1].url.params["user.fields"] == "connection_status"
    assert all(r.headers["authorization"] == "Bearer fake-user" for r in provider.requests)
    assert not provider.writes


@pytest.mark.parametrize(
    "data",
    [
        {"id": "222"},
        {"id": "999", "connection_status": []},
        {"id": "222", "connection_status": "following"},
        {"id": "222", "connection_status": ["future-status"]},
        {"id": "222", "connection_status": [None]},
        {"id": "222", "connection_status": ["following", "follow_request_sent"]},
        {"id": "222", "connection_status": ["following", "blocking"]},
    ],
)
async def test_unknown_or_contradictory_relationship_never_enables_writes(following, data):
    _, browser, provider = following
    provider.lookup_data = data
    await enable(browser)
    response = await browser.post(
        "/api/follow-actions", json={"event_id": "recorded", "following": True}
    )
    assert response.status_code == 409 and not provider.writes


@pytest.mark.parametrize(
    "body",
    [
        {"event_id": "recorded", "following": "false"},
        {"event_id": "recorded", "following": 1},
        {"event_id": "recorded", "following": True, "actor_id": "999"},
        {"event_id": "", "following": True},
        {"event_id": "a" * 201, "following": True},
    ],
)
async def test_action_input_is_strict(following, body):
    _, browser, provider = following
    await enable(browser)
    assert (await browser.post("/api/follow-actions", json=body)).status_code == 422
    assert not provider.requests


async def test_follow_and_unfollow_do_not_change_incoming_history_or_listener(following):
    app, browser, provider = following
    await enable(browser)
    before = await app.state.store.summary("111")
    for desired in (True, False):
        response = await browser.post(
            "/api/follow-actions", json={"event_id": "recorded", "following": desired}
        )
        assert response.status_code == 200 and response.json()["following"] is desired
    assert [r.method for r in provider.writes] == ["POST", "DELETE"]
    assert json.loads(provider.writes[0].content) == {"target_user_id": "222"}
    assert provider.writes[1].url.path == "/2/users/111/following/222"
    assert sum(r.url.path == "/2/users/me" for r in provider.requests) == 1
    assert await app.state.store.summary("111") == before
    assert app.state.collector.task is None and app.state.collector.notifications == 0
    assert not await app.state.store.subscriptions()


@pytest.mark.parametrize(
    "connections,desired",
    [([], False), (["following"], True), (["blocking"], True), (["follow_request_sent"], True)],
)
async def test_no_op_pending_and_blocked_states_do_not_write(following, connections, desired):
    _, browser, provider = following
    provider.connections = connections
    await enable(browser)
    response = await browser.post(
        "/api/follow-actions", json={"event_id": "recorded", "following": desired}
    )
    assert response.status_code == (
        409 if connections in (["blocking"], ["follow_request_sent"]) else 200
    )
    assert not provider.writes


@pytest.mark.parametrize(
    "data,desired,code",
    [
        ({"following": False, "pending_follow": True}, True, 200),
        ({"following": True, "pending_follow": True}, True, 409),
        ({"following": True}, True, 409),
        ({"following": "false", "pending_follow": False}, True, 409),
        ({"following": False, "pending_follow": False}, True, 409),
        ({"following": True}, False, 409),
        ({"following": False}, False, 200),
    ],
)
async def test_write_confirmation_is_not_assumed_from_http_success(following, data, desired, code):
    _, browser, provider = following
    provider.connections = [] if desired else ["following"]
    provider.write_data = data
    await enable(browser)
    response = await browser.post(
        "/api/follow-actions", json={"event_id": "recorded", "following": desired}
    )
    assert response.status_code == code
    assert len(provider.writes) == 1
    if code == 200:
        assert response.json()["pending"] is data.get("pending_follow", False)


@pytest.mark.parametrize("status", [401, 402, 403, 429, 503])
async def test_write_errors_do_not_retry_or_leak_tokens(following, status):
    app, browser, provider = following
    provider.write_status = status
    await enable(browser)
    response = await browser.post(
        "/api/follow-actions", json={"event_id": "recorded", "following": True}
    )
    assert response.status_code == 409 and len(provider.writes) == 1
    assert "fake-user" not in response.text and "fake-app" not in response.text
    assert app.state.collector.message == "Ready. Tracking is paused."


async def test_completed_disable_fences_a_queued_write(following, monkeypatch):
    app, browser, provider = following
    await enable(browser)
    provider.write_release = asyncio.Event()
    first = asyncio.create_task(
        browser.post("/api/follow-actions", json={"event_id": "recorded", "following": True})
    )
    await asyncio.wait_for(provider.write_started.wait(), 2)
    configuring = asyncio.Event()
    original = app.state.follow_actions.configure

    async def configure(enabled):
        configuring.set()
        await original(enabled)

    monkeypatch.setattr(app.state.follow_actions, "configure", configure)
    disable = asyncio.create_task(browser.post("/api/preferences", json={"follow_actions": False}))
    await asyncio.wait_for(configuring.wait(), 2)
    assert not disable.done()
    queued = asyncio.create_task(
        browser.post("/api/follow-actions", json={"event_id": "recorded", "following": False})
    )
    provider.write_release.set()
    assert (await first).status_code == 200
    assert (await disable).status_code == 200
    assert (await queued).status_code == 409
    assert len(provider.writes) == 1
    assert await app.state.store.setting("follow_actions") is False


async def test_auth_origin_and_csrf_protect_relationship_reads_and_writes(following):
    _, browser, provider = following
    await enable(browser)
    for path, body in (
        ("/api/follow-actions/relationship", {"event_id": "recorded"}),
        ("/api/follow-actions", {"event_id": "recorded", "following": True}),
    ):
        assert (
            await browser.post(path, json=body, headers={"X-XFlog-CSRF": "wrong"})
        ).status_code == 403
        assert (
            await browser.post(path, json=body, headers={"Origin": "https://other.example"})
        ).status_code == 403
    assert not provider.requests
