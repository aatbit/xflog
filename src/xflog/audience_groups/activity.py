from . import AudienceGroup, Bucket, register


def assign(event: dict) -> str:
    return event.get("kind", "unknown")


register(
    AudienceGroup(
        key="activity",
        label="Activity",
        description="Arrange people by their latest event in the loaded history.",
        default_enabled=True,
        buckets=(
            Bucket("follow.follow", "Followed you", "positive"),
            Bucket("follow.unfollow", "Unfollowed", "negative"),
            Bucket("subscriptions.subscribe", "Subscribed", "positive"),
            Bucket("subscriptions.unsubscribe", "Expired", "negative"),
            Bucket("unknown", "Unknown"),
        ),
        assign=assign,
    )
)
