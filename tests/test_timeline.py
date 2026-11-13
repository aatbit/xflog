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


@pytest.mark.parametrize("text", [None, "A saved post", "🌟" * 500])
async def test_timeline_exposes_only_saved_post_preview_without_x_requests(instance, text):
    app, browser, provider = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(payload=post(text=text)), selection)
    calls = len(provider.calls)
    event = (await browser.get("/api/timeline")).json()["events"][0]
    assert event["post_id"] == "900"
    assert event["post_text"] == (text[:281] if text else None)
    assert len(provider.calls) == calls


async def test_like_preview_uses_the_liked_post_and_saved_text_updates(instance):
    app, browser, provider = instance
    selection = await only_interactions(app, browser)
    selection["interactions"]["likes_received"] = True
    await app.state.store.save_setting("selection", selection)
    raw = envelope(
        kind="like.create",
        payload={"liking_user_id": "222", "liked_tweet_author_id": "111", "liked_tweet_id": "901"},
        includes={"posts": [post("901", "111", text="The liked post")]},
    )
    await app.state.interactions.ingest(raw, selection)
    calls = len(provider.calls)
    event = (await browser.get("/api/timeline")).json()["events"][0]
    assert (event["post_id"], event["post_text"]) == ("901", "The liked post")
    await app.state.store.db.execute("UPDATE interaction_posts SET text='Updated saved copy'")
    await app.state.store.db.commit()
    event = (await browser.get("/api/timeline")).json()["events"][0]
    assert event["post_text"] == "Updated saved copy"
    assert len(provider.calls) == calls


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


async def test_grouped_pages_include_older_audience_changes_without_x_reads(instance):
    app, browser, provider = instance
    selection = await only_interactions(app, browser)
    await app.state.store.save_setting("selection", {**selection, "profile_names": True})
    for index in range(103):
        await app.state.interactions.ingest(
            envelope(event_uuid=f"group-reply-{index}", payload=post(str(900 + index))), selection
        )
    await app.state.store.db.execute(
        "UPDATE interactions SET received_at='2026-11-06T12:00:00+00:00'"
    )
    await app.state.store.db.commit()
    for index, kind in enumerate(("follow.follow", "follow.unfollow")):
        await app.state.store.insert(
            Event(
                f"older-{index}", kind, "111", "222", None, None, None, "2026-11-05T12:00:00+00:00"
            )
        )
    calls = len(provider.calls)
    rows, cursor = [], "0"
    while cursor:
        response = await browser.get(
            "/api/timeline", params={"local_only": True, "limit": 50, "before": cursor}
        )
        assert response.status_code == 200
        page = response.json()
        rows.extend(page["events"])
        cursor = page["next"]
    assert len(rows) == len({row["event_id"] for row in rows}) == 105
    assert {row["audience_groups"]["activity"] for row in rows} == {
        "follow.follow",
        "follow.unfollow",
        "interaction.replies",
    }
    assert len(provider.calls) == calls
    recent = await browser.get(
        "/api/timeline", params={"local_only": True, "limit": 50, "since": "2026-11-06T00:00:00Z"}
    )
    assert {row["kind"] for row in recent.json()["events"]} == {"interaction.replies"}
    empty = (
        await browser.get(
            "/api/timeline", params={"local_only": True, "since": "2026-11-07T00:00:00Z"}
        )
    ).json()
    assert (empty["events"], empty["next"]) == ([], None)
    assert empty["aggregate"]["total_events"] == 0
    assert len(provider.calls) == calls


async def test_activity_drilldown_reads_matching_saved_rows_and_scopes_cursor(instance):
    app, browser, provider = instance
    selection = await only_interactions(app, browser)
    store = app.state.store
    await store.save_setting("selection", {**selection, "profile_names": True})
    for index in range(3):
        await app.state.interactions.ingest(
            envelope(event_uuid=f"saved-{index}", payload=post(str(900 + index))), selection
        )
    await store.db.execute(
        """UPDATE interactions SET received_at=CASE
             WHEN sequence=(SELECT MIN(sequence) FROM interactions)
             THEN '2026-11-01T12:00:00+00:00' ELSE '2026-11-06T12:00:00+00:00' END"""
    )
    await store.db.commit()
    for index in range(51):
        await store.insert(
            Event(
                f"newer-{index}",
                "follow.follow",
                "111",
                "222",
                None,
                None,
                None,
                "2026-11-07T12:00:00+00:00",
            )
        )
    calls = len(provider.calls)
    scope = {"lens": "activity", "since": "2026-11-05T00:00:00Z"}
    overview = (
        await browser.get("/api/timeline", params={**scope, "limit": 50, "local_only": True})
    ).json()
    assert {event["kind"] for event in overview["events"]} == {"follow.follow"}
    query = {**scope, "limit": 1, "activity_kind": "interaction.replies"}
    first = (await browser.get("/api/timeline", params=query)).json()
    second = (await browser.get("/api/timeline", params={**query, "before": first["next"]})).json()
    assert [event["post_id"] for event in first["events"] + second["events"]] == ["902", "901"]
    assert first["aggregate"]["total_events"] == 2 and second["next"] is None
    wrong = {**query, "before": first["next"], "activity_kind": "follow.follow"}
    assert (await browser.get("/api/timeline", params=wrong)).status_code == 422
    assert (await browser.get("/api/timeline", params={**query, "lens": "none"})).status_code == 422
    await store.save_setting("selection", {**selection, "interactions": {}})
    assert not (await browser.get("/api/timeline", params=query)).json()["events"]
    assert len(provider.calls) == calls


@pytest.mark.parametrize(
    "params",
    [
        {"since": "bad"},
        {"since": "2026-11-06"},
        {"since": "0001-01-01T00:00:00+01:00"},
        {"limit": 0},
        {"limit": 51},
    ],
)
async def test_invalid_history_range_or_page_size_is_rejected(instance, params):
    _, browser, provider = instance
    calls = len(provider.calls)
    assert (await browser.get("/api/timeline", params=params)).status_code == 422
    assert len(provider.calls) == calls


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


async def test_saved_thread_invalidates_only_its_accounts_timeline_revision(instance):
    app, browser, provider = instance
    selection = await only_interactions(app, browser)
    await app.state.interactions.ingest(envelope(payload=post(text=None)), selection)
    timeline = Timeline(app.state.store)
    before = await timeline.revision("111")
    other_before = await timeline.revision("333")
    calls = len(provider.calls)
    await app.state.interactions.records.save_thread(
        "111", {"conversation": "800", "posts": [post(text="Now saved")], "next_token": None}
    )
    assert await timeline.revision("111") != before
    assert await timeline.revision("333") == other_before
    assert (await browser.get("/api/timeline")).json()["events"][0]["post_text"] == "Now saved"
    assert len(provider.calls) == calls
