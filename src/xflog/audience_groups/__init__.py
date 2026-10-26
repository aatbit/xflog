"""Trusted, event-only grouping modules; no network or token access is provided."""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass


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
    assign: Callable[[dict], str]
    capture: Callable[[dict], dict] | None = None
    default_enabled: bool = False


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
            "data_policy": "received_events_only",
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


def decorate(event: dict, saved=None) -> dict:
    enabled = preferences(saved)
    groups = {}
    for key, module in MODULES.items():
        if enabled[key]:
            bucket = module.assign(event)
            groups[key] = bucket if bucket in {item.key for item in module.buckets} else "unknown"
    return {**event, "audience_groups": groups}


# Explicit imports are the allowlist; registering a module never installs third-party code.
from . import account_size, activity  # noqa: E402, F401
