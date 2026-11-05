import json

import pytest
from test_interactions import envelope, post
from test_interactions import instance as shared_instance

from xflog.history.store import Store
from xflog.history.timeline import Timeline
from xflog.tracking.events import Event

instance = shared_instance


async def only_interactions(app, browser):
    await app.state.store.db.execute("DELETE FROM events")
    await app.state.store.db.execute("DELETE FROM known_profiles")
    await app.state.store.db.commit()
    response = await browser.post("/api/preferences", json={"interactions": {"replies": True}})
    assert response.status_code == 200
    return await app.state.store.setting("selection")


async def test_interaction_only_person_appears_and_details_use_local_db(instance):
    app, browser, provider = instance
    selection = await only_interactions(app, browser)
    raw = envelope(includes={"users": [{"id": "222", "name": "Maya", "username": "maya"}]})
    assert await app.state.interactions.ingest(raw, selection)
    before = len(provider.calls)
    result = (await browser.get("/api/timeline")).json()
    event = result["events"][0]
    assert (event["actor_id"], event["name"], event["handle"], event["kind"]) == (
        "222",
        "Maya",
        "maya",
        "interaction.replies",
    )
    detail = await browser.get("/api/interactions", params={"event_id": event["event_id"]})
    assert detail.status_code == 200
    assert len(detail.json()["interactions"]) == 1
    assert len(provider.calls) == before
    assert (await browser.get("/api/events")).json()["events"] == []
    summary = (await browser.get("/api/activity-summary")).json()
    assert summary["metrics"]["gained"]["value"] == 0
    assert not (await browser.get("/api/timeline?kind=lost")).json()["events"]
    assert not (await browser.get("/api/timeline?subject=subscriptions")).json()["events"]


async def test_disabled_interactions_are_hidden_but_retained(instance):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    assert len((await browser.get("/api/timeline")).json()["events"]) == 1
    await browser.post("/api/preferences", json={"interactions": {"replies": False}})
    assert not (await browser.get("/api/timeline")).json()["events"]
    assert await app.state.store.db.execute_fetchall("SELECT * FROM interactions")


async def test_timeline_cursor_is_stable_across_new_records_and_source_ties(instance):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    for index in range(36):
        raw = envelope(event_uuid=f"reply-{index}", payload=post(str(900 + index)))
        await app.state.interactions.ingest(raw, selection)
    await app.state.store.insert(
        Event(
            "follow",
            "follow.follow",
            "111",
            "333",
            None,
            "Other",
            None,
            "2000-01-01T00:00:00+00:00",
        )
    )
    first = (await browser.get("/api/timeline")).json()
    assert len(first["events"]) == 25
    await app.state.interactions.ingest(envelope(event_uuid="arrived-later"), selection)
    second = (await browser.get("/api/timeline", params={"before": first["next"]})).json()
    combined = first["events"] + second["events"]
    assert len(combined) == 37
    assert len({event["event_id"] for event in combined}) == 37
    assert combined[-1]["kind"] == "follow.follow"
    assert second["next"] is None


async def test_profile_capture_respects_group_opt_in_and_unknown_history(instance):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.store.save_setting("audience_groups", {"account-size": True})
    await app.state.interactions.ingest(envelope(), selection)
    old = (await browser.get("/api/timeline")).json()["events"][0]
    assert old["name"] == "Account 222"
    assert old["audience_groups"]["account-size"] == "unknown"
    await app.state.interactions.ingest(
        envelope(
            event_uuid="new-profile",
            includes={
                "users": [
                    {
                        "id": "222",
                        "name": "Maya",
                        "username": "maya",
                        "public_metrics": {"followers_count": 500},
                    }
                ]
            },
        ),
        selection,
    )
    latest = (await browser.get("/api/timeline")).json()["events"][0]
    assert latest["audience_groups"]["account-size"] != "unknown"


async def test_interaction_selection_cannot_cross_account_scope(instance):
    app, browser, provider = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    event = (await browser.get("/api/timeline")).json()["events"][0]
    await app.state.store.db.execute("UPDATE interactions SET account_id='999'")
    await app.state.store.db.commit()
    before = len(provider.calls)
    assert not (await browser.get("/api/timeline")).json()["events"]
    assert (
        await browser.get("/api/interactions", params={"event_id": event["event_id"]})
    ).status_code == 409
    assert len(provider.calls) == before


async def test_revision_survives_restart_and_is_independent_of_notifications(instance):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    before = (await browser.get("/api/status")).json()["timeline_revision"]
    await app.state.interactions.ingest(envelope(), selection)
    after = (await browser.get("/api/status")).json()
    assert not after["selection"]["notifications"]
    assert after["timeline_revision"] != before
    assert await Timeline(app.state.store).revision("111") == after["timeline_revision"]


async def test_equal_receipt_times_page_across_sources_and_keep_encounter_context(instance):
    app, browser, _ = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(), selection)
    stamp = "2026-11-04T10:00:00+00:00"
    await app.state.store.db.execute("UPDATE interactions SET received_at=?", (stamp,))
    await app.state.store.db.commit()
    await app.state.store.insert(
        Event("tie", "follow.follow", "111", "222", None, None, None, stamp)
    )
    timeline = Timeline(app.state.store)
    first = await timeline.history("111", {"limit": 1})
    second = await timeline.history("111", {"limit": 1, "before": first["next"]})
    assert first["events"][0]["kind"] == "follow.follow"
    assert second["events"][0]["kind"] == "interaction.replies"
    assert second["next"] is None
    contexts = await timeline.encounter_context(first["events"] + second["events"])
    assert contexts[first["events"][0]["sequence"]]["seen_before"] is True
    assert contexts[second["events"][0]["sequence"]]["seen_before"] is False


@pytest.mark.parametrize(
    "identity",
    [
        "timeline:interaction:0",
        "timeline:bad:1",
        "timeline:interaction:" + "9" * 60,
        "timeline:interaction:١",
    ],
)
async def test_timeline_person_ids_are_bounded_before_db_or_x(instance, identity):
    _, browser, provider = instance
    before = len(provider.calls)
    assert (
        await browser.get("/api/interactions", params={"event_id": identity})
    ).status_code == 409
    assert len(provider.calls) == before


@pytest.mark.parametrize("cursor", ["bad", "[1]", "x" * 257, "eyJ4IjoxfQ"])
async def test_bad_cursor_is_rejected_without_provider_calls(instance, cursor):
    _, browser, provider = instance
    before = len(provider.calls)
    assert (await browser.get("/api/timeline", params={"before": cursor})).status_code == 422
    assert len(provider.calls) == before


async def test_old_interaction_schema_is_upgraded_without_rewriting_rows(tmp_path):
    store = Store(tmp_path / "old.sqlite3")
    await store.open()
    await store.db.execute("ALTER TABLE interactions DROP COLUMN profile_data")
    await store.db.execute("""INSERT INTO interactions
        (account_id,event_id,person_id,kind,post_id,provider_at,received_at)
        VALUES ('111','kept','222','replies','900','2026-11-04T00:00:00+00:00','2026-11-04T00:00:00+00:00')""")
    await store.db.commit()
    await store.close()
    await store.open()
    try:
        rows = await store.db.execute_fetchall("SELECT event_id,profile_data FROM interactions")
        assert [(row[0], json.loads(row[1])) for row in rows] == [("kept", {})]
    finally:
        await store.close()
