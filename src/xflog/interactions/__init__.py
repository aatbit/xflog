"""Event-only interaction capture; missing references never cause profile lookups."""

import re

from ..tracking.events import timestamp, utc_now

TYPES = {
    "replies": ("Replies received", "post.reply.create", "$0.005/event"),
    "mentions": ("Mentions received", "post.mention.create", "$0.005/event"),
    "quotes": ("Quotes received", "post.quote.create", "$0.005/event"),
    "reposts": ("Reposts received", "post.repost.create", "$0.005/event"),
    "likes_received": ("Likes received", "like.create:inbound", "$0.001/event"),
    "likes_given": ("Your likes", "like.create:outbound", "$0.001/event"),
    "your_posts": ("Your posts & replies", "post.create", "$0.005/event · all your posts"),
}
PRIVATE_POSTS = {value[1] for value in TYPES.values() if value[1].startswith("post.")} - {
    "post.create"
}


def numeric(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value) is not None


def choices(selection):
    saved = selection.get("interactions", {})
    return {key: saved.get(key) is True for key in TYPES} if isinstance(saved, dict) else {}


def selected(selection):
    kinds = [TYPES[key][1] for key, enabled in choices(selection).items() if enabled]
    if "like.create:inbound" in kinds and "like.create:outbound" in kinds:
        kinds = [kind for kind in kinds if not kind.startswith("like.")] + ["like.create:both"]
    return tuple(kinds)


def catalog():
    return [{"key": key, "label": label, "cost": cost} for key, (label, _, cost) in TYPES.items()]


def subscription_filter(kind, account):
    result = {"user_id": account}
    if kind.startswith(("follow.", "subscriptions.", "like.")) and kind != "like.create:both":
        result["qualifiers"] = {"direction": kind.split(":", 1)[1] if ":" in kind else "inbound"}
    return result


def subscription_key(item):
    kind = item["event_type"]
    if kind == "like.create":
        filters = item["filter"]
        qualifiers = filters.get("qualifiers", {})
        if not isinstance(qualifiers, dict):
            raise ValueError("Invalid like filter qualifiers.")
        direct = filters.get("direction")
        qualified = qualifiers.get("direction")
        if direct and qualified and direct != qualified:
            raise ValueError("Conflicting like direction.")
        direction = filters.get("direction") or (
            qualifiers.get("direction") if isinstance(qualifiers, dict) else None
        )
        if direction not in {None, "inbound", "outbound"}:
            raise ValueError("Invalid like direction.")
        return f"{kind}:{direction}" if direction else "like.create:both"
    return kind


def post_snapshot(source):
    if not isinstance(source, dict) or not numeric(source.get("id")):
        raise ValueError("Missing post ID.")
    conversation = source.get("conversation_id")
    author = source.get("author_id")
    if conversation is not None and not numeric(conversation):
        raise ValueError("Invalid conversation ID.")
    if author is not None and not numeric(author):
        raise ValueError("Invalid author ID.")
    text = source.get("text")
    if text is not None and not isinstance(text, str):
        raise ValueError("Invalid post text.")
    return {
        "id": source["id"],
        "author_id": author,
        "conversation_id": conversation,
        "text": text[:50000] if text is not None else None,
        "created_at": timestamp(source.get("created_at")),
    }


def parse_interaction(envelope, account, enabled=None):
    data = envelope.get("data", envelope) if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        return None
    kind = data.get("event_type")
    if kind not in {value[1].split(":")[0] for value in TYPES.values()}:
        return None
    filters = data.get("filter", {})
    if not isinstance(filters, dict) or filters.get("user_id") != account:
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Missing interaction payload.")
    people = set()
    if kind == "like.create":
        liker, author, post_id = (
            payload.get(key)
            for key in ("liking_user_id", "liked_tweet_author_id", "liked_tweet_id")
        )
        if not all(numeric(value) for value in (liker, author, post_id)):
            raise ValueError("Invalid like participants.")
        if author == account and liker != account:
            key, people = "likes_received", {liker}
        elif liker == account and author != account:
            key, people = "likes_given", {author}
        else:
            return None
    else:
        key = next(key for key, value in TYPES.items() if value[1] == kind)
    if enabled is not None and not enabled.get(key):
        return None
    identity = data.get("event_uuid")
    if not isinstance(identity, str) or not 1 <= len(identity) <= 200:
        raise ValueError("Missing interaction identity.")
    includes = data.get("includes") or {}
    if not isinstance(includes, dict):
        raise ValueError("Invalid interaction includes.")
    related = includes.get("posts", includes.get("tweets", []))
    if not isinstance(related, list) or len(related) > 100:
        raise ValueError("Invalid related posts.")
    posts = {post["id"]: post for post in map(post_snapshot, related)}
    received = utc_now()
    recorded = timestamp(data.get("created_at")) or received
    if kind == "like.create":
        posts.setdefault(
            post_id,
            {
                "id": post_id,
                "author_id": author,
                "conversation_id": None,
                "text": None,
                "created_at": None,
            },
        )
    else:
        post = post_snapshot(payload)
        posts[post["id"]] = post
        post_id = post["id"]
        author = post["author_id"]
        if not author:
            raise ValueError("Missing post author.")
        if kind == "post.create":
            if author != account:
                return None
            reply_to = payload.get("in_reply_to_user_id")
            if numeric(reply_to):
                people.add(reply_to)
            references = payload.get("referenced_posts", payload.get("referenced_tweets", []))
            if not isinstance(references, list):
                raise ValueError("Invalid post references.")
            for reference in references:
                if not isinstance(reference, dict) or not numeric(reference.get("id")):
                    raise ValueError("Invalid post reference.")
                referenced = posts.get(reference["id"], {})
                if referenced.get("author_id"):
                    people.add(referenced["author_id"])
            entities = payload.get("entities") or {}
            mentions = entities.get("mentions", []) if isinstance(entities, dict) else []
            if isinstance(mentions, list):
                people.update(
                    item["id"]
                    for item in mentions
                    if isinstance(item, dict) and numeric(item.get("id"))
                )
        elif author != account:
            people.add(author)
        else:
            return None
    return {
        "event_id": identity,
        "key": key,
        "post_id": post_id,
        "people": people - {account},
        "posts": list(posts.values()),
        "provider_at": recorded,
        "received_at": received,
    }
