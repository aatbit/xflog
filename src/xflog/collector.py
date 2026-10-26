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


def selected_kinds(selection: dict) -> tuple:
    return (FOLLOW_TYPES if selection["followers"] else ()) + (
        SUBSCRIPTION_TYPES if selection["subscriptions"] else ()
    )


class Collector:
    """One application-owned consumer; browser tabs only read its committed history."""

    def __init__(self, store, client):
        self.store = store
        self.client = client
        self.lock = asyncio.Lock()
        self.subscription_lock = asyncio.Lock()
        self.task = None
        self.preference_task = None
        self.state = "stopped"
        self.message = "Tracking is stopped."
        self.connected = False
        self.notifications = 0
        self.preference_warning = ""

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
        selection = await self.store.setting("selection", DEFAULT_SELECTION)
        setup_message = self.client.config.setup_message(selection)
        self.connected = bool(target and self.client.config.app_bearer)
        self.message = setup_message or "Ready. Tracking is paused."
        if (
            account
            and await self.store.setting("tracking", False)
            and not await self.store.restart_blocked()
        ):
            if setup_message:
                self.state = "reconnect"
                return
            await self.store.gap(
                account["id"], "Application was offline; recovery is not guaranteed."
            )
            self.task = asyncio.create_task(self.run())

    def validate_selection(self, selection: dict):
        if message := self.client.config.setup_message(selection):
            raise SetupError(message)
        if not selected_kinds(selection):
            raise SetupError("Enable at least one event category, or Pause tracking first.")

    async def start(self):
        async with self.lock:
            if self.task and not self.task.done():
                return
            selection = await self.store.setting("selection", DEFAULT_SELECTION)
            self.validate_selection(selection)
            if not await self.store.setting("account"):
                raise SetupError("Configure X_USER_ID and restart XFlog.")
            await self.store.save_setting("tracking", True)
            await self.store.allow_restart()
            self.state = "connecting"
            self.message = "Connecting to X Activity…"
            self.task = asyncio.create_task(self.run())

    async def save_preferences(self, selection: dict) -> dict:
        async with self.lock:
            if self.preference_task and not self.preference_task.done():
                raise SetupError(
                    "A preferences update is still running. Wait for it, or Pause tracking."
                )
            update = asyncio.create_task(self.apply_preferences(selection))
            self.preference_task = update
        try:
            # Own persistence and application before either can outlive the saving browser.
            await asyncio.shield(update)
        except asyncio.CancelledError:
            if not update.cancelled():
                raise
        finally:
            if update.done():
                async with self.lock:
                    if self.preference_task is update:
                        self.preference_task = None
        async with self.lock:
            if await self.store.setting("selection", DEFAULT_SELECTION) != selection:
                return {
                    "saved": False,
                    "message": "This save was interrupted or replaced. Review your preferences and save again.",
                }
            message = "Preferences saved. Tracking remains stopped."
            if self.is_running() and await self.store.setting("tracking", False):
                message = "Preferences saved. Tracking continues."
            return {"saved": True, "message": self.preference_warning or message}

    def is_running(self) -> bool:
        return (
            self.task is not None
            and not self.task.done()
            and self.state in {"connecting", "tracking", "reconnecting"}
        )

    async def apply_preferences(self, selection: dict):
        async with self.lock:
            previous = await self.store.setting("selection", DEFAULT_SELECTION)
            running = self.is_running()
            if running:
                self.validate_selection(selection)
            try:
                await self.store.save_setting("selection", selection)
            except sqlite3.Error:
                self.preference_warning = (
                    "Preferences could not be saved. Check server storage and save again."
                )
                raise
            if not running:
                self.preference_warning = ""
                return
            if (
                selected_kinds(previous) == selected_kinds(selection)
                and not self.preference_warning
            ):
                return
            account = await self.store.setting("account")
        try:
            await self.refresh_subscriptions(account)
        except (ProviderError, httpx.HTTPError, SetupError, ValueError, KeyError, sqlite3.Error):
            self.preference_warning = (
                "Preferences saved locally, but the event changes have not been fully applied. "
                "Check X access and server storage, then save again to retry."
            )

    async def cancel_preference_update(self):
        update = self.preference_task
        self.preference_task = None
        if update:
            update.cancel()
            await asyncio.gather(update, return_exceptions=True)

    async def cancel_task(self):
        await self.cancel_preference_update()
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
            self.preference_warning = ""
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

    async def remove_subscription(self, identity: str):
        try:
            await self.client.delete_subscription(identity)
        except ProviderError as error:
            if error.status != 404:
                raise
        await self.store.forget_subscription(identity)

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
                await self.remove_subscription(subscription["id"])
            except ProviderError:
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
        # Keep existing coverage until newly selected event subscriptions are ready.
        for saved in await self.store.subscriptions():
            if saved["account_id"] != account["id"] or saved["kind"] not in kinds:
                await self.remove_subscription(saved["id"])

    async def refresh_subscriptions(self, account: dict):
        async with self.subscription_lock:
            if not self.is_running() or not await self.store.setting("tracking", False):
                return False
            selection = await self.store.setting("selection", DEFAULT_SELECTION)
            await self.reconcile(account, selected_kinds(selection))
            self.preference_warning = ""
            return True

    async def run(self):
        try:
            await self.listen()
        finally:
            await self.cancel_preference_update()

    async def listen(self):
        delay = 1
        account = await self.store.setting("account")
        while True:
            try:
                self.state = "connecting"
                if not await self.refresh_subscriptions(account):
                    return
                # Reconnect every six hours to refresh the 24-hour subscription lease.
                async with asyncio.timeout(6 * 3600):
                    async for raw in self.client.stream():
                        if raw is None:
                            self.state = "tracking"
                            self.message = "Listening for incoming activity."
                            await self.store.end_gap(account["id"])
                            continue
                        groups = await self.store.setting("audience_groups", {})
                        event = parse_event(raw, account["id"], groups)
                        selection = await self.store.setting("selection", DEFAULT_SELECTION)
                        if (
                            event
                            and event.kind in selected_kinds(selection)
                            and await self.store.insert(event)
                        ):
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
