import asyncio
import sqlite3
from dataclasses import replace
from urllib.parse import parse_qs

import httpx
import pytest

from xflog import CoreConfig, Runtime, SetupError
from xflog.config import Config
from xflog.history.store import Store
from xflog.tracking.tokens import OAuthTokens
from xflog.tracking.transport import ProviderError, XClient


def token_pair(**changes):
    return {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "token_type": "bearer",
        "expires_in": 7200,
        **changes,
    }


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return CoreConfig(
        tmp_path / "history.sqlite3",
        app_bearer="app-secret",
        user_token="old-access",
        user_refresh_token="old-refresh",
        client_id="client-id",
    )


@pytest.fixture
async def store(config):
    result = Store(config.database)
    await result.open()
    try:
        yield result
    finally:
        await result.close()


async def test_runtime_renews_rejected_token_and_reuses_rotated_pair_after_restart(config):
    calls = []

    def provider(request):
        calls.append(request)
        if request.url.path == "/2/oauth2/token":
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["refresh_token"],
                "refresh_token": ["old-refresh"],
                "client_id": ["client-id"],
            }
            assert "authorization" not in request.headers
            return httpx.Response(200, json=token_pair())
        assert request.url.path == "/2/users/me"
        return httpx.Response(
            401 if request.headers["authorization"] == "Bearer old-access" else 200,
            json={"data": {"id": "111", "name": "You", "username": "you"}},
        )

    for _ in range(2):
        async with Runtime(config, transport=httpx.MockTransport(provider)) as runtime:
            assert runtime.config.user_id == "111" and not runtime.identity_error
            assert runtime.collector.task is None
    assert [r.url.path for r in calls].count("/2/oauth2/token") == 1
    assert calls[-1].headers["authorization"] == "Bearer new-access"
    assert config.database.stat().st_mode & 0o777 == 0o600


async def test_concurrent_401_responses_share_one_refresh(config, store):
    count = 0

    async def provider(request):
        nonlocal count
        if request.url.path == "/2/oauth2/token":
            count += 1
            await asyncio.sleep(0)
            return httpx.Response(200, json=token_pair())
        return httpx.Response(
            200 if request.headers["authorization"] == "Bearer new-access" else 401
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        client = XClient(config, http, tokens=OAuthTokens(config, http, store))
        responses = await asyncio.gather(
            *(client.user_request("GET", "/2/users/me") for _ in range(8))
        )
    assert count == 1 and all(r.status_code == 200 for r in responses)


async def test_known_expiry_renews_before_request_and_confidential_client_uses_basic(config, store):
    config = replace(config, client_secret="client-secret")
    requests = []

    def provider(request):
        requests.append(request)
        if request.url.path == "/2/oauth2/token":
            assert request.headers["authorization"].startswith("Basic ")
            assert "client_id" not in parse_qs(request.content.decode())
            return httpx.Response(200, json=token_pair())
        assert request.headers["authorization"] == "Bearer new-access"
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        tokens = OAuthTokens(config, http, store)
        await store.save_setting(
            "oauth_tokens",
            {
                "fingerprint": tokens.fingerprint,
                "access_token": "cached-expired",
                "refresh_token": "rotated-refresh",
                "expires_at": 1,
            },
        )
        await XClient(config, http, tokens=tokens).user_request("GET", "/2/users/me")
    assert [r.url.path for r in requests] == ["/2/oauth2/token", "/2/users/me"]


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 302])
async def test_failed_refresh_is_not_replayed_after_restart(config, store, status, caplog):
    calls = []

    def provider(request):
        calls.append(request.url.path)
        if request.url.path == "/2/oauth2/token":
            return httpx.Response(status, json={"error_description": "old-refresh client-secret"})
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        for _ in range(2):
            client = XClient(config, http, tokens=OAuthTokens(config, http, store))
            with pytest.raises(SetupError, match="fresh OAuth access/refresh") as error:
                await client.user_request("GET", "/2/users/me")
            assert "old-refresh" not in str(error.value)
    assert calls == ["/2/users/me", "/2/oauth2/token"] and "old-refresh" not in caplog.text


@pytest.mark.parametrize(
    "changes",
    [
        {"access_token": "bad\nheader"},
        {"refresh_token": None},
        {"expires_in": True},
        {"expires_in": -1},
        {"expires_in": "7200"},
        {"token_type": "Basic"},
    ],
)
async def test_invalid_exchange_never_uses_unvalidated_token(config, store, changes):
    calls = []

    def provider(request):
        calls.append(request.url.path)
        return (
            httpx.Response(200, json=token_pair(**changes))
            if request.url.path.endswith("/token")
            else httpx.Response(401)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        with pytest.raises(SetupError):
            await XClient(config, http, tokens=OAuthTokens(config, http, store)).user_request(
                "GET", "/2/users/me"
            )
    assert calls == ["/2/users/me", "/2/oauth2/token"]


async def test_cancelled_browser_waits_for_durable_rotation(config, store):
    entered, release = asyncio.Event(), asyncio.Event()

    async def provider(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json=token_pair())

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        tokens = OAuthTokens(config, http, store)
        task = asyncio.create_task(tokens.refresh("old-access"))
        await entered.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        saved = await store.setting("oauth_tokens")
        assert saved["refresh_token"] == "new-refresh" and not saved.get("pending")


async def test_storage_failure_keeps_exchange_blocked_without_issuing_unsaved_token(
    config, store, monkeypatch
):
    save = store.save_setting
    writes = 0

    async def failing(key, value):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise sqlite3.OperationalError("disk full")
        await save(key, value)

    monkeypatch.setattr(store, "save_setting", failing)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=token_pair()))
    ) as http:
        tokens = OAuthTokens(config, http, store)
        with pytest.raises(sqlite3.OperationalError):
            await tokens.refresh("old-access")
        with pytest.raises(SetupError):
            await OAuthTokens(config, http, store).access_token()


async def test_new_seed_pair_overrides_cached_failed_grant(config, store):
    async with httpx.AsyncClient() as http:
        first = OAuthTokens(config, http, store)
        await store.save_setting(
            "oauth_tokens", {"fingerprint": first.fingerprint, "pending": True}
        )
        fresh = replace(
            config, user_token="operator-new-access", user_refresh_token="operator-new-refresh"
        )
        assert await OAuthTokens(fresh, http, store).access_token() == "operator-new-access"


async def test_delayed_rejection_of_old_token_cannot_block_a_newer_pair(config, store):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=token_pair()))
    ) as http:
        tokens = OAuthTokens(config, http, store)
        await tokens.refresh("old-access")
        await tokens.block("old-access")
        assert await tokens.access_token() == "new-access"
        assert not (await store.setting("oauth_tokens")).get("pending")


async def test_app_bearer_failure_and_disabled_refresh_do_not_exchange(config, store):
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        client = XClient(config, http, tokens=OAuthTokens(config, http, store))
        with pytest.raises(ProviderError):
            await client.request("GET", "/2/activity/subscriptions")
        disabled = replace(config, user_refresh_token="")
        with pytest.raises(ProviderError):
            await XClient(disabled, http, tokens=OAuthTokens(disabled, http, store)).user_request(
                "GET", "/2/users/me"
            )
    assert len(requests) == 2 and not await store.setting("oauth_tokens")


async def test_fresh_token_rejected_again_blocks_further_refresh_loops(config, store):
    calls = []

    def provider(request):
        calls.append(request.url.path)
        return (
            httpx.Response(200, json=token_pair())
            if request.url.path.endswith("/token")
            else httpx.Response(401)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        client = XClient(config, http, tokens=OAuthTokens(config, http, store))
        with pytest.raises(ProviderError):
            await client.user_request("GET", "/2/users/me")
        with pytest.raises(SetupError):
            await client.user_request("GET", "/2/users/me")
    assert calls == ["/2/users/me", "/2/oauth2/token", "/2/users/me"]


def test_refresh_configuration_is_private_and_environment_driven(config, monkeypatch):
    for key, value in {
        "X_USER_ACCESS_TOKEN": "old-access",
        "X_USER_REFRESH_TOKEN": "old-refresh",
        "X_CLIENT_ID": "client-id",
        "X_CLIENT_SECRET": "client-secret",
    }.items():
        monkeypatch.setenv(key, value)
    core = CoreConfig.from_env()
    assert core.user_refresh_token == "old-refresh"
    assert core.client_id == "client-id" and core.client_secret == "client-secret"
    assert all(
        value not in repr(core)
        for value in ["old-access", "old-refresh", "client-id", "client-secret"]
    )
    with pytest.raises(ValueError, match="needs X_CLIENT_ID"):
        replace(config, client_id="")


async def test_only_a_definite_401_can_retry_a_mutating_user_request(config, store):
    calls = []

    def provider(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json=token_pair())
        if request.headers["authorization"] == "Bearer old-access":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": {"following": True}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        client = XClient(config, http, tokens=OAuthTokens(config, http, store))
        await client.user_request("POST", "/2/users/111/following", json={"target_user_id": "222"})
    assert [path for _, path, _ in calls] == [
        "/2/users/111/following",
        "/2/oauth2/token",
        "/2/users/111/following",
    ]


async def test_uncertain_mutation_network_error_does_not_refresh_or_retry(config, store):
    calls = []

    def provider(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("request might have completed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        client = XClient(config, http, tokens=OAuthTokens(config, http, store))
        with pytest.raises(httpx.ReadTimeout):
            await client.user_request(
                "POST", "/2/users/111/following", json={"target_user_id": "222"}
            )
    assert calls == ["/2/users/111/following"]


async def test_lost_refresh_response_is_not_replayed(config, store):
    calls = []

    def provider(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("old-refresh must not be echoed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        tokens = OAuthTokens(config, http, store)
        with pytest.raises(SetupError):
            await tokens.refresh("old-access")
        with pytest.raises(SetupError):
            await OAuthTokens(config, http, store).refresh("old-access")
    assert calls == ["/2/oauth2/token"]


async def test_cannot_exchange_before_pending_claim_is_saved(config, store, monkeypatch):
    async def fail(*args):
        raise sqlite3.OperationalError("read only")

    monkeypatch.setattr(store, "save_setting", fail)

    def forbid(request):
        pytest.fail("No token grant before the durable claim")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbid)) as http:
        with pytest.raises(sqlite3.OperationalError):
            await OAuthTokens(config, http, store).refresh("old-access")


async def test_cached_credentials_never_appear_in_browser_status(config):
    from xflog.app import create_app

    settings = Config(**vars(config))

    def provider(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json=token_pair())
        return httpx.Response(
            200 if request.headers["authorization"] == "Bearer new-access" else 401,
            json={"data": {"id": "111"}},
        )

    app = create_app(settings, transport=httpx.MockTransport(provider), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=settings.origin
        ) as browser,
    ):
        await browser.get("/")
        response = await browser.get("/api/status")
        assert response.status_code == 200
        assert all(
            secret not in response.text
            for secret in ["old-access", "old-refresh", "new-access", "new-refresh", "oauth_tokens"]
        )


async def test_public_runtime_keeps_support_for_externally_managed_user_tokens(tmp_path):
    config = CoreConfig(
        tmp_path / "manual.sqlite3",
        app_bearer="manual-app",
        user_id="111",
        user_token="manual-user",
    )
    calls = []

    def provider(request):
        calls.append(request.url.path)
        assert request.headers["authorization"] == "Bearer manual-user"
        return httpx.Response(200, json={"data": {"id": "111"}})

    async with Runtime(config, transport=httpx.MockTransport(provider)) as runtime:
        assert not runtime.client.tokens.enabled
        await runtime.client.user_request("GET", "/2/users/me")
    assert calls == ["/2/users/me"]
