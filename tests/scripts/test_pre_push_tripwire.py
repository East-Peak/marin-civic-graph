"""Tests for scripts/pre_push_tripwire.py — the pre-push gate around the committed-text tripwire.

The tripwire skips wherever its local-only strings file is absent (every worktree), so the gate
runs it in the main checkout, once per pushed commit, and accepts only one executed, passing test.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from pre_push_tripwire import main, pushed_shas, verdict  # noqa: E402

ZERO = "0" * 40
A = "a" * 40
B = "b" * 40


def _junit(tests=1, skipped=0, failures=0, errors=0):
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
        f'errors="{errors}" failures="{failures}" skipped="{skipped}" tests="{tests}">'
        "</testsuite></testsuites>"
    )


class TestPushedShas:
    def test_one_line_per_ref_deduplicated_in_order(self):
        lines = [
            f"refs/heads/main {A} refs/heads/main {ZERO}",
            f"refs/tags/v1 {B} refs/tags/v1 {ZERO}",
            f"refs/heads/other {A} refs/heads/other {ZERO}",
        ]
        assert pushed_shas(lines) == [A, B]

    def test_deletes_and_blank_lines_check_nothing(self):
        assert pushed_shas([f"(delete) {ZERO} refs/heads/gone {A}", "", "  "]) == []

    def test_malformed_line_is_refused(self):
        with pytest.raises(ValueError):
            pushed_shas(["refs/heads/main not-a-sha"])


class TestVerdict:
    def test_one_executed_passing_test_is_accepted(self):
        assert verdict(_junit()) is None

    @pytest.mark.parametrize(
        "kwargs, reason",
        [
            ({"skipped": 1}, "skipped"),
            ({"failures": 1}, "failed"),
            ({"errors": 1}, "error"),
            ({"tests": 0}, "expected exactly 1"),
            ({"tests": 2}, "expected exactly 1"),
        ],
    )
    def test_anything_else_is_refused_with_its_reason(self, kwargs, reason):
        assert reason in verdict(_junit(**kwargs))

    def test_unreadable_report_is_refused(self):
        assert "unreadable" in verdict("")


class FakeRun:
    """Stands in for subprocess.run: records each call and writes the junit report it is given."""

    def __init__(self, reports, returncode=0):
        self.reports = list(reports)
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, cwd, env, **_):
        self.calls.append({"argv": argv, "cwd": cwd, "env": env})
        junit = next(a.split("=", 1)[1] for a in argv if a.startswith("--junitxml="))
        Path(junit).write_text(self.reports.pop(0))

        class Done:
            returncode = self.returncode
            stdout = ""

        return Done()


def _main(lines, run, checkout):
    return main(lines, run=run, checkout=lambda: checkout)


class TestMain:
    def test_each_pushed_commit_is_checked_in_the_main_checkout(self, tmp_path):
        run = FakeRun([_junit(), _junit()])
        lines = [f"refs/heads/main {A} refs/heads/main {ZERO}", f"refs/tags/v1 {B} refs/tags/v1 {ZERO}"]
        assert _main(lines, run, tmp_path) == 0
        assert [c["env"]["OPEN_MARIN_TRIPWIRE_REV"] for c in run.calls] == [A, B]
        assert {c["cwd"] for c in run.calls} == {tmp_path}
        argv = run.calls[0]["argv"]
        assert argv[0] == str(tmp_path / ".venv" / "bin" / "python")
        assert "tests/scripts/test_extract_form700_interiors.py" in argv
        assert argv[argv.index("-k") + 1] == "committed_diff"

    def test_a_skipped_tripwire_blocks_the_push(self, tmp_path, capsys):
        run = FakeRun([_junit(skipped=1)])
        assert _main([f"refs/heads/main {A} refs/heads/main {ZERO}"], run, tmp_path) == 1
        assert "skipped" in capsys.readouterr().err

    def test_a_nonzero_pytest_exit_blocks_even_with_a_clean_report(self, tmp_path):
        run = FakeRun([_junit()], returncode=1)
        assert _main([f"refs/heads/main {A} refs/heads/main {ZERO}"], run, tmp_path) == 1

    def test_the_first_refusal_stops_the_gate(self, tmp_path):
        run = FakeRun([_junit(failures=1), _junit()])
        lines = [f"refs/heads/main {A} refs/heads/main {ZERO}", f"refs/heads/x {B} refs/heads/x {ZERO}"]
        assert _main(lines, run, tmp_path) == 1
        assert len(run.calls) == 1

    def test_nothing_to_push_runs_nothing(self, tmp_path):
        run = FakeRun([])
        assert _main([], run, tmp_path) == 0
        assert run.calls == []


def test_the_hook_is_executable_and_hands_stdin_to_the_gate():
    hook = REPO_ROOT / "ops" / "git-hooks" / "pre-push"
    assert hook.stat().st_mode & stat.S_IXUSR
    assert "pre_push_tripwire.py" in hook.read_text()


def test_the_tripwire_diffs_the_revision_it_is_given(monkeypatch):
    import test_extract_form700_interiors as tripwire

    monkeypatch.setenv("OPEN_MARIN_TRIPWIRE_REV", A)
    assert tripwire._tripwire_rev() == A
    monkeypatch.delenv("OPEN_MARIN_TRIPWIRE_REV")
    assert tripwire._tripwire_rev() == "HEAD"
