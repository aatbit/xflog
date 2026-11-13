"""The shared SQLite scope for timeline pages and whole-history counts."""

from dataclasses import dataclass

from ..tracking.events import FOLLOW_TYPES, SUBSCRIPTION_TYPES
from .timeline_cursor import MAX_SEQUENCE

REVISION_SQL = """SELECT
 (SELECT COALESCE(MAX(sequence),0) FROM events WHERE account_id=:account),
 (SELECT COALESCE(MAX(sequence),0) FROM interactions INDEXED BY interaction_account_sequence
  WHERE account_id=:account),
 (SELECT COALESCE(MAX(observed_at),'') FROM known_profiles WHERE account_id=:account),
 (SELECT COALESCE(MAX(checked_at),'') FROM thread_snapshots WHERE account_id=:account)"""

_PRIOR_RECEIPT_SQL = """SELECT MAX(received_at) AS receipt FROM (
 SELECT * FROM (SELECT received_at FROM events INDEXED BY event_timeline_receipt
   WHERE account_id=:account AND sequence<=:old_event_max ORDER BY received_at DESC LIMIT 1)
 UNION ALL SELECT * FROM (SELECT received_at FROM interactions INDEXED BY interaction_receipt
   WHERE account_id=:account AND sequence<=:old_interaction_max ORDER BY received_at DESC LIMIT 1)
)"""

_ENCOUNTER_ARRIVALS = """SELECT actor_id,received_at,1 AS source,kind
    FROM events INDEXED BY event_account_sequence
    WHERE account_id=:account AND sequence>:old_event_max AND sequence<=:event_max
      AND received_at<:prior_receipt
 UNION ALL SELECT person_id,received_at,0,NULL FROM interactions INDEXED BY interaction_account_sequence
    WHERE account_id=:account AND sequence>:old_interaction_max AND sequence<=:interaction_max
      AND received_at<=:prior_receipt"""
ENCOUNTER_BOUNDARY_SQL = f"""WITH previous AS ({_PRIOR_RECEIPT_SQL})
 SELECT receipt FROM previous
 WHERE receipt IS NOT NULL AND EXISTS ({_ENCOUNTER_ARRIVALS.replace(":prior_receipt", "receipt")})"""

# Separate equal-receipt and earlier-receipt seeks to avoid rescanning large timestamp ties.
_PRIOR_EVENT = """FROM events prior
 WHERE prior.account_id=:account AND prior.actor_id=r.actor_id
 AND prior.sequence<=:{context}event_max"""
_PRIOR_INTERACTION = """FROM interactions prior
 WHERE prior.account_id=:account AND prior.person_id=r.actor_id
 AND prior.sequence<=:{context}interaction_max"""
_EARLIER = " AND prior.received_at<r.received_at"
_TIED_EVENT = " AND r.source=1 AND prior.received_at=r.received_at AND prior.sequence<r.position"
_TIED_INTERACTION = """ AND prior.received_at=r.received_at
 AND prior.sequence<=CASE WHEN r.source=0 THEN r.position-1 ELSE :{context}interaction_max END"""
_FOLLOW_KINDS = "('follow.follow','follow.unfollow')"
_SEEN_BEFORE = f"""CASE
 WHEN EXISTS (SELECT 1 {_PRIOR_INTERACTION}{_TIED_INTERACTION}) THEN 1
 WHEN EXISTS (SELECT 1 {_PRIOR_EVENT}{_TIED_EVENT}) THEN 1
 WHEN EXISTS (SELECT 1 {_PRIOR_EVENT}{_EARLIER}) THEN 1
 ELSE EXISTS (SELECT 1 {_PRIOR_INTERACTION}{_EARLIER}) END"""
_PREVIOUS_FOLLOW = f"""COALESCE(
 (SELECT prior.kind {_PRIOR_EVENT}{_TIED_EVENT} AND prior.kind IN {_FOLLOW_KINDS}
  ORDER BY prior.sequence DESC LIMIT 1),
 (SELECT prior.kind {_PRIOR_EVENT}{_EARLIER} AND prior.kind IN {_FOLLOW_KINDS}
  ORDER BY prior.received_at DESC,prior.sequence DESC LIMIT 1))"""


def encounter_columns(context=""):
    return (
        f"({_SEEN_BEFORE.format(context=context)}) AS seen_before,"
        f"({_PREVIOUS_FOLLOW.format(context=context)}) AS previous_follow_kind"
    )


SNAPSHOT = "COALESCE(e.group_data,json_extract(i.profile_data,'$.group_data'),'{}') AS group_data"
RECORD_JOIN = """LEFT JOIN events e ON r.source=1 AND e.sequence=r.position
 LEFT JOIN interactions i ON r.source=0 AND i.sequence=r.position"""


def _successor(table, actor, source, *, follow=False):
    bound = "event" if source else "interaction"
    index = "event_actor_receipt" if source else "interaction_actor_receipt"
    # At a receipt tie, every older snapshot sequence is below a new row's sequence in that source.
    later = "received_at>n.received_at"
    if source:
        later = "received_at>=n.received_at AND (received_at>n.received_at OR n.source=0)"
    follow_only = f" AND n.kind IN {_FOLLOW_KINDS} AND kind IN {_FOLLOW_KINDS}" if follow else ""
    return f"""SELECT (SELECT sequence FROM {table} INDEXED BY {index}
        WHERE account_id=:account AND {actor}=n.actor_id
        AND sequence<=:old_{bound}_max AND {later}{follow_only}
        ORDER BY received_at,sequence LIMIT 1) AS position,{source} AS source FROM arrivals n"""


def encounter_corrections(query, before, after, page_size):
    scoped, params = query.records(before=before, page_size=page_size, candidates="changed")
    params.update(zip(("old_event_max", "old_interaction_max"), after, strict=True))
    successors = " UNION ".join(
        (
            _successor("events", "actor_id", 1),
            _successor("interactions", "person_id", 0),
            _successor("events", "actor_id", 1, follow=True),
        )
    )
    # Only the first old encounter and the first old follow action after an arrival can change.
    # Check both source successors, then compare actual classifications to discard unaffected rows.
    return (
        f"""arrivals AS MATERIALIZED ({_ENCOUNTER_ARRIVALS}),
    candidates AS MATERIALIZED ({successors}),
    old_context AS MATERIALIZED (
      SELECT r.*,{encounter_columns("old_")} FROM (
        SELECT e.sequence AS position,1 AS source,e.kind,e.actor_id,e.received_at
          FROM candidates c JOIN events e ON c.source=1 AND e.sequence=c.position
        UNION ALL SELECT i.sequence,0,'interaction.'||i.kind,i.person_id,i.received_at
          FROM candidates c JOIN interactions i ON c.source=0 AND i.sequence=c.position
      ) r
    ), new_context AS MATERIALIZED (
      SELECT r.position,r.source,r.kind,
        encounter_bucket(r.kind,r.seen_before,r.previous_follow_kind) AS old_bucket,
        {encounter_columns()}
      FROM old_context r
    ), changed AS (
      SELECT position,source FROM new_context
      WHERE encounter_bucket(kind,seen_before,previous_follow_kind)<>old_bucket
    ), corrections AS ({scoped}),""",
        params,
    )


def _slots(params, prefix, values):
    slots = {f"{prefix}{index}": value for index, value in enumerate(values)}
    params.update(slots)
    return ",".join(f":{key}" for key in slots) or "NULL"


@dataclass(frozen=True)
class TimelineQuery:
    account: str
    subject: str
    kind: str
    since: str
    interactions: tuple[str, ...]
    watermarks: tuple[int, int]

    def records(
        self,
        *,
        before=None,
        after=None,
        selected=None,
        page_size=None,
        encounters=False,
        candidates=None,
    ) -> tuple[str, dict]:
        event_max, interaction_max = self.watermarks
        params = {
            "account": self.account,
            "event_max": event_max,
            "interaction_max": interaction_max,
        }
        types = SUBSCRIPTION_TYPES if self.subject == "subscriptions" else FOLLOW_TYPES
        if self.kind != "all":
            types = types[:1] if self.kind == "gained" else types[1:]
        event_slots = _slots(params, "event_kind", types)
        interaction_slots = _slots(params, "interaction_kind", self.interactions)
        branches = []
        if before:
            params["before_at"] = before[0]
        if self.since:
            params["since"] = self.since
        for source, table, actor, upper, receipt_index, sequence_index in (
            (
                1,
                "events",
                "actor_id",
                "event_max",
                "event_timeline_receipt",
                "event_account_sequence",
            ),
            (
                0,
                "interactions",
                "person_id",
                "interaction_max",
                "interaction_receipt",
                "interaction_account_sequence",
            ),
        ):
            if (not source and not self.interactions and not encounters) or (
                selected and source != selected[0]
            ):
                continue
            slots = event_slots if source else interaction_slots
            kind = "kind" if source else "'interaction.'||kind"
            index = ""
            if page_size and not selected and not candidates:
                index = f" INDEXED BY {sequence_index if after is not None else receipt_index}"
            matches = f"kind IN ({slots})"
            if self.since:
                matches += " AND received_at>=:since"
            projection = f",({matches}) AS matches_scope" if encounters else ""
            branch = f"""SELECT sequence AS position,{source} AS source,{kind} AS kind,
                {actor} AS actor_id,received_at{projection} FROM {table}{index}
                WHERE account_id=:account AND sequence<=:{upper}"""
            if candidates:
                branch += (
                    f" AND sequence IN (SELECT position FROM {candidates} WHERE source={source})"
                )
            if not encounters:
                branch += f" AND {matches}"
            if before:
                mark = f"{upper}_before"
                # At a tie, a higher source is newer; within the same source use sequence.
                _, before_source, before_position = before
                params[mark] = {1: 0, 0: before_position - 1, -1: MAX_SEQUENCE}[
                    source - before_source
                ]
                if page_size and after is None:
                    params["limit"] = page_size
                    branches.append(_limited(f"{branch} AND received_at<:before_at"))
                    if params[mark]:
                        branches.append(
                            _limited(
                                f"{branch} AND received_at=:before_at AND sequence<=:{mark}",
                                tied=True,
                            )
                        )
                    continue
                branch += f" AND (received_at,sequence)<=(:before_at,:{mark})"
            if after is not None:
                mark = f"{upper}_after"
                params[mark] = after[1 - source]
                branch += f" AND sequence>:{mark}"
            if selected:
                params["selected"] = selected[1]
                branch += " AND sequence=:selected"
            if page_size:
                params["limit"] = page_size
                branch = _limited(branch)
            branches.append(branch)
        return " UNION ALL ".join(branches), params


def _limited(branch, *, tied=False):
    order = "sequence DESC" if tied else "received_at DESC,sequence DESC"
    return f"SELECT * FROM ({branch} ORDER BY {order} LIMIT :limit)"


def page_sql(records, *, encounters, correction_sql=""):
    context = f",{encounter_columns('context_')}" if encounters else ""
    return f"""WITH {correction_sql} page AS MATERIALIZED (
        {records} ORDER BY received_at DESC,source DESC,position DESC LIMIT :limit
    ) SELECT r.*,:account AS account_id,
        COALESCE(NULLIF(p.handle,''),e.handle,json_extract(i.profile_data,'$.handle'),
            (SELECT history.handle FROM events history
             WHERE r.source=0 AND history.account_id=:account AND history.actor_id=r.actor_id
             AND history.handle IS NOT NULL ORDER BY history.sequence DESC LIMIT 1)) AS handle,
        COALESCE(NULLIF(p.name,''),e.name,json_extract(i.profile_data,'$.name'),
            (SELECT history.name FROM events history
             WHERE r.source=0 AND history.account_id=:account AND history.actor_id=r.actor_id
             AND history.name IS NOT NULL ORDER BY history.sequence DESC LIMIT 1)) AS name,
        COALESCE(e.provider_at,i.provider_at) AS provider_at,{SNAPSHOT},
        i.post_id,substr(post.text,1,281) AS post_text{context}
    FROM page r {RECORD_JOIN}
    LEFT JOIN known_profiles p ON p.account_id=:account AND p.actor_id=r.actor_id
    LEFT JOIN interaction_posts post ON post.account_id=:account AND post.id=i.post_id
    ORDER BY r.received_at DESC,r.source DESC,r.position DESC"""


def kind_totals_sql(records, *, activity):
    distinct_by_kind = "COUNT(DISTINCT actor_id)" if activity else "0"
    return f"""WITH records AS MATERIALIZED ({records})
    SELECT kind,COUNT(*) AS event_count,{distinct_by_kind} AS distinct_actors,NULL AS oldest_received_at
      FROM records GROUP BY kind
    UNION ALL SELECT NULL,COUNT(*),COUNT(DISTINCT actor_id),MIN(received_at) FROM records"""


def group_rows_sql(records, *, encounters):
    if not encounters:
        return f"""WITH records AS ({records}) SELECT r.*,{SNAPSHOT}
        FROM records r {RECORD_JOIN} ORDER BY r.actor_id"""
    # Previous encounters uses the whole account, including records outside the filtered scope.
    # The receipt key sorts first; a fixed-width sequence preserves order inside ties.
    return f"""WITH history AS ({records}), encounters AS (
        SELECT history.*,
          LAG(position) OVER actor_history IS NOT NULL AS seen_before,
          MAX(CASE kind
            WHEN 'follow.follow' THEN received_at || '!' || printf('%019d',position) || '1'
            WHEN 'follow.unfollow' THEN received_at || '!' || printf('%019d',position) || '0' END)
            OVER prior_history AS previous_follow
        FROM history
        WINDOW actor_history AS (PARTITION BY actor_id ORDER BY received_at,source,position),
        prior_history AS (actor_history ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
    ) SELECT position,source,actor_id,kind,received_at,seen_before,
        CASE substr(previous_follow,-1)
          WHEN '1' THEN 'follow.follow' WHEN '0' THEN 'follow.unfollow' END AS previous_follow_kind
    FROM encounters WHERE matches_scope ORDER BY actor_id"""
