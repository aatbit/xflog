"""A local, paginated view over recorded audience and interaction events."""

import base64
import binascii
import json

from ..interactions import choices
from ..tracking.events import FOLLOW_TYPES, SUBSCRIPTION_TYPES, Event, timestamp


def decode_cursor(value: str) -> tuple:
    if value in {"", "0"}:
        return ()
    try:
        if len(value) > 256:
            raise ValueError
        result = json.loads(base64.urlsafe_b64decode(value.encode() + b"=" * (-len(value) % 4)))
        if (
            not isinstance(result, list)
            or len(result) != 3
            or not isinstance(result[0], str)
            or timestamp(result[0]) != result[0]
            or type(result[1]) is not int
            or result[1] not in {0, 1}
            or type(result[2]) is not int
            or not 0 < result[2] <= 9223372036854775807
        ):
            raise ValueError
        return tuple(result)
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise ValueError("Invalid timeline cursor.") from None


def encode_cursor(row) -> str:
    value = [row["received_at"], row["source"], row["position"]]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


class Timeline:
    def __init__(self, store):
        self.store = store

    async def revision(self, account: str) -> str:
        async with self.store.db.execute(
            """SELECT (SELECT COALESCE(MAX(sequence),0) FROM events WHERE account_id=?),
            (SELECT COALESCE(MAX(sequence),0) FROM interactions WHERE account_id=?),
            (SELECT COALESCE(MAX(observed_at),'') FROM known_profiles WHERE account_id=?)""",
            (account, account, account),
        ) as cursor:
            return ":".join(map(str, await cursor.fetchone()))

    async def history(self, account: str, query: dict) -> dict:
        before = decode_cursor(query.get("before", "0"))
        subject, kind = query.get("subject", "followers"), query.get("kind", "all")
        types = SUBSCRIPTION_TYPES if subject == "subscriptions" else FOLLOW_TYPES
        if kind != "all":
            types = types[:1] if kind == "gained" else types[1:]
        enabled = choices(await self.store.setting("selection", {}))
        interactions = (
            [key for key, on in enabled.items() if on]
            if subject == "followers" and kind == "all"
            else []
        )
        event_slots = ",".join("?" for _ in types)
        interaction_slots = ",".join("?" for _ in interactions) or "NULL"
        sql = f"""WITH activity AS (
          SELECT sequence AS position, 1 AS source, event_id, kind, account_id, actor_id,
          handle,name,provider_at,received_at,group_data,NULL AS post_id,NULL AS post_text FROM events
          WHERE account_id=? AND kind IN ({event_slots})
          UNION ALL
          SELECT i.sequence, 0, 'interaction:'||i.sequence, 'interaction.'||i.kind,
          i.account_id,i.person_id,
          COALESCE(json_extract(i.profile_data,'$.handle'),
            (SELECT e.handle FROM events e WHERE e.account_id=i.account_id AND e.actor_id=i.person_id
             AND e.handle IS NOT NULL ORDER BY e.sequence DESC LIMIT 1)),
          COALESCE(json_extract(i.profile_data,'$.name'),
            (SELECT e.name FROM events e WHERE e.account_id=i.account_id AND e.actor_id=i.person_id
             AND e.name IS NOT NULL ORDER BY e.sequence DESC LIMIT 1)),
          i.provider_at,i.received_at,COALESCE(json_extract(i.profile_data,'$.group_data'),'{{}}'),
          i.post_id,substr(post.text,1,281)
          FROM interactions i LEFT JOIN interaction_posts post
            ON post.account_id=i.account_id AND post.id=i.post_id
          WHERE i.account_id=? AND i.kind IN ({interaction_slots})
        ) SELECT activity.*,p.name AS cached_name,p.handle AS cached_handle FROM activity
          LEFT JOIN known_profiles p ON p.account_id=activity.account_id AND p.actor_id=activity.actor_id"""
        params = (account, *types, account, *interactions)
        if before:
            sql += " WHERE (received_at,source,position)<(?,?,?)"
            params += before
        if since := query.get("since"):
            sql += (" AND" if before else " WHERE") + " received_at>=?"
            params += (since,)
        limit = min(50, max(1, int(query.get("limit", 25))))
        sql += " ORDER BY received_at DESC,source DESC,position DESC LIMIT ?"
        async with self.store.db.execute(sql, (*params, limit + 1)) as cursor:
            rows = await cursor.fetchall()
        events = []
        for row in rows[:limit]:
            values = dict(row)
            source, position = values.pop("source"), values.pop("position")
            post_id, post_text = values.pop("post_id"), values.pop("post_text")
            values["name"] = values.pop("cached_name") or values["name"]
            values["handle"] = values.pop("cached_handle") or values["handle"]
            values["event_id"] = f"timeline:{'event' if source else 'interaction'}:{position}"
            values["group_data"] = json.loads(values["group_data"])
            if not values["name"] and not values["handle"]:
                values["name"] = f"Account {values['actor_id']}"
            events.append(
                {
                    **Event(**values).public(),
                    "sequence": position if source else -position,
                    **({"post_id": post_id, "post_text": post_text} if not source else {}),
                }
            )
        return {
            "events": events,
            "next": encode_cursor(rows[limit - 1]) if len(rows) > limit else None,
        }

    async def encounter_context(self, events: list[dict]) -> dict:
        result = {}
        for event in events:
            account, person, received = event["account_id"], event["actor_id"], event["received_at"]
            sequence = event["sequence"]
            async with self.store.db.execute(
                """SELECT EXISTS(
                  SELECT 1 FROM events WHERE account_id=? AND actor_id=?
                    AND (received_at,1,sequence)<(?,?,?)
                  UNION ALL SELECT 1 FROM interactions WHERE account_id=? AND person_id=?
                    AND (received_at,0,sequence)<(?,?,?)
                ), (SELECT kind FROM events WHERE account_id=? AND actor_id=?
                  AND kind IN ('follow.follow','follow.unfollow')
                  AND (received_at,1,sequence)<(?,?,?)
                  ORDER BY received_at DESC,sequence DESC LIMIT 1)""",
                (
                    account,
                    person,
                    received,
                    int(sequence > 0),
                    abs(sequence),
                    account,
                    person,
                    received,
                    int(sequence > 0),
                    abs(sequence),
                    account,
                    person,
                    received,
                    int(sequence > 0),
                    abs(sequence),
                ),
            ) as cursor:
                seen, previous = await cursor.fetchone()
            result[sequence] = {"seen_before": bool(seen), "previous_follow_kind": previous}
        return result
