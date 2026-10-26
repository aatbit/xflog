import asyncio
import json
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from .errors import SetupError
from .events import FOLLOW_TYPES, SUBSCRIPTION_TYPES, parse_event
from .transport import ProviderError, subscription_identity, subscription_result

DEFAULT_SELECTION = {"followers": True, "subscriptions": False, "notifications": False}


class Collector:
    """One application-owned consumer; browser tabs only read its committed history."""

    def __init__(self, store, client):
        self.store = store
        self.client = client
        self.lock = asyncio.Lock()
        self.task = None
        self.state = "stopped"
        self.message = "Tracking is stopped."
        self.connected = False
        self.notifications = 0

    async def initialize(self):
        account = await self.store.setting("account")
        target = self.client.config.user_id
        if target and (not account or account["id"] != target):
            if account and (
                await self.store.setting("tracking", False) or await self.store.subscriptions()
            ):
                raise SetupError(
                    "Pause and clean up the previous account before changing X_USER_ID."
                )
            account = {"id": target}
            await self.store.save_setting("account", account)
        self.connected = bool(target and self.client.config.app_bearer)
        self.message = (
            "Ready. Tracking is paused."
            if self.connected
            else "Instance setup is incomplete. Check the server configuration."
        )
        if (
            account
            and await self.store.setting("tracking", False)
            and not await self.store.restart_blocked()
        ):
            selection = await self.store.setting("selection", DEFAULT_SELECTION)
            if selection["subscriptions"] and not self.client.config.user_token:
                self.state = "reconnect"
                self.message = (
                    "Supply X_USER_ACCESS_TOKEN before resuming paid subscription events."
                )
                return
            await self.store.gap(
                account["id"], "Application was offline; recovery is not guaranteed."
            )
            if self.connected:
                self.task = asyncio.create_task(self.run())
            else:
                self.state = "reconnect"
                self.message = "Update the environment credentials and restart to resume."

    async def start(self):
        async with self.lock:
            if self.task and not self.task.done():
                return
            if not self.connected or not await self.store.setting("account"):
                raise SetupError("Configure X_USER_ID and X_APP_BEARER_TOKEN, then restart.")
            if not self.client.config.app_bearer:
                raise SetupError("Set X_APP_BEARER_TOKEN for this developer app before starting.")
            selection = await self.store.setting("selection", DEFAULT_SELECTION)
            if not selection["followers"] and not selection["subscriptions"]:
                raise SetupError("Enable at least one event category in Profile.")
            if selection["subscriptions"] and not self.client.config.user_token:
                raise SetupError(
                    "Paid subscription events require an externally authorized X_USER_ACCESS_TOKEN."
                )
            await self.store.save_setting("tracking", True)
            await self.store.allow_restart()
            self.state = "connecting"
            self.message = "Connecting to X Activity…"
            self.task = asyncio.create_task(self.run())

    async def cancel_task(self):
        if self.task:
            self.task.cancel()
            result = (await asyncio.gather(self.task, return_exceptions=True))[0]
            self.task = None
            if isinstance(result, Exception):
                self.message = "Previous collection ended unexpectedly. Cleanup is being attempted."

    async def shutdown(self):
        async with self.lock:
            await self.cancel_task()
            account = await self.store.setting("account")
            if account and await self.store.setting("tracking", False):
                await self.store.gap(account["id"], "Application closed; possible missed activity.")

    async def stop(self):
        async with self.lock:
            await self.cancel_task()
            self.state = "stopped"
            self.message = "Tracking is stopped. History is kept."
            persistence_error = None
            restart_blocked = False
            try:
                await self.store.block_restart()
                restart_blocked = True
            except OSError:
                pass
            try:
                await self.store.save_setting("tracking", False)
            except sqlite3.Error as error:
                persistence_error = error
            try:
                await self.remove_subscriptions()
                account = await self.store.setting("account")
                if account:
                    await self.store.gap(
                        account["id"], "Tracking paused; possible missed activity."
                    )
            except sqlite3.Error as error:
                persistence_error = error
            if persistence_error:
                self.state = "error"
                self.message = "Collection stopped, but local state could not be saved. Repair the database before restarting."
                self.message += (
                    " Automatic resume is blocked until an explicit Start."
                    if restart_blocked
                    else " Restart could resume collection; remove the environment credentials before restarting."
                )
                raise persistence_error

    async def discover_owned(self, account: dict) -> list[dict]:
        tag = await self.store.setting("tag")
        if not tag:
            return []
        owned = []
        token = None
        for _ in range(20):
            params = {"user_id": account["id"], "max_results": 1000}
            if token:
                params["pagination_token"] = token
            response = await self.client.request("GET", "/2/activity/subscriptions", params=params)
            body = response.json()
            if not isinstance(body, dict):
                raise SetupError("X returned unreadable subscription metadata.")
            metadata = body.get("meta", {})
            if (
                not isinstance(metadata, dict)
                or body.get("errors")
                or not isinstance(body.get("data", []), list)
            ):
                raise SetupError("X returned incomplete subscription metadata.")
            for item in body.get("data", []):
                if not isinstance(item, dict) or not isinstance(item.get("filter"), dict):
                    raise SetupError("X returned unreadable subscription filters.")
                if (
                    item.get("tag") == tag
                    and item.get("filter", {}).get("user_id") == account["id"]
                ):
                    identity = subscription_identity(item.get("subscription_id"))
                    if not isinstance(item.get("event_type"), str):
                        raise SetupError("X returned unreadable subscription event metadata.")
                    owned.append(
                        {
                            "id": identity,
                            "kind": item["event_type"],
                            "account_id": account["id"],
                            "expires_at": item.get("expires_at"),
                            "tag": tag,
                        }
                    )
            token = metadata.get("next_token")
            if token is not None and not isinstance(token, str):
                raise SetupError("X returned unreadable subscription pagination.")
            if not token:
                return owned
        raise SetupError("X subscription pagination exceeded its safety bound.")

    async def remove_subscriptions(self):
        failures = 0
        saved = {item["id"]: item for item in await self.store.subscriptions()}
        account = await self.store.setting("account")
        if account and self.connected:
            try:
                for item in await self.discover_owned(account):
                    saved[item["id"]] = item
            except (ProviderError, httpx.HTTPError, SetupError, ValueError, KeyError):
                failures += 1
        persistence_error = None
        for subscription in saved.values():
            try:
                await self.store.save_subscription(subscription)
            except sqlite3.Error as error:
                persistence_error = error
            try:
                await self.client.delete_subscription(subscription["id"])
                await self.store.forget_subscription(subscription["id"])
            except ProviderError as error:
                if error.status == 404:
                    await self.store.forget_subscription(subscription["id"])
                else:
                    failures += 1
            except (httpx.HTTPError, SetupError, ValueError):
                failures += 1
            except sqlite3.Error as error:
                persistence_error = error
        warning = (
            "Remote cleanup incomplete. Verify credentials and retry Pause; owned leases expire within 24 hours."
            if failures
            else ""
        )
        await self.store.save_setting("cleanup_warning", warning)
        if warning:
            self.message = warning
        if persistence_error:
            raise persistence_error

    async def reconcile(self, account: dict, kinds: tuple):
        tag = await self.store.setting("tag")
        if not tag:
            tag = f"xflog-{uuid.uuid4().hex[:16]}"
            await self.store.save_setting("tag", tag)
        for item in await self.discover_owned(account):
            await self.store.save_subscription(item)
        for saved in await self.store.subscriptions():
            if saved["account_id"] != account["id"] or saved["kind"] not in kinds:
                await self.client.delete_subscription(saved["id"])
                await self.store.forget_subscription(saved["id"])
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        for kind in kinds:
            # Bound orphan lifetime; repeating POST refreshes the documented subscription identity.
            response = await self.client.request(
                "POST",
                "/2/activity/subscriptions",
                json={
                    "event_type": kind,
                    "filter": {
                        "user_id": account["id"],
                        "qualifiers": {"direction": "inbound"},
                    },
                    "tag": tag,
                    "expires_at": expires,
                },
            )
            result = subscription_result(response.json())
            await self.store.save_subscription(
                {
                    "id": result["subscription_id"],
                    "kind": kind,
                    "account_id": account["id"],
                    "expires_at": result.get("expires_at", expires),
                    "tag": tag,
                }
            )

    async def run(self):
        delay = 1
        account = await self.store.setting("account")
        selection = await self.store.setting("selection", DEFAULT_SELECTION)
        kinds = (FOLLOW_TYPES if selection["followers"] else ()) + (
            SUBSCRIPTION_TYPES if selection["subscriptions"] else ()
        )
        while True:
            try:
                self.state = "connecting"
                await self.reconcile(account, kinds)
                # Reconnect every six hours to refresh the 24-hour subscription lease.
                async with asyncio.timeout(6 * 3600):
                    async for raw in self.client.stream():
                        if raw is None:
                            self.state = "tracking"
                            self.message = "Listening for incoming activity."
                            await self.store.end_gap(account["id"])
                            continue
                        event = parse_event(raw, account["id"])
                        if event and event.kind in kinds and await self.store.insert(event):
                            self.notifications += 1
                        delay = 1
                raise httpx.ReadError("Stream ended")
            except ProviderError as error:
                if error.status in {400, 401, 402, 403}:
                    await self.fail(account, str(error))
                    return
                delay = max(delay, error.delay)
                self.message = str(error)
            except SetupError as error:
                await self.fail(account, str(error))
                return
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                await self.fail(
                    account,
                    "Unrecognized X event data. Tracking stopped to protect history.",
                )
                return
            except sqlite3.Error:
                self.state = "error"
                self.message = (
                    "Local database write failed. Tracking stopped; check disk space and access."
                )
                return
            except (httpx.HTTPError, TimeoutError):
                self.message = (
                    "Connection interrupted. Retrying; missed events may not be recoverable."
                )
            self.state = "reconnecting"
            try:
                await self.store.gap(account["id"], self.message)
            except sqlite3.Error:
                self.state = "error"
                self.message = "Cannot record connection gap. Check the local database."
                return
            await asyncio.sleep(min(900, delay) + random.uniform(0, 0.5))
            delay = min(900, delay * 2)

    async def fail(self, account: dict, message: str):
        self.state = "reconnect"
        self.message = message
        await self.store.save_setting("tracking", False)
        await self.store.gap(account["id"], message)
