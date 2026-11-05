import subprocess
import sys

import httpx
import pytest

from xflog import __main__ as cli
from xflog.tracking.transport import provider_http


@pytest.fixture
def lookup_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("X_APP_BEARER_TOKEN", "fake-app-secret")
    monkeypatch.setenv("X_USER_ACCESS_TOKEN", "fake-user-secret")
    monkeypatch.setenv("X_USER_ID", "")
    monkeypatch.setenv("XFLOG_DATABASE", str(tmp_path / "unused.sqlite3"))
    monkeypatch.setenv("XFLOG_ORIGIN", "invalid-browser-origin")
    monkeypatch.setenv("XFLOG_PORT", "invalid-browser-port")
    state = {
        "body": {"data": {"id": "1234567890123456789", "username": "aakash"}},
        "status": 200,
        "calls": [],
        "clients": [],
    }

    async def provider(request):
        state["calls"].append(request)
        if "failure" in state:
            raise state["failure"]
        return httpx.Response(
            state["status"], json=state["body"], headers={"location": "https://other.example"}
        )

    def client():
        http = provider_http(httpx.MockTransport(provider))
        state["clients"].append(http)
        return http

    monkeypatch.setattr(cli, "provider_http", client)
    return state


@pytest.mark.parametrize(
    "arguments,path,token",
    [
        (["@aakash"], "/2/users/by/username/aakash", "fake-app-secret"),
        ([" @aakash "], "/2/users/by/username/aakash", "fake-app-secret"),
        (["AAKASH"], "/2/users/by/username/AAKASH", "fake-app-secret"),
        (["--me"], "/2/users/me", "fake-user-secret"),
    ],
)
def test_lookup_prints_one_id_without_opening_ui_or_database(
    lookup_provider, capsys, tmp_path, arguments, path, token
):
    cli.main(["user-id", *arguments])
    requests = lookup_provider["calls"]
    output = capsys.readouterr()
    assert (
        output.out == "1234567890123456789\n"
        and not output.err
        and len(requests) == 1
        and requests[0].method == "GET"
        and requests[0].url.path == path
        and requests[0].headers["authorization"] == f"Bearer {token}"
        and lookup_provider["clients"][0].is_closed
        and not (tmp_path / "unused.sqlite3").exists()
    )


@pytest.mark.parametrize("arguments", [[], ["--me", "aakash"], ["aakash", "extra"]])
def test_lookup_requires_exactly_one_target(lookup_provider, arguments):
    with pytest.raises(SystemExit) as error:
        cli.main(["user-id", *arguments])
    assert error.value.code == 2 and not lookup_provider["calls"]


@pytest.mark.parametrize("handle", ["@@aakash", "", "a/b", "a?query", "a" * 16, "a\nb"])
def test_invalid_handles_make_no_request(lookup_provider, handle):
    with pytest.raises(SystemExit, match="Enter an X handle"):
        cli.main(["user-id", handle])
    assert not lookup_provider["calls"]


@pytest.mark.parametrize(
    "argument,variable,message",
    [
        ("aakash", "X_APP_BEARER_TOKEN", "Set X_APP_BEARER_TOKEN"),
        ("--me", "X_USER_ACCESS_TOKEN", "no current user"),
    ],
)
def test_missing_required_token_never_falls_back(
    lookup_provider, monkeypatch, argument, variable, message
):
    monkeypatch.setenv(variable, "")
    with pytest.raises(SystemExit, match=message):
        cli.main(["user-id", argument])
    assert not lookup_provider["calls"]


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"data": []},
        {"data": {"id": 123}},
        {"data": {"id": "not-an-id"}},
        {"data": {"id": "111", "username": "different"}},
        {"data": {"id": "111", "username": "aakash"}, "errors": [{"detail": "secret"}]},
    ],
)
def test_incomplete_or_mismatched_users_are_not_printed(lookup_provider, capsys, body):
    lookup_provider["body"] = body
    with pytest.raises(SystemExit, match="valid matching user"):
        cli.main(["user-id", "aakash"])
    assert not capsys.readouterr().out and lookup_provider["clients"][0].is_closed


@pytest.mark.parametrize("status", [302, 401, 402, 403, 404, 429, 500])
def test_provider_failure_has_no_retry_redirect_or_secret_output(lookup_provider, capsys, status):
    lookup_provider["status"] = status
    lookup_provider["body"] = {"detail": "fake-app-secret"}
    with pytest.raises(SystemExit, match=f"HTTP {status}") as error:
        cli.main(["user-id", "aakash"])
    assert (
        len(lookup_provider["calls"]) == 1
        and "fake-app-secret" not in str(error.value)
        and not capsys.readouterr().out
        and lookup_provider["clients"][0].is_closed
    )


def test_network_errors_do_not_echo_request_secrets(lookup_provider):
    lookup_provider["failure"] = httpx.ConnectError("fake-app-secret")
    with pytest.raises(SystemExit, match="Could not reach X") as error:
        cli.main(["user-id", "aakash"])
    assert "fake-app-secret" not in str(error.value) and lookup_provider["clients"][0].is_closed


def test_no_arguments_keeps_existing_browser_entry_point(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "serve", lambda: calls.append("serve"))
    cli.main([])
    assert calls == ["serve"]


def test_help_does_not_import_web_dependencies():
    code = """
import sys
from xflog.__main__ import main
try:
    main(['user-id', '--help'])
except SystemExit as error:
    assert error.code == 0
assert not {'gradio', 'fastapi', 'uvicorn', 'pydantic'} & sys.modules.keys()
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
