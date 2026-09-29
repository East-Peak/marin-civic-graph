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
