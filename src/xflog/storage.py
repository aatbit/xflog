import asyncio
import json
from pathlib import Path

import aiosqlite

from .events import EVENT_TYPES, Event, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id TEXT NOT NULL,
 kind TEXT NOT NULL,
 account_id TEXT NOT NULL,
 actor_id TEXT NOT NULL,
 handle TEXT,
 name TEXT,
 provider_at TEXT,
 received_at TEXT NOT NULL,
 UNIQUE(account_id, event_id)
);
CREATE INDEX IF NOT EXISTS event_account_sequence ON events(account_id, sequence DESC);
CREATE INDEX IF NOT EXISTS event_actor_sequence ON events(account_id, actor_id, sequence DESC);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, account_id TEXT NOT NULL,
 expires_at TEXT, tag TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gaps (
 id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, started_at TEXT NOT NULL,
 ended_at TEXT, reason TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = asyncio.Lock()
        self.db = None

    async def open(self):
        await asyncio.to_thread(self._prepare_path)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        async with self.db.execute("PRAGMA table_info(events)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "group_data" not in columns:
            await self.db.execute(
                "ALTER TABLE events ADD COLUMN group_data TEXT NOT NULL DEFAULT '{}'"
            )
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA busy_timeout=5000")
        await self.db.commit()

    def _prepare_path(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)

    async def close(self):
        if self.db:
            await self.db.close()

    async def block_restart(self):
        await asyncio.to_thread(self.path.with_name(self.path.name + ".paused").touch, mode=0o600)

    async def restart_blocked(self) -> bool:
        return await asyncio.to_thread(self.path.with_name(self.path.name + ".paused").exists)

    async def allow_restart(self):
        await asyncio.to_thread(
            self.path.with_name(self.path.name + ".paused").unlink, missing_ok=True
        )

    async def setting(self, key: str, default=None):
        async with self.db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
        return json.loads(row[0]) if row else default

    async def save_setting(self, key: str, value):
        async with self.lock:
            await self.db.execute(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
            await self.db.commit()

    async def insert(self, event: Event) -> bool:
        async with self.lock:
            cursor = await self.db.execute(
                """INSERT OR IGNORE INTO events
                (event_id,kind,account_id,actor_id,handle,name,provider_at,received_at,group_data)
                VALUES (:event_id,:kind,:account_id,:actor_id,:handle,:name,:provider_at,:received_at,:group_data)""",
                {**vars(event), "group_data": json.dumps(event.group_data)},
            )
            await self.db.commit()
            return cursor.rowcount == 1

    async def history(self, account_id: str, query: dict) -> dict:
        kind = query.get("kind", "all")
        subject = query.get("subject", "followers")
        before = max(0, int(query.get("before", 0)))
        limit = min(50, max(1, int(query.get("limit", 25))))
        types = EVENT_TYPES[:2] if subject == "followers" else EVENT_TYPES[2:]
        if kind == "gained":
            types = types[:1]
        elif kind == "lost":
            types = types[1:]
        placeholders = ",".join("?" for _ in types)
        clause = f"account_id=? AND kind IN ({placeholders})"
        params = (account_id, *types)
        if before:
            clause += " AND sequence<?"
            params += (before,)
        async with self.db.execute(
            f"SELECT * FROM events WHERE {clause} ORDER BY sequence DESC LIMIT ?",
            (*params, limit + 1),
        ) as cursor:
            rows = await cursor.fetchall()
        events = []
        for row in rows[:limit]:
            values = dict(row)
            values["group_data"] = json.loads(values["group_data"])
            sequence = values.pop("sequence")
            events.append({**Event(**values).public(), "sequence": sequence})
        return {
            "events": events,
            "next": events[-1]["sequence"] if len(rows) > limit else None,
        }

    async def summary(self, account_id: str) -> dict:
        async with self.db.execute(
            "SELECT kind,COUNT(*) AS count FROM events WHERE account_id=? GROUP BY kind",
            (account_id,),
        ) as cursor:
            counts = {row["kind"]: row["count"] for row in await cursor.fetchall()}
        return {kind: counts.get(kind, 0) for kind in EVENT_TYPES}

    async def encounter_context(self, events: list[dict]) -> dict[int, dict]:
        if not events:
            return {}
        account_id = events[0]["account_id"]
        if any(event["account_id"] != account_id for event in events):
            raise ValueError("History context must belong to one account.")
        sequences = [event["sequence"] for event in events]
        placeholders = ",".join("?" for _ in sequences)
        async with self.db.execute(
            f"""SELECT current.sequence,
            EXISTS (SELECT 1 FROM events prior
                WHERE prior.account_id=current.account_id AND prior.actor_id=current.actor_id
                AND prior.sequence<current.sequence) AS seen_before,
            (SELECT prior.kind FROM events prior
                WHERE prior.account_id=current.account_id AND prior.actor_id=current.actor_id
                AND prior.sequence<current.sequence AND prior.kind IN ('follow.follow','follow.unfollow')
                ORDER BY prior.sequence DESC LIMIT 1) AS previous_follow_kind
            FROM events current WHERE current.account_id=? AND current.sequence IN ({placeholders})""",
            (account_id, *sequences),
        ) as cursor:
            return {
                row["sequence"]: {
                    "seen_before": bool(row["seen_before"]),
                    "previous_follow_kind": row["previous_follow_kind"],
                }
                for row in await cursor.fetchall()
            }

    async def subscriptions(self) -> list[dict]:
        async with self.db.execute("SELECT * FROM subscriptions") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def save_subscription(self, subscription: dict):
        async with self.lock:
            await self.db.execute(
                "INSERT OR REPLACE INTO subscriptions VALUES (:id,:kind,:account_id,:expires_at,:tag)",
                subscription,
            )
            await self.db.commit()

    async def forget_subscription(self, identity: str):
        async with self.lock:
            await self.db.execute("DELETE FROM subscriptions WHERE id=?", (identity,))
            await self.db.commit()

    async def gap(self, account_id: str, reason: str):
        async with self.lock:
            await self.db.execute(
                """INSERT INTO gaps(account_id,started_at,reason)
                SELECT ?,?,? WHERE NOT EXISTS
                (SELECT 1 FROM gaps WHERE account_id=? AND ended_at IS NULL)""",
                (account_id, utc_now(), reason, account_id),
            )
            await self.db.commit()

    async def end_gap(self, account_id: str):
        async with self.lock:
            await self.db.execute(
                "UPDATE gaps SET ended_at=? WHERE account_id=? AND ended_at IS NULL",
                (utc_now(), account_id),
            )
            await self.db.commit()

    async def gaps(self, account_id: str) -> list[dict]:
        async with self.db.execute(
            "SELECT * FROM gaps WHERE account_id=? ORDER BY id DESC LIMIT 10",
            (account_id,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
