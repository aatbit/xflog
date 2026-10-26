import json
import re
import time

import httpx

from .config import API_ROOT, Config
from .errors import SetupError


class ProviderError(Exception):
    def __init__(self, status: int, delay: float = 0):
        self.status = status
        self.delay = min(900, max(0, delay))
        messages = {
            400: "X rejected the request. Check app settings and event filters.",
            401: "X access expired or was revoked. Update the environment credentials and restart.",
            403: "X denied access. Verify app permissions, Activity eligibility and billing.",
            402: "X requires credits or billing access. Review your Developer Console.",
            429: "X rate limit reached. Collection will retry after the provider wait.",
        }
        super().__init__(messages.get(status, "X is unavailable. Collection will retry."))


def check_response(response: httpx.Response):
    if response.is_success:
        return
    delay = 0
    try:
        delay = float(response.headers.get("retry-after", 0))
        delay = max(delay, float(response.headers.get("x-rate-limit-reset", 0)) - time.time())
    except ValueError:
        pass
    raise ProviderError(response.status_code, delay)


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
    def __init__(self, config: Config, http: httpx.AsyncClient):
        self.config = config
        self.http = http

    async def request(self, method: str, path: str, **kwargs):
        event_type = kwargs.get("json", {}).get("event_type", "")
        token = (
            self.config.user_token
            if event_type.startswith("subscriptions.")
            else self.config.app_bearer
        )
        if not token:
            raise SetupError(
                "Set X_USER_ACCESS_TOKEN for paid events, or X_APP_BEARER_TOKEN for follower events."
            )
        return await self.authorized_request(method, path, token, **kwargs)

    async def user_request(self, method: str, path: str, **kwargs):
        if not self.config.user_token:
            raise SetupError("Set X_USER_ACCESS_TOKEN to use Follow/Unfollow.")
        return await self.authorized_request(method, path, self.config.user_token, **kwargs)

    async def authorized_request(self, method: str, path: str, token: str, **kwargs):
        response = await self.http.request(
            method, f"{API_ROOT}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        check_response(response)
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
