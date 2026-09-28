"""Tests for scripts/refresh_weekly.py — the I5b weekly runner.

Every external step goes through the injected runner, so these tests fake the
whole world (ingesters, Neo4j loads, reconciliation, export, bake) in tmp_path.
Nothing here touches the network, Neo4j, or the real data/ tree.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import refresh_weekly as rw  # noqa: E402

RUN = "2026-09-28T050000Z"
ENV = {"NEO4J_URI": "bolt://localhost:7688", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "pw"}
STAGED_SCRIPTS = {"permits": "ingest_socrata_permits.py", "form700": "ingest_form700.py",
                  "courtlistener": "ingest_courtlistener_cases.py"}
NORMALIZED = {"permits": "marin-county-permits", "form700": "form700", "courtlistener": "courtlistener-cases"}


def _jsonl(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"id": f"{path.parent.name}-{i}"}) + "\n" for i in range(n)))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeWorld:
    """Stands in for every subprocess the runner launches, by script name."""

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[list[str]] = []
        self.meetings = {"a": (30, []), "b": (25, [])}  # sid -> (rows, floor reasons); missing = adapter crash
        self.staged_rows = {script: 10 for script in STAGED_SCRIPTS.values()}
        self.exit_codes: dict[str, int] = {}
        self.within_budget = True

    def __call__(self, cmd, cwd, env):
        assert cwd == self.root and env["NEO4J_URI"] == ENV["NEO4J_URI"]
        self.calls.append(list(cmd))
        script = Path(cmd[1]).name
        if self.exit_codes.get(script):
            return rw.Result(self.exit_codes[script], f"{script}: boom\nlast line of trouble\n")
        if script == "ingest.py":
            ledger = self.root / "data/ingest-runs/ledger.jsonl"
            with ledger.open("a") as fh:
                for sid, (rows, reasons) in self.meetings.items():
                    fh.write(json.dumps({"source_id": sid, "run_at": "now", "rows": rows, "newest": None,
                                         "ok": not reasons, "reasons": reasons}) + "\n")
                    if not reasons:
                        capture = self.root / f"data/extracted/{sid}/2026-09-28.json"
                        capture.parent.mkdir(parents=True, exist_ok=True)
                        capture.write_text(json.dumps({"meeting_count": rows}))
        elif script in self.staged_rows and "--output-dir" in cmd:
            out = Path(cmd[cmd.index("--output-dir") + 1])
            _jsonl(out / "nodes.jsonl", self.staged_rows[script])
            _jsonl(out / "edges.jsonl", 1)
        elif script == "bake_public_substrate.py":
            sqlite = Path(cmd[cmd.index("--sqlite") + 1])
            sqlite.parent.mkdir(parents=True, exist_ok=True)
            sqlite.write_bytes(b"SQLite format 3\x00 new bake")
            (sqlite.parent / "status_manifest.json").write_text('{"node_count": 2}')
            (sqlite.parent / "catalog.json").write_text('{"counts": {}}')
            Path(cmd[cmd.index("--report") + 1]).write_text(json.dumps({
                "totals": {"nodes": 2, "edges": 1},
                "sqlite": {"size_bytes": 26, "budget_bytes": 100, "within_budget": self.within_budget}}))
        return rw.Result(0, "ok\n")

    def scripts(self) -> list[str]:
        return [Path(cmd[1]).name for cmd in self.calls]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/granicus-sources.yaml").write_text(
        "sources:\n"
        "  - {id: a, adapter: granicus, url: u, schedule: weekly}\n"
        "  - {id: b, adapter: granicus, url: u, schedule: weekly}\n"
        "  - {id: c, adapter: granicus, url: u, schedule: manual}\n"
    )
    for name in NORMALIZED.values():
        _jsonl(tmp_path / f"data/normalized/{name}/nodes.jsonl", 10)
    ledger = tmp_path / "data/ingest-runs/ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("".join(json.dumps({"source_id": s, "run_at": "seed:x", "rows": r, "newest": None,
                                          "ok": True, "reasons": []}) + "\n" for s, r in (("a", 28), ("b", 25))))
    return tmp_path


@pytest.fixture
def world(root: Path) -> FakeWorld:
    return FakeWorld(root)


@pytest.fixture
def ctx(root: Path, world: FakeWorld) -> rw.Context:
    return rw.Context(root=root, runner=world, env=dict(ENV), python="py",
                      now=lambda: datetime(2026, 9, 28, 5, 0, 0, tzinfo=timezone.utc),
                      free_bytes=lambda path: 50 * 1024**3, meeting_registries=("granicus",))


def _state(root: Path) -> dict:
    return json.loads((root / f"data/ingest-runs/{RUN}/state.json").read_text())


def _staged(ctx: rw.Context) -> None:
    assert rw.main(["stage"], ctx) == 0


def _loaded(ctx: rw.Context) -> None:
    _staged(ctx)
    assert rw.main(["load", RUN], ctx) == 0


# --- state machine -----------------------------------------------------------


def test_status_machine_allows_the_documented_path_only():
    path = [None, "staging", "staged", "awaiting_load_approval", "loaded", "awaiting_publish_approval", "published"]
    for current, nxt in zip(path, path[1:]):
        rw.check_transition(current, nxt)
    for current in path[1:-1]:
        rw.check_transition(current, "failed")
    with pytest.raises(rw.Refused):
        rw.check_transition("awaiting_load_approval", "published")
    with pytest.raises(rw.Refused):
        rw.check_transition("failed", "staged")
    with pytest.raises(rw.Refused):
        rw.check_transition("published", "failed")


# --- stage -------------------------------------------------------------------


def test_stage_captures_meetings_and_stages_refetchers_then_awaits_load_approval(ctx, world, root):
    assert rw.main(["stage"], ctx) == 0

    state = _state(root)
    assert state["status"] == "awaiting_load_approval"
    assert [h["status"] for h in state["history"]] == ["staging", "staged", "awaiting_load_approval"]
    assert world.calls[0] == ["py", "scripts/ingest.py", "--all", "--registry", "registry/granicus-sources.yaml"]
    run_dir = root / f"data/ingest-runs/{RUN}"
    for name, script in STAGED_SCRIPTS.items():
        assert ["py", f"scripts/{script}", *rw.STAGED_SOURCES[name].args,
                "--output-dir", str(run_dir / "staged" / name)] in world.calls
    assert not any("--load" in cmd or "--load-from" in cmd for cmd in world.calls)
    assert {sid: s["ok"] for sid, s in state["sources"].items()} == {
        "a": True, "b": True, "permits": True, "form700": True, "courtlistener": True}
    assert state["sources"]["a"]["rows"] == 30 and state["sources"]["a"]["last_good_rows"] == 28


def test_stage_fingerprints_the_bytes_it_asks_a_human_to_approve(ctx, root):
    _staged(ctx)

    sources = _state(root)["sources"]
    capture = root / "data/extracted/a/2026-09-28.json"
    assert sources["a"]["capture"] == {"path": "data/extracted/a/2026-09-28.json", "sha256": _sha(capture)}
    staged = root / f"data/ingest-runs/{RUN}/staged/form700"
    assert sources["form700"]["files"] == {name: _sha(staged / name) for name in ("nodes.jsonl", "edges.jsonl")}


def test_a_failed_source_exits_nonzero_but_passing_sources_stay_approvable(ctx, world, root):
    world.exit_codes["ingest_socrata_permits.py"] = 1

    assert rw.main(["stage"], ctx) == 1

    state = _state(root)
    assert state["status"] == "awaiting_load_approval"
    assert state["sources"]["permits"]["ok"] is False
    assert "exited 1" in state["sources"]["permits"]["reasons"][0]
    assert "last line of trouble" in state["sources"]["permits"]["reasons"][0]
    assert state["sources"]["form700"]["ok"] is True
    assert (root / f"data/ingest-runs/{RUN}/logs/stage-permits.log").read_text().startswith("$ py scripts/")


def test_staged_rows_are_floored_against_current_normalized_counts(ctx, world, root):
    world.staged_rows["ingest_form700.py"] = 5  # 50% of the 10 rows in data/normalized/form700

    assert rw.main(["stage"], ctx) == 1

    form700 = _state(root)["sources"]["form700"]
    assert form700["ok"] is False and form700["rows"] == 5 and form700["last_good_rows"] == 10
    assert "below 90% of the last good run (10)" in form700["reasons"][0]


def test_meeting_verdicts_come_from_this_runs_ledger_entries(ctx, world, root):
    world.meetings = {"b": (3, ["pull returned 3 rows, below 90% of the last good run (25)"])}  # a crashed

    assert rw.main(["stage"], ctx) == 1

    sources = _state(root)["sources"]
    assert sources["b"] == {"kind": "meetings", "registry": "granicus", "ok": False, "rows": 3,
                            "last_good_rows": 25, "reasons": world.meetings["b"][1]}
    assert sources["a"]["ok"] is False
    assert "no verdict recorded" in sources["a"]["reasons"][0]
    assert "c" not in sources  # manual sources never run on the schedule


@pytest.mark.parametrize("env_patch,free,reason", [
    ({"NEO4J_URI": "bolt://localhost:7687"}, 50, "family-tree"),
    ({"NEO4J_URI": ""}, 50, "NEO4J_URI is not set"),
    ({}, 1, "free disk"),
])
def test_preflight_failure_fails_the_run_before_any_step(ctx, world, root, env_patch, free, reason):
    ctx.env.update(env_patch)
    ctx.free_bytes = lambda path: free * 1024**3

    assert rw.main(["stage"], ctx) == 1

    state = _state(root)
    assert state["status"] == "failed"
    assert reason in " ".join(state["preflight"]["reasons"])
    assert world.calls == []


def test_stage_records_the_run_as_staging_before_its_first_step(ctx, world, root):
    seen = []
    ctx.runner = lambda cmd, cwd, env: (seen.append(_state(root)["status"]), world(cmd, cwd, env))[1]

    _staged(ctx)

    assert seen[0] == "staging"


def test_a_crash_inside_stage_fails_the_run_visibly_and_status_says_why(ctx, root, capsys):
    def crash(cmd, cwd, env):
        raise OSError("network stack gone")
    ctx.runner = crash

    assert rw.main(["stage"], ctx) == 1

    state = _state(root)
    assert state["status"] == "failed"
    assert [h["status"] for h in state["history"]] == ["staging", "failed"]
    assert "stage crashed: OSError: network stack gone" in state["error"]
    assert "stage crashed" in _digest(root)
    capsys.readouterr()
    assert rw.main(["status"], ctx) == 0
    out = capsys.readouterr().out
    assert f"run {RUN}: failed" in out and "error: stage crashed: OSError: network stack gone" in out


def test_a_run_where_every_source_failed_is_failed(ctx, world, root):
    world.meetings = {}
    world.exit_codes.update({script: 2 for script in STAGED_SCRIPTS.values()})

    assert rw.main(["stage"], ctx) == 1
    assert _state(root)["status"] == "failed"


# --- load --------------------------------------------------------------------


@pytest.mark.parametrize("status", ["staged", "loaded", "awaiting_publish_approval", "published", "failed"])
def test_load_refuses_a_run_in_the_wrong_state(ctx, world, root, status):
    _staged(ctx)
    state = _state(root)
    state["status"] = status
    rw.write_state(root, RUN, state)
    world.calls.clear()

    assert rw.main(["load", RUN], ctx) == 2

    assert _state(root)["status"] == status
    assert world.calls == []


def test_load_refuses_without_neo4j_credentials_and_leaves_the_run_approvable(ctx, world, root):
    _staged(ctx)
    world.calls.clear()
    del ctx.env["NEO4J_PASSWORD"]

    assert rw.main(["load", RUN], ctx) == 2
    assert _state(root)["status"] == "awaiting_load_approval"
    assert world.calls == []


def test_load_loads_only_accepted_sources_from_the_approved_bytes(ctx, world, root):
    world.exit_codes["ingest_socrata_permits.py"] = 1
    world.meetings["b"] = (3, ["too few"])
    assert rw.main(["stage"], ctx) == 1
    world.calls.clear()
    world.exit_codes.clear()
    run_dir = root / f"data/ingest-runs/{RUN}"

    assert rw.main(["load", RUN], ctx) == 0

    staging = root / "data/exports/staging"
    assert world.calls == [
        ["py", "scripts/normalize_meetings.py", "--source", "a", "--load"],
        ["py", "scripts/ingest_form700.py", "--load-from", str(run_dir / "staged/form700")],
        ["py", "scripts/ingest_courtlistener_cases.py", "--load-from", str(run_dir / "staged/courtlistener")],
        ["bash", "scripts/refresh_reconciliation.sh"],
        ["py", "scripts/export_live_graph.py"],
        ["py", "scripts/bake_public_substrate.py", "--source", "live-export",
         "--sqlite", str(staging / "public-substrate.sqlite"),
         "--report", str(staging / "substrate-bake-report.json")],
    ]
    # Passing staged dirs are promoted into data/normalized; the failed one is untouched.
    assert _sha(root / "data/normalized/form700/nodes.jsonl") == _sha(run_dir / "staged/form700/nodes.jsonl")
    assert (root / "data/normalized/marin-county-permits/nodes.jsonl").read_text().count("\n") == 10
    state = _state(root)
    assert state["status"] == "awaiting_publish_approval"
    assert [h["status"] for h in state["history"]][-2:] == ["loaded", "awaiting_publish_approval"]
    assert state["bake"]["sha256"] == {name: _sha(staging / name) for name in rw.PUBLISHED_ARTIFACTS}
    assert state["bake"]["sqlite"]["within_budget"] is True
    assert not (root / "data/exports/public-substrate.sqlite").exists()  # the bake never touches the live artifact


@pytest.mark.parametrize("tamper", ["staged", "capture"])
def test_load_fails_the_run_if_approved_bytes_changed(ctx, world, root, tamper):
    _staged(ctx)
    world.calls.clear()
    target = (root / f"data/ingest-runs/{RUN}/staged/form700/nodes.jsonl" if tamper == "staged"
              else root / "data/extracted/a/2026-09-28.json")
    target.write_text(target.read_text() + "{}\n")

    assert rw.main(["load", RUN], ctx) == 1

    state = _state(root)
    assert state["status"] == "failed"
    assert "changed since approval" in state["error"]
    assert world.calls == []


def test_a_failed_load_step_fails_the_run_and_stops(ctx, world, root):
    _staged(ctx)
    world.calls.clear()
    world.exit_codes["export_live_graph.py"] = 1

    assert rw.main(["load", RUN], ctx) == 1

    state = _state(root)
    assert state["status"] == "failed"
    assert "export" in state["error"]
    assert "bake_public_substrate.py" not in world.scripts()


def test_an_over_budget_bake_fails_the_run(ctx, world, root):
    _staged(ctx)
    world.within_budget = False

    assert rw.main(["load", RUN], ctx) == 1
    assert "budget" in _state(root)["error"]


# --- publish -----------------------------------------------------------------


@pytest.mark.parametrize("status", ["awaiting_load_approval", "loaded", "published", "failed"])
def test_publish_refuses_a_run_in_the_wrong_state(ctx, root, status):
    _loaded(ctx)
    state = _state(root)
    state["status"] = status
    rw.write_state(root, RUN, state)

    assert rw.main(["publish", RUN], ctx) == 2
    assert _state(root)["status"] == status


def test_publish_swaps_the_staged_artifacts_into_exports_and_never_deploys(ctx, world, root):
    _loaded(ctx)
    exports = root / "data/exports"
    for name in rw.PUBLISHED_ARTIFACTS:
        (exports / name).write_text(f"old {name}")
    world.calls.clear()

    assert rw.main(["publish", RUN], ctx) == 0

    assert world.calls == []
    for name in rw.PUBLISHED_ARTIFACTS:
        assert not (exports / "staging" / name).exists()
        assert (root / f"data/ingest-runs/{RUN}/previous/{name}").read_text() == f"old {name}"
    assert (exports / "public-substrate.sqlite").read_bytes() == b"SQLite format 3\x00 new bake"
    state = _state(root)
    assert state["status"] == "published"
    assert state["published"]["sqlite_sha256"] == _sha(exports / "public-substrate.sqlite")


@pytest.mark.parametrize("tamper", ["modify", "remove"])
def test_publish_refuses_bytes_other_than_the_approved_bake(ctx, root, tamper):
    _loaded(ctx)
    staged = root / "data/exports/staging"
    if tamper == "modify":
        (staged / "public-substrate.sqlite").write_bytes(b"something else")
    else:
        (staged / "catalog.json").unlink()

    assert rw.main(["publish", RUN], ctx) == 1

    assert _state(root)["status"] == "failed"
    assert not (root / "data/exports/public-substrate.sqlite").exists()


def test_subprocess_runner_captures_exit_code_and_output(tmp_path):
    result = rw.subprocess_runner([sys.executable, "-c", "import sys; print('out'); sys.exit(3)"],
                                  tmp_path, {"PATH": ""})
    assert result == rw.Result(3, "out\n")


# --- digest and status -------------------------------------------------------


def _digest(root: Path, run_id: str = RUN) -> str:
    return (root / f"data/ingest-runs/{run_id}/digest.md").read_text()


def test_stage_digest_shows_verdicts_rows_versus_last_good_and_failure_reasons(ctx, world, root):
    world.exit_codes["ingest_socrata_permits.py"] = 1
    world.staged_rows["ingest_form700.py"] = 5

    assert rw.main(["stage"], ctx) == 1

    digest = _digest(root)
    assert f"# Open Marin weekly refresh — {RUN}" in digest
    assert "awaiting_load_approval" in digest and "3 of 5 sources passed" in digest
    assert "| a | meetings (granicus) | ok | 30 | 28 | +2 |" in digest
    assert "| form700 | staged | FAILED | 5 | 10 | -5 |" in digest
    assert "| permits | staged | FAILED | – | 10 | – |" in digest
    assert "- **permits**: exited 1: last line of trouble (logs/stage-permits.log)" in digest
    assert "- **form700**: pull returned 5 rows, below 90% of the last good run (10)" in digest
    assert f"refresh_weekly.py load {RUN}" in digest


def test_digest_follows_the_run_through_load_and_publish(ctx, root):
    _loaded(ctx)
    digest = _digest(root)
    assert "awaiting_publish_approval" in digest
    assert "2 nodes · 1 edges · sqlite 26 bytes (budget 100: within budget)" in digest
    assert f"refresh_weekly.py publish {RUN}" in digest and "does not deploy" in digest

    assert rw.main(["publish", RUN], ctx) == 0
    assert _state(root)["published"]["sqlite_sha256"] in _digest(root)


def test_a_failed_runs_digest_says_why(ctx, root):
    ctx.env["NEO4J_URI"] = "bolt://localhost:7687"

    assert rw.main(["stage"], ctx) == 1

    digest = _digest(root)
    assert "preflight failed; nothing was fetched" in digest
    assert "family-tree" in digest


def test_status_prints_the_latest_runs_state_and_digest_path(ctx, root, capsys):
    older = root / "data/ingest-runs/2026-09-21T050000Z"
    older.mkdir(parents=True)
    rw.write_state(root, older.name, {"run_id": older.name, "status": "published", "history": [], "sources": {}})
    _staged(ctx)
    capsys.readouterr()

    assert rw.main(["status"], ctx) == 0
    out = capsys.readouterr().out
    assert f"run {RUN}: awaiting_load_approval" in out
    assert f"digest: {root / 'data/ingest-runs' / RUN / 'digest.md'}" in out

    assert rw.main(["status", older.name], ctx) == 0
    assert "run 2026-09-21T050000Z: published" in capsys.readouterr().out


def test_status_with_no_runs_or_an_unknown_run(ctx, capsys):
    assert rw.main(["status"], ctx) == 1
    assert "no runs yet" in capsys.readouterr().out
    assert rw.main(["status", "nope"], ctx) == 2


# --- LaunchAgent template ----------------------------------------------------


def test_launchagent_template_runs_only_stage_on_monday_at_five_with_no_secrets():
    import plistlib

    path = Path(__file__).resolve().parent.parent / "ops/launchd/cc.eastpeak.openmarin-refresh-weekly.plist"
    plist = plistlib.loads(path.read_bytes())

    assert plist["Label"] == "cc.eastpeak.openmarin-refresh-weekly"
    assert plist["ProgramArguments"][1:] == ["scripts/refresh_weekly.py", "stage"]
    assert plist["StartCalendarInterval"] == {"Weekday": 1, "Hour": 5, "Minute": 0}
    assert set(plist["EnvironmentVariables"]) == {"NEO4J_URI"}  # stage needs only the guard, never credentials
    assert "bolt://" not in plist["EnvironmentVariables"]["NEO4J_URI"]  # a hint by name; the operator fills it in
    assert "PASSWORD" not in path.read_text()


# --- the run lock (review P2-9) ----------------------------------------------


@pytest.mark.parametrize("argv", [["stage"], ["load", RUN], ["publish", RUN]])
def test_every_writing_subcommand_is_refused_while_another_run_holds_the_lock(ctx, world, root, argv, capsys):
    import run_lock

    with run_lock.run_lock(root):
        assert rw.main(argv, ctx) == 2

    assert "another ingestion run" in capsys.readouterr().err
    assert world.calls == [] and not (root / f"data/ingest-runs/{RUN}").exists()


def test_steps_tell_their_children_that_this_process_holds_the_lock(ctx, world, root):
    import os

    import run_lock

    seen = []
    ctx.runner = lambda cmd, cwd, env: (seen.append(env.get(run_lock.OWNER_ENV)), world(cmd, cwd, env))[1]
    _staged(ctx)

    assert seen and set(seen) == {str(os.getpid())}
