import json
import os
import pty
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.sh"


def executable(path, body):
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
    path.chmod(0o700)


@pytest.fixture
def installer_environment(tmp_path):
    home = tmp_path / "home"
    binaries = tmp_path / "bin"
    source = tmp_path / "source"
    for path in (home, binaries, source):
        path.mkdir()
    (source / "uv.lock").write_text("fixture")
    (source / ".env.example").write_text((ROOT / ".env.example").read_text())
    (source / "compose.yaml").write_text("services: {}\n")
    executable(
        binaries / "git",
        """printf 'git %s\\n' "$*" >> "$CALL_LOG"
if [[ $1 == init ]]; then mkdir -p "${@: -1}";
elif [[ $1 == -C && $3 == checkout ]]; then cp -R "$FIXTURE_SOURCE/." "$2/"; fi
if [[ $1 == -C && $3 == rev-parse ]]; then printf '%s\\n' "$2"; fi
if [[ $1 == -C && $3 == remote && $4 == get-url ]]; then echo https://github.com/aatbit/xflog.git; fi
if [[ $1 == -C && $3 == diff && ${DIRTY_CHECKOUT:-} == yes ]]; then exit 1; fi
if [[ $1 == -C && $3 == fetch && ${FETCH_FAIL:-} == yes ]]; then exit 9; fi
""",
    )
    executable(
        binaries / "docker",
        """printf 'docker %s\\n' "$*" >> "$CALL_LOG"
if [[ $1 == network && $2 == ls ]]; then printf 'bridge\\nproxy\\n'; fi
if [[ $1 == network && $2 == inspect ]]; then [[ $3 == proxy ]]; fi
if [[ $1 == ps ]]; then
 if [[ ${PS_FAIL:-} == yes ]]; then exit 7; fi
 printf '%s' "${EXISTING_PROJECT_CONTAINER:-}"
fi
if [[ $1 == inspect ]]; then printf '%s' "${PROJECT_WORKING_DIRECTORY:-}"; fi
if [[ $1 == volume && $2 == inspect ]]; then
 if [[ $4 == *compose.project* ]]; then printf '%s' "${VOLUME_OWNER:-xflog-installer-test}";
 else echo history; fi
fi
""",
    )
    for name in ("systemctl", "systemd-analyze", "loginctl", "sleep"):
        executable(
            binaries / name,
            'printf \'%s %s\\n\' "${0##*/}" "$*" >> "$CALL_LOG"\n'
            "if [[ ${0##*/} == loginctl && $1 == show-user ]]; then echo no; fi\n",
        )
    executable(
        binaries / "python-bootstrap",
        """[[ $1 == -m && $2 == venv ]]
mkdir -p "$3/bin"
cp "$FAKE_PYTHON" "$3/bin/python"
cp "$FAKE_UV" "$3/bin/uv"
printf '%s\\n' "$3" > "$BOOTSTRAP_PATH"
""",
    )
    executable(binaries / "python-runtime", 'exit "${HEALTH_EXIT:-0}"\n')
    executable(
        binaries / "uv",
        """while [[ $# -gt 0 ]]; do
 if [[ $1 == --project ]]; then project=$2; shift; fi
 shift
done
mkdir -p "$project/.venv/bin"
cp "$FAKE_PYTHON" "$project/.venv/bin/python"
""",
    )
    return {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "CALL_LOG": str(tmp_path / "calls"),
        "FIXTURE_SOURCE": str(source),
        "FAKE_PYTHON": str(binaries / "python-runtime"),
        "FAKE_UV": str(binaries / "uv"),
        "BOOTSTRAP_PATH": str(tmp_path / "bootstrap-path"),
    }


def interactive_run(environment, answers, timeout=15):
    pid, terminal = pty.fork()
    if pid == 0:
        os.execve("/bin/bash", ["bash", "-c", 'cat "$1" | bash', "--", str(INSTALLER)], environment)
    transcript = b""
    pending = b""
    index = 0
    deadline = time.monotonic() + timeout
    reaped = False
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([terminal], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(terminal, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                transcript += chunk
                pending += chunk
                if index < len(answers) and answers[index][0].encode() in pending:
                    os.write(terminal, answers[index][1].encode() + b"\n")
                    pending = b""
                    index += 1
            finished, status = os.waitpid(pid, os.WNOHANG)
            if finished:
                reaped = True
                break
        else:
            raise AssertionError("Installer did not finish its expected prompts")
        if not reaped:
            _, status = os.waitpid(pid, 0)
            reaped = True
        return os.waitstatus_to_exitcode(status), transcript.decode(errors="replace")
    finally:
        os.close(terminal)
        if not reaped:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)


def docker_answers(destination, activate="y"):
    return [
        ("Action:", "install"),
        ("Run with Docker", "docker"),
        ("Installation directory", str(destination)),
        ("Local port", "17861"),
        ("Browser-facing origin", ""),
        ("Compose project name", "xflog-installer-test"),
        ("Existing extra network", "proxy"),
        ("X app bearer token", ""),
        ("X user access token", ""),
        ("Instance password", "fake-private-password-12345"),
        ("Activate this installation", activate),
    ]


def test_pipe_style_installer_reads_tty_and_sets_up_docker(installer_environment, tmp_path):
    destination = tmp_path / "installed"
    code, transcript = interactive_run(installer_environment, docker_answers(destination))
    assert code == 0, transcript
    assert "fake-private-password-12345" not in transcript
    assert (destination / ".env").stat().st_mode & 0o777 == 0o600
    assert "external: true" in (destination / "compose.override.yaml").read_text()
    assert 'name: "proxy"' in (destination / "compose.override.yaml").read_text()
    assert " up -d --build --wait" in Path(installer_environment["CALL_LOG"]).read_text()


def test_declining_activation_does_not_start_docker(installer_environment, tmp_path):
    code, transcript = interactive_run(
        installer_environment, docker_answers(tmp_path / "prepared", activate="n")
    )
    assert code == 0, transcript
    assert "Canceled before activation" in transcript
    assert " up -d" not in Path(installer_environment["CALL_LOG"]).read_text()


def test_existing_install_is_not_overwritten(installer_environment, tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep"
    marker.write_text("original")
    code, transcript = interactive_run(installer_environment, docker_answers(destination))
    assert code != 0
    assert "already exists" in transcript
    assert marker.read_text() == "original"


def test_existing_compose_project_is_not_activated(installer_environment, tmp_path):
    environment = {**installer_environment, "EXISTING_PROJECT_CONTAINER": "existing-container"}
    destination = tmp_path / "fresh"
    code, transcript = interactive_run(environment, docker_answers(destination))
    assert code != 0
    assert "already has containers" in transcript
    assert not destination.exists()


def test_token_whitespace_is_rejected_without_writing_secrets(installer_environment, tmp_path):
    destination = tmp_path / "fresh"
    answers = docker_answers(destination)
    answers[7] = ("X app bearer token", "invalid token")
    code, transcript = interactive_run(installer_environment, answers)
    assert code != 0
    assert "Tokens must contain" in transcript
    assert "invalid token" not in transcript
    assert not destination.exists()


@pytest.mark.parametrize("user_token", ["", "fake-paid-token"])
def test_follower_install_accepts_optional_user_access_token(
    installer_environment, tmp_path, user_token
):
    destination = tmp_path / "followers"
    answers = docker_answers(destination)
    answers[7:9] = [
        ("X app bearer token", "fake-app-token"),
        ("Numeric target X user ID", "111"),
        ("X user access token", user_token),
    ]
    code, transcript = interactive_run(installer_environment, answers)
    assert code == 0, transcript
    assert f'X_USER_ACCESS_TOKEN="{user_token}"' in (destination / ".env").read_text()
    assert "fake-app-token" not in transcript


@pytest.mark.skipif(not shutil.which("docker"), reason="Optional Docker Compose parser integration")
def test_compose_env_round_trips_shell_special_characters(tmp_path):
    value = "fake-1234567890$()${UNSET}`echo bad`\"\\' # literal"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; mode=docker; env_line VALUE "$TEST_VALUE"',
            "--",
            str(INSTALLER),
        ],
        env={**os.environ, "TEST_VALUE": value},
        capture_output=True,
        text=True,
        check=True,
    )
    (tmp_path / ".env").write_text(result.stdout)
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        "services:\n  app:\n    image: test\n    environment:\n      VALUE: ${VALUE}\n"
    )
    parsed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(tmp_path / ".env"),
            "-f",
            str(compose),
            "config",
            "--environment",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"VALUE={value}" in parsed.stdout.splitlines()


@pytest.mark.skipif(not shutil.which("docker"), reason="Optional Docker Compose parser integration")
def test_compose_uses_prompted_settings_despite_ambient_overrides(tmp_path):
    (tmp_path / "compose.yaml").write_text((ROOT / "compose.yaml").read_text())
    (tmp_path / ".env").write_text(
        "XFLOG_PUBLISH_PORT=17861\nXFLOG_ADMIN_PASSWORD=fake-saved-password-12345\n"
    )
    parsed = subprocess.run(
        ["bash", "-c", 'source "$1"; compose config --format json', "--", str(INSTALLER)],
        env={
            **os.environ,
            "install_dir": str(tmp_path),
            "project": "prompted-project",
            "COMPOSE_PROJECT_NAME": "existing-project",
            "COMPOSE_FILE": "/does-not-exist.yaml",
            "COMPOSE_ENV_FILES": "/does-not-exist.env",
            "XFLOG_PUBLISH_PORT": "19999",
            "XFLOG_ADMIN_PASSWORD": "fake-ambient-password-12345",
            "X_APP_BEARER_TOKEN": "fake-ambient-token",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(parsed.stdout)
    assert config["name"] == "prompted-project"
    service = config["services"]["xflog"]
    assert service["ports"][0]["published"] == "17861"
    assert service["environment"]["XFLOG_ADMIN_PASSWORD"] == "fake-saved-password-12345"
    assert service["environment"]["X_APP_BEARER_TOKEN"] == ""


def test_native_setup_generates_user_service_and_boot_start(installer_environment, tmp_path):
    destination = tmp_path / "native"
    destination.mkdir()
    (destination / ".env.example").write_text((ROOT / ".env.example").read_text())
    data = tmp_path / "data"
    config = tmp_path / "units"
    environment = {
        **installer_environment,
        "install_dir": str(destination),
        "data_dir": str(data),
        "unit_dir": str(config),
        "python": str(Path(installer_environment["FAKE_UV"]).with_name("python-bootstrap")),
    }
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; exec 3>/dev/null; mode=native; port=17861; origin=http://127.0.0.1:17861; bearer=; user_id=; user_token=; password=fake-private-password-12345; write_environment; install_native',
            "--",
            str(INSTALLER),
        ],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    unit = (config / "xflog.service").read_text()
    assert "WantedBy=default.target" in unit
    assert "NoNewPrivileges=yes" in unit
    calls = Path(installer_environment["CALL_LOG"]).read_text()
    assert "enable-linger" in calls
    assert "systemctl --user enable --now xflog.service" in calls
    assert not Path(Path(environment["BOOTSTRAP_PATH"]).read_text().strip()).exists()


def test_native_dependency_failure_cannot_enable_service(installer_environment, tmp_path):
    failing_python = tmp_path / "fail-python"
    executable(failing_python, "exit 9\n")
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; install_native', "--", str(INSTALLER)],
        env={
            **installer_environment,
            "python": str(failing_python),
            "TMPDIR": str(tmp_path),
        },
        capture_output=True,
    )
    assert result.returncode == 9
    assert not Path(installer_environment["CALL_LOG"]).exists()
    assert not list(tmp_path.glob("xflog-bootstrap.*"))


def managed_checkout(environment, destination):
    shutil.copytree(environment["FIXTURE_SOURCE"], destination)
    (destination / ".env").write_text(
        'COMPOSE_PROJECT_NAME="xflog-installer-test"\n'
        'XFLOG_PUBLISH_PORT="17861"\nXFLOG_ORIGIN="http://127.0.0.1:17861"\n'
        'XFLOG_ADMIN_PASSWORD="fake-saved-password-12345"\n'
        'X_APP_BEARER_TOKEN=""\nX_USER_ID=""\nX_USER_ACCESS_TOKEN=""\n'
    )
    (destination / "compose.override.yaml").write_text("# operator network settings\n")


def management_answers(destination, action, confirm="y"):
    return [
        ("Action:", action),
        ("Run with Docker", "docker"),
        ("Installation directory", str(destination)),
        ("Update and restart" if action == "update" else "Uninstall this runtime", confirm),
    ]


def test_update_preserves_settings_and_network_and_adds_only_missing_defaults(
    installer_environment, tmp_path
):
    destination = tmp_path / "managed"
    managed_checkout(installer_environment, destination)
    original = (destination / ".env").read_text()
    source = Path(installer_environment["FIXTURE_SOURCE"])
    with (source / ".env.example").open("a") as template:
        template.write("NEW_OPTION=default-value\n")
    code, transcript = interactive_run(
        installer_environment, management_answers(destination, "update")
    )
    assert code == 0, transcript
    assert (destination / ".env").read_text().startswith(original)
    assert "NEW_OPTION=default-value" in (destination / ".env").read_text()
    assert (destination / "compose.override.yaml").read_text() == "# operator network settings\n"
    assert "fake-saved-password-12345" not in transcript
    assert not (destination / ".xflog-maintenance.lock").exists()
    updated = (destination / ".env").read_bytes()
    code, transcript = interactive_run(
        installer_environment, management_answers(destination, "update")
    )
    assert code == 0, transcript
    assert (destination / ".env").read_bytes() == updated


@pytest.mark.parametrize("failure", ["DIRTY_CHECKOUT", "FETCH_FAIL"])
def test_update_failure_does_not_restart_or_replace_settings(
    installer_environment, tmp_path, failure
):
    destination = tmp_path / "managed"
    managed_checkout(installer_environment, destination)
    original = (destination / ".env").read_bytes()
    code, transcript = interactive_run(
        {**installer_environment, failure: "yes"}, management_answers(destination, "update")
    )
    assert code != 0
    assert (destination / ".env").read_bytes() == original
    assert " up -d" not in Path(installer_environment["CALL_LOG"]).read_text()
    assert not (destination / ".xflog-maintenance.lock").exists()


@pytest.mark.parametrize("action", ["update", "uninstall"])
def test_canceling_management_leaves_runtime_and_settings_unchanged(
    installer_environment, tmp_path, action
):
    destination = tmp_path / "managed"
    managed_checkout(installer_environment, destination)
    original = (destination / ".env").read_bytes()
    code, transcript = interactive_run(
        installer_environment, management_answers(destination, action, confirm="n")
    )
    assert code == 0, transcript
    calls = Path(installer_environment["CALL_LOG"]).read_text()
    assert " up -d" not in calls and " down" not in calls and " checkout" not in calls
    assert (destination / ".env").read_bytes() == original


def test_default_uninstall_preserves_config_history_and_external_network(
    installer_environment, tmp_path
):
    destination = tmp_path / "managed"
    managed_checkout(installer_environment, destination)
    original = (destination / ".env").read_bytes()
    answers = management_answers(destination, "uninstall") + [
        ("Delete recorded history", ""),
        ("Delete saved .env", ""),
    ]
    code, transcript = interactive_run(installer_environment, answers)
    assert code == 0, transcript
    calls = Path(installer_environment["CALL_LOG"]).read_text()
    assert " down" in calls and " down -v" not in calls
    assert "volume rm" not in calls and "network rm" not in calls
    assert (destination / ".env").read_bytes() == original
    assert (destination / "compose.override.yaml").exists()


def test_explicit_docker_data_deletion_checks_owner_and_removes_only_history(
    installer_environment, tmp_path
):
    destination = tmp_path / "managed"
    managed_checkout(installer_environment, destination)
    answers = management_answers(destination, "uninstall") + [
        ("Delete recorded history", "DELETE"),
        ("Delete saved .env", "DELETE"),
    ]
    code, transcript = interactive_run(installer_environment, answers)
    assert code == 0, transcript
    calls = Path(installer_environment["CALL_LOG"]).read_text()
    assert "volume rm xflog-installer-test_history" in calls
    assert not (destination / ".env").exists()
    assert "network rm" not in calls and " down -v" not in calls


def test_copied_checkout_cannot_manage_another_project(installer_environment, tmp_path):
    destination = tmp_path / "copy"
    managed_checkout(installer_environment, destination)
    code, transcript = interactive_run(
        {
            **installer_environment,
            "EXISTING_PROJECT_CONTAINER": "other-container",
            "PROJECT_WORKING_DIRECTORY": "/another/checkout",
        },
        management_answers(destination, "uninstall"),
    )
    assert code != 0
    assert "belongs to another checkout" in transcript
    assert " down" not in Path(installer_environment["CALL_LOG"]).read_text()


@pytest.mark.parametrize("failure", ["VOLUME_OWNER", "PS_FAIL"])
def test_unverified_docker_ownership_cannot_delete_data_or_settings(
    installer_environment, tmp_path, failure
):
    destination = tmp_path / "managed"
    managed_checkout(installer_environment, destination)
    answers = management_answers(destination, "uninstall") + [
        ("Delete recorded history", "DELETE"),
        ("Delete saved .env", "DELETE"),
    ]
    code, transcript = interactive_run({**installer_environment, failure: "yes"}, answers)
    assert code != 0
    assert (destination / ".env").exists()
    assert "volume rm" not in Path(installer_environment["CALL_LOG"]).read_text()
    assert not (destination / ".xflog-maintenance.lock").exists()


def test_default_merge_preserves_equivalent_assignment_syntax_and_never_executes(
    tmp_path,
):
    (tmp_path / ".env").write_text(
        ' XFLOG_ORIGIN = "https://saved.example"\n'
        "export XFLOG_PUBLISH_PORT=17861\n"
        f'TOKEN="$(touch {tmp_path}/executed)"\n'
        'EMPTY=""\n'
    )
    original = (tmp_path / ".env").read_bytes()
    (tmp_path / ".env.example").write_text(
        "XFLOG_ORIGIN=http://127.0.0.1:7860\nXFLOG_PUBLISH_PORT=7860\n"
        "TOKEN=\nEMPTY=replace-me\nNEW_OPTION=default\n"
    )
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; exec 3>/dev/null; merge_defaults', "--", str(INSTALLER)],
        env={
            **os.environ,
            "install_dir": str(tmp_path),
            "mode": "docker",
            "origin": "http://127.0.0.1:7860",
            "port": "7860",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    merged = (tmp_path / ".env").read_bytes()
    assert merged == original + b"\nNEW_OPTION=default\n"
    assert not (tmp_path / "executed").exists()


def test_saved_database_with_whitespace_never_falls_back_to_unrelated_history(tmp_path):
    database = tmp_path / "actual.sqlite3"
    (tmp_path / ".env").write_text(f' XFLOG_DATABASE = "{database}"\n')
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; saved_setting XFLOG_DATABASE /unrelated/history.sqlite3',
            "--",
            str(INSTALLER),
        ],
        env={**os.environ, "install_dir": str(tmp_path), "mode": "native"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == str(database)


def native_fixture(environment, destination):
    managed_checkout(environment, destination)
    data = destination.parent / "data"
    data.mkdir()
    database = data / "history.sqlite3"
    for suffix in ("", "-wal", "-shm", ".paused"):
        Path(str(database) + suffix).write_text("keep-recorded-history")
    fallback = Path(environment["HOME"]) / ".local/share/xflog/history.sqlite3"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("unrelated-history")
    with (destination / ".env").open("a") as settings:
        settings.write(f' XFLOG_DATABASE = "{database}"\nXFLOG_PORT=17861\n')
    config = Path(environment["XDG_CONFIG_HOME"]) / "systemd/user"
    config.mkdir(parents=True)
    binaries = destination / ".venv/bin"
    binaries.mkdir(parents=True)
    shutil.copy(Path(environment["FAKE_UV"]).with_name("python-bootstrap"), binaries / "python")
    result = {
        **environment,
        "install_dir": str(destination),
        "unit_dir": str(config),
        "mode": "native",
        "reference": "main",
    }
    subprocess.run(
        ["bash", "-c", 'source "$1"; write_unit', "--", str(INSTALLER)],
        env=result,
        check=True,
    )
    shutil.copy(destination / "xflog.service", config / "xflog.service")
    return result, database, fallback


def run_native_management(environment, answers):
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; exec 3>/dev/null; ask(){ IFS= read -r reply; }; manage_installation',
            "--",
            str(INSTALLER),
        ],
        env=environment,
        input=answers,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("delete", [False, True])
def test_native_uninstall_keeps_data_by_default_and_deletes_only_selected_database(
    installer_environment, tmp_path, delete
):
    destination = tmp_path / "native"
    environment, database, fallback = native_fixture(installer_environment, destination)
    original = (destination / ".env").read_bytes()
    result = run_native_management(
        {**environment, "action": "uninstall"}, "y\nDELETE\n\n" if delete else "y\n\n\n"
    )
    assert result.returncode == 0, result.stderr
    assert not (Path(environment["unit_dir"]) / "xflog.service").exists()
    assert (destination / ".env").read_bytes() == original
    assert database.exists() != delete
    assert Path(str(database) + ".paused").exists() != delete
    assert fallback.read_text() == "unrelated-history"
    assert "disable-linger" not in Path(environment["CALL_LOG"]).read_text()


def test_native_update_preserves_history_and_can_restore_removed_service(
    installer_environment, tmp_path
):
    destination = tmp_path / "native"
    environment, database, _ = native_fixture(installer_environment, destination)
    (Path(environment["unit_dir"]) / "xflog.service").unlink()
    result = run_native_management({**environment, "action": "update"}, "y\n")
    assert result.returncode == 0, result.stderr
    assert database.read_text() == "keep-recorded-history"
    calls = Path(environment["CALL_LOG"]).read_text()
    assert "systemctl --user enable --now xflog.service" in calls
    assert "systemctl --user stop" not in calls
    assert (Path(environment["unit_dir"]) / "xflog.service").exists()


def test_native_unit_for_another_checkout_is_never_stopped(installer_environment, tmp_path):
    environment, _, _ = native_fixture(installer_environment, tmp_path / "native")
    unit = Path(environment["unit_dir"]) / "xflog.service"
    unit.write_text("WorkingDirectory=/unrelated\n")
    result = run_native_management({**environment, "action": "uninstall"}, "y\nDELETE\nDELETE\n")
    assert result.returncode != 0
    assert unit.read_text() == "WorkingDirectory=/unrelated\n"
    assert "systemctl" not in Path(environment["CALL_LOG"]).read_text()


def test_native_update_failure_keeps_history_and_never_restarts_partial_environment(
    installer_environment, tmp_path
):
    destination = tmp_path / "native"
    environment, database, _ = native_fixture(installer_environment, destination)
    executable(destination / ".venv/bin/python", "exit 9\n")
    result = run_native_management({**environment, "action": "update"}, "y\n")
    assert result.returncode == 9
    calls = Path(environment["CALL_LOG"]).read_text()
    assert "systemctl --user stop xflog.service" in calls
    assert "enable --now" not in calls
    assert database.read_text() == "keep-recorded-history"
    assert not (destination / ".xflog-maintenance.lock").exists()


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example:7860",
        "https://xf.example/path",
        "https://u:p@xf.example",
        "https://xf.example:99999",
    ],
)
def test_installer_rejects_unsafe_origins(origin):
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; port=7860; valid_origin "$TEST_ORIGIN"', "--", str(INSTALLER)],
        env={**os.environ, "TEST_ORIGIN": origin},
        capture_output=True,
    )
    assert result.returncode != 0
