import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_installer import INSTALLER, executable, interactive_run


def git(repository, *arguments):
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(repository):
    git(repository, "add", ".")
    git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return git(repository, "rev-parse", "HEAD")


@pytest.fixture
def update_source(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-q", "-b", "main")
    (remote / "install.sh").write_bytes(INSTALLER.read_bytes())
    (remote / "app.py").write_text("initial app\n")
    (remote / "README.md").write_text("initial docs\n")
    commit(remote)
    installed = tmp_path / "installed"
    git(tmp_path, "clone", "-q", "--no-hardlinks", str(remote), str(installed))
    git(installed, "remote", "set-url", "origin", "https://github.com/aatbit/xflog.git")
    (installed / ".env").write_text("PRIVATE=fake-never-print-this\n")
    (installed / "history.sqlite3").write_text("keep history\n")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    transport = binaries / "git"
    executable(
        transport,
        'arguments=(); for argument in "$@"; do\n'
        " if [[ $argument == https://github.com/aatbit/xflog.git ]]; then argument=$TEST_REMOTE; fi\n"
        ' arguments+=("$argument"); done\nexec "$REAL_GIT" "${arguments[@]}"\n',
    )
    environment = {
        **os.environ,
        "install_dir": str(installed),
        "reference": "main",
        "TMPDIR": str(temporary),
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "REAL_GIT": shutil.which("git"),
        "TEST_REMOTE": str(remote),
        "TEST_GIT_TRANSPORT": str(transport),
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_TERMINAL_PROMPT": "0",
    }
    return remote, installed, environment


def run_check(environment, script=INSTALLER, answers="n\n"):
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; exec 3>&1; ask(){ printf "%s\\n" "$1"; IFS= read -r reply; }; check_updates',
            "--",
            str(script),
        ],
        env=environment,
        input=answers,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize(
    "changed", [(), ("app.py",), ("install.sh",), ("app.py", "install.sh"), ("README.md",)]
)
def test_check_reports_app_and_installer_separately_without_touching_installation(
    update_source, changed
):
    remote, installed, environment = update_source
    for name in changed:
        with (remote / name).open("a") as file:
            file.write("\n# remote change\n")
    if changed:
        commit(remote)
    before = {p: p.read_bytes() for p in installed.iterdir() if p.is_file()}
    revision = git(installed, "rev-parse", "HEAD")
    result = run_check(environment)
    assert result.returncode == 0, result.stderr
    app_status = "update available" if "app.py" in changed else "up to date"
    installer_status = "update available" if "install.sh" in changed else "up to date"
    assert f"XFlog app: {app_status}" in result.stdout
    assert f"Installer: {installer_status}" in result.stdout
    assert {p: p.read_bytes() for p in installed.iterdir() if p.is_file()} == before
    assert git(installed, "rev-parse", "HEAD") == revision
    assert not list(Path(environment["TMPDIR"]).iterdir())
    assert "fake-never-print-this" not in result.stdout + result.stderr
    if "app.py" in changed:
        assert (
            f"/{git(remote, 'rev-parse', 'HEAD')}/install.sh | XFLOG_REF=main bash" in result.stdout
        )


def test_current_downloaded_installer_is_not_confused_with_older_installed_copy(update_source):
    remote, _, environment = update_source
    with (remote / "install.sh").open("a") as file:
        file.write("\n# new installer\n")
    commit(remote)
    result = run_check(environment, remote / "install.sh")
    assert result.returncode == 0, result.stderr
    assert "XFlog app: up to date" in result.stdout
    assert "Installer: up to date" in result.stdout
    assert "Run the updated installer" not in result.stdout


def test_pipe_check_refreshes_once_then_reopens_real_menu_with_selected_reference(update_source):
    remote, installed, environment = update_source
    with (remote / "install.sh").open("a") as file:
        file.write("\n# new installer\n")
    commit(remote)
    git(remote, "branch", "test-release")
    code, transcript = interactive_run(
        {**environment, "XFLOG_REF": "test-release"},
        [
            ("Action:", "check for updates"),
            ("Installation directory", str(installed)),
            ("Run the updated installer", "y"),
            ("Action:", "check"),
            ("Installation directory", str(installed)),
        ],
    )
    assert code == 0, transcript
    assert transcript.count("Installer: update available") == 1
    assert transcript.count("Installer: up to date") == 1
    assert transcript.count("Checking source: test-release") == 2
    assert "Run with Docker" not in transcript
    assert not list(Path(environment["TMPDIR"]).iterdir())


def test_refresh_executes_fetched_snapshot_and_propagates_failure_after_cleanup(update_source):
    remote, _, environment = update_source
    (remote / "install.sh").write_text(
        '#!/usr/bin/env bash\nprintf "verified installer %s\\n" "$XFLOG_REF"\nexit 7\n'
    )
    commit(remote)
    result = run_check(environment, answers="y\n")
    assert result.returncode == 7
    assert "verified installer main" in result.stdout
    assert not list(Path(environment["TMPDIR"]).iterdir())


@pytest.mark.parametrize("broken", ["syntax", "missing", "network", "reference"])
def test_bad_download_or_reference_never_executes_or_changes_saved_data(update_source, broken):
    remote, installed, environment = update_source
    marker = installed / "should-not-execute"
    if broken == "syntax":
        (remote / "install.sh").write_text(f'touch "{marker}"\nif then\n')
        commit(remote)
    elif broken == "missing":
        (remote / "install.sh").unlink()
        commit(remote)
    elif broken == "network":
        environment["TEST_REMOTE"] = str(remote) + "-missing"
    else:
        environment["reference"] = "missing-branch"
    before = (installed / ".env").read_bytes()
    result = run_check(environment, answers="y\n")
    assert result.returncode != 0
    assert not marker.exists()
    assert (installed / ".env").read_bytes() == before
    assert "up to date" not in result.stdout
    assert not list(Path(environment["TMPDIR"]).iterdir())


def test_check_uses_fixed_official_source_and_rejects_other_origin(update_source):
    _, installed, environment = update_source
    git(installed, "remote", "set-url", "origin", "https://example.invalid/fake.git")
    result = run_check(environment)
    assert result.returncode != 0
    assert "official aatbit/xflog origin" in result.stderr
    assert not list(Path(environment["TMPDIR"]).iterdir())


@pytest.mark.parametrize("staged", [False, True])
def test_check_reports_local_edits_without_replacing_them(update_source, staged):
    _, installed, environment = update_source
    (installed / "app.py").write_text("local edit\n")
    if staged:
        git(installed, "add", "app.py")
    result = run_check(environment)
    assert result.returncode == 0, result.stderr
    assert "Local app files have edits" in result.stdout
    assert (installed / "app.py").read_text() == "local edit\n"


def test_comparison_error_is_not_reported_as_available_update(update_source, tmp_path):
    _, _, environment = update_source
    binaries = tmp_path / "failing-bin"
    binaries.mkdir()
    executable(
        binaries / "git",
        'if [[ $* == *"xflog-update-check."* && $* == *" diff "* ]]; then exit 9; fi\nexec "$TEST_GIT_TRANSPORT" "$@"\n',
    )
    result = run_check({**environment, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]})
    assert result.returncode != 0
    assert "Could not compare application files" in result.stderr
    assert "update available" not in result.stdout


def test_branch_movement_cannot_replace_the_already_checked_installer(update_source, tmp_path):
    remote, _, environment = update_source
    (remote / "install.sh").write_text("#!/usr/bin/env bash\necho checked-snapshot\n")
    checked = commit(remote)
    binaries = tmp_path / "moving-bin"
    binaries.mkdir()
    executable(
        binaries / "git",
        'if [[ $* == *" show "* ]]; then\n'
        ' printf "#!/usr/bin/env bash\\necho moved-snapshot\\n" > "$TEST_REMOTE/install.sh"\n'
        ' "$REAL_GIT" -C "$TEST_REMOTE" add install.sh\n'
        ' "$REAL_GIT" -C "$TEST_REMOTE" -c user.name=Test -c user.email=test@example.invalid commit -qm move\n'
        'fi\nexec "$TEST_GIT_TRANSPORT" "$@"\n',
    )
    result = run_check(
        {**environment, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]}, answers="y\n"
    )
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "HEAD") != checked
    assert "checked-snapshot" in result.stdout
    assert "moved-snapshot" not in result.stdout


def test_standalone_installer_file_is_preserved_when_refreshing(update_source, tmp_path):
    remote, _, environment = update_source
    saved = tmp_path / "saved-installer.sh"
    saved.write_bytes(INSTALLER.read_bytes())
    original = saved.read_bytes()
    (remote / "install.sh").write_text("#!/usr/bin/env bash\necho refreshed-installer\n")
    commit(remote)
    result = run_check(environment, saved, "y\n")
    assert result.returncode == 0, result.stderr
    assert "refreshed-installer" in result.stdout
    assert saved.read_bytes() == original


@pytest.mark.parametrize("refresh", ["n", "y"])
def test_pipe_check_supports_legacy_checkout_without_installer(update_source, refresh):
    _, installed, environment = update_source
    git(installed, "rm", "install.sh")
    git(
        installed,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "legacy checkout without installer",
    )
    before = (installed / ".env").read_bytes()
    answers = [
        ("Action:", "check"),
        ("Installation directory", str(installed)),
        ("Run the updated installer", refresh),
    ]
    if refresh == "y":
        answers += [("Action:", "check"), ("Installation directory", str(installed))]
    code, transcript = interactive_run(environment, answers)
    assert code == 0, transcript
    assert "XFlog app: up to date" in transcript
    assert transcript.count("Installer: no saved version to compare") == 1
    if refresh == "y":
        assert "Installer: up to date" in transcript
    assert not (installed / "install.sh").exists()
    assert (installed / ".env").read_bytes() == before
    assert not list(Path(environment["TMPDIR"]).iterdir())
