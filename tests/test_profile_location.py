from dataclasses import replace

import pytest
from test_history import envelope

from xflog import audience_groups as groups
from xflog.audience_groups import profile_location as locations
from xflog.demo import demo_history
from xflog.events import EVENT_TYPES, parse_event
from xflog.storage import Store

ENABLED = {locations.KEY: True}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("  New\tYork   City  ", "New York City"),
        ("ＮＹＣ", "New York City"),
        ("New York , NY", "New York City"),
        ("U.S.A.", "United States"),
        ("u.s.", "United States"),
        ("UK", "United Kingdom"),
        ("BANGALORE", "Bengaluru"),
        ("Bangalore | India", "Bengaluru, India"),
        ("Bengaluru;India", "Bengaluru, India"),
        ("London /Paris", "London / Paris"),
        ("São Paulo", "São Paulo"),
        ("Sa\u0303o Paulo", "São Paulo"),
        ("東京", "東京"),
        ("🌍 Remote", "🌍 Remote"),
        ("Null Island", "Null Island"),
        ("Unknown, Texas", "Unknown, Texas"),
        ("a" * 160, "a" * 160),
        (None, None),
        (False, None),
        (1, None),
        ({"city": "London"}, None),
        (["London"], None),
        ("", None),
        (" \t\n ", None),
        ("Unknown", None),
        ("N/A", None),
        (" N / A ", None),
        ("N.A.", None),
        ("not specified", None),
        ("None", None),
        ("NULL", None),
        ("---", None),
        ("🌍", None),
        ("12345", None),
        ("London\x00", None),
        ("London\u202e", None),
        ("London\ud800", None),
        ("a" * 161, None),
        ("a," * 79, None),
        ("\ufdfa" * 10, None),
    ],
)
def test_location_cleanup_and_unusable_values(value, expected):
    assert locations.normalize(value) == expected
    if expected:
        assert locations.normalize(expected) == expected


@pytest.mark.parametrize(
    "left,right",
    [
        ("NYC", "New York City"),
        ("New York, NY", "new york city"),
        (" USA ", "United States of America"),
        ("U.K.", "United Kingdom"),
        ("Bangalore, India", "bengaluru,india"),
        ("London", " london "),
        ("St.Louis", "St Louis"),
        ("Paris,France", "PARIS ; FRANCE"),
        ("London/Paris", "london / paris"),
        ("MÜNCHEN", "münchen"),
        ("São Paulo", "Sa\u0303o Paulo"),
    ],
)
def test_equivalent_labels_have_stable_group_keys(left, right):
    def bucket(value):
        return locations.assign(
            {"group_data": {locations.KEY: locations.capture({"location": value})}}
        )

    assert bucket(left).key == bucket(right).key


@pytest.mark.parametrize(
    "left,right",
    [
        ("New York", "New York City"),
        ("London, UK", "London, Ontario"),
        ("Paris, France", "Paris, Texas"),
        ("London / Paris", "London"),
        ("Bengaluru", "Bengaluru, India"),
        ("Great Britain", "United Kingdom"),
        ("Sao Paulo", "São Paulo"),
        ("Londen", "London"),
    ],
)
def test_ambiguous_regions_accents_and_typos_are_not_guessed(left, right):
    assert (
        locations.assign({"group_data": {locations.KEY: {"location": left}}}).key
        != locations.assign({"group_data": {locations.KEY: {"location": right}}}).key
    )


@pytest.mark.parametrize("kind", EVENT_TYPES)
@pytest.mark.parametrize("wrapped", [True, False])
def test_only_source_metadata_captured_while_enabled(kind, wrapped):
    raw = envelope(kind)
    raw["data"]["payload"]["target"]["data"]["location"] = "NYC"
    assert parse_event(raw, "111", ENABLED).group_data == {}
    raw["data"]["payload"]["source"]["data"]["location"] = "Bangalore"
    if not wrapped:
        raw = raw["data"]
        raw["payload"] = {key: value["data"] for key, value in raw["payload"].items()}
    assert parse_event(raw, "111").group_data == {}
    event = parse_event(raw, "111", ENABLED)
    assert event.group_data == {locations.KEY: {"location": "Bengaluru"}}
    decorated = groups.decorate(event.public(), ENABLED)
    descriptor = decorated["audience_group_buckets"][locations.KEY]
    assert decorated["audience_groups"][locations.KEY] == descriptor["key"]
    assert descriptor["label"] == "Bengaluru" and descriptor["tone"] == "neutral"
    assert groups.decorate(decorated)["audience_group_buckets"] == {}


def test_disabled_module_does_not_run_capture(monkeypatch):
    def forbidden(source):
        raise AssertionError("Disabled module must not process profile locations")

    monkeypatch.setitem(
        groups.MODULES, locations.KEY, replace(groups.MODULES[locations.KEY], capture=forbidden)
    )
    assert parse_event(envelope(), "111").group_data == {}


@pytest.mark.parametrize("snapshot", [None, [], "London", {}, {"location": False}])
def test_missing_invalid_and_legacy_snapshots_are_unknown(snapshot):
    assert locations.assign({"group_data": {locations.KEY: snapshot}}) == locations.UNKNOWN


async def test_saved_location_survives_reopen_and_old_events_stay_unknown(tmp_path):
    raw = envelope()
    raw["data"]["payload"]["source"]["data"]["location"] = "NYC"
    event = parse_event(raw, "111", ENABLED)
    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    try:
        await store.insert(event)
        await store.insert(replace(event, event_id="old", group_data={}))
        await store.save_setting("audience_groups", ENABLED)
    finally:
        await store.close()
    await store.open()
    try:
        enabled = await store.setting("audience_groups")
        rows = (await store.history("111", {}))["events"]
        assert groups.decorate(rows[0], enabled)["audience_groups"][locations.KEY] == "unknown"
        assert (
            groups.decorate(rows[1], enabled)["audience_group_buckets"][locations.KEY]["label"]
            == "New York City"
        )
        assert locations.KEY not in groups.decorate(rows[1])["audience_groups"]
        assert rows[1]["group_data"] == event.group_data
    finally:
        await store.close()


def test_demo_contains_cleaned_locations_and_unknown_without_enabling_by_default():
    module = next(item for item in groups.catalog() if item["key"] == locations.KEY)
    assert module["dynamic_buckets"] and not module["enabled"]
    labels = {
        groups.decorate(event, ENABLED)["audience_group_buckets"][locations.KEY]["label"].casefold()
        for event in demo_history({})["events"]
    }
    assert labels == {
        "new york city",
        "london",
        "bengaluru, india",
        "united states",
        "remote",
        "unknown",
    }
