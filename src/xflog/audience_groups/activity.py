from . import AudienceGroup, Bucket, register


def assign(event: dict) -> str:
    return event.get("kind", "unknown")


register(
    AudienceGroup(
        key="activity",
        label="Activity",
        description="Group recorded audience changes and enabled interactions by activity.",
        default_enabled=True,
        buckets=(
            Bucket("follow.follow", "Followed you", "positive"),
            Bucket("follow.unfollow", "Unfollowed", "negative"),
            Bucket("subscriptions.subscribe", "Subscribed", "positive"),
            Bucket("subscriptions.unsubscribe", "Expired", "negative"),
            Bucket("interaction.replies", "Replies"),
            Bucket("interaction.mentions", "Mentions"),
            Bucket("interaction.quotes", "Quotes"),
            Bucket("interaction.reposts", "Reposts"),
            Bucket("interaction.likes_received", "Likes received"),
            Bucket("interaction.likes_given", "Your likes"),
            Bucket("interaction.your_posts", "Your posts & replies"),
            Bucket("unknown", "Unknown"),
        ),
        assign=assign,
    )
)
