"""The weekly run and crosswalk-required sources (scripts/refresh_weekly.py).

A crosswalk-required source's ids come from a reviewed crosswalk (scripts/crosswalk.py). The stage pins
the crosswalk version each capture was made with, so the load can refuse a capture whose crosswalk
changed since. Same fake world as tests/test_refresh_weekly.py: nothing touches the network or the real data/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_refresh_weekly import (  # noqa: F401  (pytest fixtures, used by name)
    ENV, RUN, FakeWorld, _state, alarm_pings, ctx, pings, root, rw)

PINNED = "5" * 64


class CrosswalkWorld(FakeWorld):
    """FakeWorld whose ingest.py records a crosswalk version for source `a`, as ingest.py does."""

    def __call__(self, cmd, cwd, env, timeout):
        result = super().__call__(cmd, cwd, env, timeout)
        if Path(cmd[1]).name == "ingest.py":
            ledger = self.root / "data/ingest-runs/ledger.jsonl"
            lines = [json.loads(line) for line in ledger.read_text().splitlines()]
            for line in lines:
                if line["source_id"] == "a" and line["run_at"] == "now":
                    line["crosswalk_sha256"] = PINNED
            ledger.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return result


@pytest.fixture
def world(root: Path) -> CrosswalkWorld:
    return CrosswalkWorld(root)


def test_stage_pins_the_crosswalk_version_of_each_capture(ctx, root):
    assert rw.main(["stage"], ctx) == 0
    sources = _state(root)["sources"]
    assert sources["a"]["crosswalk_sha256"] == PINNED
    assert "crosswalk_sha256" not in sources["b"]


# --- load: a crosswalk source's outcome comes from its report ------------------------------------------


class ReportingWorld(CrosswalkWorld):
    """normalize_meetings.py for source `a` writes the load report the guarded path writes."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.report: dict | None = {"outcome": "loaded", "holds": []}
        self.report_overrides: dict = {}

    def __call__(self, cmd, cwd, env, timeout):
        if Path(cmd[1]).name == "normalize_meetings.py" and cmd[cmd.index("--source") + 1] == "a" \
                and self.report is not None:
            state = json.loads((self.root / f"data/ingest-runs/{RUN}/state.json").read_text())
            source = state["sources"]["a"]
            report = {"source_id": "a", "capture_sha256": source["capture"]["sha256"],
                      "crosswalk_sha256": source["crosswalk_sha256"], **self.report, **self.report_overrides}
            out = Path(cmd[cmd.index("--report") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report))
        return super().__call__(cmd, cwd, env, timeout)


@pytest.fixture
def reporting(root: Path, ctx) -> tuple[ReportingWorld, rw.Context]:
    import dataclasses
    world = ReportingWorld(root)
    return world, dataclasses.replace(ctx, runner=world)


def _load(ctx) -> dict:
    assert rw.main(["stage"], ctx) == 0
    rw.main(["load", RUN], ctx)
    return _state(ctx.root)


def test_meeting_loads_resolve_under_the_runs_root_and_report_per_attempt(reporting):
    world, ctx = reporting
    _load(ctx)
    loads = [c for c in world.calls if Path(c[1]).name == "normalize_meetings.py"]
    assert {c[c.index("--source") + 1] for c in loads} == {"a", "b"}
    for cmd in loads:
        assert cmd[cmd.index("--root") + 1] == str(ctx.root)
        report = Path(cmd[cmd.index("--report") + 1])
        assert report.parent == rw.run_dir(ctx.root, RUN) / "load-reports"


def test_load_pins_the_backup_it_took(reporting):
    world, ctx = reporting
    state = _load(ctx)
    backup = ctx.root / state["backup"]
    assert state["backup_sha256"] == {f: rw._sha256(backup / f) for f in ("nodes.jsonl", "edges.jsonl")}


def test_a_loaded_report_loads_the_source(reporting):
    world, ctx = reporting
    state = _load(ctx)
    assert state["status"] == "awaiting_publish_approval"
    assert {"a", "b"} <= set(state["loaded"])
    assert state["sources"]["a"]["load_report"]["outcome"] == "loaded"


def test_a_held_report_holds_only_that_source_and_the_run_goes_on(reporting):
    world, ctx = reporting
    world.report = {"outcome": "held", "holds": [{"reason": "artifact_url_changed", "meeting": "meeting-x"}]}
    state = _load(ctx)
    assert state["status"] == "awaiting_publish_approval"
    assert "a" not in state["loaded"] and "b" in state["loaded"]
    a = state["sources"]["a"]
    assert a["ok"] is False and a["held"] is True
    assert "artifact_url_changed" in a["reasons"][0]
    digest = (rw.run_dir(ctx.root, RUN) / "digest.md").read_text()
    assert "**a**" in digest and "artifact_url_changed" in digest


@pytest.mark.parametrize("bad", [None, {"source_id": "b"}, {"capture_sha256": "0" * 64},
                                 {"crosswalk_sha256": "0" * 64}, {"outcome": "skipped"}])
def test_a_crosswalk_load_without_a_fresh_valid_report_is_a_failed_load(reporting, bad):
    world, ctx = reporting
    if bad is None:
        world.report = None
    else:
        world.report_overrides = bad
    state = _load(ctx)
    assert state["status"] == "load_failed"
    assert "load report" in state["error"]


def test_a_source_made_crosswalk_required_after_staging_still_has_its_hold_read(reporting):
    world, ctx = reporting
    assert rw.main(["stage"], ctx) == 0
    registry = ctx.root / "registry/granicus-sources.yaml"
    registry.write_text(registry.read_text().replace(
        "{id: b, adapter: granicus, url: u, schedule: weekly}",
        "{id: b, adapter: granicus, url: u, schedule: weekly, identity: crosswalk-required, crosswalk: x.json}"))
    rw.main(["load", RUN], ctx)  # b has no pin and its load wrote no report
    state = _state(ctx.root)
    assert state["status"] == "load_failed" and "load-b" in state["error"]


def test_a_retry_never_reads_a_report_an_earlier_attempt_left(reporting):
    world, ctx = reporting
    assert rw.main(["stage"], ctx) == 0
    attempt = len(_state(ctx.root)["history"])
    stale = rw.run_dir(ctx.root, RUN) / "load-reports" / f"a.{attempt}.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")  # a killed attempt's leftover, at the path the next attempt would pick
    world.report = None  # this attempt exits 0 and writes nothing
    rw.main(["load", RUN], ctx)
    state = _state(ctx.root)
    assert state["status"] == "load_failed" and "load report" in state["error"]
    loads = [c for c in world.calls if Path(c[1]).name == "normalize_meetings.py"]
    assert all(Path(c[c.index("--report") + 1]) != stale for c in loads)
