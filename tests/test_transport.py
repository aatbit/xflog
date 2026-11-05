import httpx
import pytest

from xflog.config import CoreConfig
from xflog.errors import SetupError
from xflog.tracking.transport import ProviderError, XClient


@pytest.mark.parametrize(
    ("kind", "user_token", "expected"),
    [
        ("follow.follow", "fake-user", "fake-user"),
        ("follow.unfollow", "fake-user", "fake-user"),
        ("post.create", "fake-user", "fake-user"),
        ("subscriptions.subscribe", "fake-user", "fake-user"),
        ("post.reply.create", "fake-user", "fake-user"),
        ("like.create", "fake-user", "fake-user"),
        ("follow.follow", "", "fake-app"),
        ("follow.unfollow", "", "fake-app"),
        ("post.create", "", "fake-app"),
    ],
)
async def test_subscription_prefers_supplied_user_token(tmp_path, kind, user_token, expected):
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"subscription_id": "test"}})

    config = CoreConfig(tmp_path / "history.sqlite3", app_bearer="fake-app", user_token=user_token)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        await XClient(config, http).request(
            "POST", "/2/activity/subscriptions", json={"event_type": kind}
        )
    assert calls[0].headers["authorization"] == f"Bearer {expected}"


@pytest.mark.parametrize("kind", ["subscriptions.subscribe", "like.create", "post.reply.create"])
async def test_private_subscription_never_falls_back_to_app_token(tmp_path, kind):
    def unexpected(request):
        pytest.fail("Private event must not make a request without a user token")

    config = CoreConfig(tmp_path / "history.sqlite3", app_bearer="fake-app")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
        with pytest.raises(SetupError, match="X_USER_ACCESS_TOKEN"):
            await XClient(config, http).request(
                "POST", "/2/activity/subscriptions", json={"event_type": kind}
            )


async def test_subscription_failure_logs_context_without_provider_body(tmp_path, caplog):
    def provider(request):
        return httpx.Response(
            400,
            json={
                "errors": [{"message": "OauthAccessTokenRequired: fake-app fake-user private-body"}]
            },
        )

    config = CoreConfig(tmp_path / "history.sqlite3", app_bearer="fake-app", user_token="fake-user")
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        with pytest.raises(ProviderError, match="Set X_USER_ACCESS_TOKEN") as error:
            await XClient(config, http).request(
                "POST", "/2/activity/subscriptions", json={"event_type": "follow.follow"}
            )
    output = str(error.value) + caplog.text
    assert "HTTP 400; event follow.follow" in output
    assert all(secret not in output for secret in ("fake-app", "fake-user", "private-body"))
