from dataclasses import replace

import pytest
from test_history import envelope

from xflog import audience_groups as groups
from xflog.audience_groups import account_age, verification
from xflog.demo import demo_history
from xflog.events import EVENT_TYPES, parse_event
from xflog.storage import Store

ENABLED = {"account-age": True, "verification": True}
RECORDED = "2026-10-26T12:00:00+00:00"


@pytest.mark.parametrize(
    "created,bucket",
    [
        (RECORDED, "under-1-year"),
        ("2025-10-26T12:00:00.000001Z", "under-1-year"),
        ("2025-10-26T12:00:00Z", "1-3-years"),
        ("2025-10-26T13:00:00+01:00", "1-3-years"),
        ("2023-10-26T12:00:00.000001Z", "1-3-years"),
        ("2023-10-26T12:00:00Z", "3-plus-years"),
        ("2010-01-01T00:00:00Z", "3-plus-years"),
        ("2026-10-26T12:00:00.000001Z", "unknown"),
        ("2025-10-26", "unknown"),
        ("2025-10-26T12:00:00", "unknown"),
        ("2025-02-29T12:00:00Z", "unknown"),
        ("0001-01-01T00:00:00+01:00", "unknown"),
        ("9999-12-31T23:59:59-01:00", "unknown"),
        ("not-a-date", "unknown"),
        (None, "unknown"),
        (True, "unknown"),
        ({}, "unknown"),
    ],
)
def test_age_uses_calendar_years_and_recorded_time(created, bucket):
    event = {
        "received_at": RECORDED,
        "provider_at": "2000-01-01T00:00:00Z",
        "group_data": {"account-age": account_age.capture({"created_at": created})},
    }
    assert account_age.assign(event) == bucket


@pytest.mark.parametrize(
    "recorded,bucket",
    [
        ("2025-02-28T23:59:59Z", "under-1-year"),
        ("2025-03-01T00:00:00Z", "1-3-years"),
        ("2027-02-28T23:59:59Z", "1-3-years"),
        ("2027-03-01T00:00:00Z", "3-plus-years"),
        ("2026-10-26T12:00:00", "unknown"),
        (None, "unknown"),
    ],
)
def test_leap_day_anniversary_and_invalid_recorded_date(recorded, bucket):
    assert (
        account_age.assign(
            {
                "received_at": recorded,
                "group_data": {"account-age": {"created_at": "2024-02-29T00:00:00Z"}},
            }
        )
        == bucket
    )


@pytest.mark.parametrize(
    "recorded,bucket",
    [
        ("2025-03-01T00:00:00Z", "under-1-year"),
        ("2025-03-01T11:59:59.999999Z", "under-1-year"),
        ("2025-03-01T12:00:00Z", "1-3-years"),
        ("2027-03-01T00:00:00Z", "1-3-years"),
        ("2027-03-01T11:59:59.999999Z", "1-3-years"),
        ("2027-03-01T12:00:00Z", "3-plus-years"),
    ],
)
def test_leap_anniversary_preserves_creation_time(recorded, bucket):
    assert (
        account_age.assign(
            {
                "received_at": recorded,
                "group_data": {"account-age": {"created_at": "2024-02-29T12:00:00Z"}},
            }
        )
        == bucket
    )


@pytest.mark.parametrize(
    "source,bucket",
    [
        ({"verified": True, "verified_type": "blue"}, "blue"),
        ({"verified": True, "verified_type": "business"}, "business"),
        ({"verified": True, "verified_type": "government"}, "government"),
        ({"verified": True}, "verified"),
        ({"verified": True, "verified_type": "future-badge"}, "verified"),
        ({"verified": True, "verified_type": []}, "verified"),
        ({"verified": False}, "unverified"),
        ({"verified": False, "verified_type": "none"}, "unverified"),
        ({"verified": True, "verified_type": "none"}, "unknown"),
        ({"verified": False, "verified_type": "blue"}, "unknown"),
        ({"verified_type": "government"}, "unknown"),
        ({"is_identity_verified": True}, "unknown"),
        ({"verified": "false"}, "unknown"),
        ({"verified": 0}, "unknown"),
        ({"verified": 1}, "unknown"),
        ({"verified": None}, "unknown"),
        ({"verified": []}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_verification_requires_boolean_and_preserves_badge_types(source, bucket):
    assert (
        verification.assign({"group_data": {"verification": verification.capture(source)}})
        == bucket
    )


@pytest.mark.parametrize("snapshot", [None, [], "false", {}])
def test_missing_or_invalid_snapshots_stay_unknown(snapshot):
    event = {"group_data": dict.fromkeys(ENABLED, snapshot), "received_at": RECORDED}
    assert (account_age.assign(event), verification.assign(event)) == ("unknown", "unknown")


@pytest.mark.parametrize("kind", EVENT_TYPES)
@pytest.mark.parametrize("wrapped", [False, True])
def test_only_incoming_actor_metadata_is_captured(kind, wrapped, monkeypatch):
    monkeypatch.setattr("xflog.events.utc_now", lambda: RECORDED)
    raw = envelope(kind)
    target = raw["data"]["payload"]["target"]["data"]
    target.update(created_at="2026-07-01T00:00:00Z", verified=True, verified_type="blue")
    assert parse_event(raw, "111", ENABLED).group_data == {}
    raw["data"]["payload"]["source"]["data"].update(
        created_at="2024-01-01T00:00:00Z", verified=False
    )
    if not wrapped:
        raw = raw["data"]
        raw["payload"] = {key: value["data"] for key, value in raw["payload"].items()}
    event = parse_event(raw, "111", ENABLED)
    assert groups.decorate(event.public(), ENABLED)["audience_groups"] == {
        "activity": kind,
        "account-age": "1-3-years",
        "verification": "unverified",
    }


def test_disabled_modules_bypass_capture(monkeypatch):
    def forbidden(source):
        raise AssertionError("Disabled group must not execute")

    for key in ENABLED:
        monkeypatch.setitem(groups.MODULES, key, replace(groups.MODULES[key], capture=forbidden))
    raw = envelope()
    raw["data"]["payload"]["source"]["data"].update(created_at=RECORDED, verified=True)
    assert parse_event(raw, "111").group_data == {}


async def test_snapshots_survive_reopen_without_backfilling_disabled_events(tmp_path, monkeypatch):
    monkeypatch.setattr("xflog.events.utc_now", lambda: RECORDED)
    raw = envelope(identity="captured")
    raw["data"]["payload"]["source"]["data"].update(
        created_at="2023-10-26T12:00:00Z", verified=True, verified_type="business"
    )
    event = parse_event(raw, "111", ENABLED)
    path = tmp_path / "history.sqlite3"
    store = Store(path)
    await store.open()
    try:
        await store.insert(event)
        await store.insert(replace(event, event_id="before-enabling", group_data={}))
        await store.save_setting("audience_groups", ENABLED)
    finally:
        await store.close()
    await store.open()
    try:
        enabled = await store.setting("audience_groups")
        rows = (await store.history("111", {}))["events"]
        assert rows[1]["group_data"] == event.group_data
        assert groups.decorate(rows[1], enabled)["audience_groups"] == {
            "activity": "follow.follow",
            "account-age": "3-plus-years",
            "verification": "business",
        }
        assert groups.decorate(rows[0], enabled)["audience_groups"] == {
            "activity": "follow.follow",
            "account-age": "unknown",
            "verification": "unknown",
        }
        assert groups.decorate(rows[1])["audience_groups"] == {"activity": "follow.follow"}
        assert rows[1]["group_data"] == event.group_data
    finally:
        await store.close()


def test_demo_uses_same_modules_and_contains_each_bucket():
    events = [groups.decorate(event, ENABLED) for event in demo_history({})["events"]]
    for key in ENABLED:
        assert {event["audience_groups"][key] for event in events} == {
            bucket.key for bucket in groups.MODULES[key].buckets
        }
