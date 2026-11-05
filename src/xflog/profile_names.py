"""Opt-in, once-per-person display-name lookups; no grouping enrichment."""

import asyncio

import httpx

from .errors import SetupError
from .history.profiles import remember_profile
from .tracking.events import utc_now
from .tracking.transport import ProviderError


class ProfileNames:
    def __init__(self, store, client):
        self.store, self.client = store, client
        self.lock = asyncio.Lock()

    async def retry_unresolved(self):
        account = self.client.config.user_id
        async with self.store.lock:
            try:
                await self.store.db.execute(
                    """DELETE FROM profile_lookups WHERE account_id=? AND actor_id NOT IN (
                    SELECT actor_id FROM known_profiles WHERE account_id=?
                    AND name IS NOT NULL AND handle IS NOT NULL)""",
                    (account, account),
                )
                await self.store.db.commit()
            except BaseException:
                await self.store.db.rollback()
                raise
        await self.store.save_setting("profile_warning", "")

    async def ensure(self, events: list[dict]) -> bool:
        async with self.lock:
            selection = await self.store.setting("selection", {})
            if not selection.get("profile_names") or not self.client.config.app_bearer:
                return False
            account = self.client.config.user_id
            identities = sorted(
                {
                    event["actor_id"]
                    for event in events
                    if event["account_id"] == account
                    and not (event.get("handle") and event.get("name"))
                }
            )
            if not identities:
                return False
            slots = ",".join("?" for _ in identities)
            async with self.store.db.execute(
                f"""SELECT actor_id FROM profile_lookups WHERE account_id=? AND actor_id IN ({slots})
                UNION SELECT actor_id FROM known_profiles WHERE account_id=? AND actor_id IN ({slots})
                AND name IS NOT NULL AND handle IS NOT NULL""",
                (account, *identities, account, *identities),
            ) as cursor:
                known = {row[0] for row in await cursor.fetchall()}
            pending = [identity for identity in identities if identity not in known][:100]
            if not pending:
                return bool(known)
            async with self.store.lock:
                try:
                    claimed = []
                    for identity in pending:
                        cursor = await self.store.db.execute(
                            "INSERT OR IGNORE INTO profile_lookups VALUES (?,?,?)",
                            (account, identity, utc_now()),
                        )
                        if cursor.rowcount == 1:
                            claimed.append(identity)
                    await self.store.db.commit()
                except BaseException:
                    await self.store.db.rollback()
                    raise
            pending = claimed
            if not pending:
                return True
            try:
                profiles = await self.client.lookup_users(pending)
            except (ProviderError, SetupError, httpx.HTTPError):
                await self.store.save_setting(
                    "profile_warning",
                    "Names could not be resolved from X. History is kept. Check access and credits; disable and re-enable name resolution to retry.",
                )
                return False
            async with self.store.lock:
                try:
                    for profile in profiles:
                        await remember_profile(
                            self.store.db,
                            account,
                            {
                                "id": profile["id"],
                                "name": profile.get("name"),
                                "handle": profile.get("username"),
                            },
                        )
                    await self.store.db.commit()
                except BaseException:
                    await self.store.db.rollback()
                    raise
            complete = {
                profile["id"]
                for profile in profiles
                if profile.get("name") and profile.get("username")
            }
            await self.store.save_setting(
                "profile_warning",
                ""
                if complete == set(pending)
                else "Some profiles were unavailable on X. Saved history is kept; their names will update if supplied by a later event.",
            )
            return True
