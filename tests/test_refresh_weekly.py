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
    for current, nxt in (("awaiting_load_approval", "load_failed"), ("load_failed", "load_failed"),
                         ("load_failed", "loaded"), ("load_failed", "failed")):
        rw.check_transition(current, nxt)  # a load that stops partway stays retryable
    for current in path[1:-1]:
        rw.check_transition(current, "failed")
    with pytest.raises(rw.Refused):
        rw.check_transition("awaiting_load_approval", "published")
    with pytest.raises(rw.Refused):
        rw.check_transition("failed", "staged")
    rw.check_transition("published", "rolled_back")
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


@pytest.mark.parametrize("status", ["staging", "staged", "loaded", "awaiting_publish_approval", "published", "failed"])
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
    approved_a = json.loads((run_dir / "state.json").read_text())["sources"]["a"]["capture"]["path"]
    assert world.calls == [
        # Meetings load from exactly the approved capture, never "the latest".
        ["py", "scripts/normalize_meetings.py", "--source", "a", "--capture", str(root / approved_a), "--load"],
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


def _at(ctx: rw.Context, when: datetime) -> rw.Context:
    return rw.Context(root=ctx.root, runner=ctx.runner, env=ctx.env, python=ctx.python, now=lambda: when,
                      free_bytes=ctx.free_bytes, meeting_registries=ctx.meeting_registries)


def _permit_rows(root: Path) -> int:
    return (root / "data/normalized/marin-county-permits/nodes.jsonl").read_text().count("\n")


NEXT_WEEK = datetime(2026, 10, 5, 5, 0, 0, tzinfo=timezone.utc)
NEXT_RUN = "2026-10-05T050000Z"


def test_loading_a_run_older_than_one_already_loaded_is_refused(ctx, world, root):
    world.staged_rows = dict.fromkeys(world.staged_rows, 11)
    _staged(ctx)
    world.meetings = {sid: (rows, ["pull returned 0 rows"]) for sid, (rows, _) in world.meetings.items()}
    world.staged_rows = dict.fromkeys(world.staged_rows, 14)
    assert rw.main(["stage"], _at(ctx, NEXT_WEEK)) == 1  # meetings failed, so this run's captures stay latest
    assert rw.main(["load", NEXT_RUN], ctx) == 0
    world.calls.clear()

    assert rw.main(["load", RUN], ctx) == 2

    assert _permit_rows(root) == 14 and world.calls == []
    assert _state(root)["status"] == "awaiting_load_approval"


def test_a_newer_run_that_is_only_staged_does_not_block_an_older_load(ctx, root):
    _staged(ctx)
    assert rw.main(["stage"], _at(ctx, NEXT_WEEK)) == 0

    assert rw.main(["load", RUN], ctx) == 0


@pytest.mark.parametrize("how", ["exit", "crash"])
def test_a_load_that_stops_partway_promotes_nothing_and_can_be_retried(ctx, world, root, how):
    world.staged_rows = dict.fromkeys(world.staged_rows, 12)
    _staged(ctx)
    if how == "exit":
        world.exit_codes["ingest_form700.py"] = 1  # after the meetings loaded, before courtlistener
    else:
        ctx.runner = lambda cmd, cwd, env: (_ for _ in ()).throw(OSError("bolt reset")) \
            if "ingest_form700.py" in cmd[1] else world(cmd, cwd, env)

    assert rw.main(["load", RUN], ctx) == 1

    state = _state(root)
    assert state["status"] == "load_failed"
    assert ("load-form700 exited 1" if how == "exit" else "load crashed: OSError: bolt reset") in state["error"]
    assert _permit_rows(root) == 10  # nothing was promoted into data/normalized
    assert f"refresh_weekly.py load {RUN}" in _digest(root)

    world.exit_codes.clear()
    ctx.runner = world
    assert rw.main(["load", RUN], ctx) == 0

    state = _state(root)
    assert state["status"] == "awaiting_publish_approval" and not state.get("error")
    assert _permit_rows(root) == 12
    assert [h["status"] for h in state["history"]][-3:] == ["load_failed", "loaded", "awaiting_publish_approval"]


def test_a_capture_that_changes_while_it_loads_fails_the_run(ctx, world, root):
    _staged(ctx)
    world.calls.clear()
    capture = root / "data/extracted/a/2026-09-28.json"

    def racing(cmd, cwd, env):
        if cmd[1] == "scripts/normalize_meetings.py":
            capture.write_text('{"meeting_count": 99}')  # a writer that ignored the run lock
        return world(cmd, cwd, env)
    ctx.runner = racing

    assert rw.main(["load", RUN], ctx) == 1

    state = _state(root)
    assert state["status"] == "failed" and "a changed while loading" in state["error"]
    assert _permit_rows(root) == 10
    assert world.scripts() == ["normalize_meetings.py"]  # stopped at once


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


def _live(root: Path) -> dict[str, bytes | None]:
    exports = root / "data/exports"
    return {n: (exports / n).read_bytes() if (exports / n).is_file() else None for n in rw.PUBLISHED_ARTIFACTS}


def _no_temps_left(root: Path) -> bool:
    return not list((root / "data/exports").glob(".*.tmp"))


def test_staging_that_changes_after_the_hash_check_is_never_published(ctx, root, monkeypatch):
    _loaded(ctx)  # review R3: another run bakes into staging while the live artifacts are backed up
    (root / "data/exports/public-substrate.sqlite").write_bytes(b"old live")
    real_copy2 = rw.shutil.copy2

    def backup_then_race(src, dst, *a, **k):
        real_copy2(src, dst, *a, **k)
        (root / "data/exports/staging/public-substrate.sqlite").write_bytes(b"UNREVIEWED bake from another run")
    monkeypatch.setattr(rw.shutil, "copy2", backup_then_race)

    assert rw.main(["publish", RUN], ctx) == 1

    assert _state(root)["status"] == "failed"
    assert _live(root)["public-substrate.sqlite"] == b"old live"


def test_publish_renames_the_verified_copy_whatever_staging_does_next(ctx, root, monkeypatch):
    _loaded(ctx)
    approved = _state(root)["bake"]["sha256"]
    real_replace, raced = rw.os.replace, []

    def race_then_replace(src, dst):
        if Path(dst).parent == root / "data/exports" and not raced:
            raced.append(dst)
            (root / "data/exports/staging/public-substrate.sqlite").write_bytes(b"UNREVIEWED")
        return real_replace(src, dst)
    monkeypatch.setattr(rw.os, "replace", race_then_replace)

    assert rw.main(["publish", RUN], ctx) == 0

    assert _sha(root / "data/exports/public-substrate.sqlite") == approved["public-substrate.sqlite"]
    assert _state(root)["published"]["sha256"] == approved and _no_temps_left(root)


def test_a_copy_that_does_not_match_the_approved_hash_is_never_published(ctx, root, monkeypatch):
    _loaded(ctx)
    (root / "data/exports/public-substrate.sqlite").write_bytes(b"old live")
    real_copyfile = rw.shutil.copyfile

    def corrupting(src, dst, *a, **k):  # staging changed between the approval and the copy
        real_copyfile(src, dst, *a, **k)
        if Path(src).name == "public-substrate.sqlite":
            Path(dst).write_bytes(b"UNREVIEWED")
        return dst
    monkeypatch.setattr(rw.shutil, "copyfile", corrupting)

    assert rw.main(["publish", RUN], ctx) == 1

    state = _state(root)
    assert state["status"] == "failed" and "public-substrate.sqlite" in state["error"]
    assert _live(root)["public-substrate.sqlite"] == b"old live" and _no_temps_left(root)


def test_a_swap_that_breaks_partway_restores_what_was_live(ctx, root, monkeypatch):
    _loaded(ctx)
    (root / "data/exports/public-substrate.sqlite").write_bytes(b"old live")
    before = _live(root)
    real_replace, raised = rw.os.replace, []

    def flaky(src, dst):
        if Path(dst).name == "catalog.json" and not raised:
            raised.append(dst)
            raise OSError("disk hiccup")
        return real_replace(src, dst)
    monkeypatch.setattr(rw.os, "replace", flaky)

    assert rw.main(["publish", RUN], ctx) == 1

    assert _state(root)["status"] == "failed" and "restored" in _state(root)["error"]
    assert _live(root) == before and _no_temps_left(root)


def test_rollback_restores_exactly_what_was_live_before_the_publish(ctx, root):
    _loaded(ctx)
    exports = root / "data/exports"
    for name in rw.PUBLISHED_ARTIFACTS[:3]:  # substrate-bake-report.json was never live
        (exports / name).write_text(f"old {name}")
    before = _live(root)
    assert rw.main(["publish", RUN], ctx) == 0
    assert f"refresh_weekly.py rollback {RUN}" in _digest(root)

    assert rw.main(["rollback", RUN], ctx) == 0

    assert _live(root) == before
    assert _state(root)["status"] == "rolled_back" and "Rolled back" in _digest(root)
    assert rw.main(["rollback", RUN], ctx) == 2  # only a published run rolls back


def test_rollback_refuses_to_overwrite_artifacts_this_run_did_not_publish(ctx, root):
    _loaded(ctx)
    assert rw.main(["rollback", RUN], ctx) == 2  # not published yet
    assert rw.main(["publish", RUN], ctx) == 0
    (root / "data/exports/catalog.json").write_text("a later publish")

    assert rw.main(["rollback", RUN], ctx) == 2

    assert _state(root)["status"] == "published"
    assert (root / "data/exports/catalog.json").read_text() == "a later publish"


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


def test_credentials_in_a_neo4j_uri_never_reach_state_digest_logs_or_output(ctx, world, root, capsys):
    secret_uri = "bolt://neo4j:s3cret@localhost:7688"

    def leaky(cmd, cwd, env):  # children echo the URI they connect to
        world(cmd, cwd, {**env, "NEO4J_URI": ENV["NEO4J_URI"]})
        return rw.Result(1 if "ingest_form700.py" in cmd[1] else 0, f"Connecting to Neo4j: {env['NEO4J_URI']}\n")
    ctx.runner, ctx.env["NEO4J_URI"] = leaky, secret_uri
    assert rw.main(["stage"], ctx) == 1  # form700 fails with the URI as its last line
    ctx.env["NEO4J_URI"] = "bolt://neo4j:s3cret@localhost:7687"  # refused by the target guard, which quotes it
    assert rw.main(["load", RUN], ctx) == 2
    assert rw.main(["stage"], _at(ctx, NEXT_WEEK)) == 1  # the same refusal, recorded by stage preflight

    written = "".join(f.read_text() for f in (root / "data/ingest-runs").rglob("*") if f.is_file())
    out = capsys.readouterr()
    assert "s3cret" not in written + out.out + out.err
    assert "bolt://***@localhost:7688" in written and "bolt://***@localhost:7687" in written + out.err


@pytest.mark.parametrize("text,expected", [
    ("neo4j+s://u:p%40ss@db.example:7688/x", "neo4j+s://***@db.example:7688/x"),
    ("bolt://localhost:7688 and https://example.com/a@b", "bolt://localhost:7688 and https://example.com/a@b"),
    ("mail stuart@eastpeak.cc", "mail stuart@eastpeak.cc"),
])
def test_redact_drops_only_uri_userinfo(text, expected):
    assert rw.redact(text) == expected


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


@pytest.mark.parametrize("argv", [["stage"], ["load", RUN], ["publish", RUN], ["rollback", RUN]])
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
