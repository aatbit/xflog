import json

from ..history.profiles import remember_profile
from ..tracking.events import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS interaction_posts (
 account_id TEXT NOT NULL, id TEXT NOT NULL, author_id TEXT, conversation_id TEXT,
 text TEXT, created_at TEXT, PRIMARY KEY(account_id,id)
);
CREATE TABLE IF NOT EXISTS interactions (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
 event_id TEXT NOT NULL, person_id TEXT NOT NULL, kind TEXT NOT NULL,
 post_id TEXT NOT NULL, provider_at TEXT NOT NULL, received_at TEXT NOT NULL,
 UNIQUE(account_id,event_id,person_id)
);
CREATE INDEX IF NOT EXISTS interaction_person ON interactions(account_id,person_id,sequence DESC);
CREATE INDEX IF NOT EXISTS interaction_account_sequence ON interactions(account_id,sequence DESC);
CREATE INDEX IF NOT EXISTS interaction_receipt ON interactions(account_id,received_at,sequence);
CREATE INDEX IF NOT EXISTS interaction_actor_receipt ON interactions(account_id,person_id,received_at,sequence);
CREATE TABLE IF NOT EXISTS thread_snapshots (
 account_id TEXT NOT NULL, conversation_id TEXT NOT NULL, checked_at TEXT NOT NULL,
 next_token TEXT, PRIMARY KEY(account_id,conversation_id)
);
CREATE TABLE IF NOT EXISTS thread_posts (
 account_id TEXT NOT NULL, conversation_id TEXT NOT NULL, post_id TEXT NOT NULL,
 PRIMARY KEY(account_id,conversation_id,post_id)
);
"""


class InteractionStore:
    def __init__(self, store):
        self.store = store

    async def save_posts(self, account, posts):
        for post in posts:
            await self.store.db.execute(
                """INSERT INTO interaction_posts VALUES (:account,:id,:author_id,:conversation_id,:text,:created_at)
                ON CONFLICT(account_id,id) DO UPDATE SET
                author_id=COALESCE(excluded.author_id,author_id),
                conversation_id=COALESCE(excluded.conversation_id,conversation_id),
                text=COALESCE(excluded.text,text),created_at=COALESCE(excluded.created_at,created_at)""",
                {"account": account, **post},
            )
            if post.get("conversation_id"):
                await self.store.db.execute(
                    """INSERT OR IGNORE INTO thread_posts
                    SELECT account_id,conversation_id,? FROM thread_snapshots
                    WHERE account_id=? AND conversation_id=?""",
                    (post["id"], account, post["conversation_id"]),
                )

    async def remember_posts(self, account, posts):
        async with self.store.lock:
            try:
                await self.save_posts(account, posts)
                await self.store.db.commit()
            except BaseException:
                await self.store.db.rollback()
                raise

    async def insert(self, account, event):
        async with self.store.lock:
            try:
                await self.save_posts(account, event["posts"])
                inserted = False
                for person in event["people"]:
                    cursor = await self.store.db.execute(
                        """INSERT OR IGNORE INTO interactions
                        (account_id,event_id,person_id,kind,post_id,provider_at,received_at,profile_data)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            account,
                            event["event_id"],
                            person,
                            event["key"],
                            event["post_id"],
                            event["provider_at"],
                            event["received_at"],
                            json.dumps(event.get("profiles", {}).get(person, {})),
                        ),
                    )
                    if cursor.rowcount == 1:
                        await remember_profile(
                            self.store.db,
                            account,
                            {
                                "id": person,
                                **event.get("profiles", {}).get(person, {}),
                            },
                        )
                    inserted |= cursor.rowcount == 1
                await self.store.db.commit()
                return inserted
            except BaseException:
                await self.store.db.rollback()
                raise

    async def history(self, account, query):
        async with self.store.lock:
            async with self.store.db.execute(
                """SELECT i.*,p.text,p.conversation_id,p.author_id,
                EXISTS(SELECT 1 FROM thread_snapshots t WHERE t.account_id=i.account_id
                AND t.conversation_id=p.conversation_id) AS thread_saved FROM interactions i
                JOIN interaction_posts p ON p.account_id=i.account_id AND p.id=i.post_id
                WHERE i.account_id=? AND i.person_id=? AND (?=0 OR i.sequence<?)
                ORDER BY i.sequence DESC LIMIT 31""",
                (account, query["person"], query["before"], query["before"]),
            ) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]
        return {"interactions": rows[:30], "next": rows[29]["sequence"] if len(rows) > 30 else None}

    async def interaction(self, account, query):
        async with self.store.lock:
            async with self.store.db.execute(
                """SELECT p.* FROM interactions i
                JOIN interaction_posts p ON p.account_id=i.account_id AND p.id=i.post_id
                WHERE i.account_id=? AND i.person_id=? AND i.sequence=?""",
                (account, query["person"], query["sequence"]),
            ) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row else None

    async def snapshot(self, account, conversation):
        async with self.store.lock:
            async with self.store.db.execute(
                "SELECT * FROM thread_snapshots WHERE account_id=? AND conversation_id=?",
                (account, conversation),
            ) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row else None

    async def thread(self, account, query):
        async with self.store.lock:
            async with self.store.db.execute(
                """SELECT p.* FROM thread_posts t JOIN interaction_posts p
                ON p.account_id=t.account_id AND p.id=t.post_id
                WHERE t.account_id=? AND t.conversation_id=?
                ORDER BY LENGTH(p.id),p.id LIMIT 101 OFFSET ?""",
                (account, query["conversation"], query.get("offset", 0)),
            ) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]
            async with self.store.db.execute(
                "SELECT COUNT(*) FROM thread_posts WHERE account_id=? AND conversation_id=?",
                (account, query["conversation"]),
            ) as cursor:
                total = (await cursor.fetchone())[0]
        return {
            "posts": rows[:100],
            "more_saved": len(rows) > 100,
            "total": total,
            "offset": query.get("offset", 0),
        }

    async def save_thread(self, account, page):
        async with self.store.lock:
            try:
                await self.save_posts(account, page["posts"])
                for post in page["posts"]:
                    await self.store.db.execute(
                        "INSERT OR IGNORE INTO thread_posts VALUES (?,?,?)",
                        (account, page["conversation"], post["id"]),
                    )
                await self.store.db.execute(
                    """INSERT INTO thread_snapshots VALUES (?,?,?,?)
                    ON CONFLICT(account_id,conversation_id) DO UPDATE SET
                    checked_at=excluded.checked_at,next_token=excluded.next_token""",
                    (account, page["conversation"], utc_now(), page["next_token"]),
                )
                await self.store.db.execute(
                    """INSERT OR IGNORE INTO thread_posts
                    SELECT account_id,conversation_id,id FROM interaction_posts
                    WHERE account_id=? AND conversation_id=?""",
                    (account, page["conversation"]),
                )
                await self.store.db.commit()
            except BaseException:
                await self.store.db.rollback()
                raise
