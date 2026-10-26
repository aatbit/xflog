"""Rolling readings from recorded receipts, independent of timeline pagination."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .events import FOLLOW_TYPES, SUBSCRIPTION_TYPES

PERIODS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "12h": 12 * 3600,
    "24h": 24 * 3600,
    "3d": 3 * 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
    "90d": 90 * 86400,
}
SUBJECT_TYPES = {"followers": FOLLOW_TYPES, "subscriptions": SUBSCRIPTION_TYPES}


@dataclass(frozen=True)
class ActivityWindow:
    period: str
    end: datetime

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=PERIODS[self.period])

    @property
    def start(self) -> datetime:
        return self.end - self.duration

    @property
    def previous_start(self) -> datetime:
        return self.start - self.duration


def activity_window(period: str, as_of: datetime | None = None) -> ActivityWindow:
    if period not in PERIODS:
        raise ValueError("Invalid activity period.")
    end = as_of or datetime.now(timezone.utc)
    if end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("Activity time must include a timezone.")
    return ActivityWindow(period, end.astimezone(timezone.utc).replace(microsecond=0))


def compare(current: float | None, previous: float | None) -> dict:
    if current is None or previous is None:
        comparison, percent = "unavailable", None
    elif previous == 0:
        comparison, percent = ("new", None) if current else ("percent", 0)
    else:
        comparison, percent = "percent", (current - previous) / previous * 100
    return {
        "value": current,
        "previous": previous,
        "comparison": comparison,
        "change_percent": percent,
    }


def readings(counts: dict, window: ActivityWindow, subject: str) -> dict:
    gained, lost = SUBJECT_TYPES[subject]
    hours = window.duration.total_seconds() / 3600
    values = []
    for bucket in ("current", "previous"):
        gains, losses = (counts.get(bucket, {}).get(kind, 0) for kind in (gained, lost))
        values.append(
            {
                "gained": gains,
                "lost": losses,
                "gain_rate": gains / hours,
                "loss_rate": losses / hours,
                "ratio": gains / losses if losses else None,
            }
        )
    current, previous = values
    return {
        "period": window.period,
        "periods": list(PERIODS),
        "subject": subject,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "previous_start": window.previous_start.isoformat(),
        "metrics": {key: compare(value, previous[key]) for key, value in current.items()},
    }
