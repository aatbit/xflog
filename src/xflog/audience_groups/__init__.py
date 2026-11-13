"""Trusted event/history grouping modules; no X client or tokens are provided."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

HistoryLookup = Callable[[list[dict]], Awaitable[dict[int, dict]]]
HistoryPreparation = Callable[[list[dict], HistoryLookup], Awaitable[list[dict]]]


@dataclass(frozen=True)
class Bucket:
    key: str
    label: str
    tone: str = "neutral"


@dataclass(frozen=True)
class AudienceGroup:
    key: str
    label: str
    description: str
    buckets: tuple[Bucket, ...]
    assign: Callable[[dict], str | Bucket]
    capture: Callable[[dict], dict] | None = None
    default_enabled: bool = False
    prepare: HistoryPreparation | None = None
    dynamic_buckets: bool = False


MODULES: dict[str, AudienceGroup] = {}


def register(module: AudienceGroup):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", module.key) or module.key in MODULES:
        raise ValueError("Audience group IDs must be unique lowercase names.")
    keys = [bucket.key for bucket in module.buckets]
    if not keys or len(keys) != len(set(keys)) or "unknown" not in keys:
        raise ValueError("Audience groups need unique buckets and an unknown bucket.")
    if any(bucket.tone not in {"neutral", "positive", "negative"} for bucket in module.buckets):
        raise ValueError("Audience groups must use shared semantic color tones.")
    MODULES[module.key] = module


def preferences(saved=None) -> dict[str, bool]:
    saved = saved if isinstance(saved, dict) else {}
    return {
        key: saved[key] if type(saved.get(key)) is bool else module.default_enabled
        for key, module in MODULES.items()
    }


def catalog(saved=None) -> list[dict]:
    enabled = preferences(saved)
    return [
        {
            "key": key,
            "label": module.label,
            "description": module.description,
            "enabled": enabled[key],
            "dynamic_buckets": module.dynamic_buckets,
            "data_policy": "recorded_history" if module.prepare else "received_events_only",
            "buckets": [asdict(bucket) for bucket in module.buckets],
        }
        for key, module in sorted(MODULES.items(), key=lambda item: not item[1].default_enabled)
    ]


def capture(source: dict, saved=None) -> dict:
    enabled = preferences(saved)
    captured = {}
    for key, module in MODULES.items():
        if enabled[key] and module.capture:
            value = module.capture(source)
            if value:
                captured[key] = value
    return captured


def bucket_for(module: AudienceGroup, event: dict) -> Bucket:
    return _resolve_bucket(module, module.assign(event))


def _resolve_bucket(module: AudienceGroup, value: str | Bucket) -> Bucket:
    if module.dynamic_buckets and isinstance(value, Bucket):
        return value
    return next(
        (bucket for bucket in module.buckets if bucket.key == value),
        next(bucket for bucket in module.buckets if bucket.key == "unknown"),
    )


def decorate(event: dict, saved=None) -> dict:
    enabled = preferences(saved)
    groups, descriptors = {}, {}
    for key, module in MODULES.items():
        if enabled[key]:
            value = module.assign(event)
            bucket = _resolve_bucket(module, value)
            groups[key] = bucket.key
            if module.dynamic_buckets and isinstance(value, Bucket):
                descriptors[key] = asdict(bucket)
    return {**event, "audience_groups": groups, "audience_group_buckets": descriptors}


async def decorate_history(events: list[dict], saved, lookup: HistoryLookup) -> list[dict]:
    if not events:
        return []
    enabled = preferences(saved)
    for key, module in MODULES.items():
        if enabled[key] and module.prepare:
            events = await module.prepare(events, lookup)
    return [decorate(event, enabled) for event in events]


# Explicit imports are the allowlist; registering a module never installs third-party code.
from . import (  # noqa: E402, F401
    account_age,
    account_size,
    activity,
    previous_encounters,
    profile_location,
    verification,
)
