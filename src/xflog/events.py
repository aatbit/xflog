import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

FOLLOW_TYPES = ("follow.follow", "follow.unfollow")
SUBSCRIPTION_TYPES = ("subscriptions.subscribe", "subscriptions.unsubscribe")
EVENT_TYPES = FOLLOW_TYPES + SUBSCRIPTION_TYPES
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}\Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must have a timezone.")
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class Event:
    event_id: str
    kind: str
    account_id: str
    actor_id: str
    handle: str | None
    name: str | None
    provider_at: str | None
    received_at: str

    def public(self) -> dict:
        result = asdict(self)
        result["profile_url"] = (
            f"https://x.com/{self.handle}"
            if self.handle and HANDLE.fullmatch(self.handle)
            else None
        )
        return result


def parse_event(envelope: dict, account_id: str) -> Event | None:
    """Only incoming activity for this authenticated account crosses the storage boundary."""
    if isinstance(envelope, dict):
        envelope = envelope.get("data", envelope)
    if not isinstance(envelope, dict) or envelope.get("event_type") not in EVENT_TYPES:
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Missing activity payload.")
    kind = envelope["event_type"]
    source = payload.get("source", {})
    target = payload.get("target", {})
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ValueError("Invalid activity users.")
    source = source.get("data", source)
    target = target.get("data", target)
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ValueError("Invalid activity users.")
    actor_id = source.get("id")
    target_id = target.get("id")
    if not isinstance(actor_id, str) or not actor_id.isdigit():
        raise ValueError("Missing source user ID.")
    if not isinstance(target_id, str) or not target_id.isdigit():
        raise ValueError("Missing target user ID.")
    if target_id != account_id or actor_id == account_id:
        return None
    identity = envelope.get("event_uuid")
    if not isinstance(identity, str) or not 1 <= len(identity) <= 200:
        raise ValueError("Missing stable event identity.")
    handle = source.get("username")
    name = source.get("name")
    return Event(
        event_id=identity,
        kind=kind,
        account_id=account_id,
        actor_id=actor_id,
        handle=handle if isinstance(handle, str) and HANDLE.fullmatch(handle) else None,
        name=name[:200] if isinstance(name, str) else None,
        provider_at=timestamp(envelope.get("created_at")),
        received_at=utc_now(),
    )
