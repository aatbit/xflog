"""Shared, account-scoped display identities supplied by X."""

import re

from ..tracking.events import HANDLE, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS known_profiles (
 account_id TEXT NOT NULL, actor_id TEXT NOT NULL, name TEXT, handle TEXT,
 observed_at TEXT NOT NULL, PRIMARY KEY(account_id,actor_id)
);
CREATE TABLE IF NOT EXISTS profile_lookups (
 account_id TEXT NOT NULL, actor_id TEXT NOT NULL, attempted_at TEXT NOT NULL,
 PRIMARY KEY(account_id,actor_id)
);
"""


async def backfill_profiles(db):
    await db.execute(
        """INSERT INTO known_profiles (account_id,actor_id,name,handle,observed_at)
        SELECT account_id,actor_id,name,handle,observed_at FROM (
          SELECT account_id,actor_id,name,handle,received_at AS observed_at FROM events
          UNION ALL
          SELECT account_id,person_id,json_extract(profile_data,'$.name'),
            json_extract(profile_data,'$.handle'),received_at FROM interactions
        ) WHERE name IS NOT NULL OR handle IS NOT NULL ORDER BY observed_at
        ON CONFLICT(account_id,actor_id) DO UPDATE SET
        name=COALESCE(excluded.name,name),handle=COALESCE(excluded.handle,handle),
        observed_at=excluded.observed_at"""
    )


async def remember_profile(db, account: str, fields: dict):
    identity = fields.get("id")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9]{1,19}", identity):
        return
    name, handle = fields.get("name"), fields.get("handle")
    name = name[:200] if isinstance(name, str) and name.strip() else None
    handle = handle if isinstance(handle, str) and HANDLE.fullmatch(handle) else None
    if not name and not handle:
        return
    await db.execute(
        """INSERT INTO known_profiles VALUES (?,?,?,?,?)
        ON CONFLICT(account_id,actor_id) DO UPDATE SET
        name=COALESCE(excluded.name,name),handle=COALESCE(excluded.handle,handle),
        observed_at=excluded.observed_at""",
        (account, identity, name, handle, utc_now()),
    )
