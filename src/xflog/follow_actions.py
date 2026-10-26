import asyncio
import re

from .errors import SetupError
from .transport import ProviderError

CONNECTIONS = {
    "following",
    "followed_by",
    "follow_request_sent",
    "follow_request_received",
    "blocking",
    "muting",
}


class FollowActions:
    """User-authorized outgoing actions, isolated from the incoming Activity listener."""

    def __init__(self, store, client):
        self.store = store
        self.client = client
        self.lock = asyncio.Lock()
        self.verified_account = False

    def configuration(self) -> dict:
        configured = bool(self.client.config.user_id and self.client.config.user_token.strip())
        return {
            "available": configured,
            "reason": ""
            if configured
            else "Requires X_USER_ID and X_USER_ACCESS_TOKEN with follows.read and follows.write.",
        }

    async def status(self) -> dict:
        return {
            "enabled": await self.store.setting("follow_actions", False) is True,
            **self.configuration(),
        }

    def validate_setting(self, enabled: bool):
        if enabled and not self.configuration()["available"]:
            raise SetupError(self.configuration()["reason"])

    async def configure(self, enabled: bool):
        async with self.lock:
            self.validate_setting(enabled)
            await self.store.save_setting("follow_actions", enabled)
            if not enabled:
                self.verified_account = False

    async def target(self, event_id: str) -> str:
        if await self.store.setting("follow_actions", False) is not True:
            raise SetupError("Enable Allow Follow/Unfollow in Profile first.")
        self.validate_setting(True)
        source = self.client.config.user_id
        account = await self.store.setting("account")
        if not isinstance(account, dict) or account.get("id") != source:
            raise SetupError(
                "Restart XFlog with the configured account before using follow actions."
            )
        target = await self.store.event_actor(source, event_id)
        if not isinstance(target, str) or not re.fullmatch(r"[0-9]{1,19}", target):
            raise SetupError("Choose a recorded person from this account's history.")
        if target == source:
            raise SetupError("You cannot follow or unfollow your own account.")
        return target

    async def request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.client.user_request(method, path, **kwargs)
        except ProviderError as error:
            if error.status == 401:
                self.verified_account = False
            messages = {
                400: "X rejected this follow action. Check your user token's permissions.",
                401: "X user access expired or was revoked. Replace X_USER_ACCESS_TOKEN and restart.",
                402: "X requires credits for this action. Check your Developer Console.",
                403: "X denied this action. Check user token scopes and your app's endpoint access.",
                404: "This X account is unavailable.",
                429: "X rate limit reached. Wait before checking or trying this action again.",
            }
            raise SetupError(messages.get(error.status, "X is unavailable. Check again later."))
        try:
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict) or body.get("errors"):
                raise ValueError
        except ValueError:
            raise SetupError("X returned an unreadable result. Check the relationship again.")
        return data

    async def verify_account(self):
        if not self.verified_account:
            account = await self.request("GET", "/2/users/me")
            if account.get("id") != self.client.config.user_id:
                raise SetupError("X_USER_ACCESS_TOKEN must belong to the account in X_USER_ID.")
            self.verified_account = True

    async def lookup(self, target: str) -> dict:
        data = await self.request(
            "GET", f"/2/users/{target}", params={"user.fields": "connection_status"}
        )
        connections = data.get("connection_status")
        if (
            data.get("id") != target
            or not isinstance(connections, list)
            or any(not isinstance(item, str) or item not in CONNECTIONS for item in connections)
            or (
                "following" in connections
                and bool({"follow_request_sent", "blocking"} & set(connections))
            )
        ):
            raise SetupError(
                "X did not supply the relationship. Check your user token's read permissions."
            )
        return {
            "following": "following" in connections,
            "pending": "follow_request_sent" in connections,
            "blocked": "blocking" in connections,
        }

    async def relationship(self, event_id: str) -> dict:
        async with self.lock:
            target = await self.target(event_id)
            await self.verify_account()
            return await self.lookup(target)

    async def change(self, event_id: str, following: bool) -> dict:
        async with self.lock:
            target = await self.target(event_id)
            await self.verify_account()
            current = await self.lookup(target)
            if current["blocked"]:
                raise SetupError("This account is blocked. Manage the block on X first.")
            if current["pending"]:
                raise SetupError("A follow request is pending. Manage it on X.")
            if current["following"] == following:
                return current
            path = f"/2/users/{self.client.config.user_id}/following"
            data = (
                await self.request("POST", path, json={"target_user_id": target})
                if following
                else await self.request("DELETE", f"{path}/{target}")
            )
            pending = data.get("pending_follow", None if following else False)
            if (
                type(data.get("following")) is not bool
                or type(pending) is not bool
                or (pending and data["following"])
                or (following and not data["following"] and not pending)
                or (not following and (data["following"] or pending))
            ):
                raise SetupError("X did not confirm the action. Check the relationship again.")
            return {"following": data["following"], "pending": pending, "blocked": False}
