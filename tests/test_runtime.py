import asyncio
import sqlite3
import subprocess
import sys
from dataclasses import replace

import httpx
import pytest

from xflog import CoreConfig, Runtime, RuntimeBusyError, SetupError, ThreadOptions
from xflog.config import Config
from xflog.tracking.events import Event, utc_now


@pytest.fixture(autouse=True)
def isolated_ownership(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_core_environment_ignores_browser_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XFLOG_DATABASE", str(tmp_path / "history.sqlite3"))
    monkeypatch.setenv("XFLOG_ORIGIN", "invalid web origin")
    monkeypatch.setenv("XFLOG_PORT", "invalid web port")
    core = CoreConfig.from_env()
    assert core.database == tmp_path / "history.sqlite3" and not hasattr(core, "origin")
    with pytest.raises(ValueError):
        Config.from_env()


def test_core_settings_keep_credentials_private(tmp_path):
    config = CoreConfig(tmp_path / "history.sqlite3", "fake-app-secret", "111", "fake-user-secret")
    assert "fake-app-secret" not in repr(config) and "fake-user-secret" not in repr(config)


def test_core_validates_account_id_without_browser_configuration(tmp_path):
    with pytest.raises(ValueError, match="numeric"):
        CoreConfig(tmp_path / "history.sqlite3", user_id="@wrong")


def test_domain_runtime_does_not_import_the_web_interface():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from xflog import Runtime, CoreConfig; import sys; "
            "assert not {'gradio', 'fastapi', 'uvicorn', 'pydantic'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


async def test_runtime_services_share_the_same_store_and_provider(tmp_path):
    runtime = Runtime(CoreConfig(tmp_path / "history.sqlite3"))
    async with runtime as entered:
        assert (
            entered is runtime
            and runtime.collector.store is runtime.store
            and runtime.follow_actions.store is runtime.store
            and runtime.interactions.store is runtime.store
            and runtime.interactions.identity is runtime.follow_actions
            and runtime.collector.client is runtime.client
        )


async def test_standalone_runtime_saves_preferences_without_starting_collection(tmp_path):
    calls = []

    async def provider(request):
        calls.append(request)
        raise AssertionError("Paused runtime must not call X.")

    runtime = Runtime(
        CoreConfig(tmp_path / "history.sqlite3"), transport=httpx.MockTransport(provider)
    )
    async with runtime:
        await runtime.collector.save_preferences(
            {"followers": True, "subscriptions": False, "notifications": True}
        )
        saved = await runtime.store.setting("selection")
        assert saved["notifications"] and runtime.collector.task is None and not calls
    assert runtime.http.is_closed


@pytest.mark.parametrize("same_database", [True, False])
async def test_runtime_excludes_duplicate_owner_and_keeps_first_owner(tmp_path, same_database):
    config = CoreConfig(tmp_path / "history.sqlite3", app_bearer="fake-sdk-app", user_id="111")
    second = config if same_database else replace(config, database=tmp_path / "other.sqlite3")
    contender = Runtime(second)
    async with Runtime(config) as owner:
        with pytest.raises(RuntimeBusyError):
            async with contender:
                pytest.fail("Duplicate owner entered.")
        await owner.store.save_setting("still_owned", True)
        with pytest.raises(RuntimeBusyError):
            async with Runtime(second):
                pytest.fail("Failed contender released the original owner's lock.")
    async with Runtime(second) as successor:
        assert successor.store.db is not None and contender.http.is_closed


async def test_database_cannot_be_reopened_with_different_credentials(tmp_path):
    config = CoreConfig(tmp_path / "history.sqlite3", app_bearer="fake-first")
    async with Runtime(config):
        with pytest.raises(RuntimeBusyError):
            async with Runtime(replace(config, app_bearer="fake-second")):
                pytest.fail("Database was concurrently reopened.")


async def test_runtime_ownership_is_enforced_across_processes(tmp_path):
    config = CoreConfig(tmp_path / "history.sqlite3", app_bearer="fake-cross-process")
    code = """
import asyncio, sys
from pathlib import Path
from xflog import CoreConfig, Runtime, RuntimeBusyError
async def check():
    try:
        async with Runtime(CoreConfig(Path(sys.argv[1]), app_bearer='fake-cross-process')):
            return 1
    except RuntimeBusyError:
        return 0
sys.exit(asyncio.run(check()))
"""
    async with Runtime(config):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            str(tmp_path / "separate.sqlite3"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, error = await asyncio.wait_for(process.communicate(), 5)
        assert process.returncode == 0, error.decode()


@pytest.mark.parametrize("stage", ["open", "initialize", "shutdown"])
async def test_partial_failures_close_resources_and_release_ownership(tmp_path, monkeypatch, stage):
    config = CoreConfig(tmp_path / "history.sqlite3")
    runtime = Runtime(config)
    owner = runtime.store if stage == "open" else runtime.collector
    original = getattr(owner, stage)

    async def fail():
        await original()
        raise sqlite3.OperationalError("injected storage failure")

    monkeypatch.setattr(owner, stage, fail)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        async with runtime:
            pass
    async with Runtime(config):
        assert runtime.http.is_closed and runtime.store.db is None


async def test_cancelled_startup_releases_resources_and_ownership(tmp_path, monkeypatch):
    config = CoreConfig(tmp_path / "history.sqlite3")
    runtime = Runtime(config)
    initializing = asyncio.Event()

    async def initialize():
        initializing.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.collector, "initialize", initialize)
    task = asyncio.create_task(runtime.__aenter__())
    await asyncio.wait_for(initializing.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with Runtime(config):
        assert runtime.store.db is None and runtime.http.is_closed


async def test_cancellation_keeps_ownership_until_shutdown_finishes(tmp_path, monkeypatch):
    config = CoreConfig(tmp_path / "history.sqlite3")
    runtime = Runtime(config)
    shutting_down, finish = asyncio.Event(), asyncio.Event()
    original = runtime.collector.shutdown

    async def shutdown():
        shutting_down.set()
        await finish.wait()
        await original()

    monkeypatch.setattr(runtime.collector, "shutdown", shutdown)
    await runtime.__aenter__()
    closing = asyncio.create_task(runtime.__aexit__(None, None, None))
    await asyncio.wait_for(shutting_down.wait(), 1)
    for _ in range(2):
        closing.cancel()
        await asyncio.sleep(0)
    try:
        with pytest.raises(RuntimeBusyError):
            async with Runtime(config):
                pytest.fail("Lock released during shutdown.")
    finally:
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
    async with Runtime(config):
        assert runtime.store.db is None and runtime.http.is_closed


async def test_runtime_cannot_be_nested_or_reused(tmp_path):
    runtime = Runtime(CoreConfig(tmp_path / "history.sqlite3"))
    async with runtime:
        with pytest.raises(RuntimeError, match="single-use"):
            async with runtime:
                pass
        assert runtime.store.db is not None
    with pytest.raises(RuntimeError, match="single-use"):
        async with runtime:
            pass


async def test_headless_history_and_threads_persist_without_implicit_x_reads(tmp_path):
    config = CoreConfig(tmp_path / "history.sqlite3", "fake-app", "111", "fake-user")
    calls = []
    post = {"id": "900", "author_id": "222", "conversation_id": "800", "text": "Hello"}

    async def provider(request):
        calls.append(request.url.path)
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": "111"}})
        assert request.url.path == "/2/tweets/search/all"
        return httpx.Response(200, json={"data": [post], "meta": {"result_count": 1}})

    transport = httpx.MockTransport(provider)
    async with Runtime(config, transport=transport) as runtime:
        event = Event("person", "follow.follow", "111", "222", "maya", "Maya", None, utc_now())
        await runtime.store.insert(event)
        await runtime.collector.save_preferences(
            {
                "followers": True,
                "subscriptions": False,
                "notifications": False,
                "interactions": {"replies": True},
            }
        )
        await runtime.interactions.ingest(
            {
                "data": {
                    "event_uuid": "reply",
                    "event_type": "post.reply.create",
                    "filter": {"user_id": "111"},
                    "payload": post,
                }
            },
            await runtime.store.setting("selection"),
        )
        history = await runtime.interactions.history("person")
        sequence = history["interactions"][0]["sequence"]
        with pytest.raises(SetupError, match="Confirm X read charges"):
            await runtime.interactions.thread("person", ThreadOptions(sequence))
        assert not calls
        first = await runtime.interactions.thread(
            "person", ThreadOptions(sequence, accepted_costs=True)
        )
    async with Runtime(config, transport=httpx.MockTransport(provider)) as reopened:
        cached = await reopened.interactions.thread("person", ThreadOptions(sequence, "cached"))
        page = await reopened.store.history("111", {})
        assert (
            page["events"][0]["event_id"] == "person"
            and cached["posts"] == first["posts"]
            and cached["fetched"] is False
            and calls == ["/2/users/me", "/2/tweets/search/all"]
        )


@pytest.mark.parametrize(
    "values",
    [
        {"sequence": True},
        {"sequence": 0},
        {"sequence": 2**63},
        {"sequence": 1, "action": "invalid"},
        {"sequence": 1, "action": []},
        {"sequence": 1, "offset": -1},
        {"sequence": 1, "offset": True},
        {"sequence": 1, "offset": 1000001},
        {"sequence": 1, "checked_at": 3},
        {"sequence": 1, "accepted_costs": "yes"},
    ],
)
def test_thread_options_reject_ambiguous_values(values):
    with pytest.raises(ValueError):
        ThreadOptions(**values)


def test_base_install_cli_explains_missing_ui_extra(tmp_path):
    code = """
import builtins
original = builtins.__import__
def core_only(name, *args, **kwargs):
    if name == 'uvicorn':
        raise ModuleNotFoundError(name, name=name)
    return original(name, *args, **kwargs)
builtins.__import__ = core_only
from xflog.__main__ import main
main()
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode != 0 and 'pip install "xflog[ui] @ git+' in result.stderr
