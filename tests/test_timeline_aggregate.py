import asyncio
import random
from collections import Counter
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from test_interactions import envelope, post
from test_interactions import instance as shared_instance

from xflog import audience_groups
from xflog.history import demo as demo_module
from xflog.history import timeline as timeline_module
from xflog.history.profiles import remember_profile
from xflog.history.timeline import Timeline
from xflog.history.timeline_cursor import InvalidTimelineRequest, decode_cursor
from xflog.tracking.events import Event

instance = shared_instance
ENABLED = dict.fromkeys(audience_groups.MODULES, True)
STAMP = "2026-11-05T12:00:00+00:00"


def record(
    identity, kind="follow.follow", actor="222", received=STAMP, *, account="111", groups=None
):
    return Event(identity, kind, account, actor, None, None, None, received, groups or {})


async def page(browser, **params):
    response = await browser.get("/api/timeline", params={"local_only": True, **params})
    assert response.status_code == 200, response.text
    return response.json()


async def mixed_history(app):
    store = app.state.store
    selection = {"interactions": {"replies": True}}
    await store.save_setting("selection", selection)
    await store.save_setting("audience_groups", ENABLED)
    for index, (kind, actor, stamp, fields) in enumerate(
        [
            ("follow.unfollow", "222", "2026-11-04T11:00:00+00:00", {}),
            ("follow.follow", "222", STAMP, {"location": "NYC", "verified": True}),
            ("follow.follow", "444", STAMP, {"location": "new york city", "verified": False}),
            (
                "follow.follow",
                "555",
                STAMP,
                {"location": "London", "created_at": "2025-01-01T00:00:00Z"},
            ),
            (
                "follow.unfollow",
                "555",
                STAMP,
                {"location": "LONDON", "public_metrics": {"followers_count": 123}},
            ),
            ("subscriptions.subscribe", "222", STAMP, {"location": "remote"}),
            ("subscriptions.unsubscribe", "444", STAMP, {"location": "N/A"}),
        ]
    ):
        await store.insert(
            record(
                f"mixed-{index}",
                kind,
                actor,
                stamp,
                groups=audience_groups.capture(fields, ENABLED),
            )
        )
    for index, actor in enumerate(("222", "333", "333")):
        await app.state.interactions.ingest(
            envelope(event_uuid=f"reply-{index}", payload=post(str(990 + index), actor)), selection
        )
    await store.db.execute("UPDATE interactions SET received_at=?", (STAMP,))
    await store.db.execute(
        "UPDATE interactions SET kind='mentions' WHERE sequence=(SELECT MIN(sequence) FROM interactions)"
    )
    await store.db.commit()
    await store.insert(record("foreign", account="333"))


def group_oracle(events, lens):
    module = audience_groups.MODULES.get(lens)
    if not module:
        return {}
    fixed = {bucket.key: (bucket.label, bucket.tone) for bucket in module.buckets}
    buckets = {}
    for event in events:
        key = event["audience_groups"][lens]
        descriptor = event["audience_group_buckets"].get(lens)
        label, tone = (descriptor["label"], descriptor["tone"]) if descriptor else fixed[key]
        count, actors, first_label, first_tone = buckets.get(key, (0, set(), label, tone))
        actors.add(event["actor_id"])
        buckets[key] = (count + 1, actors, first_label, first_tone)
    return {
        key: (count, len(actors), label, tone)
        for key, (count, actors, label, tone) in buckets.items()
    }


@pytest.mark.parametrize(
    "subject,kind,since",
    [
        ("followers", "all", ""),
        ("followers", "gained", ""),
        ("followers", "lost", "2026-11-05T00:00:00Z"),
        ("followers", "all", "2026-11-06T00:00:00Z"),
        ("subscriptions", "all", ""),
        ("subscriptions", "lost", ""),
    ],
)
async def test_aggregate_matches_exhaustive_timeline_for_every_lens(instance, subject, kind, since):
    app, browser, provider = instance
    await mixed_history(app)
    calls = len(provider.calls)
    for lens in (*audience_groups.MODULES, "none"):
        scope = {"subject": subject, "kind": kind, "since": since, "lens": lens, "limit": 2}
        first = await page(browser, **scope)
        rows, before = first["events"], first["next"]
        while before:
            continuation = await page(browser, **scope, before=before)
            assert "aggregate" not in continuation
            rows += continuation["events"]
            before = continuation["next"]
        assert len({event["event_id"] for event in rows}) == len(rows)
        assert not any(event["kind"] == "interaction.mentions" for event in rows)
        aggregate = first["aggregate"]
        assert aggregate["total_events"] == len(rows)
        assert aggregate["oldest_received_at"] == min(
            (event["received_at"] for event in rows), default=None
        )
        assert aggregate["distinct_actors"] == len({event["actor_id"] for event in rows})
        assert aggregate["kinds"] == Counter(event["kind"] for event in rows)
        assert {
            group["key"]: (
                group["event_count"],
                group["distinct_actors"],
                group["label"],
                group["tone"],
            )
            for group in aggregate["groups"]
        } == group_oracle(rows, lens)
        assert aggregate["revision"] == await Timeline(app.state.store).revision("111")
    assert len(provider.calls) == calls


async def test_snapshot_survives_backdated_and_tied_inserts_and_delta_fetches_them(instance):
    app, browser, _ = instance
    await mixed_history(app)
    old = await page(browser, limit=1, lens="previous-encounters")
    before = old["next"]
    await app.state.store.insert(record("tie-new"))
    await app.state.store.insert(record("backdated-new", received="2026-11-01T10:00:00+00:00"))
    await app.state.interactions.ingest(
        envelope(event_uuid="inserted-new"), {"interactions": {"replies": True}}
    )
    await app.state.store.db.execute(
        "UPDATE interactions SET received_at=? WHERE event_id='inserted-new'", (STAMP,)
    )
    await app.state.store.db.commit()

    old_events = list(old["events"])
    while before:
        older = await page(browser, limit=2, lens="previous-encounters", before=before)
        old_events += older["events"]
        before = older["next"]
    assert len(old_events) == old["aggregate"]["total_events"]
    assert len({event["event_id"] for event in old_events}) == len(old_events)
    assert (
        next(event for event in old_events if event["received_at"].startswith("2026-11-04"))[
            "audience_groups"
        ]["previous-encounters"]
        == "first-appearance"
    )

    query = {
        "after_revision": old["aggregate"]["revision"],
        "lens": "previous-encounters",
        "limit": 2,
    }
    delta = await page(browser, **query, selected=old_events[-1]["event_id"])
    last = await page(browser, **query, before=delta["next"])
    merged = delta["events"] + last["events"]
    assert last["next"] is None
    assert {event["event_id"] for event in merged}.isdisjoint(
        event["event_id"] for event in old_events
    )
    assert [event["kind"] for event in merged] == [
        "follow.follow",
        "interaction.replies",
        "follow.follow",
    ]
    assert delta["aggregate"]["scope"] == old["aggregate"]["scope"]
    assert delta["aggregate"]["total_events"] == len(old_events) + 3
    assert delta["selected_event"]["event_id"] == old_events[-1]["event_id"]
    assert delta["selected_event"]["audience_groups"]["previous-encounters"] == "seen-before"


async def test_previous_follow_uses_receipt_order_before_sequence(instance):
    app, browser, _ = instance
    await app.state.store.save_setting("audience_groups", ENABLED)
    for identity, kind, receipt in (
        ("leave", "follow.unfollow", "2026-11-04T10:01:00+00:00"),
        ("return", "follow.follow", "2026-11-04T10:02:00+00:00"),
        ("late-old-follow", "follow.follow", "2026-11-04T10:00:00+00:00"),
    ):
        await app.state.store.insert(record(identity, kind=kind, actor="333", received=receipt))
    result = await page(browser, kind="gained", lens="previous-encounters", limit=50)
    returned = next(
        event for event in result["events"] if event["received_at"] == "2026-11-04T10:02:00+00:00"
    )
    assert returned["audience_groups"]["previous-encounters"] == "followed-again"
    groups = {item["key"]: item for item in result["aggregate"]["groups"]}
    assert groups["followed-again"]["event_count"] == 1
    assert groups["followed-again"]["distinct_actors"] == 1


async def test_mixed_source_keyset_and_encounter_window_match_chronological_reference(instance):
    app, browser, _ = instance
    store = app.state.store
    await store.db.execute("DELETE FROM events")
    await store.db.commit()
    await store.save_setting("selection", {"interactions": {"replies": True}})
    await store.save_setting("audience_groups", ENABLED)
    rng = random.Random(25)
    times = (
        "2026-11-05T11:59:59+00:00",
        STAMP,
        "2026-11-05T12:00:00.100000+00:00",
        "2026-11-05T12:00:00.200000+00:00",
        "2026-11-05T12:00:01+00:00",
    )
    kinds = ("follow.follow", "follow.unfollow", "subscriptions.subscribe", "replies", "mentions")
    raw = []
    for index in range(65):
        kind, stamp, actor = rng.choice(kinds), rng.choice(times), str(rng.randrange(222, 229))
        source = int("." in kind)
        if source:
            cursor = await store.db.execute(
                """INSERT INTO events(event_id,kind,account_id,actor_id,received_at)
                   VALUES (?,?,'111',?,?)""",
                (f"reference-{index}", kind, actor, stamp),
            )
        else:
            cursor = await store.db.execute(
                """INSERT INTO interactions(account_id,event_id,person_id,kind,post_id,provider_at,received_at)
                   VALUES ('111',?,?,?,'123',?,?)""",
                (f"reference-{index}", actor, kind, stamp, stamp),
            )
        position = cursor.lastrowid
        await cursor.close()
        raw.append((stamp, source, position, actor, kind))
    await store.db.commit()

    seen, follow, expected = set(), {}, []
    for stamp, source, position, actor, kind in sorted(raw):
        bucket = "first-appearance"
        if actor in seen:
            bucket = (
                "followed-again"
                if kind == "follow.follow" and follow.get(actor) == "follow.unfollow"
                else "seen-before"
            )
        seen.add(actor)
        if kind in {"follow.follow", "follow.unfollow"}:
            follow[actor] = kind
        if stamp >= STAMP and kind in {"follow.follow", "follow.unfollow", "replies"}:
            expected.append((f"timeline:{'event' if source else 'interaction'}:{position}", bucket))

    params = {"lens": "previous-encounters", "since": STAMP, "limit": 3}
    result = await page(browser, **params)
    counts = {item["key"]: item["event_count"] for item in result["aggregate"]["groups"]}
    actual = []
    while True:
        actual += [
            (event["event_id"], event["audience_groups"]["previous-encounters"])
            for event in result["events"]
        ]
        if not result["next"]:
            break
        result = await page(browser, **params, before=result["next"])
    assert actual == list(reversed(expected))
    assert counts == Counter(bucket for _, bucket in expected)


async def test_continuation_cannot_trigger_opt_in_profile_lookup(instance, monkeypatch):
    app, browser, _ = instance
    await app.state.store.save_setting("selection", {"profile_names": True})
    await app.state.store.insert(
        record("newest-missing", actor="555", received="2030-01-01T00:00:00+00:00")
    )
    await app.state.store.insert(record("older-missing", actor="666"))
    lookup = AsyncMock(return_value=[])
    monkeypatch.setattr(app.state.client, "lookup_users", lookup)
    result = (await browser.get("/api/timeline?limit=1")).json()
    lookup.assert_awaited_once_with(["555"])
    while result["next"]:
        response = await browser.get("/api/timeline", params={"limit": 1, "before": result["next"]})
        assert response.status_code == 200, response.text
        result = response.json()
    assert lookup.await_count == 1


async def test_cursor_is_rejected_outside_query_scope(instance):
    app, browser, _ = instance
    await mixed_history(app)
    before = (await page(browser, limit=1, lens="activity"))["next"]
    for changes in (
        {"kind": "gained"},
        {"subject": "subscriptions"},
        {"lens": "verification"},
        {"since": "2026-11-04T00:00:00Z"},
        {"after_revision": "0:0"},
    ):
        params = {"lens": "activity", "before": before, **changes}
        assert (await browser.get("/api/timeline", params=params)).status_code == 422
    with pytest.raises(InvalidTimelineRequest):
        await Timeline(app.state.store).history("333", {"before": before, "lens": "activity"})
    await app.state.store.save_setting("selection", {"interactions": {"replies": False}})
    assert (
        await browser.get("/api/timeline", params={"before": before, "lens": "activity"})
    ).status_code == 422
    await app.state.store.save_setting("selection", {"interactions": {"replies": True}})
    await app.state.store.save_setting("account", {"id": "333"})
    assert (
        await browser.get("/api/timeline", params={"before": before, "lens": "activity"})
    ).status_code == 422


async def test_local_profile_update_revises_aggregate_and_refreshes_selected_without_draining(
    instance,
):
    app, browser, provider = instance
    await mixed_history(app)
    first = await page(browser, limit=1)
    selected = first["events"][0]["event_id"]
    actor = first["events"][0]["actor_id"]
    async with app.state.store.lock:
        await remember_profile(
            app.state.store.db, "111", {"id": actor, "name": "Updated", "handle": "updated"}
        )
        await app.state.store.db.commit()
    calls = len(provider.calls)
    newer = await page(
        browser, limit=1, after_revision=first["aggregate"]["revision"], selected=selected
    )
    assert newer["events"] == []
    assert newer["selected_event"]["name"] == "Updated"
    assert newer["selected_event"]["handle"] == "updated"
    assert newer["aggregate"]["revision"] != first["aggregate"]["revision"]
    assert newer["aggregate"]["profile_revision"] != first["aggregate"]["profile_revision"]
    assert newer["aggregate"]["total_events"] == first["aggregate"]["total_events"]
    assert len(provider.calls) == calls


async def test_page_and_aggregate_share_sqlite_snapshot_while_writer_commits(instance, monkeypatch):
    app, browser, _ = instance
    await mixed_history(app)
    started, resume = asyncio.Event(), asyncio.Event()
    aggregate_records = timeline_module.aggregate_records

    async def delayed(*args):
        started.set()
        await resume.wait()
        return await aggregate_records(*args)

    monkeypatch.setattr(timeline_module, "aggregate_records", delayed)
    task = asyncio.create_task(page(browser, limit=1))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert await asyncio.wait_for(
            app.state.store.insert(record("concurrent-commit")), timeout=2
        )
    finally:
        resume.set()
        result = await asyncio.wait_for(task, timeout=2)
    current = await page(browser, limit=1)
    assert result["aggregate"]["total_events"] == current["aggregate"]["total_events"] - 1
    assert (
        decode_cursor(result["next"]).watermarks[0] < decode_cursor(current["next"]).watermarks[0]
    )


async def test_demo_cursor_keeps_same_synthetic_snapshot_and_aggregate(instance, monkeypatch):
    _, browser, provider = instance
    params = {"limit": 10, "lens": "activity"}
    first = (await browser.get("/api/demo", params=params)).json()
    original = datetime.fromisoformat(first["aggregate"]["revision"])

    class Later(datetime):
        @classmethod
        def now(cls, tz):
            return (original + timedelta(hours=2)).astimezone(tz)

    monkeypatch.setattr(demo_module, "datetime", Later)
    assert first["synthetic"] and len(first["events"]) == 10
    assert first["aggregate"]["total_events"] > len(first["events"])
    rows, before = first["events"], first["next"]
    while before:
        response = await browser.get("/api/demo", params={**params, "before": before})
        assert response.status_code == 200, response.text
        result = response.json()
        rows += result["events"]
        before = result["next"]
    assert (
        len(rows)
        == len({event["event_id"] for event in rows})
        == first["aggregate"]["total_events"]
    )
    assert rows[-1]["received_at"] == first["aggregate"]["oldest_received_at"]
    assert (
        await browser.get("/api/demo", params={**params, "kind": "lost", "before": first["next"]})
    ).status_code == 422
    assert (await browser.get("/api/timeline", params={"before": first["next"]})).status_code == 422
    assert not provider.calls
