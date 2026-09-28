#!/usr/bin/env python3
"""Weekly ingestion runner (I5b): stage automatically; load and publish only on approval.

    refresh_weekly.py stage              # the weekly LaunchAgent runs only this
    refresh_weekly.py load <run_id>      # operator gate: load the approved bytes into the graph
    refresh_weekly.py publish <run_id>   # operator gate: swap the new artifact into data/exports/
    refresh_weekly.py rollback <run_id>  # restore what was live before that run's publish
    refresh_weekly.py status [<run_id>]  # latest (or named) run's state and digest

See docs/specs/2026-09-28-persistent-ingestion-design.md, "I5b". The rule is
approved bytes == loaded bytes: `stage` fingerprints every capture and staged
file it asks a human to approve, and `load`/`publish` refuse bytes that changed
since. Each run lives in data/ingest-runs/<run_id>/ (state.json, digest.md,
logs/, staged/). Every external step goes through ONE injectable runner, so
tests never touch the network, Neo4j or the real data/. Nothing here deploys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest import load_sources, resolve_sources  # noqa: E402
from ingest_guard import Floors, evaluate  # noqa: E402
from load_from import STAGED_FILES  # noqa: E402
from neo4j_target import UnsafeNeo4jTarget, check_target  # noqa: E402
from run_lock import OWNER_ENV, RunLockHeld, run_lock  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path("data/ingest-runs")
LEDGER = RUNS_DIR / "ledger.jsonl"  # ingest.py's run ledger (I1)
EXPORTS = Path("data/exports")
STAGING = EXPORTS / "staging"
PUBLISHED_ARTIFACTS = ("public-substrate.sqlite", "status_manifest.json", "catalog.json", "substrate-bake-report.json")
MEETING_REGISTRIES = ("granicus", "civicplus", "drupal", "proudcity")  # registry/<name>-sources.yaml
MIN_FREE_BYTES = 5 * 1024**3  # live export + staged bake + a backup of the published one


class StagedSource(NamedTuple):
    script: str
    args: tuple[str, ...]
    normalized: str  # its current good output: data/normalized/<normalized>/


STAGED_SOURCES = {
    "permits": StagedSource("ingest_socrata_permits.py", (), "marin-county-permits"),
    "form700": StagedSource("ingest_form700.py", ("--all",), "form700"),
    "courtlistener": StagedSource("ingest_courtlistener_cases.py", (), "courtlistener-cases"),
}

# staging → staged → awaiting_load_approval → loaded → awaiting_publish_approval → published.
# `staging` is written before the first step, so a run that dies is never invisible.
# `load_failed`: a load step stopped partway. Nothing was promoted into data/normalized,
# and `load` may be retried (loads are MERGE-idempotent).
TRANSITIONS = {
    None: ("staging",),
    "staging": ("staged", "failed"),
    "staged": ("awaiting_load_approval", "failed"),
    "awaiting_load_approval": ("loaded", "load_failed", "failed"),
    "load_failed": ("loaded", "load_failed", "failed"),
    "loaded": ("awaiting_publish_approval", "failed"),
    "awaiting_publish_approval": ("published", "failed"),
    "published": ("rolled_back",),
}


class Refused(Exception):
    """The request doesn't apply to this run as it stands; nothing was changed."""


def check_transition(current: str | None, new: str) -> None:
    if new in TRANSITIONS.get(current, ()):
        return
    raise Refused(f"illegal status transition {current} -> {new}")


@dataclass(frozen=True)
class Result:
    returncode: int
    output: str


Runner = Callable[[list[str], Path, Mapping[str, str]], Result]


def subprocess_runner(cmd: list[str], cwd: Path, env: Mapping[str, str]) -> Result:
    proc = subprocess.run(cmd, cwd=cwd, env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return Result(proc.returncode, proc.stdout)


@dataclass
class Context:
    root: Path = ROOT
    runner: Runner = subprocess_runner
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    python: str = sys.executable
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    free_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free
    meeting_registries: tuple[str, ...] = MEETING_REGISTRIES


# --- files and state ---------------------------------------------------------


def run_dir(root: Path, run_id: str) -> Path:
    return root / RUNS_DIR / run_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _copy_atomic(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    os.close(fd)
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def _count_rows(path: Path) -> int | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def read_state(root: Path, run_id: str) -> dict:
    path = run_dir(root, run_id) / "state.json"
    if not path.is_file():
        raise Refused(f"no run {run_id!r} under {RUNS_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(root: Path, run_id: str, state: dict) -> None:
    _write_atomic(run_dir(root, run_id) / "state.json", json.dumps(state, indent=2, sort_keys=True) + "\n")


def _set_status(ctx: Context, state: dict, status: str, **fields) -> dict:
    check_transition(state["status"], status)
    state.update(fields, status=status)
    state["history"].append({"status": status, "at": ctx.now().isoformat(timespec="seconds")})
    write_state(ctx.root, state["run_id"], state)
    _write_atomic(run_dir(ctx.root, state["run_id"]) / "digest.md", render_digest(state))
    return state


def _fail(ctx: Context, state: dict, error: str) -> dict:
    return _set_status(ctx, state, "failed", error=error)


def _require(state: dict, action: str, *statuses: str) -> None:
    if state["status"] not in statuses:
        raise Refused(f"run {state['run_id']} is {state['status']}; {action} needs {' or '.join(statuses)}")


def _step(ctx: Context, run_id: str, name: str, cmd: list[str]) -> Result:
    """Run one external command through the injected runner and keep its log."""
    # Children that take the run lock themselves (ingest.py) run under ours.
    result = ctx.runner(cmd, ctx.root, {**ctx.env, "PYTHON": ctx.python, OWNER_ENV: str(os.getpid())})
    _write_atomic(run_dir(ctx.root, run_id) / "logs" / f"{name}.log",
                  f"$ {' '.join(cmd)}\n{result.output}\n[exit {result.returncode}]\n")
    return result


def _failure(name: str, result: Result) -> str:
    tail = next((line.strip() for line in reversed(result.output.splitlines()) if line.strip()), "")
    return f"exited {result.returncode}: {tail} (logs/{name}.log)"


# --- stage -------------------------------------------------------------------


def preflight(ctx: Context, *, credentials: bool) -> list[str]:
    reasons = []
    try:
        check_target(ctx.env.get("NEO4J_URI"), ctx.env)
    except UnsafeNeo4jTarget as exc:
        reasons.append(str(exc))
    missing = [var for var in ("NEO4J_USER", "NEO4J_PASSWORD") if credentials and not ctx.env.get(var)]
    if missing:
        reasons.append(f"missing {', '.join(missing)}")
    free = ctx.free_bytes(ctx.root)
    if free < MIN_FREE_BYTES:
        reasons.append(f"only {free / 1024**3:.1f} GiB free disk; need {MIN_FREE_BYTES / 1024**3:.0f} GiB")
    return reasons


def _read_ledger(root: Path) -> list[dict]:
    path = root / LEDGER
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _latest_capture(root: Path, source_id: str) -> Path | None:
    captures = sorted((root / "data" / "extracted" / source_id).glob("*.json"))
    return captures[-1] if captures else None


def _stage_meetings(ctx: Context, run_id: str, registry: str) -> dict[str, dict]:
    """`ingest.py --all` for one registry; verdicts come from the ledger lines this run appended."""
    registry_path = f"registry/{registry}-sources.yaml"
    expected = [s["id"] for s in resolve_sources(load_sources(ctx.root / registry_path), all_sources=True)]
    if not expected:
        return {}
    before = _read_ledger(ctx.root)
    name = f"ingest-{registry}"
    _step(ctx, run_id, name, [ctx.python, "scripts/ingest.py", "--all", "--registry", registry_path])
    appended = _read_ledger(ctx.root)[len(before):]
    # First-run baseline seeds (I5a) are history, not this run's verdicts.
    history = before + [e for e in appended if e["run_at"].startswith("seed:")]
    verdicts = {e["source_id"]: e for e in appended if not e["run_at"].startswith("seed:")}

    sources = {}
    for sid in expected:
        last_good = next((e["rows"] for e in reversed(history) if e["source_id"] == sid and e["ok"]), None)
        entry = verdicts.get(sid, {"ok": False, "rows": None,
                                   "reasons": [f"no verdict recorded; the adapter errored (logs/{name}.log)"]})
        source = {"kind": "meetings", "registry": registry, "ok": entry["ok"], "rows": entry["rows"],
                  "last_good_rows": last_good, "reasons": entry["reasons"]}
        capture = _latest_capture(ctx.root, sid) if source["ok"] else None
        if capture is not None:
            source["capture"] = {"path": capture.relative_to(ctx.root).as_posix(), "sha256": _sha256(capture)}
        elif source["ok"]:
            source.update(ok=False, reasons=["passed its floors but no capture file was written"])
        sources[sid] = source
    return sources


def _stage_refetcher(ctx: Context, run_id: str, name: str, src: StagedSource) -> dict:
    """Stage one refetching ingester into <run>/staged/<name>/ and floor it against data/normalized."""
    out_dir = run_dir(ctx.root, run_id) / "staged" / name
    step = f"stage-{name}"
    result = _step(ctx, run_id, step, [ctx.python, f"scripts/{src.script}", *src.args, "--output-dir", str(out_dir)])
    last_good = _count_rows(ctx.root / "data" / "normalized" / src.normalized / "nodes.jsonl")
    source = {"kind": "staged", "ok": False, "rows": None, "last_good_rows": last_good}
    if result.returncode != 0:
        return {**source, "reasons": [_failure(step, result)]}
    if not all((out_dir / f).is_file() for f in STAGED_FILES):
        return {**source, "reasons": [f"exited 0 but staged no {' / '.join(STAGED_FILES)}"]}
    rows = _count_rows(out_dir / "nodes.jsonl")
    # Refetchers carry no uniform record date, so only the row-ratio floor applies.
    verdict = evaluate(rows=rows, newest=None, last_good_rows=last_good, today=ctx.now().date(),
                       floors=Floors(max_newest_age_days=None))
    source.update(ok=verdict.ok, rows=rows, reasons=verdict.reasons)
    if verdict.ok:
        source["files"] = {f: _sha256(out_dir / f) for f in STAGED_FILES}
    return source


def stage(ctx: Context) -> dict:
    run_id = ctx.now().strftime("%Y-%m-%dT%H%M%SZ")
    try:
        run_dir(ctx.root, run_id).mkdir(parents=True)
    except FileExistsError:
        raise Refused(f"run {run_id} already exists") from None
    state = {"run_id": run_id, "status": None, "history": [], "sources": {}}
    _set_status(ctx, state, "staging")
    try:
        return _stage(ctx, state)
    except Exception as exc:  # a crash must end in a visible, failed run, never a bare run dir
        traceback.print_exc()
        return _fail(ctx, state, f"stage crashed: {type(exc).__name__}: {exc}")


def _stage(ctx: Context, state: dict) -> dict:
    run_id = state["run_id"]
    reasons = preflight(ctx, credentials=False)
    state["preflight"] = {"ok": not reasons, "reasons": reasons}
    if reasons:
        return _fail(ctx, state, "preflight failed; nothing was fetched")

    for registry in ctx.meeting_registries:
        state["sources"].update(_stage_meetings(ctx, run_id, registry))
    for name, src in STAGED_SOURCES.items():
        state["sources"][name] = _stage_refetcher(ctx, run_id, name, src)

    if not any(s["ok"] for s in state["sources"].values()):
        return _fail(ctx, state, "every source failed its pull or floors; nothing to approve")
    _set_status(ctx, state, "staged")
    return _set_status(ctx, state, "awaiting_load_approval")


# --- load (operator gate) ----------------------------------------------------


def _unchanged(ctx: Context, run_id: str, sid: str, source: dict) -> bool:
    if source["kind"] == "meetings":
        latest = _latest_capture(ctx.root, sid)
        return (latest is not None and latest.relative_to(ctx.root).as_posix() == source["capture"]["path"]
                and _sha256(latest) == source["capture"]["sha256"])
    staged = run_dir(ctx.root, run_id) / "staged" / sid
    return all((staged / f).is_file() and _sha256(staged / f) == h for f, h in source["files"].items())


def _newer_loaded_run(root: Path, run_id: str) -> str | None:
    """The newest run after `run_id` whose data reached the graph, if any (run ids sort by time)."""
    for path in sorted((root / RUNS_DIR).glob("*/state.json"), reverse=True):
        if path.parent.name <= run_id:
            return None
        if {h["status"] for h in json.loads(path.read_text(encoding="utf-8"))["history"]} & {"loaded", "load_failed"}:
            return path.parent.name
    return None


def load(ctx: Context, run_id: str) -> dict:
    state = read_state(ctx.root, run_id)
    _require(state, "load", "awaiting_load_approval", "load_failed")
    newer = _newer_loaded_run(ctx.root, run_id)
    if newer:
        raise Refused(f"run {run_id} is older than {newer}, which was already loaded; loading it would roll "
                      "data/normalized and the graph back. Stage a fresh run instead.")
    reasons = preflight(ctx, credentials=True)
    if reasons:
        raise Refused("preflight failed: " + "; ".join(reasons))

    accepted = {sid: s for sid, s in state["sources"].items() if s["ok"]}
    changed = [sid for sid, s in accepted.items() if not _unchanged(ctx, run_id, sid, s)]
    if changed:
        return _fail(ctx, state, f"{', '.join(changed)} changed since approval; refusing to load unreviewed bytes")

    # Load from exactly the approved bytes: refetchers from their hashed staged dir. normalize_meetings
    # can only read the latest capture, so the run lock keeps it the approved one and each meeting
    # load is re-verified after it runs.
    staged_root = run_dir(ctx.root, run_id) / "staged"
    refetchers = [sid for sid in STAGED_SOURCES if sid in accepted]
    steps = [(sid, [ctx.python, "scripts/normalize_meetings.py", "--source", sid, "--load"])
             for sid, source in accepted.items() if source["kind"] == "meetings"]
    steps += [(sid, [ctx.python, f"scripts/{STAGED_SOURCES[sid].script}", "--load-from", str(staged_root / sid)])
              for sid in refetchers]
    try:
        for sid, cmd in steps:
            result = _step(ctx, run_id, f"load-{sid}", cmd)
            if result.returncode != 0:
                return _set_status(ctx, state, "load_failed", error=f"load-{sid} {_failure(f'load-{sid}', result)}; "
                                   "nothing was promoted into data/normalized")
            if not _unchanged(ctx, run_id, sid, accepted[sid]):
                return _fail(ctx, state, f"{sid} changed while loading; the graph may hold unreviewed bytes. "
                                         "Stage a fresh run.")
        for sid in refetchers:  # promote only once every load succeeded
            for f in STAGED_FILES:
                _copy_atomic(staged_root / sid / f, ctx.root / "data" / "normalized" / STAGED_SOURCES[sid].normalized / f)
    except Exception as exc:
        traceback.print_exc()
        return _set_status(ctx, state, "load_failed", error=f"load crashed: {type(exc).__name__}: {exc}")
    _set_status(ctx, state, "loaded", loaded=list(accepted), error=None)

    staging = ctx.root / STAGING
    for name, cmd in (
        ("reconciliation", ["bash", "scripts/refresh_reconciliation.sh"]),
        ("export", [ctx.python, "scripts/export_live_graph.py"]),
        ("bake", [ctx.python, "scripts/bake_public_substrate.py", "--source", "live-export",
                  "--sqlite", str(staging / PUBLISHED_ARTIFACTS[0]), "--report", str(staging / PUBLISHED_ARTIFACTS[3])]),
    ):
        result = _step(ctx, run_id, name, cmd)
        if result.returncode != 0:
            return _fail(ctx, state, f"{name} {_failure(name, result)}")

    missing = [n for n in PUBLISHED_ARTIFACTS if not (staging / n).is_file()]
    if missing:
        return _fail(ctx, state, f"bake exited 0 but wrote no {', '.join(missing)}")
    report = json.loads((staging / PUBLISHED_ARTIFACTS[3]).read_text(encoding="utf-8"))
    state["bake"] = {"totals": report.get("totals"), "sqlite": report["sqlite"],
                     "sha256": {n: _sha256(staging / n) for n in PUBLISHED_ARTIFACTS}}
    if not report["sqlite"]["within_budget"]:
        return _fail(ctx, state, f"baked sqlite is {report['sqlite']['size_bytes']:,} bytes, over its "
                                 f"{report['sqlite']['budget_bytes']:,}-byte budget")
    return _set_status(ctx, state, "awaiting_publish_approval")


# --- publish (operator gate) -------------------------------------------------


def _swap_in(exports: Path, sources: Mapping[str, Path | None], expected: Mapping[str, str | None]) -> list[str]:
    """Make each exports/<name> hold exactly the bytes `expected[name]` (None: absent), or change nothing.

    Each source is first copied to a temp file inside data/exports/ and the COPY is hashed, so what
    is renamed into place is the verified bytes, whatever happens to the source afterwards. Returns
    the names that did not match; if any did, nothing was changed.
    """
    temps: dict[str, Path] = {}
    try:
        bad = []
        for name, src in sources.items():
            if src is None:
                continue
            if not src.is_file():
                bad.append(name)
                continue
            fd, tmp = tempfile.mkstemp(dir=exports, prefix=f".{name}.", suffix=".tmp")
            os.close(fd)
            temps[name] = Path(tmp)
            shutil.copyfile(src, tmp)
            if _sha256(temps[name]) != expected[name]:
                bad.append(name)
        if bad:
            return bad
        for name in sources:  # each rename is atomic; the set is restored by the caller on failure
            if name in temps:
                os.replace(temps[name], exports / name)
                del temps[name]
            else:
                (exports / name).unlink(missing_ok=True)
        return []
    finally:
        for tmp in temps.values():
            tmp.unlink(missing_ok=True)


def _kept(previous: Path, before: Mapping[str, str | None]) -> dict[str, Path | None]:
    return {name: previous / name if sha else None for name, sha in before.items()}


def publish(ctx: Context, run_id: str) -> dict:
    state = read_state(ctx.root, run_id)
    _require(state, "publish", "awaiting_publish_approval")
    staging, exports = ctx.root / STAGING, ctx.root / EXPORTS
    approved = state["bake"]["sha256"]

    previous = run_dir(ctx.root, run_id) / "previous"
    previous.mkdir(exist_ok=True)
    before: dict[str, str | None] = {}
    for name in PUBLISHED_ARTIFACTS:  # keep what was live, and note what was absent, for rollback
        before[name] = None
        if (exports / name).is_file():
            shutil.copy2(exports / name, previous / name)
            before[name] = _sha256(previous / name)
    try:
        bad = _swap_in(exports, {n: staging / n for n in PUBLISHED_ARTIFACTS}, approved)
    except OSError as exc:
        _swap_in(exports, _kept(previous, before), before)
        return _fail(ctx, state, f"publish broke mid-swap ({exc}); the previously live artifacts were restored")
    if bad:
        return _fail(ctx, state, f"{', '.join(bad)} missing or changed since the approved bake; nothing published")
    for name in PUBLISHED_ARTIFACTS:
        (staging / name).unlink(missing_ok=True)
    return _set_status(ctx, state, "published", published={
        "sqlite_sha256": approved[PUBLISHED_ARTIFACTS[0]], "sha256": dict(approved),
        "previous": previous.relative_to(ctx.root).as_posix(), "previous_sha256": before,
    })


def rollback(ctx: Context, run_id: str) -> dict:
    """Restore the artifacts that were live before this run's publish (absent ones are removed)."""
    state = read_state(ctx.root, run_id)
    _require(state, "rollback", "published")
    exports, published = ctx.root / EXPORTS, state["published"]
    if "previous_sha256" not in published:
        raise Refused(f"run {run_id} was published before rollback existed; restore {published['previous']} by hand")
    before = published["previous_sha256"]
    for name, prior in before.items():  # a partly-finished rollback may be retried
        live = _sha256(exports / name) if (exports / name).is_file() else None
        if live not in (published["sha256"][name], prior):
            raise Refused(f"live {name} is neither run {run_id}'s publish nor what it replaced "
                          "(a later publish?); refusing to roll back over it")
    bad = _swap_in(exports, _kept(ctx.root / published["previous"], before), before)
    if bad:
        raise Refused(f"kept {', '.join(bad)} changed since the publish; nothing was rolled back")
    return _set_status(ctx, state, "rolled_back")


# --- digest and status -------------------------------------------------------

NEXT_STEP = {
    "staging": "Staging is in progress. If no run holds data/ingest-runs/.lock, it died mid-stage.",
    "awaiting_load_approval": "Approve the passing sources: `python scripts/refresh_weekly.py load {run_id}`. "
                              "Failed sources are skipped; their previous good data stays authoritative.",
    "load_failed": "The load stopped partway and promoted nothing into data/normalized. Fix the cause, then "
                   "retry: `python scripts/refresh_weekly.py load {run_id}`.",
    "awaiting_publish_approval": "Publish: `python scripts/refresh_weekly.py publish {run_id}` swaps the staged "
                                 "artifact into data/exports/. It does not deploy; deploying is a separate decision.",
    "published": "Published. Deploying is a separate launch decision. "
                 "To undo: `python scripts/refresh_weekly.py rollback {run_id}`.",
    "rolled_back": "Rolled back: the artifacts that were live before this run's publish are restored.",
    "failed": "Nothing further to approve in this run.",
}


def _num(value: int | None) -> str:
    return "–" if value is None else str(value)


def render_digest(state: dict) -> str:
    sources = sorted(state["sources"].items(), key=lambda item: (item[1]["kind"], item[0]))
    passed = sum(s["ok"] for _, s in sources)
    lines = [f"# Open Marin weekly refresh — {state['run_id']}", "",
             f"**Status:** {state['status']} · {passed} of {len(sources)} sources passed", ""]
    if state.get("error"):
        lines += [f"**Error:** {state['error']}", ""]
    if not state.get("preflight", {}).get("ok", True):
        lines += ["## Preflight", "", *(f"- {reason}" for reason in state["preflight"]["reasons"]), ""]
    if sources:
        lines += ["## Sources", "", "| Source | Kind | Verdict | Rows | Last good | Δ |", "|---|---|---|---:|---:|---:|"]
        for sid, s in sources:
            kind = f"meetings ({s['registry']})" if s["kind"] == "meetings" else s["kind"]
            delta = "–" if None in (s["rows"], s["last_good_rows"]) else f"{s['rows'] - s['last_good_rows']:+d}"
            lines.append(f"| {sid} | {kind} | {'ok' if s['ok'] else 'FAILED'} | {_num(s['rows'])} "
                         f"| {_num(s['last_good_rows'])} | {delta} |")
        lines.append("")
    failures = [(sid, s) for sid, s in sources if not s["ok"]]
    if failures:
        lines += ["## Failures", "", *(f"- **{sid}**: {'; '.join(s['reasons'])}" for sid, s in failures), ""]
    if state.get("bake"):
        totals, sqlite = state["bake"].get("totals") or {}, state["bake"]["sqlite"]
        lines += ["## Bake (data/exports/staging/)", "",
                  f"- {_num(totals.get('nodes'))} nodes · {_num(totals.get('edges'))} edges · "
                  f"sqlite {sqlite['size_bytes']:,} bytes (budget {sqlite['budget_bytes']:,}: "
                  f"{'within budget' if sqlite['within_budget'] else 'OVER BUDGET'})", ""]
    if state.get("published"):
        lines += ["## Published", "", f"- public-substrate.sqlite sha256 `{state['published']['sqlite_sha256']}`",
                  f"- previous artifacts kept in `{state['published']['previous']}`", ""]
    lines += ["## Next", "", NEXT_STEP.get(state["status"], "").format(run_id=state["run_id"]), ""]
    return "\n".join(lines)


def latest_run_id(root: Path) -> str | None:
    runs = sorted(path.parent.name for path in (root / RUNS_DIR).glob("*/state.json"))
    return runs[-1] if runs else None


def status(ctx: Context, run_id: str | None) -> int:
    run_id = run_id or latest_run_id(ctx.root)
    if run_id is None:
        print(f"no runs yet under {ctx.root / RUNS_DIR}")
        return 1
    _report(ctx, read_state(ctx.root, run_id))
    return 0


def _report(ctx: Context, state: dict) -> None:
    print(_summary(state))
    print(f"digest: {run_dir(ctx.root, state['run_id']) / 'digest.md'}")


# --- CLI ---------------------------------------------------------------------


def _summary(state: dict) -> str:
    lines = [f"run {state['run_id']}: {state['status']}"]
    lines += [f"  {sid}: {'ok' if s['ok'] else 'FAILED — ' + '; '.join(s['reasons'])}"
              for sid, s in state["sources"].items()]
    if state.get("error"):
        lines.append(f"  error: {state['error']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, ctx: Context | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stage", help="fetch, stage, floor and digest every weekly source (automated)")
    for gate in ("load", "publish", "rollback"):
        sub.add_parser(gate, help=f"operator gate: {gate} an approved run").add_argument("run_id")
    sub.add_parser("status", help="print a run's state and digest path (default: latest)").add_argument(
        "run_id", nargs="?")
    args = parser.parse_args(argv)
    ctx = ctx or Context()

    try:
        if args.command == "status":
            return status(ctx, args.run_id)
        with run_lock(ctx.root):  # every other subcommand writes
            if args.command == "stage":
                state = stage(ctx)
                _report(ctx, state)
                return 0 if state["status"] != "failed" and all(s["ok"] for s in state["sources"].values()) else 1
            state = {"load": load, "publish": publish, "rollback": rollback}[args.command](ctx, args.run_id)
        _report(ctx, state)
        return 1 if state["status"] in ("failed", "load_failed") else 0
    except (Refused, RunLockHeld) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
