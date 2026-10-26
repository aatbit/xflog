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
    (source / "compose.yaml").write_text("services: {}\n")
    executable(
        binaries / "git",
        """if [[ $1 == init ]]; then mkdir -p "${@: -1}";
elif [[ $1 == -C && $3 == checkout ]]; then cp -R "$FIXTURE_SOURCE/." "$2/"; fi
""",
    )
    executable(
        binaries / "docker",
        """printf 'docker %s\\n' "$*" >> "$CALL_LOG"
if [[ $1 == network && $2 == ls ]]; then printf 'bridge\\nproxy\\n'; fi
if [[ $1 == network && $2 == inspect ]]; then [[ $3 == proxy ]]; fi
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


def interactive_run(environment, answers):
    pid, terminal = pty.fork()
    if pid == 0:
        os.execve("/bin/bash", ["bash", "-c", 'cat "$1" | bash', "--", str(INSTALLER)], environment)
    transcript = b""
    pending = b""
    index = 0
    deadline = time.monotonic() + 15
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
            'source "$1"; mode=native; port=17861; origin=http://127.0.0.1:17861; bearer=; user_id=; user_token=; password=fake-private-password-12345; write_environment; write_unit; install_native',
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
