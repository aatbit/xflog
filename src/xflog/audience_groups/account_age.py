from datetime import datetime, timezone

from . import AudienceGroup, Bucket, register

KEY = "account-age"


def parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def capture(source: dict) -> dict:
    created = parse_time(source.get("created_at"))
    return {"created_at": created.isoformat()} if created else {}


def assign(event: dict) -> str:
    snapshot = event.get("group_data", {}).get(KEY, {})
    if not isinstance(snapshot, dict):
        return "unknown"
    created = parse_time(snapshot.get("created_at"))
    recorded = parse_time(event.get("received_at"))
    if not created or not recorded or created > recorded:
        return "unknown"
    try:
        anniversary = created.replace(year=recorded.year)
    except ValueError:
        # Feb 29 uses March 1 in non-leap years, keeping the original time of day.
        anniversary = created.replace(year=recorded.year, month=3, day=1)
    age = recorded.year - created.year
    if recorded < anniversary:
        age -= 1
    if age < 1:
        return "under-1-year"
    if age < 3:
        return "1-3-years"
    return "3-plus-years"


register(
    AudienceGroup(
        key=KEY,
        label="Account age",
        description="Age when the event was recorded, using the creation date delivered by X. No extra requests; missing dates stay Unknown.",
        buckets=(
            Bucket("under-1-year", "Under 1 year"),
            Bucket("1-3-years", "1–3 years"),
            Bucket("3-plus-years", "3+ years"),
            Bucket("unknown", "Unknown"),
        ),
        capture=capture,
        assign=assign,
    )
)
