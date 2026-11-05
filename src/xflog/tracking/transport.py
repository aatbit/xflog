import json
import logging
import re
import time

import httpx

from ..config import API_ROOT, CoreConfig
from ..errors import SetupError
from ..interactions import PRIVATE_POSTS, numeric
from .events import HANDLE

logger = logging.getLogger(__name__)


def user_profile(data: dict) -> dict:
    profile = {"id": data["id"]}
    if isinstance(data.get("username"), str) and HANDLE.fullmatch(data["username"]):
        profile["username"] = data["username"]
    if isinstance(data.get("name"), str):
        profile["name"] = data["name"][:200]
    return profile


def provider_http(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=20, transport=transport, trust_env=False, follow_redirects=False
    )


class ProviderError(Exception):
    def __init__(self, status: int, delay: float = 0, message: str = ""):
        self.status = status
        self.delay = min(900, max(0, delay))
        messages = {
            400: "X rejected the request. Check app settings and event filters.",
            401: "X access expired or was revoked. Update the environment credentials and restart.",
            403: "X denied access. Verify app permissions, Activity eligibility and billing.",
            402: "X requires credits or billing access. Review your Developer Console.",
            429: "X rate limit reached. Collection will retry after the provider wait.",
        }
        super().__init__(
            message or messages.get(status, "X is unavailable. Collection will retry.")
        )


def check_response(response: httpx.Response):
    if response.is_success:
        return
    delay = 0
    try:
        delay = float(response.headers.get("retry-after", 0))
        delay = max(delay, float(response.headers.get("x-rate-limit-reset", 0)) - time.time())
    except ValueError:
        pass
    message = ""
    if response.status_code == 400 and response.is_stream_consumed:
        try:
            body = response.json()
            errors = body.get("errors", []) if isinstance(body, dict) else []
            if isinstance(errors, list) and any(
                isinstance(error, dict)
                and str(error.get("message", "")).startswith("OauthAccessTokenRequired:")
                for error in errors
            ):
                message = (
                    "X requires a user access token for this event on your app. "
                    "Set X_USER_ACCESS_TOKEN to an OAuth 2.0 user token and restart XFlog."
                )
        except ValueError:
            pass
    raise ProviderError(response.status_code, delay, message)


def subscription_identity(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise SetupError("X returned no valid subscription ID; check app subscriptions.")
    return value


def subscription_result(body: dict) -> dict:
    if not isinstance(body, dict):
        raise SetupError("X returned unreadable subscription metadata.")
    data = body.get("data", {})
    if isinstance(data, dict):
        data = data.get("subscription", data)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise SetupError("X returned unreadable subscription metadata.")
    subscription_identity(data.get("subscription_id"))
    return data


class XClient:
    def __init__(self, config: CoreConfig, http: httpx.AsyncClient, *, tokens=None):
        self.config = config
        self.http = http
        self.tokens = tokens

    async def lookup_user_id(self, handle: str | None = None) -> str:
        return (await self.lookup_user(handle))["id"]

    async def lookup_user(self, handle: str | None = None) -> dict:
        """One explicit user read; None resolves the supplied OAuth 2.0 user token."""
        if handle is None:
            if not self.config.user_token.strip():
                raise SetupError(
                    "--me requires X_USER_ACCESS_TOKEN (OAuth 2.0). "
                    "An app bearer token has no current user."
                )
            response = await self.user_request("GET", "/2/users/me")
        else:
            handle = handle.strip().removeprefix("@")
            if not HANDLE.fullmatch(handle):
                raise SetupError("Enter an X handle using 1–15 letters, numbers or underscores.")
            if not self.config.app_bearer.strip():
                raise SetupError("Set X_APP_BEARER_TOKEN before looking up an @handle.")
            response = await self.request("GET", f"/2/users/by/username/{handle}")
        try:
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict) or body.get("errors") or not numeric(data.get("id")):
                raise ValueError
            if handle is not None and (
                not isinstance(data.get("username"), str)
                or data["username"].lower() != handle.lower()
            ):
                raise ValueError
        except ValueError:
            raise SetupError("X did not return a valid matching user. No ID was saved.") from None
        return user_profile(data)

    async def lookup_users(self, identities: list[str]) -> list[dict]:
        if not identities:
            return []
        if len(identities) > 100 or not all(numeric(identity) for identity in identities):
            raise SetupError("Profile lookup needs at most 100 valid user IDs.")
        identities = list(dict.fromkeys(identities))
        response = await self.request(
            "GET",
            "/2/users",
            params={"ids": ",".join(identities), "user.fields": "id,name,username"},
        )
        try:
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("errors", []), list):
                raise ValueError
            users = body.get("data", [])
            if not isinstance(users, list) or len(users) > len(identities):
                raise ValueError
            if any(
                not isinstance(user, dict) or user.get("id") not in identities for user in users
            ):
                raise ValueError
            if len({user["id"] for user in users}) != len(users):
                raise ValueError
        except ValueError:
            raise SetupError(
                "X returned unreadable profile details. Saved history is kept."
            ) from None
        return [user_profile(user) for user in users]

    async def request(self, method: str, path: str, **kwargs):
        event_type = kwargs.get("json", {}).get("event_type", "")
        private_event = (
            event_type.startswith(("subscriptions.", "like.")) or event_type in PRIVATE_POSTS
        )
        token = self.config.app_bearer
        if private_event or (event_type and self.config.user_token):
            return await self.user_request(method, path, **kwargs)
        if not token:
            raise SetupError(
                "Set X_USER_ACCESS_TOKEN for paid events, or X_APP_BEARER_TOKEN for follower events."
            )
        return await self.authorized_request(method, path, token, **kwargs)

    async def user_request(self, method: str, path: str, **kwargs):
        if not self.config.user_token:
            raise SetupError("Set X_USER_ACCESS_TOKEN to use Follow/Unfollow.")
        token = await self.tokens.access_token() if self.tokens else self.config.user_token
        try:
            return await self.authorized_request(method, path, token, **kwargs)
        except ProviderError as error:
            if error.status != 401 or not self.tokens or not self.tokens.enabled:
                raise
        token = await self.tokens.refresh(token)
        try:
            return await self.authorized_request(method, path, token, **kwargs)
        except ProviderError as error:
            if error.status == 401:
                await self.tokens.block(token)
            raise

    async def authorized_request(self, method: str, path: str, token: str, **kwargs):
        response = await self.http.request(
            method, f"{API_ROOT}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        try:
            check_response(response)
        except ProviderError as error:
            logger.warning(
                "X request failed: %s %s (HTTP %s; event %s): %s",
                method,
                path,
                error.status,
                kwargs.get("json", {}).get("event_type", "none"),
                error,
            )
            raise
        return response

    async def delete_subscription(self, identity: str):
        subscription_identity(identity)
        response = await self.request("DELETE", f"/2/activity/subscriptions/{identity}")
        if response.status_code == 204:
            return
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or data.get("deleted") is not True:
            raise SetupError("X did not confirm removal. Remote cleanup remains incomplete.")

    async def stream(self):
        timeout = httpx.Timeout(20, read=45)
        async with self.http.stream(
            "GET",
            f"{API_ROOT}/2/activity/stream",
            timeout=timeout,
            headers={"Authorization": f"Bearer {self.config.app_bearer}"},
        ) as response:
            check_response(response)
            yield None  # A successful HTTP connection closes the current local gap.
            pending = bytearray()
            async for chunk in response.aiter_bytes():
                pending.extend(chunk)
                if len(pending) > 1_048_576:
                    raise SetupError("X sent an oversized event. Collection stopped safely.")
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    if line.strip():
                        try:
                            yield json.loads(line)
                        except (ValueError, UnicodeDecodeError):
                            raise SetupError(
                                "X sent unreadable event data. Collection stopped safely."
                            )
