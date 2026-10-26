from . import AudienceGroup, Bucket, register


def capture(source: dict) -> dict:
    metrics = source.get("public_metrics")
    count = metrics.get("followers_count") if isinstance(metrics, dict) else None
    if type(count) is not int or not 0 <= count <= 2**53 - 1:
        return {}
    return {"followers_count": count}


def assign(event: dict) -> str:
    snapshot = event.get("group_data", {}).get("account-size", {})
    count = snapshot.get("followers_count")
    if type(count) is not int or not 0 <= count <= 2**53 - 1:
        return "unknown"
    if count < 100:
        return "under-100"
    if count < 1000:
        return "100-999"
    if count < 10000:
        return "1k-9999"
    return "10k-plus"


register(
    AudienceGroup(
        key="account-size",
        label="Account size",
        description="Follower count included with new events. No extra X requests; older or missing data stays Unknown.",
        buckets=(
            Bucket("under-100", "Under 100 followers"),
            Bucket("100-999", "100–999 followers"),
            Bucket("1k-9999", "1K–9,999 followers"),
            Bucket("10k-plus", "10K+ followers"),
            Bucket("unknown", "Unknown"),
        ),
        capture=capture,
        assign=assign,
    )
)
