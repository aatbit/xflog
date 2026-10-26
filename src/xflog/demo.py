"""Synthetic examples returned in memory, never inserted into the real event database."""

from datetime import datetime, timedelta, timezone

from . import audience_groups
from .events import FOLLOW_TYPES, Event

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


def demo_events() -> list[dict]:
    anchor = datetime(2026, 10, 26, 10, 42, tzinfo=timezone.utc)
    events = []
    for index in range(76):
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
            f"synthetic-{76 - index}",
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
        event["sequence"] = 76 - index
        events.append(event)
    return events


async def encounter_context(events: list[dict]) -> dict[int, dict]:
    if any(event["account_id"] != "demo" for event in events):
        return {}
    wanted = {event["sequence"] for event in events}
    seen, followers, contexts = set(), {}, {}
    for event in reversed(demo_events()):
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


def demo_history(query: dict) -> dict:
    events = demo_events()
    prefix = "subscriptions." if query.get("subject") == "subscriptions" else "follow."
    filtered = [event for event in events if event["kind"].startswith(prefix)]
    counts = {
        kind: sum(event["kind"] == kind for event in events)
        for kind in (
            "follow.follow",
            "follow.unfollow",
            "subscriptions.subscribe",
            "subscriptions.unsubscribe",
        )
    }
    kind = query.get("kind", "all")
    if kind != "all":
        suffix = ("follow", "subscribe") if kind == "gained" else ("unfollow", "unsubscribe")
        filtered = [event for event in filtered if event["kind"].split(".")[1] in suffix]
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
