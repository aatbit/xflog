"""Single-account domain services, reusable without the HTTP or browser interface."""

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from types import TracebackType
from typing import AsyncIterator, Self

import httpx

from .config import CoreConfig
from .errors import SetupError
from .history.store import Store
from .interactions.history import InteractionHistory
from .ownership import runtime_ownership
from .tracking.collector import Collector
from .tracking.follow_actions import FollowActions
from .tracking.tokens import OAuthTokens
from .tracking.transport import ProviderError, XClient, provider_http

logger = logging.getLogger(__name__)


class Runtime:
    """Single-use async context owning the database, HTTP client and listener.

    Entering may resume a previously started listener. A new database stays paused.
    Raises RuntimeBusyError for duplicate ownership, SetupError for incompatible
    saved state, and OSError/sqlite3.Error for local storage failures.
    """

    def __init__(
        self, config: CoreConfig, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.store = Store(config.database)
        self.http = provider_http(transport)
        self.client = XClient(config, self.http, tokens=OAuthTokens(config, self.http, self.store))
        self.follow_actions = FollowActions(self.store, self.client)
        self.interactions = InteractionHistory(self.store, self.follow_actions)
        self.collector = Collector(self.store, self.client, self.interactions)
        self.identity_error = ""
        self._account_profile = None
        self._used = False
        self._resources: AsyncExitStack | None = None

    @property
    def config(self) -> CoreConfig:
        return self.client.config

    async def _resolve_account(self) -> bool:
        config = self.config
        if config.user_id or not (config.user_token.strip() and config.app_bearer.strip()):
            return True
        try:
            profile = await self.client.lookup_user()
        except ProviderError as error:
            self.identity_error = f"X account lookup failed (HTTP {error.status})."
            if error.status in {401, 403}:
                self.identity_error += (
                    " Use an OAuth 2.0 user access token with users.read and tweet.read."
                )
        except httpx.HTTPError:
            self.identity_error = "Could not reach X to identify your account."
        except SetupError as error:
            self.identity_error = str(error)
        else:
            self.client.config = replace(config, user_id=profile["id"])
            self._account_profile = profile
            self.follow_actions.verified_account = True
            return True
        self.identity_error += " Check the user token, permissions and credits, then restart XFlog."
        logger.warning("GET /2/users/me: %s", self.identity_error)
        self.collector.state = "reconnect"
        self.collector.message = self.identity_error
        return False

    async def __aenter__(self) -> Self:
        if self._used:
            raise RuntimeError("Runtime instances are single-use; create a new Runtime.")
        self._used = True
        resources = AsyncExitStack()
        try:
            resources.enter_context(runtime_ownership(self.config))
        except BaseException:
            await self.http.aclose()
            raise
        resources.push_async_callback(self.store.close)
        resources.push_async_callback(self.http.aclose)
        try:
            await self.store.open()
            resources.push_async_callback(self.collector.shutdown)
            if await self._resolve_account():
                await self.collector.initialize()
                if self._account_profile is not None:
                    account = await self.store.setting("account")
                    await self.store.save_setting("account", {**account, **self._account_profile})
        except BaseException:
            await self._close(resources)
            raise
        self._resources = resources
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        resources, self._resources = self._resources, None
        if resources is not None:
            await self._close(resources)

    @staticmethod
    async def _close(resources: AsyncExitStack) -> None:
        # Ownership must outlive cleanup, even if the caller cancels during shutdown.
        cleanup = asyncio.create_task(resources.aclose())
        cancelled = None
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as error:
                cancelled = error
        cleanup.result()
        if cancelled is not None:
            raise cancelled

    @asynccontextmanager
    async def lifespan(self, app=None) -> AsyncIterator[None]:
        """ASGI-compatible adapter; library callers can use ``async with runtime``."""
        async with self:
            yield
