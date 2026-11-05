"""Optional server-side renewal of externally authorized OAuth credentials."""

import asyncio
import hashlib
import json
import logging
import math
import time

import httpx

from ..config import API_ROOT
from ..errors import SetupError

logger = logging.getLogger(__name__)
RENEWAL_MARGIN = 60
RENEWAL_HELP = (
    "X token renewal could not complete safely. Supply a fresh OAuth access/refresh token pair "
    "with offline.access, check the OAuth client settings, then restart XFlog."
)


def valid_token(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 8192
        and all(33 <= ord(character) <= 126 for character in value)
    )


class OAuthTokens:
    def __init__(self, config, http, store):
        self.config, self.http, self.store = config, http, store
        self.enabled = bool(config.user_refresh_token)
        self.lock = asyncio.Lock()
        self.state = None
        self.fingerprint = hashlib.sha256(
            json.dumps(
                [
                    config.app_bearer,
                    config.client_id,
                    config.client_secret,
                    config.user_token,
                    config.user_refresh_token,
                ]
            ).encode()
        ).hexdigest()

    async def load(self):
        if self.state is None:
            saved = await self.store.setting("oauth_tokens", {})
            if not isinstance(saved, dict):
                raise SetupError(RENEWAL_HELP)
            self.state = (
                saved
                if saved.get("fingerprint") == self.fingerprint
                else {
                    "fingerprint": self.fingerprint,
                    "access_token": self.config.user_token,
                    "refresh_token": self.config.user_refresh_token,
                    "expires_at": None,
                }
            )
        if self.state.get("pending"):
            raise SetupError(RENEWAL_HELP)
        expiry = self.state.get("expires_at")
        if not all(valid_token(self.state.get(key)) for key in ("access_token", "refresh_token")):
            raise SetupError(RENEWAL_HELP)
        if expiry is not None and (
            type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= 0
        ):
            raise SetupError(RENEWAL_HELP)

    async def access_token(self):
        if not self.enabled:
            return self.config.user_token
        async with self.lock:
            await self.load()
            expiry = self.state["expires_at"]
            if expiry is not None and expiry <= time.time() + RENEWAL_MARGIN:
                await self.renew()
            return self.state["access_token"]

    async def refresh(self, rejected):
        async with self.lock:
            await self.load()
            if rejected == self.state["access_token"]:
                await self.renew()
            return self.state["access_token"]

    async def block(self, rejected):
        async with self.lock:
            if self.state["access_token"] != rejected:
                return
            self.state = {**self.state, "pending": True}
            await self.store.save_setting("oauth_tokens", self.state)

    async def renew(self):
        exchange = asyncio.create_task(self.exchange())
        cancelled = None
        while not exchange.done():
            try:
                await asyncio.shield(exchange)
            except asyncio.CancelledError as error:
                cancelled = error
        exchange.result()
        if cancelled is not None:
            raise cancelled

    async def exchange(self):
        # Claim durably before a possibly rotating exchange; an interrupted grant must not replay.
        self.state = {**self.state, "pending": True}
        await self.store.save_setting("oauth_tokens", self.state)
        options = {
            "data": {
                "grant_type": "refresh_token",
                "refresh_token": self.state["refresh_token"],
            }
        }
        if self.config.client_secret:
            options["auth"] = httpx.BasicAuth(self.config.client_id, self.config.client_secret)
        else:
            options["data"]["client_id"] = self.config.client_id
        try:
            response = await self.http.post(f"{API_ROOT}/2/oauth2/token", **options)
            if not response.is_success:
                raise SetupError(
                    f"X token renewal failed (HTTP {response.status_code}). {RENEWAL_HELP}"
                )
            body = response.json()
            if not isinstance(body, dict) or not all(
                valid_token(body.get(key)) for key in ("access_token", "refresh_token")
            ):
                raise ValueError
            expiry = body.get("expires_in")
            if (
                type(expiry) is not int
                or not 0 < expiry <= 2**31
                or not isinstance(body.get("token_type"), str)
                or body["token_type"].lower() != "bearer"
            ):
                raise ValueError
        except (httpx.HTTPError, ValueError):
            raise SetupError(RENEWAL_HELP) from None
        saved = {
            "fingerprint": self.fingerprint,
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "expires_at": time.time() + expiry,
        }
        await self.store.save_setting("oauth_tokens", saved)
        self.state = saved
        logger.info("X user token renewed and saved privately.")
