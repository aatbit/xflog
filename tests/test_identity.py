import asyncio
from dataclasses import replace

import httpx
import pytest

from xflog import CoreConfig, Runtime, RuntimeBusyError, SetupError
from xflog.history.store import Store
from xflog.tracking.collector import Collector
from xflog.tracking.transport import XClient


@pytest.fixture
def self_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return CoreConfig(tmp_path / "history.sqlite3", app_bearer="fake-app", user_token="fake-user")


async def test_user_token_resolves_self_once_per_startup_and_shares_config(self_config):
    calls = []

    async def provider(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"id": "111"}})

    for _ in range(2):
        async with Runtime(self_config, transport=httpx.MockTransport(provider)) as runtime:
            assert (
                runtime.config.user_id == "111"
                and runtime.config is runtime.client.config
                and runtime.config is runtime.collector.client.config
                and await runtime.store.setting("account") == {"id": "111"}
                and runtime.collector.connected
                and runtime.collector.task is None
                and not runtime.config.missing_settings({})
            )
            await runtime.interactions.authorize({"interactions": {"replies": True}})
    assert [call.url.path for call in calls] == ["/2/users/me", "/2/users/me"]
    assert all(call.headers["authorization"] == "Bearer fake-user" for call in calls)


async def test_self_profile_is_saved_from_the_same_identity_request(self_config):
    calls = []

    async def provider(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "111",
                    "username": "aakash",
                    "name": "Aakash",
                    "secret_field": "discard",
                }
            },
        )

    async with Runtime(self_config, transport=httpx.MockTransport(provider)) as runtime:
        assert await runtime.store.setting("account") == {
            "id": "111",
            "username": "aakash",
            "name": "Aakash",
        }
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": "111"},
        {"user_token": ""},
        {"app_bearer": ""},
        {"app_bearer": "", "user_token": ""},
    ],
)
async def test_explicit_target_or_incomplete_credentials_make_no_identity_request(
    self_config, changes
):
    async def forbid(request):
        raise AssertionError("No identity lookup expected.")

    async with Runtime(replace(self_config, **changes), transport=httpx.MockTransport(forbid)):
        pass


async def saved_account(config):
    store = Store(config.database)
    await store.open()
    await store.save_setting("account", {"id": "999"})
    await store.save_setting("tracking", True)
    await store.close()


@pytest.mark.parametrize("failure", [401, 402, 403, 429, 500, "network", "malformed"])
async def test_discovery_failure_never_resumes_or_guesses_saved_account(self_config, failure):
    await saved_account(self_config)
    calls = []

    async def provider(request):
        calls.append(request)
        if failure == "network":
            raise httpx.ConnectError("fake-user")
        if failure == "malformed":
            return httpx.Response(200, json={"data": {"id": 111}, "detail": "fake-user"})
        return httpx.Response(failure, json={"detail": "fake-user"})

    async with Runtime(self_config, transport=httpx.MockTransport(provider)) as runtime:
        assert (
            runtime.collector.state == "reconnect"
            and not runtime.collector.connected
            and runtime.collector.task is None
            and runtime.config.user_id == ""
            and await runtime.store.setting("account") == {"id": "999"}
            and "fake-user" not in runtime.collector.message
        )
        with pytest.raises(SetupError, match="restart XFlog"):
            await runtime.collector.start()
        assert len(calls) == 1


async def test_discovery_failure_is_logged_without_credentials(self_config, caplog):
    async def provider(request):
        return httpx.Response(403, json={"detail": self_config.user_token})

    async with Runtime(self_config, transport=httpx.MockTransport(provider)) as runtime:
        messages = [
            record.getMessage() for record in caplog.records if record.name == "xflog.runtime"
        ]
        assert len(messages) == 1
        assert "GET /2/users/me" in messages[0] and "HTTP 403" in messages[0]
        assert "OAuth 2.0" in messages[0] and "OAuth 2.0" in runtime.collector.message
        assert (
            self_config.app_bearer not in messages[0] and self_config.user_token not in messages[0]
        )


async def test_resolved_account_cannot_replace_active_saved_account(self_config):
    await saved_account(self_config)

    async def provider(request):
        return httpx.Response(200, json={"data": {"id": "111"}})

    runtime = Runtime(self_config, transport=httpx.MockTransport(provider))
    with pytest.raises(SetupError, match="previous account"):
        async with runtime:
            pass
    async with Runtime(replace(self_config, app_bearer="", user_id="999")) as recovered:
        assert runtime.http.is_closed and await recovered.store.setting("account") == {"id": "999"}


async def test_duplicate_runtime_is_rejected_before_identity_read(self_config):
    calls = []

    async def provider(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"id": "111"}})

    async with Runtime(self_config, transport=httpx.MockTransport(provider)):
        with pytest.raises(RuntimeBusyError):
            async with Runtime(self_config, transport=httpx.MockTransport(provider)):
                pass
    assert len(calls) == 1


@pytest.mark.parametrize("message", [None, "", "Previous account lookup failed."])
async def test_collector_initializer_also_rejects_unresolved_saved_identity(self_config, message):
    await saved_account(self_config)
    store = Store(self_config.database)
    await store.open()

    async def forbid(request):
        raise AssertionError("An unresolved collector must not contact X.")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbid)) as http:
        collector = Collector(store, XClient(self_config, http))
        if message is not None:
            collector.state, collector.message = "reconnect", message
        try:
            await collector.initialize()
            assert collector.task is None and not collector.connected
        finally:
            await collector.shutdown()
            await store.close()


async def test_cancellation_during_discovery_cleans_up_without_saving_account(self_config):
    entered = asyncio.Event()

    async def provider(request):
        entered.set()
        await asyncio.Event().wait()

    runtime = Runtime(self_config, transport=httpx.MockTransport(provider))
    opening = asyncio.create_task(runtime.__aenter__())
    await asyncio.wait_for(entered.wait(), 1)
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening
    async with Runtime(replace(self_config, user_token="")) as recovered:
        assert (
            runtime.http.is_closed
            and runtime.store.db is None
            and await recovered.store.setting("account") is None
        )
