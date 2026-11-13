"""Synthetic examples returned in memory, never inserted into the real event database."""

from datetime import datetime, timedelta, timezone

from .. import audience_groups
from ..tracking.events import FOLLOW_TYPES, Event, timestamp
from .summary import SUBJECT_TYPES, activity_window, all_readings, readings
from .timeline_aggregate import aggregate_demo
from .timeline_cursor import Cursor, InvalidTimelineRequest, decode_cursor, scope_key

DEMO_EVENT_COUNT = 76

PEOPLE = [
    ("Maya Chen", "mayamakes"),
    ("Arjun Mehta", "arjunbuilds"),
    ("Sofia Reyes", "sofiadraws"),
    ("Theo Park", "theopark"),
    ("Nina Wilson", "ninawrites"),
    ("Oscar Lee", "oscarcodes"),
    ("Amara Okafor", "amarastudio"),
    ("Eli Brooks", "elibrooks"),
    ("Lena Fischer", "lenafischer"),
    ("Ravi Shah", "ravishah"),
    ("Isla Morgan", "islamorgan"),
    ("Jules Martin", "julesdesign"),
]


def profile_metadata(index: int) -> dict:
    person = index % len(PEOPLE)
    count = (0, 43, 189, 650, 1200, 5900, 15000, 42000, None, 88, 300, 11000)[person]
    created = ("2026-07-01T12:00:00Z", "2024-05-01T12:00:00Z", "2018-01-01T12:00:00Z", None)[
        person % 4
    ]
    verification = (
        {"verified": True, "verified_type": "blue"},
        {"verified": True, "verified_type": "business"},
        {"verified": True, "verified_type": "government"},
        {"verified": True},
        {"verified": False},
        {},
    )[person % 6]
    location = (
        "NYC",
        "New York City",
        "London",
        " london ",
        "Bangalore, India",
        "Bengaluru, India",
        "U.S.A.",
        "United States",
        "Remote",
        None,
        "",
        "Unknown",
    )[person]
    return {
        "public_metrics": {"followers_count": count},
        "created_at": created,
        "location": location,
        **verification,
    }


def demo_events(anchor=None) -> list[dict]:
    if anchor is None:
        anchor = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1)
    events = []
    for index in range(DEMO_EVENT_COUNT):
        subject = "subscriptions" if index % 7 == 6 else "followers"
        lost = index % 5 == 3
        kind = (
            ("subscriptions.unsubscribe" if lost else "subscriptions.subscribe")
            if subject == "subscriptions"
            else ("follow.unfollow" if lost else "follow.follow")
        )
        name, handle = PEOPLE[index % len(PEOPLE)]
        provider = anchor - timedelta(minutes=index * 147 + (index % 4) * 31)
        event = Event(
            f"synthetic-{DEMO_EVENT_COUNT - index}",
            kind,
            "demo",
            str(1000 + index % len(PEOPLE)),
            handle,
            name,
            provider.isoformat() if index % 9 else None,
            (provider + timedelta(seconds=4)).isoformat(),
        ).public()
        event["group_data"] = audience_groups.capture(
            profile_metadata(index), dict.fromkeys(audience_groups.MODULES, True)
        )
        event["sequence"] = DEMO_EVENT_COUNT - index
        events.append(event)
    return events


def demo_activity(period: str, subject: str) -> dict:
    if period == "all":
        return {
            **all_readings(demo_history({"subject": subject})["counts"], subject),
            "synthetic": True,
        }
    events = demo_events()
    end = max(datetime.fromisoformat(event["received_at"]) for event in events)
    window = activity_window(period, end + timedelta(seconds=1))
    counts = {"current": {}, "previous": {}}
    for event in events:
        received = datetime.fromisoformat(event["received_at"])
        if event["kind"] not in SUBJECT_TYPES[subject] or not (
            window.previous_start <= received < window.end
        ):
            continue
        bucket = "current" if received >= window.start else "previous"
        kind = event["kind"]
        counts[bucket][kind] = counts[bucket].get(kind, 0) + 1
    return {**readings(counts, window, subject), "synthetic": True}


async def encounter_context(events: list[dict]) -> dict[int, dict]:
    return _encounters(events, demo_events())


def _encounters(events, records):
    if any(event["account_id"] != "demo" for event in events):
        return {}
    wanted = {event["sequence"] for event in events}
    seen, followers, contexts = set(), {}, {}
    for event in reversed(records):
        actor = (event["account_id"], event["actor_id"])
        if event["sequence"] in wanted:
            contexts[event["sequence"]] = {
                "seen_before": actor in seen,
                "previous_follow_kind": followers.get(actor),
            }
        seen.add(actor)
        if event["kind"] in FOLLOW_TYPES:
            followers[actor] = event["kind"]
    return contexts


def _filtered(events, query):
    subject = query.get("subject", "followers")
    types = SUBJECT_TYPES[subject]
    kind = query.get("kind", "all")
    if kind != "all":
        types = types[:1] if kind == "gained" else types[1:]
    since = query.get("since", "")
    return [event for event in events if event["kind"] in types and event["received_at"] >= since]


def demo_history(query: dict) -> dict:
    events = demo_events()
    filtered = _filtered(events, query)
    counts = {
        kind: sum(event["kind"] == kind for event in events)
        for kind in (
            "follow.follow",
            "follow.unfollow",
            "subscriptions.subscribe",
            "subscriptions.unsubscribe",
        )
    }
    before = int(query.get("before", 0))
    if before:
        filtered = [event for event in filtered if event["sequence"] < before]
    limit = min(50, max(1, int(query.get("limit", 25))))
    return {
        "events": filtered[:limit],
        "next": filtered[limit - 1]["sequence"] if len(filtered) > limit else None,
        "counts": counts,
        "synthetic": True,
    }


async def demo_timeline(query, saved):
    before = decode_cursor(query["before"])
    groups = audience_groups.preferences(saved)
    lens = query["lens"]
    module = audience_groups.MODULES.get(lens) if groups.get(lens) else None
    scope = scope_key(("demo", query["subject"], query["kind"], query["since"], lens, groups))
    if before and (before.scope != scope or before.key[1] != 1):
        raise InvalidTimelineRequest("Timeline cursor does not match this history scope.")
    if before:
        anchor_time, marker = before.watermarks
        if marker or before.key[2] > DEMO_EVENT_COUNT:
            raise InvalidTimelineRequest("Invalid demo snapshot.")
        try:
            anchor = datetime.fromtimestamp(anchor_time, timezone.utc)
        except (ValueError, OverflowError, OSError):
            raise InvalidTimelineRequest("Invalid demo snapshot.") from None
    else:
        anchor = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1)
    try:
        records = demo_events(anchor)
    except OverflowError:
        raise InvalidTimelineRequest("Invalid demo snapshot.") from None

    async def lookup(rows):
        return _encounters(rows, records)

    filtered = _filtered(records, query)
    if before:
        if not any(
            (event["received_at"], 1, event["sequence"]) == before.key for event in filtered
        ):
            raise InvalidTimelineRequest("Invalid demo snapshot.")
        filtered = [event for event in filtered if event["sequence"] < before.key[2]]
    limit = query["limit"]
    rows = await audience_groups.decorate_history(
        filtered if not before else filtered[:limit], groups, lookup
    )
    result = {"events": rows[:limit], "next": None, "synthetic": True}
    anchor_time = int(anchor.timestamp())
    if len(filtered) > limit:
        last = rows[limit - 1]
        result["next"] = Cursor(
            (last["received_at"], 1, last["sequence"]), (anchor_time, 0), scope
        ).encode()
    if not before:
        result["aggregate"] = {
            **aggregate_demo(rows, module),
            "revision": timestamp(anchor.isoformat()),
            "profile_revision": "",
            "scope": scope,
        }
    return result
