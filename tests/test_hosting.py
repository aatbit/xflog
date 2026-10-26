import asyncio
import sqlite3
from dataclasses import replace

import httpx
import pytest

from xflog.app import create_app
from xflog.collector import Collector
from xflog.config import ASSETS, Config
from xflog.errors import SetupError
from xflog.storage import Store
from xflog.transport import XClient

PASSWORD = "fake-instance-password-for-tests"


def forbid_x(request):
    raise AssertionError("Environment/UI tests must not call X")


@pytest.fixture
def hosted_config(tmp_path):
    return Config(
        tmp_path / "history.sqlite3",
        origin="https://xf.example",
        host="0.0.0.0",
        user_id="111",
        app_bearer="fake-bearer",
        admin_password=PASSWORD,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "http://xf.example"},
        {"origin": "https://xf.example:bad"},
        {"origin": "https://user:password@xf.example"},
        {"origin": "https://xf.example?extra=1"},
        {"admin_password": ""},
        {"admin_password": "short"},
        {"host": "untrusted.example"},
        {"port": 0},
    ],
)
def test_unsafe_hosted_configuration_is_rejected(hosted_config, change):
    with pytest.raises(ValueError):
        replace(hosted_config, **change)


def test_network_binding_requires_password_even_with_loopback_origin(tmp_path):
    with pytest.raises(ValueError, match="Hosted binding"):
        Config(tmp_path / "history.sqlite3", host="0.0.0.0")


def test_config_repr_never_contains_secrets(hosted_config):
    config = replace(hosted_config, user_token="fake-private-token")
    assert all(
        value not in repr(config) for value in (PASSWORD, config.user_token, config.app_bearer)
    )


async def test_instance_auth_guards_ui_api_assets(hosted_config):
    app = create_app(hosted_config, transport=httpx.MockTransport(forbid_x), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://xf.example"
        ) as browser,
    ):
        for path in ("/", "/api/status", "/static/xf/mark.svg"):
            response = await browser.get(path)
            assert response.status_code == 401
            assert response.headers["www-authenticate"].startswith("Basic")
            assert "set-cookie" not in response.headers
        assert (await browser.get("/healthz")).json() == {"ok": True}
        assert (await browser.get("/", auth=("xflog", "incorrect"))).status_code == 401
        assert (await browser.get("/", headers={"authorization": "Basic !!!"})).status_code == 401
        browser.auth = ("xflog", PASSWORD)
        home = await browser.get("/")
        assert home.status_code == 200
        assert "Secure" in home.headers["set-cookie"]
        status = (await browser.get("/api/status")).json()
        assert status["connected"]
        assert status["account"]["id"] == "111"
        for removed in ("/auth/x/start", "/auth/x/callback", "/api/disconnect"):
            assert (await browser.get(removed)).status_code == 404
        assert not {"database", "callback", "setup"} & status.keys()
        assert (await browser.get("/", headers={"host": "attacker.example"})).status_code == 403
        assert (
            await browser.post(
                "/api/preferences",
                json={"followers": True, "subscriptions": False},
                headers={"origin": "https://attacker.example", "x-xflog-csrf": status["csrf"]},
            )
        ).status_code == 403
        assert (
            await browser.post(
                "/api/preferences",
                json={"followers": True, "subscriptions": False},
                headers={"origin": "https://xf.example", "x-xflog-csrf": status["csrf"]},
            )
        ).status_code == 200


def test_profile_has_no_storage_or_developer_settings():
    html = (ASSETS / "shell.html").read_text()
    javascript = (ASSETS / "app.js").read_text()
    for removed in (
        "database-path",
        "callback-url",
        "setup-status",
        "profile-advanced",
        "connect-button",
        "signup-followers",
        "/auth/x/",
    ):
        assert removed not in html + javascript


async def test_event_creation_uses_correct_environment_token(hosted_config):
    requests = []

    def provider(request):
        requests.append(request.headers["authorization"])
        return httpx.Response(200, json={"data": {"subscription_id": "fake-sub"}})

    config = replace(hosted_config, user_token="fake-private-user-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        client = XClient(config, http)
        for kind in (
            "follow.follow",
            "follow.unfollow",
            "subscriptions.subscribe",
            "subscriptions.unsubscribe",
        ):
            await client.request("POST", "/2/activity/subscriptions", json={"event_type": kind})
    assert requests == ["Bearer fake-bearer"] * 2 + ["Bearer fake-private-user-token"] * 2


async def test_paid_events_without_user_token_fail_before_start(hosted_config):
    app = create_app(hosted_config, transport=httpx.MockTransport(forbid_x), mount_ui=False)
    async with app.router.lifespan_context(app):
        await app.state.store.save_setting("selection", {"followers": True, "subscriptions": True})
        with pytest.raises(SetupError, match="X_USER_ACCESS_TOKEN"):
            await app.state.collector.start()
        assert app.state.collector.task is None
        assert not await app.state.store.setting("tracking", False)


async def test_restart_without_private_token_does_not_create_partial_subscriptions(hosted_config):
    store = Store(hosted_config.database)
    await store.open()
    await store.save_setting("account", {"id": "111"})
    await store.save_setting("selection", {"followers": True, "subscriptions": True})
    await store.save_setting("tracking", True)
    collector = Collector(store, XClient(hosted_config, None))
    try:
        await collector.initialize()
        assert collector.task is None
        assert "X_USER_ACCESS_TOKEN" in collector.message
    finally:
        await store.close()


@pytest.mark.parametrize("resume", [False, True])
async def test_followers_can_start_and_resume_without_user_access_token(hosted_config, resume):
    assert not hosted_config.user_token
    store = Store(hosted_config.database)
    await store.open()
    collector = Collector(store, XClient(hosted_config, None))
    entered = asyncio.Event()

    async def waiting():
        entered.set()
        await asyncio.Event().wait()

    collector.run = waiting
    try:
        await store.save_setting("tracking", resume)
        await collector.initialize()
        assert collector.connected
        if not resume:
            await collector.start()
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert await store.setting("tracking")
    finally:
        await collector.shutdown()
        await store.close()


async def test_failed_pause_blocks_restart_after_database_repair(hosted_config, monkeypatch):
    store = Store(hosted_config.database)
    await store.open()
    app_client = XClient(hosted_config, None)
    collector = Collector(store, app_client)
    await collector.initialize()
    await store.save_setting("tracking", True)
    original_save = store.save_setting

    async def fail_tracking(key, value):
        if key == "tracking":
            raise sqlite3.OperationalError("read only")
        await original_save(key, value)

    monkeypatch.setattr(store, "save_setting", fail_tracking)
    with pytest.raises(sqlite3.Error):
        await collector.stop()
    assert await store.restart_blocked()
    await store.close()
    repaired = Store(hosted_config.database)
    await repaired.open()
    resumed = Collector(repaired, app_client)
    try:
        await resumed.initialize()
        assert resumed.task is None
        assert await repaired.setting("tracking") is True
    finally:
        await repaired.close()


async def test_account_change_cannot_orphan_active_history(hosted_config):
    store = Store(hosted_config.database)
    await store.open()
    await store.save_setting("account", {"id": "222"})
    await store.save_setting("tracking", True)
    try:
        with pytest.raises(SetupError, match="previous account"):
            await Collector(store, XClient(hosted_config, None)).initialize()
        assert (await store.setting("account"))["id"] == "222"
    finally:
        await store.close()


async def test_failed_pause_warns_when_both_persistence_paths_fail(hosted_config, monkeypatch):
    store = Store(hosted_config.database)
    await store.open()
    collector = Collector(store, XClient(hosted_config, None))
    await collector.initialize()

    async def no_marker():
        raise OSError("disk full")

    async def no_database(*_args):
        raise sqlite3.OperationalError("read only")

    monkeypatch.setattr(store, "block_restart", no_marker)
    monkeypatch.setattr(store, "save_setting", no_database)
    try:
        with pytest.raises(sqlite3.Error):
            await collector.stop()
        assert "remove the environment credentials" in collector.message
    finally:
        await store.close()
