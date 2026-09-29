"""The weekly LaunchAgent: its plist, the wrapper launchd runs, and the operator's installer.

The shell scripts run for real against temp dirs, with a fake python, a fake
launchctl and a fake plutil. Nothing here installs, loads or starts a job.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
OPS = REPO / "ops/launchd"
LABEL = "cc.eastpeak.openmarin-refresh-weekly"
MACHINE_REPO = "/Users/tammypais/projects/marin-civic-graph"
SECRET = "https://hc-ping.com/0f3c9e2a-5b7d-4e61-9a0c-7d2b1e4f8a63"
MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"  # what launchd gives a job


# --- the plist -------------------------------------------------------------------


def _plist() -> dict:
    return plistlib.loads((OPS / f"{LABEL}.plist").read_bytes())


def test_the_plist_runs_the_wrapper_for_this_machine_on_monday_at_five():
    plist = _plist()

    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == ["/bin/bash", f"{MACHINE_REPO}/ops/launchd/run-weekly-stage.sh"]
    assert plist["WorkingDirectory"] == MACHINE_REPO
    assert plist["StartCalendarInterval"] == {"Weekday": 1, "Hour": 5, "Minute": 0}
    assert plist["EnvironmentVariables"] == {"NEO4J_URI": "bolt://localhost:7688"}  # the guard only; never 7687
    for key in ("StandardOutPath", "StandardErrorPath"):
        assert plist[key].startswith(f"{MACHINE_REPO}/data/ingest-runs/launchd/")  # install.sh pre-creates it


def test_the_plist_never_holds_a_secret_or_keeps_the_job_alive():
    plist, text = _plist(), (OPS / f"{LABEL}.plist").read_text()

    assert not plist.get("KeepAlive") and not plist.get("RunAtLoad")
    for secret in ("OPEN_MARIN_HEARTBEAT_URL", "hc-ping", "PASSWORD", "NEO4J_USER"):
        assert secret not in text


@pytest.mark.skipif(shutil.which("plutil") is None, reason="plutil is macOS-only")
def test_the_plist_passes_plutil_lint():
    subprocess.run(["plutil", "-lint", str(OPS / f"{LABEL}.plist")], check=True, capture_output=True)


def test_the_env_file_is_gitignored_and_only_its_example_is_committed():
    ignored = subprocess.run(["git", "check-ignore", "-q", "ops/launchd/weekly.env"], cwd=REPO)
    assert ignored.returncode == 0
    example = (OPS / "weekly.env.example").read_text()
    assert "OPEN_MARIN_HEARTBEAT_URL=\n" in example and "hc-ping.com/" not in example


# --- the wrapper -----------------------------------------------------------------


FAKE_PYTHON = """#!/bin/bash
echo "cwd=$(pwd) args=$*"
echo "neo4j=${NEO4J_URI:-unset} heartbeat=${OPEN_MARIN_HEARTBEAT_URL:+set}"
exit "${FAKE_EXIT:-0}"
"""


def _executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o755)
    return path


@pytest.fixture
def wrapper_env(tmp_path: Path) -> dict[str, str]:
    env_file = tmp_path / "weekly.env"
    env_file.write_text(f"OPEN_MARIN_HEARTBEAT_URL={SECRET}\n")
    env_file.chmod(0o600)
    return {"PATH": MINIMAL_PATH, "HOME": str(tmp_path), "NEO4J_URI": "bolt://localhost:7688",
            "OPEN_MARIN_ENV_FILE": str(env_file), "OPEN_MARIN_LOG_DIR": str(tmp_path / "logs"),
            "OPEN_MARIN_PYTHON": str(_executable(tmp_path / "python", FAKE_PYTHON))}


def _wrap(env: dict[str, str]) -> tuple[int, str]:
    proc = subprocess.run(["/bin/bash", str(OPS / "run-weekly-stage.sh")], env=env, capture_output=True, text=True)
    log = Path(env["OPEN_MARIN_LOG_DIR"]) / "weekly-stage.log"
    return proc.returncode, proc.stdout + proc.stderr + (log.read_text() if log.exists() else "")


def test_the_wrapper_sources_the_env_file_and_runs_stage_from_the_repo(wrapper_env):
    code, log = _wrap(wrapper_env)

    assert code == 0
    assert f"cwd={REPO} args=scripts/refresh_weekly.py stage" in log
    assert "neo4j=bolt://localhost:7688 heartbeat=set" in log
    assert SECRET not in log


def test_the_wrapper_passes_stages_exit_code_through(wrapper_env):
    code, log = _wrap({**wrapper_env, "FAKE_EXIT": "1"})

    assert code == 1 and "exited 1" in log


def test_a_missing_env_file_is_reported_and_stage_still_runs_without_a_heartbeat(wrapper_env):
    Path(wrapper_env["OPEN_MARIN_ENV_FILE"]).unlink()

    code, log = _wrap(wrapper_env)

    assert code == 0 and "WARNING" in log and "weekly.env" in log
    assert "args=scripts/refresh_weekly.py stage" in log and "heartbeat=set" not in log


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o606])
def test_an_env_file_others_can_read_or_write_is_never_sourced(wrapper_env, mode):
    Path(wrapper_env["OPEN_MARIN_ENV_FILE"]).chmod(mode)

    code, log = _wrap(wrapper_env)

    assert code == 0 and "heartbeat=set" not in log
    assert "WARNING" in log and "chmod 600" in log


def test_the_wrapper_creates_its_log_dir_and_appends_run_after_run(wrapper_env):
    _wrap(wrapper_env)
    _wrap(wrapper_env)

    log = (Path(wrapper_env["OPEN_MARIN_LOG_DIR"]) / "weekly-stage.log").read_text()
    assert log.count("args=scripts/refresh_weekly.py stage") == 2


def test_logs_over_the_size_limit_rotate_keeping_three_generations(wrapper_env):
    logs = Path(wrapper_env["OPEN_MARIN_LOG_DIR"])
    logs.mkdir()
    for name, text in {"weekly-stage.log": "current " * 50, "weekly-stage.log.1": "gen1",
                       "weekly-stage.log.2": "gen2", "weekly-stage.log.3": "gen3",
                       "launchd.err.log": "stderr " * 50, "launchd.out.log": "small"}.items():
        (logs / name).write_text(text)

    _wrap({**wrapper_env, "OPEN_MARIN_LOG_MAX_BYTES": "100"})

    assert (logs / "weekly-stage.log.1").read_text().startswith("current")
    assert (logs / "weekly-stage.log.2").read_text() == "gen1"
    assert (logs / "weekly-stage.log.3").read_text() == "gen2"  # gen3 was the oldest and is gone
    assert not (logs / "weekly-stage.log.4").exists()
    assert "current" not in (logs / "weekly-stage.log").read_text()
    assert (logs / "launchd.err.log.1").read_text().startswith("stderr")
    assert (logs / "launchd.out.log").read_text() == "small" and not (logs / "launchd.out.log.1").exists()


# --- the installer (the operator runs it; tests use fakes) -------------------------


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A throwaway checkout whose plist points at itself, with fake launchctl and plutil."""
    repo = tmp_path / "repo"
    (repo / "ops/launchd").mkdir(parents=True)
    (repo / "data/ingest-runs").mkdir(parents=True)
    for name in ("install.sh", "run-weekly-stage.sh"):
        shutil.copy2(OPS / name, repo / "ops/launchd" / name)
    plist = (OPS / f"{LABEL}.plist").read_text().replace(MACHINE_REPO, str(repo))
    (repo / f"ops/launchd/{LABEL}.plist").write_text(plist)
    (repo / ".venv/bin").mkdir(parents=True)
    _executable(repo / ".venv/bin/python", "#!/bin/bash\n")
    env_file = repo / "ops/launchd/weekly.env"
    env_file.write_text(f"OPEN_MARIN_HEARTBEAT_URL={SECRET}\n")
    env_file.chmod(0o600)
    calls = tmp_path / "calls"
    for tool in ("launchctl", "plutil"):
        _executable(tmp_path / tool, f'#!/bin/bash\necho "{tool} $*" >> {calls}\n'
                                     f'[ "$1" = print ] && exit "${{FAKE_LOADED:-1}}"\nexit 0\n')
    return repo


def _install(checkout: Path, *args: str, **extra: str) -> subprocess.CompletedProcess:
    tmp = checkout.parent
    env = {"PATH": MINIMAL_PATH, "HOME": str(tmp), "LAUNCHCTL": str(tmp / "launchctl"),
           "PLUTIL": str(tmp / "plutil"), "OPEN_MARIN_LAUNCH_AGENTS_DIR": str(tmp / "LaunchAgents"), **extra}
    return subprocess.run(["/bin/bash", str(checkout / "ops/launchd/install.sh"), *args],
                          env=env, capture_output=True, text=True)


def _calls(checkout: Path) -> str:
    path = checkout.parent / "calls"
    return path.read_text() if path.exists() else ""


def test_install_lints_copies_and_bootstraps_after_precreating_the_log_dir(checkout):
    proc = _install(checkout)

    assert proc.returncode == 0, proc.stderr
    installed = checkout.parent / f"LaunchAgents/{LABEL}.plist"
    assert installed.read_text() == (checkout / f"ops/launchd/{LABEL}.plist").read_text()
    assert (checkout / "data/ingest-runs/launchd").is_dir()
    calls = _calls(checkout)
    assert "plutil -lint" in calls
    assert f"launchctl bootstrap gui/{os.getuid()} {installed}" in calls
    assert "launchctl kickstart" in proc.stdout  # tells the operator how to run it once, by hand
    assert SECRET not in proc.stdout + proc.stderr


@pytest.mark.parametrize("problem,expected", [
    ("missing", "weekly.env"), ("mode", "chmod 600"), ("empty-url", "OPEN_MARIN_HEARTBEAT_URL"),
])
def test_install_refuses_without_a_private_env_file_holding_the_heartbeat_url(checkout, problem, expected):
    env_file = checkout / "ops/launchd/weekly.env"
    if problem == "missing":
        env_file.unlink()
    elif problem == "mode":
        env_file.chmod(0o644)
    else:
        env_file.write_text("OPEN_MARIN_HEARTBEAT_URL=\n")

    proc = _install(checkout)

    assert proc.returncode != 0 and expected in proc.stderr
    assert "bootstrap" not in _calls(checkout)
    assert not (checkout.parent / f"LaunchAgents/{LABEL}.plist").exists()


def test_install_refuses_a_plist_that_targets_another_checkout(checkout):
    plist = checkout / f"ops/launchd/{LABEL}.plist"
    plist.write_text(plist.read_text().replace(str(checkout), "/elsewhere"))

    proc = _install(checkout)

    assert proc.returncode != 0 and "/elsewhere" not in _calls(checkout)
    assert "bootstrap" not in _calls(checkout)


def test_reinstalling_boots_out_the_loaded_job_first(checkout):
    proc = _install(checkout, FAKE_LOADED="0")

    calls = _calls(checkout).splitlines()
    assert proc.returncode == 0
    assert calls.index(f"launchctl bootout gui/{os.getuid()}/{LABEL}") < \
        next(i for i, c in enumerate(calls) if c.startswith("launchctl bootstrap"))


def test_uninstall_boots_out_and_removes_only_the_installed_plist(checkout):
    assert _install(checkout).returncode == 0

    proc = _install(checkout, "--uninstall", FAKE_LOADED="0")

    assert proc.returncode == 0
    assert f"launchctl bootout gui/{os.getuid()}/{LABEL}" in _calls(checkout)
    assert not (checkout.parent / f"LaunchAgents/{LABEL}.plist").exists()
    assert (checkout / "ops/launchd/weekly.env").exists()  # the operator's secrets stay
