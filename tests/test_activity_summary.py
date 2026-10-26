from datetime import datetime, timedelta, timezone

import httpx
import pytest

from xflog.activity_summary import PERIODS, activity_window, compare, readings
from xflog.app import create_app
from xflog.config import Config
from xflog.demo import demo_activity, demo_events
from xflog.events import Event
from xflog.storage import Store

END = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("period,seconds", PERIODS.items())
def test_windows_are_adjacent_equal_utc_periods(period, seconds):
    window = activity_window(period, END.replace(microsecond=500000))
    assert (window.end, window.start, window.previous_start) == (
        END,
        END - timedelta(seconds=seconds),
        END - timedelta(seconds=seconds * 2),
    )


def test_window_normalizes_offsets_and_rejects_naive_time():
    offset = END.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert activity_window("24h", offset).end == END
    with pytest.raises(ValueError, match="timezone"):
        activity_window("24h", END.replace(tzinfo=None))
    with pytest.raises(ValueError, match="period"):
        activity_window("forever")


@pytest.mark.parametrize(
    "current,previous,comparison,percent",
    [
        (0, 0, "percent", 0),
        (3, 0, "new", None),
        (0, 4, "percent", -100),
        (6, 4, "percent", 50),
        (1, 4, "percent", -75),
        (None, 1, "unavailable", None),
        (1, None, "unavailable", None),
    ],
)
def test_zero_and_unavailable_comparisons(current, previous, comparison, percent):
    assert compare(current, previous) == {
        "value": current,
        "previous": previous,
        "comparison": comparison,
        "change_percent": percent,
    }


def test_rate_is_per_hour_and_ratio_is_gains_divided_by_losses():
    counts = {
        "current": {"follow.follow": 12, "follow.unfollow": 3},
        "previous": {"follow.follow": 6, "follow.unfollow": 6},
    }
    metrics = readings(counts, activity_window("6h", END), "followers")["metrics"]
    assert {key: (value["value"], value["change_percent"]) for key, value in metrics.items()} == {
        "gained": (12, 100),
        "lost": (3, -50),
        "gain_rate": (2, 100),
        "loss_rate": (0.5, -50),
        "ratio": (4, 300),
    }


def test_no_losses_means_no_ratio_not_infinity():
    result = readings({}, activity_window("1h", END), "followers")
    assert result["metrics"]["ratio"] == compare(None, None)


async def test_receipt_edges_subject_and_account_scope(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    await store.open()
    try:
        timestamps = [
            "2026-10-26T09:59:59.999999+00:00",  # outside both windows
            "2026-10-26T10:00:00+00:00",  # previous inclusive
            "2026-10-26T10:59:59.999999+00:00",
            "2026-10-26T11:00:00+00:00",  # current inclusive
            "2026-10-26T11:59:59.999999+00:00",
            "2026-10-26T12:00:00+00:00",  # current exclusive
        ]
        for index, stamp in enumerate(timestamps):
            for account in ("one", "two"):
                for kind in ("follow.follow", "follow.unfollow", "subscriptions.subscribe"):
                    await store.insert(
                        Event(
                            f"{index}-{kind}",
                            kind,
                            account,
                            "actor",
                            None,
                            None,
                            "2000-01-01T00:00:00Z",
                            stamp,
                        )
                    )
        window = activity_window("1h", END)
        assert await store.activity_counts("one", window, "followers") == {
            "current": {"follow.follow": 2, "follow.unfollow": 2},
            "previous": {"follow.follow": 2, "follow.unfollow": 2},
        }
        assert await store.activity_counts("two", window, "subscriptions") == {
            "current": {"subscriptions.subscribe": 2},
            "previous": {"subscriptions.subscribe": 2},
        }
    finally:
        await store.close()


def forbid_x(request):
    raise AssertionError("Activity readings must never call X")


async def test_api_uses_full_log_and_demo_is_separate(tmp_path, monkeypatch):
    monkeypatch.setattr("xflog.app.activity_window", lambda period: activity_window(period, END))
    config = Config(tmp_path / "history.sqlite3", user_id="111", app_bearer="fake")
    app = create_app(config, transport=httpx.MockTransport(forbid_x), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=config.origin) as client,
    ):
        await client.get("/")
        store = app.state.store
        for index in range(61):
            await store.insert(
                Event(
                    str(index),
                    "follow.follow",
                    "111",
                    str(index),
                    None,
                    None,
                    None,
                    "2026-10-26T11:30:00+00:00",
                )
            )
        assert len((await client.get("/api/events")).json()["events"]) == 25
        response = await client.get("/api/activity-summary?period=1h")
        assert response.status_code == 200
        assert response.json()["metrics"]["gained"]["value"] == 61
        paid = (await client.get("/api/activity-summary?subject=subscriptions")).json()
        assert paid["metrics"]["gained"]["value"] == 0
        demo = (await client.get("/api/activity-summary?period=1h&demo=true")).json()
        assert demo == demo_activity("1h", "followers")
        assert (await store.summary("111"))["follow.follow"] == 61
        assert len(await store.subscriptions()) == 0


async def test_empty_instance_and_invalid_parameters(tmp_path):
    config = Config(tmp_path / "history.sqlite3")
    app = create_app(config, transport=httpx.MockTransport(forbid_x), mount_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=config.origin) as client,
    ):
        await client.get("/")
        result = (await client.get("/api/activity-summary")).json()
        assert result["periods"] == list(PERIODS)
        assert result["metrics"]["gained"]["value"] == 0
        for query in ("period=all", "subject=other", "period=1H", "demo=wrong"):
            assert (await client.get(f"/api/activity-summary?{query}")).status_code == 422


@pytest.mark.parametrize(
    "subject,prefix", [("followers", "follow."), ("subscriptions", "subscriptions.")]
)
def test_long_demo_window_contains_every_record_once(subject, prefix):
    metrics = demo_activity("90d", subject)["metrics"]
    events = [event for event in demo_events() if event["kind"].startswith(prefix)]
    assert metrics["gained"]["value"] + metrics["lost"]["value"] == len(events)
    assert metrics["gained"]["previous"] + metrics["lost"]["previous"] == 0
