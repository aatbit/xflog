"""Exact totals over local records, with per-actor streaming for derived buckets."""

import json
from collections import Counter
from dataclasses import asdict

from .. import audience_groups
from ..audience_groups.previous_encounters import KEY as ENCOUNTERS_KEY
from .timeline_cursor import InvalidTimelineRequest
from .timeline_queries import group_rows_sql, kind_totals_sql


def empty_aggregate(scope, revision):
    return {
        "total_events": 0,
        "distinct_actors": 0,
        "kinds": {},
        "groups": [],
        "revision": revision,
        "profile_revision": "",
        "scope": scope,
        "oldest_received_at": None,
    }


class BucketCounts:
    def __init__(self, module):
        self.module = module
        self.counts = {}
        self.latest = {}
        self.actor = None
        self.actor_buckets = set()

    def add(self, event, order):
        if event["actor_id"] != self.actor:
            self.actor = event["actor_id"]
            self.actor_buckets.clear()
        bucket = audience_groups.bucket_for(self.module, event)
        key = bucket.key
        if key not in self.counts:
            self.counts[key] = {**asdict(bucket), "event_count": 0, "distinct_actors": 0}
            if self.module.dynamic_buckets:
                self.latest[key] = order
        item = self.counts[key]
        if self.module.dynamic_buckets and order > self.latest[key]:
            self.latest[key] = order
            item["label"] = bucket.label
        item["event_count"] += 1
        if key not in self.actor_buckets:
            item["distinct_actors"] += 1
            self.actor_buckets.add(key)

    def result(self):
        if self.module.dynamic_buckets:
            return sorted(
                self.counts.values(), key=lambda item: (item["key"] == "unknown", item["label"])
            )
        return [
            self.counts[bucket.key] for bucket in self.module.buckets if bucket.key in self.counts
        ]


def encounter_from_row(row):
    return {
        "seen_before": bool(row["seen_before"]),
        "previous_follow_kind": row["previous_follow_kind"],
    }


async def aggregate_records(db, query, module):
    if module and module.prepare and module.key != ENCOUNTERS_KEY:
        raise InvalidTimelineRequest("History totals are unavailable for this audience group.")
    activity = module is not None and module.key == "activity"
    records, params = query.records()
    async with db.execute(kind_totals_sql(records, activity=activity), params) as cursor:
        kind_counts = {row["kind"]: dict(row) async for row in cursor}
    totals = kind_counts.pop(None)
    groups = []
    if activity:
        for bucket in module.buckets:
            if item := kind_counts.get(bucket.key):
                groups.append(
                    {
                        **asdict(bucket),
                        "event_count": item["event_count"],
                        "distinct_actors": item["distinct_actors"],
                    }
                )
    elif module:
        counts = BucketCounts(module)
        encounters = module.key == ENCOUNTERS_KEY
        if encounters:
            records, params = query.records(encounters=True)
        async with db.execute(group_rows_sql(records, encounters=encounters), params) as cursor:
            async for row in cursor:
                data = (
                    {ENCOUNTERS_KEY: encounter_from_row(row)}
                    if encounters
                    else json.loads(row["group_data"])
                )
                event = {
                    "actor_id": row["actor_id"],
                    "kind": row["kind"],
                    "received_at": row["received_at"],
                    "group_data": data,
                }
                counts.add(event, (row["received_at"], row["source"], row["position"]))
        groups = counts.result()
    return {
        "total_events": totals["event_count"],
        "distinct_actors": totals["distinct_actors"],
        "kinds": {key: item["event_count"] for key, item in kind_counts.items()},
        "groups": groups,
        "oldest_received_at": totals["oldest_received_at"],
    }


def aggregate_demo(events, module):
    kinds = Counter(event["kind"] for event in events)
    actors = {event["actor_id"] for event in events}
    groups = []
    if module:
        counts = BucketCounts(module)
        for event in sorted(events, key=lambda event: event["actor_id"]):
            counts.add(event, (event["received_at"], 1, event["sequence"]))
        groups = counts.result()
    return {
        "total_events": len(events),
        "distinct_actors": len(actors),
        "kinds": kinds,
        "groups": groups,
        "oldest_received_at": min((event["received_at"] for event in events), default=None),
    }
