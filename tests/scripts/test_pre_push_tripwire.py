"""Tests for scripts/pre_push_tripwire.py — the pre-push gate around the committed-text tripwire.

The tripwire skips wherever its local-only strings file is absent (every worktree), so the gate
runs it in the main checkout once for every commit the push makes newly reachable, and accepts
only a report of the one tripwire testcase, executed and passing, that names the commit it scanned.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from pre_push_tripwire import TESTCASE, main, new_commits, pushed_shas, verdict  # noqa: E402

ZERO = "0" * 40
A = "a" * 40
B = "b" * 40
C = "c" * 40


def _case(rev=A, name=TESTCASE, outcome=""):
    return (
        f'<testcase classname="tests.scripts.test_extract_form700_interiors.TestCommittedTextScan" name="{name}">'
        f'<properties><property name="tripwire_rev" value="{rev}"/></properties>{outcome}</testcase>'
    )


def _junit(*cases):
    cases = cases or (_case(),)
    return '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">' + "".join(cases) + "</testsuite></testsuites>"


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


class TestNewCommits:
    def test_every_commit_not_on_a_remote_oldest_first(self):
        calls = []

        def git(*args):
            calls.append(args)
            return f"{A}\n{B}\n"

        assert new_commits([B, C], git) == [A, B]
        assert calls == [("rev-list", "--reverse", B, C, "--not", "--remotes")]

    def test_no_tips_asks_git_nothing(self):
        assert new_commits([], lambda *a: pytest.fail("git called")) == []


class TestVerdict:
    def test_the_tripwire_executed_and_passing_on_this_commit_is_accepted(self):
        assert verdict(_junit(), A) is None

    @pytest.mark.parametrize(
        "report, reason",
        [
            (_junit(_case(outcome='<skipped message="absent"/>')), "skipped"),
            (_junit(_case(outcome='<failure message="leak"/>')), "failure"),
            (_junit(_case(outcome='<error message="boom"/>')), "error"),
            (_junit(_case(rev=B)), "scanned " + B[:12]),
            (_junit(_case(name="test_something_else")), "expected exactly 1"),
            (_junit(_case(), _case()), "expected exactly 1"),
            ('<testsuites><testsuite name="pytest" tests="1"/></testsuites>', "expected exactly 1"),
            ("", "unreadable"),
        ],
    )
    def test_anything_else_is_refused_with_its_reason(self, report, reason):
        assert reason in verdict(report, A)

    def test_a_case_without_the_revision_property_is_refused(self):
        bare = f'<testsuites><testsuite name="pytest"><testcase name="{TESTCASE}"/></testsuite></testsuites>'
        assert "scanned none" in verdict(bare, A)


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


def _main(lines, run, checkout, commits=None):
    return main(lines, run=run, checkout=lambda: checkout,
                commits=lambda shas: list(commits if commits is not None else shas))


class TestMain:
    def test_each_pushed_commit_is_checked_in_the_main_checkout(self, tmp_path):
        run = FakeRun([_junit(_case(A)), _junit(_case(C)), _junit(_case(B))])
        lines = [f"refs/heads/main {B} refs/heads/main {ZERO}"]
        assert _main(lines, run, tmp_path, commits=[A, C, B]) == 0
        assert [c["env"]["OPEN_MARIN_TRIPWIRE_REV"] for c in run.calls] == [A, C, B]
        assert {c["cwd"] for c in run.calls} == {tmp_path}
        argv = run.calls[0]["argv"]
        assert argv[0] == str(tmp_path / ".venv" / "bin" / "python")
        assert "tests/scripts/test_extract_form700_interiors.py" in argv
        assert argv[argv.index("-k") + 1] == "committed_diff"
        assert "junit_family=xunit1" in argv

    def test_git_hook_variables_do_not_reach_the_scan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_DIR", "/elsewhere/.git")
        run = FakeRun([_junit()])
        assert _main([f"refs/heads/main {A} refs/heads/main {ZERO}"], run, tmp_path) == 0
        assert not any(k.startswith("GIT_") for k in run.calls[0]["env"])

    def test_a_skipped_tripwire_blocks_the_push(self, tmp_path, capsys):
        run = FakeRun([_junit(_case(outcome='<skipped message="absent"/>'))])
        assert _main([f"refs/heads/main {A} refs/heads/main {ZERO}"], run, tmp_path) == 1
        assert "skipped" in capsys.readouterr().err

    def test_a_nonzero_pytest_exit_blocks_even_with_a_clean_report(self, tmp_path):
        run = FakeRun([_junit()], returncode=1)
        assert _main([f"refs/heads/main {A} refs/heads/main {ZERO}"], run, tmp_path) == 1

    def test_the_first_refusal_stops_the_gate(self, tmp_path):
        run = FakeRun([_junit(_case(A, outcome='<failure message="leak"/>')), _junit(_case(B))])
        lines = [f"refs/heads/main {A} refs/heads/main {ZERO}", f"refs/heads/x {B} refs/heads/x {ZERO}"]
        assert _main(lines, run, tmp_path) == 1
        assert len(run.calls) == 1

    def test_nothing_to_push_runs_nothing(self, tmp_path):
        run = FakeRun([])
        assert _main([], run, tmp_path) == 0
        assert run.calls == []

    def test_tips_already_on_a_remote_scan_nothing(self, tmp_path):
        run = FakeRun([])
        assert _main([f"refs/heads/main {A} refs/heads/main {A}"], run, tmp_path, commits=[]) == 0
        assert run.calls == []

    def test_a_commit_listing_failure_blocks_the_push(self, tmp_path, capsys):
        def boom(shas):
            raise RuntimeError("rev-list failed")

        assert main([f"refs/heads/main {A} refs/heads/main {ZERO}"], run=FakeRun([]),
                    checkout=lambda: tmp_path, commits=boom) == 1
        assert "rev-list failed" in capsys.readouterr().err


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
    assert "record_property" in tripwire.TestCommittedTextScan.__dict__[TESTCASE].__code__.co_varnames
