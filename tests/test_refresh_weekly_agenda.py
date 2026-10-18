"""The weekly run's agenda-items stage (scripts/refresh_weekly.py): off until activation; when on, it runs after
every meeting load succeeded, bracketed by two full exports whose delta must be exactly its committed items. A
stage that fails never stops the run (the meetings are loaded) but the run is not clean. Same fake world as
tests/test_refresh_weekly.py: nothing touches the network, a graph or the real data/."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_refresh_weekly import (  # noqa: F401  (pytest fixtures, used by name)
    ENV, RUN, FakeWorld, _state, alarm_pings, ctx, pings, root, rw)

AGENDA_STEPS = ["export_live_graph.py", "agenda_items.py", "export_live_graph.py", "agenda_delta.py"]


class AgendaWorld(FakeWorld):
    def __init__(self, root: Path):
        super().__init__(root)
        self.stage_report: dict | None = {"run_id": RUN, "sources": {
            "lakeport-town-council": {"eligible": True, "reason": "eligible", "loaded": {"m1": 3}, "held":
                                      {"m2": "agenda_date_mismatch"}, "revised": {}, "selected": 2, "backlog": 9,
                                      "backlog_after": 7, "held_waiting": 0, "unverifiable_legacy": 4,
                                      "excluded": {}, "cap": 20},
            "lakeport-planning": {"eligible": False, "reason": "parser not qualified"}},
            "load": {"created": {"meetings": {"m1": ["i1", "i2", "i3"]}}, "holds": [], "already_loaded": [],
                     "outcome": "loaded"}}
        self.delta = {"ok": True, "problems": [], "problem_count": 0, "added_nodes": 3, "added_edges": 6}

    def __call__(self, cmd, cwd, env, timeout):
        script = Path(cmd[1]).name if len(cmd) > 1 and cmd[0] != "git" else ""
        if script == "agenda_items.py" and not self.exit_codes.get(script) and self.stage_report is not None:
            out = self.root / "data/ingest-runs" / cmd[cmd.index("--run-id") + 1] / "agenda-items" / "report.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(self.stage_report))
        if script == "agenda_delta.py" and not self.exit_codes.get(script):
            Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps(self.delta))
        return super().__call__(cmd, cwd, env, timeout)


@pytest.fixture
def world(root: Path) -> AgendaWorld:
    return AgendaWorld(root)


def _load(ctx, enabled=True):
    ctx.agenda_items = enabled
    assert rw.main(["stage"], ctx) == 0
    rw.main(["load", RUN], ctx)
    return _state(ctx.root)


def test_the_stage_is_off_until_activation(root, ctx, world):
    assert rw.Context().agenda_items is False and rw.AGENDA_ITEMS_ENABLED is False
    state = _load(ctx, enabled=False)
    assert "agenda_items.py" not in world.scripts() and "agenda_items" not in state


def test_the_stage_runs_after_the_loads_bracketed_by_two_exports_then_reconciliation(root, ctx, world):
    state = _load(ctx)
    scripts = world.scripts()
    first = scripts.index("agenda_items.py") - 1
    assert scripts[first:first + 4] == AGENDA_STEPS
    assert scripts.index("normalize_meetings.py") < first < scripts.index("refresh_reconciliation.sh") \
        if "refresh_reconciliation.sh" in scripts else True
    pre, post = (Path(c[c.index("--out-dir") + 1]) for c in world.calls
                 if len(c) > 1 and Path(c[1]).name == "export_live_graph.py" and "agenda-items" in " ".join(c))
    assert pre.name == "pre" and post.name == "post"
    assert state["status"] == "awaiting_publish_approval"
    agenda = state["agenda_items"]
    assert agenda["ok"] is True and agenda["delta"]["ok"] is True
    assert agenda["sources"]["lakeport-town-council"]["loaded_meetings"] == 1
    assert agenda["sources"]["lakeport-town-council"]["loaded_items"] == 3


def test_the_digest_reports_each_source(root, ctx, world):
    _load(ctx)
    digest = (rw.run_dir(root, RUN) / "digest.md").read_text()
    section = digest.split("## Agenda items", 1)[1]
    assert "lakeport-town-council" in section and "agenda_date_mismatch" in section
    assert "lakeport-planning" in section and "parser not qualified" in section


def test_a_failing_stage_never_stops_the_run_but_it_is_not_clean(root, ctx, world):
    world.exit_codes["agenda_items.py"] = 1
    state = _load(ctx)
    assert state["status"] == "awaiting_publish_approval"
    assert state["agenda_items"]["ok"] is False and "agenda-items" in state["agenda_items"]["error"]
    assert "agenda_delta.py" not in world.scripts()


def test_a_stage_report_for_another_run_is_a_failure(root, ctx, world):
    world.stage_report["run_id"] = "2026-09-21T050000Z"
    state = _load(ctx)
    assert state["agenda_items"]["ok"] is False and "report" in state["agenda_items"]["error"]


def test_a_delta_with_problems_is_a_failure(root, ctx, world):
    world.delta = {"ok": False, "problems": ["changed node meeting-x"], "problem_count": 1, "added_nodes": 3,
                   "added_edges": 6}
    state = _load(ctx)
    assert state["agenda_items"]["ok"] is False and "changed node meeting-x" in state["agenda_items"]["error"]


def test_a_weekly_run_with_a_failed_agenda_stage_pings_fail(root, ctx, world, pings):
    ctx.agenda_items = True
    ctx.env["OPEN_MARIN_HEARTBEAT_URL"] = "https://heartbeat.example/weekly-check"
    world.exit_codes["agenda_items.py"] = 1
    assert rw.main(["weekly"], ctx) == 1
    assert pings and pings[-1][0].endswith("/fail") and "agenda items" in pings[-1][1]


# --- review (c1) ------------------------------------------------------------------------------------------


class Killed(BaseException):
    """The process dies mid-step (not an Exception: nothing in the runner may catch it)."""


def test_a_stage_killed_midway_blocks_later_runs_and_resumes_with_load(root, ctx, world):
    ctx.agenda_items = True
    assert rw.main(["stage"], ctx) == 0
    real = AgendaWorld.__call__

    def die(self, cmd, cwd, env, timeout):
        if len(cmd) > 1 and Path(cmd[1]).name == "agenda_items.py":
            raise Killed()
        return real(self, cmd, cwd, env, timeout)

    AgendaWorld.__call__ = die
    try:
        with pytest.raises(Killed):
            rw.load(ctx, RUN)
    finally:
        AgendaWorld.__call__ = real
    state = _state(root)
    assert state["status"] == "loaded" and state["agenda_items"]["status"] == "running"
    assert rw._unresolved_load(root) == RUN  # a weekly run would refuse to start over it
    loads_before = world.scripts().count("normalize_meetings.py")
    rw.main(["load", RUN], ctx)  # resumes the stage only, then export + bake
    state = _state(root)
    assert world.scripts().count("normalize_meetings.py") == loads_before
    assert state["status"] == "awaiting_publish_approval" and state["agenda_items"]["ok"] is True
    assert rw._unresolved_load(root) is None


def test_a_pre_export_that_did_not_finish_is_taken_again(root, ctx, world):
    ctx.agenda_items = True
    assert rw.main(["stage"], ctx) == 0
    pre = rw.run_dir(root, RUN) / "agenda-items" / "pre"
    pre.mkdir(parents=True)
    (pre / "nodes.jsonl").write_text('{"id": "half"}\n')  # an earlier attempt died after the nodes
    rw.main(["load", RUN], ctx)
    exports = [c for c in world.calls if len(c) > 1 and Path(c[1]).name == "export_live_graph.py"
               and str(pre) in c]
    assert exports and (pre / "complete.json").is_file()


def test_the_digest_shows_legacy_and_waiting_holds(root, ctx, world):
    world.stage_report["sources"]["lakeport-town-council"]["held_waiting"] = 2
    _load(ctx)
    digest = (rw.run_dir(root, RUN) / "digest.md").read_text().split("## Agenda items", 1)[1]
    assert "| 4 |" in digest and "2 waiting to retry" in digest
