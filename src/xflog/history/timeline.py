"""A local, paginated view over recorded audience and interaction events."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from .. import audience_groups
from ..audience_groups.previous_encounters import KEY as ENCOUNTERS_KEY
from ..audience_groups.previous_encounters import encounter_bucket
from ..interactions import choices
from ..tracking.events import Event
from .timeline_aggregate import aggregate_records, empty_aggregate, encounter_from_row
from .timeline_cursor import (
    MAX_SEQUENCE,
    Cursor,
    InvalidTimelineRequest,
    decode_cursor,
    revision_watermarks,
    scope_key,
    selected_position,
)
from .timeline_queries import (
    ENCOUNTER_BOUNDARY_SQL,
    REVISION_SQL,
    TimelineQuery,
    encounter_columns,
    encounter_corrections,
    page_sql,
)

_CURRENT_ACCOUNT = object()


async def _revision(db, account):
    async with db.execute(REVISION_SQL, {"account": account}) as cursor:
        return tuple(await cursor.fetchone())


async def _prior_backfill_boundary(db, query, after):
    params = dict(zip(("old_event_max", "old_interaction_max"), after, strict=True))
    params.update(
        account=query.account, event_max=query.watermarks[0], interaction_max=query.watermarks[1]
    )
    async with db.execute(ENCOUNTER_BOUNDARY_SQL, params) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None


def _sequence(row):
    return row["position"] if row["source"] else -row["position"]


def _event(row):
    sequence = _sequence(row)
    actor_id = row["actor_id"]
    handle, name = row["handle"], row["name"]
    return {
        **Event(
            f"timeline:{'event' if sequence > 0 else 'interaction'}:{abs(sequence)}",
            row["kind"],
            row["account_id"],
            actor_id,
            handle,
            name if handle or name else f"Account {actor_id}",
            row["provider_at"],
            row["received_at"],
            json.loads(row["group_data"]),
        ).public(),
        "sequence": sequence,
        **(
            {"encounter_correction": True}
            if "encounter_correction" in row.keys() and row["encounter_correction"]
            else {}
        ),
        **({"post_id": row["post_id"], "post_text": row["post_text"]} if sequence < 0 else {}),
    }


async def _decorate(rows, groups):
    async def encounters(_):
        return {_sequence(row): encounter_from_row(row) for row in rows}

    return await audience_groups.decorate_history([_event(row) for row in rows], groups, encounters)


class Timeline:
    def __init__(self, store):
        self.store = store

    @asynccontextmanager
    async def _snapshot(self):
        # A WAL reader can hold a consistent snapshot while ingestion commits on Store's connection.
        address = Path(self.store.path).resolve().as_uri() + "?mode=ro"
        async with aiosqlite.connect(address, uri=True) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN")
            yield db

    async def revision(self, account: str) -> str:
        return ":".join(map(str, await _revision(self.store.db, account)))

    async def current_history(self, query: dict) -> dict:
        return await self.history(_CURRENT_ACCOUNT, query)

    async def history(self, account, query: dict) -> dict:
        before = decode_cursor(query.get("before", "0"))
        after = (
            revision_watermarks(query["after_revision"]) if query.get("after_revision") else None
        )
        selected = selected_position(query["selected"]) if query.get("selected") else None
        context = (
            revision_watermarks(query["encounter_revision"])
            if query.get("encounter_revision")
            else None
        )
        if context and (not before or after):
            raise InvalidTimelineRequest("Encounter revision applies to an older history page.")
        if before and selected:
            raise InvalidTimelineRequest("Select a timeline event on the first page.")
        subject, kind = query.get("subject", "followers"), query.get("kind", "all")
        lens, since = query.get("lens", "none"), query.get("since", "")
        if lens != "none" and lens not in audience_groups.MODULES:
            raise InvalidTimelineRequest("Invalid audience group.")
        limit = min(50, max(1, int(query.get("limit", 25))))
        async with self._snapshot() as db:
            async with db.execute(
                "SELECT key,value FROM settings WHERE key IN ('account','selection','audience_groups')"
            ) as cursor:
                settings = {row[0]: json.loads(row[1]) async for row in cursor}
            if account is _CURRENT_ACCOUNT:
                account = (settings.get("account") or {}).get("id")
            groups = audience_groups.preferences(settings.get("audience_groups"))
            module = audience_groups.MODULES.get(lens) if groups.get(lens) else None
            active_encounters = bool(module and lens == ENCOUNTERS_KEY)
            if context and not active_encounters:
                raise InvalidTimelineRequest(
                    "Encounter revision requires the Previous encounters group."
                )
            enabled = choices(settings.get("selection", {}))
            interactions = (
                tuple(key for key, on in enabled.items() if on)
                if subject == "followers" and kind == "all"
                else ()
            )
            scope = scope_key((account, subject, kind, since, lens, interactions, groups))
            cursor_scope = scope_key((scope, after))
            if before and before.scope != cursor_scope:
                raise InvalidTimelineRequest("Timeline cursor does not match this history scope.")
            if account is None:
                result = {"events": [], "next": None, "aggregate": empty_aggregate(scope, "0:0")}
                if selected:
                    result["selected_event"] = None
                return result
            if before:
                watermarks = before.watermarks
            else:
                marks = await _revision(db, account)
                watermarks = marks[:2]
            if after and any(mark > upper for mark, upper in zip(after, watermarks, strict=True)):
                raise InvalidTimelineRequest(
                    "Timeline revision belongs to an unavailable snapshot."
                )
            if context and context != watermarks:
                latest = (await _revision(db, account))[:2]
                if any(
                    not lower <= mark <= upper
                    for lower, mark, upper in zip(watermarks, context, latest, strict=True)
                ):
                    raise InvalidTimelineRequest(
                        "Encounter revision belongs to an unavailable snapshot."
                    )
            scope_query = TimelineQuery(account, subject, kind, since, interactions, watermarks)
            result = await self._page(
                db,
                scope_query,
                groups,
                before,
                after,
                selected,
                limit,
                context or watermarks,
                active_encounters,
            )
            if result["next"] is not None:
                result["next"] = Cursor(result["next"], watermarks, cursor_scope).encode()
            if not before:
                result["aggregate"] = {
                    **await aggregate_records(db, scope_query, module),
                    "revision": ":".join(map(str, marks)),
                    "profile_revision": marks[2],
                    "scope": scope,
                }
            return result

    async def _page(
        self, db, query, groups, before, after, selected, limit, context, active_encounters
    ):
        needs_context = groups[ENCOUNTERS_KEY]
        boundary_key = before.key if before else None
        sql, params = query.records(before=boundary_key, after=after, page_size=limit + 1)
        correction_sql = ""
        if active_encounters and after and after != query.watermarks:
            prior_receipt = await _prior_backfill_boundary(db, query, after)
            if prior_receipt is not None:
                await db.create_function(
                    "encounter_bucket", 3, encounter_bucket, deterministic=True
                )
                correction_sql, correction_params = encounter_corrections(
                    query, boundary_key, after, limit + 1
                )
                params.update(correction_params, prior_receipt=prior_receipt)
                sql = f"SELECT fresh.*,0 AS encounter_correction FROM ({sql}) fresh UNION ALL SELECT corrections.*,1 FROM corrections"
        context_params = dict(
            zip(("context_event_max", "context_interaction_max"), context, strict=True)
        )
        async with db.execute(
            page_sql(sql, encounters=needs_context, correction_sql=correction_sql),
            {**params, **context_params},
        ) as cursor:
            rows = await cursor.fetchall()
        boundary = None
        if len(rows) > limit:
            last = rows[limit - 1]
            boundary = (last["received_at"], last["source"], last["position"])
        rows = rows[:limit]
        selected_rows = []
        if selected and not any((row["source"], row["position"]) == selected for row in rows):
            sql, params = query.records(selected=selected, page_size=1)
            if sql:
                async with db.execute(
                    page_sql(sql, encounters=needs_context), {**params, **context_params}
                ) as cursor:
                    selected_rows = await cursor.fetchall()
        events = await _decorate(rows + selected_rows, groups)
        result = {"events": events[: len(rows)], "next": boundary}
        if selected:
            sequence = selected[1] if selected[0] else -selected[1]
            selected_event = next(
                (event for event in events if event["sequence"] == sequence),
                None,
            )
            if selected_event and selected_event.get("encounter_correction"):
                selected_event = dict(selected_event)
                del selected_event["encounter_correction"]
            result["selected_event"] = selected_event
        return result

    async def encounter_context(self, events: list[dict]) -> dict:
        if not events:
            return {}
        account = events[0]["account_id"]
        if any(event["account_id"] != account for event in events):
            raise ValueError("History context must belong to one account.")
        params = {"account": account, "event_max": MAX_SEQUENCE, "interaction_max": MAX_SEQUENCE}
        for index, event in enumerate(events):
            seq = event["sequence"]
            params.update(
                {
                    f"p{index}": abs(seq),
                    f"s{index}": int(seq > 0),
                    f"a{index}": event["actor_id"],
                    f"r{index}": event["received_at"],
                }
            )
        slots = ",".join(f"(:p{i},:s{i},:a{i},:r{i})" for i in range(len(events)))
        # The legacy helper has no paging snapshot. It describes the current account history.
        sql = f"""WITH wanted(position,source,actor_id,received_at) AS (VALUES {slots})
        SELECT r.position,r.source,{encounter_columns()} FROM wanted r"""
        async with self.store.db.execute(sql, params) as cursor:
            return {_sequence(row): encounter_from_row(row) async for row in cursor}
