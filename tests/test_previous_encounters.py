import asyncio
import random
import sqlite3
from dataclasses import replace

import httpx
import pytest
from test_preferences import ActivityProvider

from xflog import audience_groups
from xflog.app import create_app
from xflog.audience_groups.previous_encounters import KEY, assign
from xflog.config import Config
from xflog.demo import demo_history
from xflog.demo import encounter_context as demo_context
from xflog.events import EVENT_TYPES, FOLLOW_TYPES, Event
from xflog.storage import Store

ENABLED = {KEY: True}


@pytest.mark.parametrize(
    "context,kind,expected",
    [
        ({"seen_before": False}, "follow.follow", "first-appearance"),
        ({"seen_before": False}, "follow.unfollow", "first-appearance"),
        (
            {"seen_before": True, "previous_follow_kind": "follow.unfollow"},
            "follow.follow",
            "followed-again",
        ),
        (
            {"seen_before": True, "previous_follow_kind": "follow.follow"},
            "follow.follow",
            "seen-before",
        ),
        (
            {"seen_before": True, "previous_follow_kind": "follow.unfollow"},
            "subscriptions.subscribe",
            "seen-before",
        ),
        ({"seen_before": True}, "follow.unfollow", "seen-before"),
        ({}, "follow.follow", "unknown"),
        ({"seen_before": "false"}, "follow.follow", "unknown"),
        (None, "follow.follow", "unknown"),
    ],
)
def test_missing_history_never_invents_a_first_encounter(context, kind, expected):
    assert assign({"kind": kind, "group_data": {KEY: context}}) == expected


def record(identity, kind, account="111"):
    return Event(
        identity,
        kind,
        account,
        "222",
        "person",
        "Person",
        "2020-01-01T00:00:00Z",
        "2026-10-26T10:00:00Z",
    )


async def test_full_log_context_survives_filters_pages_reopen_and_retrospective_enable(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = Store(path)
    await store.open()
    kinds = [
        "subscriptions.subscribe",
        "follow.unfollow",
        "subscriptions.unsubscribe",
        "follow.follow",
        "follow.follow",
        "follow.unfollow",
        "follow.follow",
    ]
    for index, kind in enumerate(kinds):
        assert await store.insert(record(str(index), kind))
    assert not await store.insert(record("3", "follow.follow"))
    await store.close()
    with sqlite3.connect(path) as database:
        database.execute("DROP INDEX event_actor_sequence")
    await store.open()
    try:
        page = await store.history("111", {"kind": "gained", "limit": 2})
        before = [dict(event) for event in page["events"]]
        decorated = await audience_groups.decorate_history(
            page["events"], ENABLED, store.encounter_context
        )
        assert [event["audience_groups"][KEY] for event in decorated] == [
            "followed-again",
            "seen-before",
        ]
        assert page["events"] == before and all(KEY not in event["group_data"] for event in before)
        older = await store.history("111", {"kind": "gained", "before": page["next"]})
        older = await audience_groups.decorate_history(
            older["events"], ENABLED, store.encounter_context
        )
        assert older[0]["audience_groups"][KEY] == "followed-again"
        lost = await store.history("111", {"kind": "lost"})
        lost = await audience_groups.decorate_history(
            lost["events"], ENABLED, store.encounter_context
        )
        assert all(event["audience_groups"][KEY] == "seen-before" for event in lost)
        paid = await store.history("111", {"subject": "subscriptions"})
        paid = await audience_groups.decorate_history(
            paid["events"], ENABLED, store.encounter_context
        )
        assert [event["audience_groups"][KEY] for event in paid] == [
            "seen-before",
            "first-appearance",
        ]
        assert all(
            KEY not in event["group_data"] for event in (await store.history("111", {}))["events"]
        )
    finally:
        await store.close()


async def test_seeded_full_history_oracle_across_accounts_actors_and_filters(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    rng, seen, last_follow, expected = random.Random(9173), set(), {}, {}
    try:
        for sequence in range(1, 121):
            account, actor, kind = (
                rng.choice(["111", "333"]),
                rng.choice(["2", "22", "222", "2222"]),
                rng.choice(EVENT_TYPES),
            )
            entry = replace(
                record(str(sequence), kind, account),
                actor_id=actor,
                provider_at=f"2020-01-{31 - sequence % 30:02d}T00:00:00Z",
            )
            key = (account, actor)
            if key not in seen:
                expected[sequence] = "first-appearance"
            elif kind == "follow.follow" and last_follow.get(key) == "follow.unfollow":
                expected[sequence] = "followed-again"
            else:
                expected[sequence] = "seen-before"
            seen.add(key)
            if kind in FOLLOW_TYPES:
                last_follow[key] = kind
            await store.insert(entry)
        checked = set()
        for account in ["111", "333"]:
            for subject in ["followers", "subscriptions"]:
                for kind in ["all", "gained", "lost"]:
                    cursor = 0
                    while True:
                        page = await store.history(
                            account,
                            {"subject": subject, "kind": kind, "limit": 7, "before": cursor},
                        )
                        rows = await audience_groups.decorate_history(
                            page["events"], ENABLED, store.encounter_context
                        )
                        for event in rows:
                            checked.add(event["sequence"])
                            assert event["account_id"] == account
                            assert event["audience_groups"][KEY] == expected[event["sequence"]]
                        if page["next"] is None:
                            break
                        cursor = page["next"]
        assert len(checked) == 120
        page = (await store.history("111", {}))["events"]
        context = await store.encounter_context(page)
        await store.insert(record("late-provider-time", "follow.unfollow"))
        assert await store.encounter_context(page) == context
        statements = []
        await store.db.set_trace_callback(statements.append)
        await store.encounter_context(page)
        await store.db.set_trace_callback(None)
        selects = [
            statement for statement in statements if statement.startswith("SELECT current.sequence")
        ]
        assert len(selects) == 1, "One batch query serves the whole page."
        plan = await store.db.execute_fetchall("EXPLAIN QUERY PLAN " + selects[0])
        assert any("event_actor_sequence" in row["detail"] for row in plan)
        assert not any("SCAN prior" in row["detail"] for row in plan)
        with pytest.raises(ValueError, match="one account"):
            await store.encounter_context([page[0], {**page[0], "account_id": "333"}])
    finally:
        await store.close()


async def test_disabled_module_and_empty_pages_do_not_request_history():
    async def forbidden(events):
        raise AssertionError("Disabled grouping must not read extra history")

    event = {**record("one", "follow.follow").public(), "sequence": 1}
    result = await audience_groups.decorate_history([event], {}, forbidden)
    assert KEY not in result[0]["audience_groups"]
    assert await audience_groups.decorate_history([], ENABLED, forbidden) == []
    assert not next(item for item in audience_groups.catalog() if item["key"] == KEY)["enabled"]
    assert (
        next(item for item in audience_groups.catalog() if item["key"] == KEY)["data_policy"]
        == "recorded_history"
    )


async def test_missing_or_foreign_record_context_stays_unknown(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    try:
        await store.insert(record("foreign-unfollow", "follow.unfollow", "333"))
        await store.insert(record("local-first", "follow.follow"))
        page = (await store.history("111", {}))["events"]
        result = await audience_groups.decorate_history(page, ENABLED, store.encounter_context)
        assert result[0]["audience_groups"][KEY] == "first-appearance"
        missing = [{**page[0], "sequence": 999}]
        result = await audience_groups.decorate_history(missing, ENABLED, store.encounter_context)
        assert result[0]["audience_groups"][KEY] == "unknown"
    finally:
        await store.close()


async def test_demo_history_uses_unfiltered_demo_log_and_never_foreign_sequences():
    page = demo_history({"kind": "gained"})
    all_rows = demo_history({"limit": 50})
    page_context = await demo_context(page["events"])
    for event in page["events"]:
        context = await demo_context([event])
        assert context[event["sequence"]] == page_context[event["sequence"]]
    assert all(item["seen_before"] for item in page_context.values())
    assert await demo_context([{**all_rows["events"][0], "account_id": "111"}]) == {}
    result = await audience_groups.decorate_history(page["events"], ENABLED, demo_context)
    assert any(event["audience_groups"][KEY] == "followed-again" for event in result)


async def test_enabling_previous_encounters_does_not_touch_listener_or_x(tmp_path, monkeypatch):
    provider = ActivityProvider()
    config = Config(tmp_path / "history.sqlite3", app_bearer="fake", user_id="111")
    app = create_app(config, transport=httpx.MockTransport(provider), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=config.origin,
        ) as browser,
    ):
        await browser.get("/")
        status = (await browser.get("/api/status")).json()
        headers = {"origin": config.origin, "x-xflog-csrf": status["csrf"]}
        collector = app.state.collector
        await collector.start()
        await asyncio.wait_for(provider.body.opened.wait(), timeout=2)
        await provider.body.send("follow.unfollow", "left")
        await provider.body.send("follow.follow", "returned")
        task, requests = collector.task, list(provider.requests)
        response = await browser.post(
            "/api/audience-groups", json={"enabled": ENABLED}, headers=headers
        )
        assert response.status_code == 200
        rows = (await browser.get("/api/events?kind=gained")).json()["events"]
        assert rows[0]["audience_groups"][KEY] == "followed-again"
        assert collector.task is task and not task.done()
        assert provider.requests == requests and provider.streams == 1
        assert await collector.store.setting("tracking")

        async def forbidden_real_history(events):
            raise AssertionError("Demo must not read the stored account's context")

        with monkeypatch.context() as guard:
            guard.setattr(collector.store, "encounter_context", forbidden_real_history)
            demo = await browser.get("/api/demo")
            assert demo.status_code == 200
            assert all(
                event["audience_groups"][KEY] != "unknown" for event in demo.json()["events"]
            )
        await browser.post("/api/audience-groups", json={"enabled": {KEY: False}}, headers=headers)

        async def forbidden(events):
            raise AssertionError("OFF must bypass the history context query")

        monkeypatch.setattr(collector.store, "encounter_context", forbidden)
        rows = (await browser.get("/api/events")).json()["events"]
        assert KEY not in rows[0]["audience_groups"]
        assert provider.requests == requests
