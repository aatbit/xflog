from . import AudienceGroup, Bucket, HistoryLookup, register

KEY = "previous-encounters"


def assign(event: dict) -> str:
    context = event.get("group_data", {}).get(KEY, {})
    if not isinstance(context, dict) or type(context.get("seen_before")) is not bool:
        return "unknown"
    return encounter_bucket(
        event.get("kind"), context["seen_before"], context.get("previous_follow_kind")
    )


def encounter_bucket(kind, seen_before, previous_follow_kind) -> str:
    if not seen_before:
        return "first-appearance"
    if kind == "follow.follow" and previous_follow_kind == "follow.unfollow":
        return "followed-again"
    return "seen-before"


async def prepare(events: list[dict], lookup: HistoryLookup) -> list[dict]:
    contexts = await lookup(events)
    return [
        {
            **event,
            "group_data": {
                **event.get("group_data", {}),
                KEY: contexts.get(event.get("sequence"), {}),
            },
        }
        for event in events
    ]


register(
    AudienceGroup(
        key=KEY,
        label="Previous encounters",
        description="First appearance, seen before, or followed again after a recorded unfollow. Uses this account's full saved log; no extra X requests.",
        buckets=(
            Bucket("first-appearance", "First appearance"),
            Bucket("seen-before", "Seen before"),
            Bucket("followed-again", "Followed again", "positive"),
            Bucket("unknown", "Unknown"),
        ),
        assign=assign,
        prepare=prepare,
    )
)
