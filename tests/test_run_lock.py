"""Tests for scripts/run_lock.py — one exclusive lock for everything that writes ingestion state."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest  # noqa: E402
import run_lock  # noqa: E402


def test_a_second_holder_is_refused_immediately_and_the_lock_frees_on_exit(tmp_path):
    with run_lock.run_lock(tmp_path):
        assert (tmp_path / "data/ingest-runs/.lock").is_file()
        with pytest.raises(run_lock.RunLockHeld, match=r"another ingestion run \(pid \d+\) holds"):
            with run_lock.run_lock(tmp_path):
                pass
    with run_lock.run_lock(tmp_path):  # released, so it can be taken again
        pass


def _child(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    code = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import run_lock\n"
            f"with run_lock.run_lock(__import__('pathlib').Path({str(root)!r})): print('got it')")
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)


def test_another_process_is_refused_unless_its_parent_holds_the_lock_for_it(tmp_path):
    env = {"PATH": os.environ.get("PATH", "")}
    with run_lock.run_lock(tmp_path):
        refused = _child(tmp_path, env)
        assert refused.returncode != 0 and "RunLockHeld" in refused.stderr
        inherited = _child(tmp_path, {**env, run_lock.OWNER_ENV: str(os.getpid())})
        assert inherited.returncode == 0 and "got it" in inherited.stdout
        # A stale owner variable (not this child's parent) is no pass.
        stale = _child(tmp_path, {**env, run_lock.OWNER_ENV: "1"})
        assert stale.returncode != 0


def test_ingest_main_refuses_to_capture_while_another_run_holds_the_lock(tmp_path, monkeypatch, capsys):
    registry = tmp_path / "reg.yaml"
    registry.write_text("sources:\n  - {id: a, adapter: fake, url: u, schedule: weekly}\n")
    monkeypatch.setattr(ingest, "ROOT", tmp_path)
    monkeypatch.setattr(ingest, "run_source", lambda *a, **k: pytest.fail("captured while locked"))

    with run_lock.run_lock(tmp_path):
        assert ingest.main(["--all", "--registry", str(registry)]) == 2

    assert "another ingestion run" in capsys.readouterr().err
