#!/usr/bin/env python3
"""Weekly ingestion runner: stage, load, publish and snapshot, unattended; the checks are the gate.

    refresh_weekly.py weekly             # the weekly LaunchAgent runs this: all of the below, then heartbeat
    refresh_weekly.py stage              # fetch, floor and fingerprint every source
    refresh_weekly.py load <run_id>      # back up the graph, then load the staged bytes; export + bake
    refresh_weekly.py publish <run_id>   # swap the new artifact into data/exports/
    refresh_weekly.py rollback <run_id>  # restore what was live before that run's publish
    refresh_weekly.py rebake <run_id>    # redo export + bake for a run that failed after loading
    refresh_weekly.py status [<run_id>]  # latest (or named) run's state and digest

See docs/specs/2026-09-28-persistent-ingestion-design.md ("I5b") and
docs/specs/2026-09-29-automatic-weekly-refresh.md ("I5c"). The rule is staged
bytes == loaded bytes: `stage` fingerprints every capture and staged file, and
`load`/`publish` refuse bytes that changed since. The manual subcommands remain
for recovery. Each run lives in data/ingest-runs/<run_id>/ (state.json,
digest.md, logs/, staged/). Every external step goes through ONE injectable
runner, under a bounded timeout, so tests never touch the network, Neo4j, git
or the real data/. Nothing here deploys. Only `weekly` pings
OPEN_MARIN_HEARTBEAT_URL, if set (see heartbeat()).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import traceback
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest import load_sources, resolve_sources  # noqa: E402
from ingest_guard import Floors, evaluate  # noqa: E402
from load_from import STAGED_FILES  # noqa: E402
from neo4j_target import UnsafeNeo4jTarget, check_target  # noqa: E402
from net_retry import retry_transient  # noqa: E402
from run_lock import OWNER_ENV, RunLockHeld, run_lock  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path("data/ingest-runs")
LEDGER = RUNS_DIR / "ledger.jsonl"  # ingest.py's run ledger (I1)
EXPORTS = Path("data/exports")
STAGING = EXPORTS / "staging"
BACKUPS = EXPORTS / "backups"  # pre-load-<run_id>/: the whole graph before that run's load
DATA_LAYERS = ("normalized", "extracted")  # data/<layer> symlinks into the private data repo
DATA_BRANCH = "main"
LOAD_DATABASE = "neo4j"  # the loaders write to the server's default database
PUBLISHED_ARTIFACTS = ("public-substrate.sqlite", "status_manifest.json", "catalog.json", "substrate-bake-report.json")
MEETING_REGISTRIES = ("granicus", "civicplus", "drupal", "proudcity")  # registry/<name>-sources.yaml
MIN_FREE_BYTES = 5 * 1024**3  # live export + staged bake + a backup of the published one

# Wall-clock ceiling, in seconds, for each external step; one that outlives it is killed and
# fails with that reason. The 2026-09-28 stage took ~15 minutes end to end (proudcity ~10),
# so these leave ample headroom while the whole default stage (every ingest-* and stage-*
# step, in sequence) stays under 3 hours, well inside the heartbeat's 6-hour grace. A step
# with no entry of its own takes its family's (`load-<sid>` -> `load`). Override one with
# OPEN_MARIN_TIMEOUT_<STEP> in the environment, e.g. OPEN_MARIN_TIMEOUT_STAGE_COURTLISTENER=900
# or OPEN_MARIN_TIMEOUT_LOAD=7200.
STEP_TIMEOUTS = {
    "ingest-granicus": 20 * 60, "ingest-civicplus": 20 * 60, "ingest-drupal": 10 * 60,
    "ingest-proudcity": 45 * 60, "ingest": 30 * 60,
    "stage-permits": 20 * 60, "stage-form700": 30 * 60, "stage-courtlistener": 30 * 60, "stage": 30 * 60,
    "backup": 60 * 60, "load": 60 * 60, "reconciliation": 3 * 3600, "export": 3 * 3600, "bake": 2 * 3600,
    "snapshot": 10 * 60,
}
DEFAULT_STEP_TIMEOUT = 60 * 60
TIMEOUT_ENV = "OPEN_MARIN_TIMEOUT_"

# The external dead-man's switch (Healthchecks.io check "Open Marin weekly refresh"). Its URL
# embeds the check's secret; it never reaches a log, state.json, a digest, a ping body, or a step.
HEARTBEAT_ENV = "OPEN_MARIN_HEARTBEAT_URL"
HEARTBEAT_TIMEOUT_SECS = 10
PING_ERROR_CHARS = 300  # of each error quoted in a ping body
PING_BODY_CHARS = 2000

# Environment variables whose values are secrets: scrubbed from everything this runner writes,
# prints or pings (step output, state.json, digests, crash tracebacks, ping bodies).
_SECRET_VAR = re.compile(r"PASSWORD|TOKEN|SECRET|API_KEY", re.IGNORECASE)


class StagedSource(NamedTuple):
    script: str
    args: tuple[str, ...]
    normalized: str  # its current good output: data/normalized/<normalized>/


STAGED_SOURCES = {
    "permits": StagedSource("ingest_socrata_permits.py", (), "marin-county-permits"),
    "form700": StagedSource("ingest_form700.py", ("--all",), "form700"),
    # Incremental: a full refetch no longer fits CourtListener's hourly limit (May 2026).
    "courtlistener": StagedSource("ingest_courtlistener_cases.py",
                                  ("--incremental-from", "data/normalized/courtlistener-cases"),
                                  "courtlistener-cases"),
}

# staging → staged → awaiting_load_approval → loaded → awaiting_publish_approval → published.
# `staging` is written before the first step, so a run that dies is never invisible.
# `load_failed`: a load step stopped partway. Nothing was promoted into data/normalized,
# and `load` may be retried (loads are MERGE-idempotent).
# `rebake`: a run that `failed` AFTER reaching `loaded` (export/bake/budget) re-enters
# `loaded` and redoes only export + bake; the approved data is already in the graph.
TRANSITIONS = {
    None: ("staging",),
    "staging": ("staged", "failed"),
    "staged": ("awaiting_load_approval", "failed"),
    "awaiting_load_approval": ("loaded", "load_failed", "failed"),
    "load_failed": ("loaded", "load_failed", "failed"),
    "loaded": ("awaiting_publish_approval", "failed"),
    "awaiting_publish_approval": ("published", "failed"),
    "published": ("rolled_back",),
    # Only `rebake` takes this edge, and only for a run whose history shows it
    # reached `loaded` (its data is already in the graph; export+bake failed).
    "failed": ("loaded",),
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
    timed_out_after: float | None = None  # seconds, when the step was killed for outliving its timeout


Runner = Callable[[list[str], Path, Mapping[str, str], float], Result]


def subprocess_runner(cmd: list[str], cwd: Path, env: Mapping[str, str], timeout: float | None = None) -> Result:
    """Run `cmd` in its own process group; past `timeout` seconds, kill the whole group.

    Killing the group, not just the child, takes its children with it (refresh_reconciliation.sh
    runs several), so nothing it started keeps writing, or keeps the output pipe open, after
    the step has failed. Whatever the step printed before the kill is kept for its log.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, process_group=0)
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            output, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:  # a descendant left the group and holds the pipe open
            proc.stdout.close()
            output = ""
        proc.wait()
        return Result(proc.returncode, output, timed_out_after=timeout)
    except BaseException:  # Ctrl-C: our group no longer receives the terminal's signals, so pass it on
        _kill_group(proc)
        raise
    return Result(proc.returncode, output)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _timeout_seconds(var: str, raw: str) -> float:
    try:
        seconds = float(raw)
    except ValueError:
        seconds = math.nan
    if not (math.isfinite(seconds) and seconds > 0):
        raise ValueError(f"{var}={raw!r} is not a positive number of seconds")
    return seconds


def step_timeout(env: Mapping[str, str], name: str) -> float:
    """Seconds step `name` may run: an environment override, else its default (own, then family's)."""
    keys = (name, name.split("-", 1)[0])
    for key in keys:
        var = TIMEOUT_ENV + re.sub(r"[^A-Za-z0-9]", "_", key).upper()
        if env.get(var) is not None:
            return _timeout_seconds(var, env[var])
    return next((STEP_TIMEOUTS[key] for key in keys if key in STEP_TIMEOUTS), DEFAULT_STEP_TIMEOUT)


@dataclass
class Context:
    root: Path = ROOT
    runner: Runner = subprocess_runner
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    python: str = sys.executable
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    free_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free
    meeting_registries: tuple[str, ...] = MEETING_REGISTRIES
    ping: Callable[[str, str], None] = lambda url, body: http_ping(url, body)


# --- files and state ---------------------------------------------------------

_USERINFO = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s/@'\"]+@", re.IGNORECASE)


def redact(text: str) -> str:
    """Drop any URI's `user:pass@` before text is written or printed (a NEO4J_URI may embed credentials)."""
    return _USERINFO.sub(r"\1***@", text)


def _heartbeat_secrets(url: str) -> set[str]:
    """The heartbeat URL, and any part of it long enough to be its secret."""
    parts = urllib.parse.urlsplit(url)
    return {s for s in (url, parts.query, *(seg for seg in parts.path.split("/") if len(seg) >= 8)) if s}


def scrub(text: str, env: Mapping[str, str]) -> str:
    """redact(), and remove every secret value in `env` (credentials, tokens, the heartbeat URL)."""
    secrets = {v for k, v in env.items() if _SECRET_VAR.search(k) and v.strip()}
    if env.get(HEARTBEAT_ENV, "").strip():
        secrets |= _heartbeat_secrets(env[HEARTBEAT_ENV].strip())
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return redact(text)


def _print_crash(ctx: Context) -> None:
    print(scrub(traceback.format_exc(), ctx.env), file=sys.stderr)


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


def write_state(root: Path, run_id: str, state: dict, env: Mapping[str, str] = {}) -> None:
    _write_atomic(run_dir(root, run_id) / "state.json", scrub(json.dumps(state, indent=2, sort_keys=True) + "\n", env))


def _set_status(ctx: Context, state: dict, status: str, **fields) -> dict:
    check_transition(state["status"], status)
    state.update(fields, status=status)
    state["history"].append({"status": status, "at": ctx.now().isoformat(timespec="seconds")})
    return _persist(ctx, state)


def _persist(ctx: Context, state: dict) -> dict:
    write_state(ctx.root, state["run_id"], state, ctx.env)
    _write_atomic(run_dir(ctx.root, state["run_id"]) / "digest.md", scrub(render_digest(state), ctx.env))
    return state


def _fail(ctx: Context, state: dict, error: str) -> dict:
    return _set_status(ctx, state, "failed", error=error)


def _require(state: dict, action: str, *statuses: str) -> None:
    if state["status"] not in statuses:
        raise Refused(f"run {state['run_id']} is {state['status']}; {action} needs {' or '.join(statuses)}")


def _step(ctx: Context, run_id: str, name: str, cmd: list[str]) -> Result:
    """Run one external command through the injected runner and keep its log."""
    # Children that take the run lock themselves (ingest.py) run under ours.
    env = {var: value for var, value in ctx.env.items() if var != HEARTBEAT_ENV}
    raw = ctx.runner(cmd, ctx.root, {**env, "PYTHON": ctx.python, OWNER_ENV: str(os.getpid())},
                     step_timeout(ctx.env, name))
    result = Result(raw.returncode, scrub(raw.output, ctx.env), raw.timed_out_after)
    end = (f"[timed out after {result.timed_out_after:g}s; killed]" if result.timed_out_after is not None
           else f"[exit {result.returncode}]")
    _write_atomic(run_dir(ctx.root, run_id) / "logs" / f"{name}.log",
                  scrub(f"$ {' '.join(cmd)}\n{result.output}\n{end}\n", ctx.env))
    return result


def _failure(name: str, result: Result) -> str:
    tail = next((line.strip() for line in reversed(result.output.splitlines()) if line.strip()), "")
    how = (f"timed out after {result.timed_out_after:g}s and was killed" if result.timed_out_after is not None
           else f"exited {result.returncode}")
    return f"{how}: {tail} (logs/{name}.log)"


# --- stage -------------------------------------------------------------------


def preflight(ctx: Context, *, credentials: bool) -> list[str]:
    reasons = []
    try:
        check_target(ctx.env.get("NEO4J_URI"), ctx.env)
    except UnsafeNeo4jTarget as exc:
        reasons.append(str(exc))
    missing = [var for var in ("NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")
               if credentials and not ctx.env.get(var)]
    if missing:
        reasons.append(f"missing {', '.join(missing)}")
    database = ctx.env.get("NEO4J_DATABASE")
    if credentials and database and database != LOAD_DATABASE:
        reasons.append(f"NEO4J_DATABASE={database}: the loaders write to the default database ({LOAD_DATABASE}), "
                       "so a backup or export of another would not be the graph they changed")
    for var, raw in ctx.env.items():  # a typo'd override fails here, before anything is fetched
        if var.startswith(TIMEOUT_ENV):
            try:
                _timeout_seconds(var, raw)
            except ValueError as exc:
                reasons.append(str(exc))
    free = ctx.free_bytes(ctx.root)
    if free < MIN_FREE_BYTES:
        reasons.append(f"only {free / 1024**3:.1f} GiB free disk; need {MIN_FREE_BYTES / 1024**3:.0f} GiB")
    return reasons


def _read_ledger(root: Path) -> list[dict]:
    path = root / LEDGER
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _latest_capture(root: Path, source_id: str) -> Path | None:
    """Newest dated capture (<YYYY-MM-DD>.json); stray non-date files never win."""
    captures = [p for p in sorted((root / "data" / "extracted" / source_id).glob("*.json"))
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)]
    return captures[-1] if captures else None


def _stage_meetings(ctx: Context, run_id: str, registry: str) -> dict[str, dict]:
    """`ingest.py --all` for one registry; verdicts come from the ledger lines this run appended."""
    registry_path = f"registry/{registry}-sources.yaml"
    expected = [s["id"] for s in resolve_sources(load_sources(ctx.root / registry_path), all_sources=True)]
    if not expected:
        return {}
    before = _read_ledger(ctx.root)
    name = f"ingest-{registry}"
    result = _step(ctx, run_id, name, [ctx.python, "scripts/ingest.py", "--all", "--registry", registry_path])
    unfinished = (f"no verdict recorded; {name} {_failure(name, result)}" if result.timed_out_after is not None
                  else f"no verdict recorded; the adapter errored (logs/{name}.log)")
    appended = _read_ledger(ctx.root)[len(before):]
    # First-run baseline seeds (I5a) are history, not this run's verdicts.
    history = before + [e for e in appended if e["run_at"].startswith("seed:")]
    verdicts = {e["source_id"]: e for e in appended if not e["run_at"].startswith("seed:")}

    sources = {}
    for sid in expected:
        last_good = next((e["rows"] for e in reversed(history) if e["source_id"] == sid and e["ok"]), None)
        entry = verdicts.get(sid, {"ok": False, "rows": None, "reasons": [unfinished]})
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
        _print_crash(ctx)
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


# --- heartbeat -----------------------------------------------------------------


@retry_transient(backoff=1.0)
def http_ping(url: str, body: str | None = None) -> None:
    data = None if body is None else body.encode("utf-8")  # with a body, a POST: Healthchecks keeps it
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers={"User-Agent": "open-marin-refresh"}),
                                timeout=HEARTBEAT_TIMEOUT_SECS) as resp:
        resp.read()


def _clean_on_disk(ctx: Context, run_id: str) -> bool:
    """On disk, not just in memory: published, every source passed, snapshot pushed, digest complete."""
    try:
        persisted = read_state(ctx.root, run_id)
        digest = (run_dir(ctx.root, run_id) / "digest.md").read_text(encoding="utf-8")
    except (Refused, OSError, ValueError):
        return False
    return (persisted["status"] == "published" and all(s["ok"] for s in persisted["sources"].values())
            and persisted.get("snapshot", {}).get("ok") is True and digest == scrub(render_digest(persisted), ctx.env))


def _outcome_body(ctx: Context, state: dict | None, problem: str | None) -> str:
    """What the ping tells the operator: ids and reasons, never a log tail or a secret."""
    def quote(text: str) -> str:  # scrub whole, then cut: a secret split by the cut would survive
        return scrub(text, ctx.env)[:PING_ERROR_CHARS]

    lines = []
    if state is not None:
        lines.append(f"Open Marin weekly refresh {state['run_id']}: {state['status']}")
        held = sorted(sid for sid, s in state["sources"].items() if not s["ok"])
        if held:
            lines.append("held sources (not refreshed): " + ", ".join(held))
        if state.get("error"):
            lines.append("error: " + quote(state["error"]))
        if state.get("snapshot", {}).get("ok") is False:
            lines.append("private data snapshot failed: " + quote(state["snapshot"]["error"]))
        lines.append(f"digest: {(RUNS_DIR / state['run_id'] / 'digest.md').as_posix()}")
    if problem:
        lines.append(quote(problem))
    return scrub("\n".join(lines), ctx.env)[:PING_BODY_CHARS]


def heartbeat(ctx: Context, state: dict | None, problem: str | None) -> bool:
    """Report the weekly run to the external monitor, once; return whether it was clean.

    Clean pings the URL (no email). Anything else pings `<URL>/fail`, which emails the operator
    at once; a run that never reports is caught by the check's grace deadline. `state` is re-read
    from disk, so the verdict and the body describe what was persisted. A failed ping is recorded
    in the run and reported, but never changes its status.
    """
    if state is not None:
        try:
            state = read_state(ctx.root, state["run_id"])
        except (Refused, OSError, ValueError):
            pass
    clean = problem is None and state is not None and _clean_on_disk(ctx, state["run_id"])
    url = ctx.env.get(HEARTBEAT_ENV, "").strip()
    if not url:
        return clean
    try:
        ctx.ping(url if clean else url.rstrip("/") + "/fail", _outcome_body(ctx, state, problem))
        outcome = {"ok": True}
    except Exception as exc:
        outcome = {"ok": False, "error": scrub(f"{type(exc).__name__}: {exc}", ctx.env)}
        print(f"heartbeat: ping failed ({outcome['error']}); the run itself is unaffected", file=sys.stderr)
    if state is not None:
        state["heartbeat"] = {**outcome, "at": ctx.now().isoformat(timespec="seconds"),
                              "signal": "success" if clean else "fail"}
        try:
            _persist(ctx, state)
        except Exception as exc:
            print(f"heartbeat: could not record the outcome: {type(exc).__name__}: {exc}", file=sys.stderr)
    return clean


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

    # Load from exactly the approved bytes: refetchers from their hashed staged dir, meetings from
    # the exact approved capture path (normalize_meetings --capture); each is re-verified after.
    staged_root = run_dir(ctx.root, run_id) / "staged"
    refetchers = [sid for sid in STAGED_SOURCES if sid in accepted]
    if "backup" not in state:  # a retry keeps the first backup: the graph before this run touched it
        backup = BACKUPS / f"pre-load-{run_id}"
        result = _step(ctx, run_id, "backup", [ctx.python, "scripts/export_live_graph.py", "--backup",
                                               "--out-dir", str(ctx.root / backup)])
        if result.returncode != 0:
            return _fail(ctx, state, f"backup {_failure('backup', result)}; nothing was loaded")
        state["backup"] = backup.as_posix()
        _persist(ctx, state)
    steps = [(sid, [ctx.python, "scripts/normalize_meetings.py", "--source", sid,
                    "--capture", str(ctx.root / source["capture"]["path"]), "--load"])
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
            normalized = ctx.root / "data" / "normalized" / STAGED_SOURCES[sid].normalized
            for f in STAGED_FILES:
                _copy_atomic(staged_root / sid / f, normalized / f)
    except Exception as exc:
        _print_crash(ctx)
        return _set_status(ctx, state, "load_failed", error=f"load crashed: {type(exc).__name__}: {exc}")
    _set_status(ctx, state, "loaded", loaded=list(accepted), error=None)
    return _export_and_bake(ctx, state, run_id, reconcile=True)


def _export_and_bake(ctx: Context, state: dict, run_id: str, *, reconcile: bool) -> dict:
    """From `loaded`: (reconciliation,) export, bake into staging, then budget + hashes."""
    try:
        return _export_and_bake_steps(ctx, state, run_id, reconcile=reconcile)
    except Exception as exc:  # the data is in the graph: fail visibly, so `rebake` can recover it
        _print_crash(ctx)
        return _fail(ctx, state, f"export/bake crashed: {type(exc).__name__}: {exc}")


def _export_and_bake_steps(ctx: Context, state: dict, run_id: str, *, reconcile: bool) -> dict:
    staging = ctx.root / STAGING
    steps = [("reconciliation", ["bash", "scripts/refresh_reconciliation.sh"])] if reconcile else []
    steps += [
        ("export", [ctx.python, "scripts/export_live_graph.py"]),
        ("bake", [ctx.python, "scripts/bake_public_substrate.py", "--source", "live-export",
                  "--sqlite", str(staging / PUBLISHED_ARTIFACTS[0]), "--report", str(staging / PUBLISHED_ARTIFACTS[3])]),
    ]
    for name, cmd in steps:
        result = _step(ctx, run_id, name, cmd)
        if result.returncode != 0:
            return _fail(ctx, state, f"{name} {_failure(name, result)}")
        if name == "reconciliation":
            state["reconciled"] = True
            _persist(ctx, state)

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


def rebake(ctx: Context, run_id: str) -> dict:
    """Redo export + bake for a run that failed after its approved data was loaded."""
    state = read_state(ctx.root, run_id)
    _require(state, "rebake", "failed")
    if "loaded" not in {h["status"] for h in state["history"]}:
        raise Refused(f"run {run_id} failed before loading; rebake only recovers export/bake failures")
    newer = _newer_loaded_run(ctx.root, run_id)
    if newer:
        raise Refused(f"run {newer} is newer and already reached the graph; rebaking {run_id} would publish stale data")
    _set_status(ctx, state, "loaded", error=None)
    return _export_and_bake(ctx, state, run_id, reconcile=not state.get("reconciled"))


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


# --- snapshot: commit + push the private data repo ------------------------------


class SnapshotFailed(Exception):
    """The private data repo was not snapshotted; the publish stands."""


def _data_repo(root: Path) -> Path:
    layers = [(root / "data" / layer).resolve() for layer in DATA_LAYERS]
    repo = layers[0].parent
    if any(layer.parent != repo for layer in layers) or not (repo / ".git").exists():
        raise SnapshotFailed(f"{repo} is not a git repo holding data/{' and data/'.join(DATA_LAYERS)}")
    return repo


def _commit_snapshot(ctx: Context, run_id: str) -> dict:
    repo = _data_repo(ctx.root)

    def git(name: str, *args: str, ok: tuple[int, ...] = (0,)) -> Result:
        step = f"snapshot-{name}"
        result = _step(ctx, run_id, step, ["git", "-C", str(repo), *args])
        if result.returncode not in ok:
            raise SnapshotFailed(f"{step} {_failure(step, result)}")
        return result

    branch = git("branch", "rev-parse", "--abbrev-ref", "HEAD").output.strip()
    if branch != DATA_BRANCH:
        raise SnapshotFailed(f"the private data repo is on {branch}, not {DATA_BRANCH}; nothing committed")
    if git("index", "diff", "--cached", "--quiet", ok=(0, 1)).returncode:
        raise SnapshotFailed("the private data repo already had staged changes; not committing someone else's work")
    git("add", "add", "--", *DATA_LAYERS)
    changed = git("staged", "diff", "--cached", "--quiet", ok=(0, 1)).returncode == 1
    if changed:
        git("commit", "commit", "-m", f"data: snapshot at publish {run_id}")
    git("push", "push", "origin", DATA_BRANCH)
    return {"commit": git("head", "rev-parse", "--short", "HEAD").output.strip(), "changed": changed}


def snapshot(ctx: Context, state: dict) -> dict:
    """After a publish: commit data/normalized + data/extracted to the private repo and push.

    A failure is recorded as `snapshot: {ok: false, error}`; it never changes the run's status.
    """
    try:
        outcome = {"ok": True, **_commit_snapshot(ctx, state["run_id"])}
    except SnapshotFailed as exc:
        outcome = {"ok": False, "error": str(exc)}
    except Exception as exc:
        _print_crash(ctx)
        outcome = {"ok": False, "error": f"snapshot crashed: {type(exc).__name__}: {exc}"}
    state["snapshot"] = outcome
    return _persist(ctx, state)


# --- weekly: the unattended run ------------------------------------------------


def _unresolved_load(root: Path) -> str | None:
    """A run whose load stopped partway, so the graph may hold part of it: `load_failed`, or killed
    mid-load (its backup, taken just before the first load step, recorded; no outcome after)."""
    for path in sorted((root / RUNS_DIR).glob("*/state.json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["status"] == "load_failed" or (state["status"] == "awaiting_load_approval" and "backup" in state):
            return path.parent.name
    return None


def _weekly_run(ctx: Context) -> tuple[dict | None, str | None]:
    """stage -> load -> publish -> snapshot, as far as the run gets; returns (state, problem)."""
    state = None
    try:
        # Checked before fetching: a new capture would make that run's retry refuse its bytes.
        blocker = _unresolved_load(ctx.root)
        if blocker:
            return None, (f"not run: run {blocker} stopped partway through its load, so the graph may hold "
                          f"part of it. Retry `refresh_weekly.py load {blocker}`, or restore "
                          f"{(BACKUPS / f'pre-load-{blocker}').as_posix()}; weekly runs resume once it is resolved")
        state = stage(ctx)
        run_id = state["run_id"]
        if state["status"] == "awaiting_load_approval":
            state = load(ctx, run_id)
        if state["status"] == "awaiting_publish_approval":
            state = publish(ctx, run_id)
        if state["status"] == "published":
            state = snapshot(ctx, state)
        return state, None
    except Refused as exc:
        return state, f"refused: {exc}"
    except Exception as exc:
        _print_crash(ctx)
        return state, f"crashed: {type(exc).__name__}: {exc}"


def weekly(ctx: Context) -> int:
    """The scheduled run: 0 only when it was clean; any other outcome has pinged /fail."""
    reported = False
    try:
        with run_lock(ctx.root):
            state, problem = _weekly_run(ctx)
            clean = heartbeat(ctx, state, problem)
            reported = True
    except RunLockHeld as exc:
        heartbeat(ctx, None, f"not run: the run lock is held ({exc})")
        print(scrub(f"REFUSED: {exc}", ctx.env), file=sys.stderr)
        return 2
    except Exception as exc:  # the lock could not be taken (or released): still tell the monitor
        _print_crash(ctx)
        if not reported:
            heartbeat(ctx, None, f"crashed outside the run: {type(exc).__name__}: {exc}")
        return 1
    if state is not None:
        _report(ctx, read_state(ctx.root, state["run_id"]))
    if problem:
        print(scrub(problem, ctx.env), file=sys.stderr)
    return 0 if clean else 1


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
    if state.get("heartbeat", {}).get("ok") is False:
        lines += [f"**Heartbeat:** FAILED ({state['heartbeat']['error']}). The external monitor will report "
                  "this run as missing; the staged data is unaffected.", ""]
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
    if state.get("backup"):
        lines += [f"**Graph backup (before load):** `{state['backup']}`", ""]
    if state.get("published"):
        lines += ["## Published", "", f"- public-substrate.sqlite sha256 `{state['published']['sqlite_sha256']}`",
                  f"- previous artifacts kept in `{state['published']['previous']}`", ""]
    snap = state.get("snapshot")
    if snap:
        lines += ["## Private data snapshot", "",
                  (f"- pushed `{snap['commit']}`{'' if snap['changed'] else ' (no new data)'}" if snap["ok"]
                   else f"- FAILED: {snap['error']}"), ""]
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
    print(scrub(_summary(state), ctx.env))
    print(f"digest: {run_dir(ctx.root, state['run_id']) / 'digest.md'}")


# --- CLI ---------------------------------------------------------------------


def _summary(state: dict) -> str:
    lines = [f"run {state['run_id']}: {state['status']}"]
    lines += [f"  {sid}: {'ok' if s['ok'] else 'FAILED — ' + '; '.join(s['reasons'])}"
              for sid, s in state["sources"].items()]
    if state.get("error"):
        lines.append(f"  error: {state['error']}")
    if state.get("snapshot", {}).get("ok") is False:
        lines.append(f"  private data snapshot FAILED: {state['snapshot']['error']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, ctx: Context | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("weekly", help="the scheduled run: stage, load, publish, snapshot, heartbeat")
    sub.add_parser("stage", help="fetch, stage, floor and digest every weekly source")
    for gate in ("load", "publish", "rollback"):
        sub.add_parser(gate, help=f"{gate} a run by hand (recovery)").add_argument("run_id")
    sub.add_parser("rebake", help="redo export + bake for a run that failed after loading").add_argument("run_id")
    sub.add_parser("status", help="print a run's state and digest path (default: latest)").add_argument(
        "run_id", nargs="?")
    args = parser.parse_args(argv)
    ctx = ctx or Context()

    try:
        if args.command == "status":
            return status(ctx, args.run_id)
        if args.command == "weekly":
            return weekly(ctx)
        with run_lock(ctx.root):  # every other subcommand writes
            if args.command == "stage":
                state = stage(ctx)
                _report(ctx, state)
                return 0 if state["status"] != "failed" and all(s["ok"] for s in state["sources"].values()) else 1
            state = {"load": load, "publish": publish, "rollback": rollback,
                     "rebake": rebake}[args.command](ctx, args.run_id)
        _report(ctx, state)
        return 1 if state["status"] in ("failed", "load_failed") else 0
    except (Refused, RunLockHeld) as exc:
        print(scrub(f"REFUSED: {exc}", ctx.env), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
