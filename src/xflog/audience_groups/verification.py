from . import AudienceGroup, Bucket, register

KEY = "verification"
BADGE_TYPES = ("blue", "business", "government")


def capture(source: dict) -> dict:
    verified = source.get("verified")
    badge = source.get("verified_type")
    if type(verified) is not bool:
        return {}
    if (verified and badge == "none") or (not verified and badge in BADGE_TYPES):
        return {}
    snapshot = {"verified": verified}
    if verified and badge in BADGE_TYPES:
        snapshot["verified_type"] = badge
    return snapshot


def assign(event: dict) -> str:
    snapshot = event.get("group_data", {}).get(KEY, {})
    if not isinstance(snapshot, dict):
        return "unknown"
    snapshot = capture(snapshot)
    if not snapshot:
        return "unknown"
    if not snapshot["verified"]:
        return "unverified"
    return snapshot.get("verified_type", "verified")


register(
    AudienceGroup(
        key=KEY,
        label="Verification",
        description="Verification and badge type delivered with new events. No extra X requests; missing status stays Unknown.",
        buckets=(
            Bucket("blue", "Blue badge"),
            Bucket("business", "Business badge"),
            Bucket("government", "Government badge"),
            Bucket("verified", "Verified · type unknown"),
            Bucket("unverified", "Unverified"),
            Bucket("unknown", "Unknown"),
        ),
        capture=capture,
        assign=assign,
    )
)
