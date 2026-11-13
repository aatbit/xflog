"""Scoped continuations for the mixed local timeline."""

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass

from ..tracking.events import timestamp

MAX_SEQUENCE = 2**63 - 1


class InvalidTimelineRequest(ValueError):
    pass


def scope_key(parts) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def sequence(value: str) -> int:
    if value.isascii() and value.isdecimal() and len(value) <= 19:
        result = int(value)
        if result <= MAX_SEQUENCE:
            return result
    raise InvalidTimelineRequest("Invalid timeline sequence.")


def revision_watermarks(value: str) -> tuple[int, int]:
    first, separator, remaining = value.partition(":")
    if separator and len(value) <= 128:
        return sequence(first), sequence(remaining.partition(":")[0])
    raise InvalidTimelineRequest("Invalid timeline revision.")


def selected_position(value: str) -> tuple[int, int]:
    prefix, _, kind_and_position = value.partition(":")
    kind, _, number = kind_and_position.partition(":")
    if prefix == "timeline" and kind in {"event", "interaction"}:
        position = sequence(number)
        if position and str(position) == number:
            return int(kind == "event"), position
    raise InvalidTimelineRequest("Invalid selected timeline event.")


@dataclass(frozen=True)
class Cursor:
    key: tuple[str, int, int]
    watermarks: tuple[int, int]
    scope: str

    def encode(self) -> str:
        payload = json.dumps((*self.key, *self.watermarks, self.scope), separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(value: str) -> Cursor | None:
    if value in {"", "0"}:
        return None
    try:
        if len(value) > 256:
            raise ValueError
        data = base64.b64decode(value.encode() + b"=" * (-len(value) % 4), b"-_", validate=True)
        decoded = json.loads(data)
        if not isinstance(decoded, list) or len(decoded) != 6:
            raise ValueError
        received, source, position, event_max, interaction_max, scope = decoded
        watermarks = (event_max, interaction_max)
        if (
            timestamp(received) != received
            or not isinstance(received, str)
            or type(source) is not int
            or source not in {0, 1}
            or type(position) is not int
            or not all(type(mark) is int and 0 <= mark <= MAX_SEQUENCE for mark in watermarks)
            or not 0 < position <= watermarks[1 - source]
            or not isinstance(scope, str)
            or len(scope) != 64
            or any(character not in "0123456789abcdef" for character in scope)
        ):
            raise ValueError
        cursor = Cursor((received, source, position), watermarks, scope)
        if cursor.encode() != value:
            raise ValueError
        return cursor
    except (ValueError, TypeError, binascii.Error, UnicodeError, OverflowError, RecursionError):
        raise InvalidTimelineRequest("Invalid timeline cursor.") from None
