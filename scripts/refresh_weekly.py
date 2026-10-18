#!/usr/bin/env python3
"""Weekly ingestion runner: stage, load, publish and snapshot, unattended; the checks are the gate.

    refresh_weekly.py weekly             # the weekly LaunchAgent runs this: all of the below, then heartbeat
    refresh_weekly.py stage              # fetch, floor and fingerprint every source
    refresh_weekly.py load <run_id>      # back up the graph, then load the staged bytes; export + bake
    refresh_weekly.py publish <run_id>   # swap the new artifact into data/exports/
    refresh_weekly.py rollback <run_id>  # restore what was live before that run's publish
    refresh_weekly.py rebake <run_id>    # redo export + bake for a run that failed after loading
    refresh_weekly.py status [<run_id>]  # latest (or named) run's state and digest
    refresh_weekly.py export-due [--dry-run]  # judge which campaign exports are due (dry run: print only)

See docs/specs/2026-09-28-persistent-ingestion-design.md ("I5b") and
docs/specs/2026-09-29-automatic-weekly-refresh.md ("I5c"). The rule is staged
bytes == loaded bytes: `stage` fingerprints every capture and staged file, and
`load`/`publish` refuse bytes that changed since. The manual subcommands remain
for recovery. Each run lives in data/ingest-runs/<run_id>/ (state.json,
digest.md, logs/, staged/). Every external step goes through ONE injectable
runner, under a bounded timeout, so tests never touch the network, Neo4j, git
or the real data/. Nothing here deploys. Only `weekly` pings
OPEN_MARIN_HEARTBEAT_URL, if set (see heartbeat()); `weekly` and `export-due` ping
OPEN_MARIN_EXPORT_DUE_URL (see run_export_due() and docs/specs/2026-10-06-campaign-export-freshness-design.md).
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
import time
import traceback
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, NamedTuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cf_export_due  # noqa: E402
import cf_prepare  # noqa: E402
from cf_inventory import inventory as cf_inventory  # noqa: E402
from ingest import is_date, load_sources, resolve_sources  # noqa: E402
from ingest_guard import Floors, evaluate  # noqa: E402
from load_from import STAGED_FILES  # noqa: E402
from neo4j_target import UnsafeNeo4jTarget, check_target  # noqa: E402
import robots_gate  # noqa: E402
import votes_refresh  # noqa: E402
from net_retry import retry_transient  # noqa: E402
from run_lock import OWNER_ENV, RunLockHeld, run_lock  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
RUNS_DIR = Path("data/ingest-runs")
LEDGER = RUNS_DIR / "ledger.jsonl"  # ingest.py's run ledger (I1)
EXPORTS = Path("data/exports")
STAGING = EXPORTS / "staging"
BACKUPS = EXPORTS / "backups"  # pre-load-<run_id>/: the whole graph before that run's load
DATA_LAYERS = ("normalized", "extracted")  # data/<layer> symlinks into the private data repo
IDENTITY_DECISIONS = "identity/person"  # Stuart's person-identity decisions, in the private data repo itself
DATA_BRANCH = "main"
LOAD_DATABASE = "neo4j"  # the loaders write to the server's default database
PUBLISHED_ARTIFACTS = ("public-substrate.sqlite", "status_manifest.json", "catalog.json", "substrate-bake-report.json")
MEETING_REGISTRIES = ("granicus", "civicplus", "drupal", "proudcity")  # registry/<name>-sources.yaml
SAVED_PAGE_SCHEDULE = "saved-page"  # never fetched (robots.txt says no); the operator saves the page by hand
SAVED_PAGE_DIR = Path("data/raw/manual")  # <YYYY-MM-DD>/<adapter>/<source id>.html; never moved or deleted
SAVED_PAGE_FRESH_DAYS = 14
SAVED_PAGE_RUNBOOK = "docs/runbooks/saved-pages.md"
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
    "cf": 2 * 3600,  # each campaign-preparation step (export, normalize, plan, a bake, the scan)
}
DEFAULT_STEP_TIMEOUT = 60 * 60
TIMEOUT_ENV = "OPEN_MARIN_TIMEOUT_"

# The external dead-man's switch (Healthchecks.io check "Open Marin weekly refresh"). Its URL
# embeds the check's secret; it never reaches a log, state.json, a digest, a ping body, or a step.
HEARTBEAT_ENV = "OPEN_MARIN_HEARTBEAT_URL"
# The second check, "Open Marin campaign export due": the same rules for its URL.
EXPORT_DUE_ENV = "OPEN_MARIN_EXPORT_DUE_URL"
MONITOR_ENVS = (HEARTBEAT_ENV, EXPORT_DUE_ENV)
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

CF_REGISTRY = Path("registry/netfile-sources.yaml")
CF_STATE = RUNS_DIR / "campaign-finance.json"  # validation cache and campaign-export hashes (not a run)
VOTES_REFRESH_ENV = "OPEN_MARIN_VOTES_REFRESH_ROOT"  # the votes refresh's registry, read only; default its REFRESH_ROOT
CF_STAGING_ENV = "OPEN_MARIN_CF_STAGING"  # where preparations go; default ~/open-marin-staging/cf-refresh


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
    staged_sources: Mapping[str, StagedSource] = field(default_factory=lambda: dict(STAGED_SOURCES))
    ping: Callable[[str, str], None] = lambda url, body: http_ping(url, body)
    netfile_fetch: Callable[[str], dict] = lambda url: cf_export_due.fetch_json(url)
    sleep: Callable[[float], None] = lambda seconds: time.sleep(seconds)
    monotonic: Callable[[], float] = lambda: time.monotonic()
    prepare_campaign_exports: bool = True  # tests of the alarm alone switch preparation off (it has its own)


# --- files and state ---------------------------------------------------------

_USERINFO = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s/@'\"]+@", re.IGNORECASE)


def redact(text: str) -> str:
    """Drop any URI's `user:pass@` before text is written or printed (a NEO4J_URI may embed credentials)."""
    return _USERINFO.sub(r"\1***@", text)


def _monitor_secrets(url: str) -> set[str]:
    """A check's ping URL, and every part of it that could be its secret: the query, and each query value and path
    segment of 8+ characters, raw and percent-decoded (shorter ones would redact ordinary digits and words).
    Never raises: an unparseable URL is split by hand."""
    try:
        parts = urllib.parse.urlsplit(url)
        path, query = parts.path, parts.query
    except ValueError:
        path, _, query = url.partition("?")
        path = re.sub(r"^[a-z]+://", "", path, flags=re.I).replace("[", "/").replace("]", "/")
    pieces = {url, query, *(seg for seg in path.split("/") if len(seg) >= 8)}
    pieces |= {value for value in (pair.partition("=")[2] for pair in query.split("&")) if len(value) >= 8}
    pieces |= {urllib.parse.unquote_plus(piece) for piece in pieces}
    return {piece for piece in pieces if piece.strip() and (len(piece) >= 8 or piece in (url, query))}


def _fail_url(url: str) -> str:
    """The check's /fail endpoint: on the path, before any query."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url.rstrip("/") + "/fail"
    return urllib.parse.urlunsplit(parts._replace(path=parts.path.rstrip("/") + "/fail"))


def _scrub_tree(value, env: Mapping[str, str]):
    """scrub() every string in a JSON-able value, before encoding can escape a secret past it."""
    if isinstance(value, str):
        return scrub(value, env)
    if isinstance(value, dict):
        return {scrub(str(k), env): _scrub_tree(v, env) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_tree(v, env) for v in value]
    return value


def scrub(text: str, env: Mapping[str, str]) -> str:
    """redact(), and remove every secret value in `env` (credentials, tokens, both check URLs)."""
    secrets = {v for k, v in env.items() if _SECRET_VAR.search(k) and v.strip()}
    for var in MONITOR_ENVS:
        if env.get(var, "").strip():
            secrets |= _monitor_secrets(env[var].strip())
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
    # Scrubbed value by value, before encoding: scrubbing the encoded text could miss an escaped secret and
    # could break the JSON.
    _write_atomic(run_dir(root, run_id) / "state.json",
                  json.dumps(_scrub_tree(state, env), indent=2, sort_keys=True) + "\n")


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
    env = {var: value for var, value in ctx.env.items() if var not in MONITOR_ENVS}
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


def _ingest(ctx: Context, run_id: str, name: str, *args: str) -> tuple[Result, list[dict], dict[str, dict]]:
    """One ingest.py step under this run's root: (result, ledger history, this step's verdicts by source)."""
    before = _read_ledger(ctx.root)
    result = _step(ctx, run_id, name, [ctx.python, str(SCRIPTS / "ingest.py"), "--root", str(ctx.root), *args])
    appended = _read_ledger(ctx.root)[len(before):]
    # First-run baseline seeds (I5a) are history, not this run's verdicts.
    history = before + [e for e in appended if e["run_at"].startswith("seed:")]
    return result, history, {e["source_id"]: e for e in appended if not e["run_at"].startswith("seed:")}


def _meeting_source(ctx: Context, sid: str, registry: str, entry: dict, history: list[dict]) -> dict:
    last_good = next((e["rows"] for e in reversed(history) if e["source_id"] == sid and e["ok"]), None)
    source = {"kind": "meetings", "registry": registry, "ok": entry["ok"], "rows": entry["rows"],
              "last_good_rows": last_good, "reasons": entry["reasons"]}
    if entry.get("outcome"):  # robots_* (the gate refused a request) / crosswalk_* (scripts/crosswalk.py)
        source["status"] = entry["outcome"]
        if entry["outcome"].startswith("robots_"):
            source["robots"] = entry.get("robots")
    if entry.get("crosswalk_sha256"):  # the crosswalk version this capture was made with; load re-checks it
        source["crosswalk_sha256"] = entry["crosswalk_sha256"]
    if entry.get("identity"):  # native-only: its capture pins the load policy, which the load re-checks
        source["identity"] = entry["identity"]
    capture = _latest_capture(ctx.root, sid) if source["ok"] else None
    if capture is not None:
        source["capture"] = {"path": capture.relative_to(ctx.root).as_posix(), "sha256": _sha256(capture)}
    elif source["ok"]:
        source.update(ok=False, reasons=["passed its floors but no capture file was written"])
    return source


def _no_verdict(name: str, result: Result) -> str:
    return (f"no verdict recorded; {name} {_failure(name, result)}" if result.timed_out_after is not None
            else f"no verdict recorded; the adapter errored (logs/{name}.log)")


def _stage_meetings(ctx: Context, run_id: str, registry: str) -> dict[str, dict]:
    """`ingest.py --all` for one registry; verdicts come from the ledger lines this run appended.

    Every request goes through the robots gate; this run's ingest.py processes share one robots.txt
    cache (<run>/robots.json, so each host's is fetched once) and log every request decision.
    """
    registry_path = f"registry/{registry}-sources.yaml"
    expected = [s["id"] for s in resolve_sources(load_sources(ctx.root / registry_path), all_sources=True)]
    if not expected:
        return {}
    run = run_dir(ctx.root, run_id)
    name = f"ingest-{registry}"
    result, history, verdicts = _ingest(ctx, run_id, name, "--all", "--registry", registry_path,
                                        "--robots-cache", str(run / "robots.json"),
                                        "--request-log", str(run / "logs" / f"requests-{registry}.jsonl"))
    unfinished = {"ok": False, "rows": None, "reasons": [_no_verdict(name, result)]}
    return {sid: _meeting_source(ctx, sid, registry, verdicts.get(sid, unfinished), history) for sid in expected}


def _newest_saved_page(root: Path, adapter: str, sid: str) -> tuple[Path, str] | None:
    """The newest saved page: under a real calendar date, and a readable file (not a dir or dangling link)."""
    pages = sorted((p.parent.parent.name, p) for p in (root / SAVED_PAGE_DIR).glob(f"*/{adapter}/{sid}.html")
                   if is_date(p.parent.parent.name) and p.is_file())
    return (pages[-1][1], pages[-1][0]) if pages else None


def _saved_page_history(root: Path, run_id: str, sid: str, sha: str) -> set[str]:
    """What earlier runs did with these exact bytes: {"loaded"} and/or {"rejected"} (by their floors)."""
    seen = set()
    for path in sorted((root / RUNS_DIR).glob("*/state.json")):
        if path.parent.name >= run_id:
            continue
        state = json.loads(path.read_text(encoding="utf-8"))
        source = state["sources"].get(sid) or {}
        if source.get("saved_page", {}).get("sha256") != sha:
            continue
        if sid in state.get("loaded", []):
            seen.add("loaded")
        elif source["saved_page"].get("verdict") == "rejected":
            seen.add("rejected")
    return seen


def _stage_saved_pages(ctx: Context, run_id: str, registry: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """(sources, saved_pages) for this registry's saved-page sources; nothing is fetched.

    Only an `accepted` page becomes a source (captured through `ingest.py --saved-page`, then loaded like
    a fetch). missing / stale / unchanged / rejected are informational: they appear in the digest and
    can fail neither the run nor the heartbeat. The saved files are only read.
    """
    sources, pages = {}, {}
    for config in load_sources(ctx.root / f"registry/{registry}-sources.yaml"):
        if config.get("schedule") != SAVED_PAGE_SCHEDULE:
            continue
        sid = config["id"]
        try:
            pages[sid], source = _saved_page_outcome(ctx, run_id, registry, config)
        except Exception as exc:  # one unreadable page fails its own source, never the rest of the stage
            pages[sid] = {"outcome": "error", "url": config["url"], "adapter": config["adapter"]}
            source = {"kind": "meetings", "registry": registry, "ok": False, "rows": None, "last_good_rows": None,
                      "reasons": [f"saved page: {type(exc).__name__}: {exc}"]}
        if source is not None:
            sources[sid] = source
    return sources, pages


def _saved_page_outcome(ctx: Context, run_id: str, registry: str, config: dict) -> tuple[dict, dict | None]:
    """(this source's saved_pages entry, its state.sources entry when the page was accepted)."""
    sid = config["id"]
    known = {"url": config["url"], "adapter": config["adapter"]}
    newest = _newest_saved_page(ctx.root, config["adapter"], sid)
    if newest is None:
        return {"outcome": "missing", **known}, None
    path, saved_on = newest
    page = {**known, "path": path.relative_to(ctx.root).as_posix(), "saved_on": saved_on,
            "age_days": (ctx.now().date() - datetime.strptime(saved_on, "%Y-%m-%d").date()).days,
            "sha256": _sha256(path)}
    seen = _saved_page_history(ctx.root, run_id, sid, page["sha256"])
    if page["age_days"] > SAVED_PAGE_FRESH_DAYS:
        return {"outcome": "stale", **page}, None
    if "loaded" in seen:
        return {"outcome": "unchanged", **page}, None
    if "rejected" in seen:
        return {"outcome": "rejected", **page}, None
    return {"outcome": "accepted", **page}, _ingest_saved_page(ctx, run_id, registry, config, path, page)


def _ingest_saved_page(ctx: Context, run_id: str, registry: str, config: dict, path: Path, page: dict) -> dict:
    sid, name = config["id"], f"saved-{config['id']}"
    result, history, verdicts = _ingest(ctx, run_id, name, "--source", sid,
                                        "--registry", f"registry/{registry}-sources.yaml", "--saved-page", str(path))
    entry = verdicts.get(sid)
    verdict = "no verdict" if entry is None else "passed" if entry["ok"] else "rejected"
    source = _meeting_source(ctx, sid, registry, entry or {"ok": False, "rows": None,
                                                           "reasons": [_no_verdict(name, result)]}, history)
    source["saved_page"] = {"path": page["path"], "sha256": page["sha256"], "saved_on": page["saved_on"],
                            "verdict": verdict}
    if source.get("capture"):
        captured = json.loads((ctx.root / source["capture"]["path"]).read_text(encoding="utf-8")).get("raw_sha256")
        if captured != page["sha256"]:
            source.pop("capture")
            source.update(ok=False, reasons=[f"the newest capture ({captured}) is not the saved page ({page['sha256']})"])
    return source


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

    state["saved_pages"] = {}
    for registry in ctx.meeting_registries:
        state["sources"].update(_stage_meetings(ctx, run_id, registry))
        saved_sources, saved_pages = _stage_saved_pages(ctx, run_id, registry)
        state["sources"].update(saved_sources)
        state["saved_pages"].update(saved_pages)
    robots = run_dir(ctx.root, run_id) / "robots.json"
    if robots.is_file():  # what each host's robots.txt said this run (bodies stay in robots.json)
        state["robots"] = robots_gate.summarize(json.loads(robots.read_text(encoding="utf-8")))
    for name, src in ctx.staged_sources.items():
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
    if state is not None and state.get("export_due"):
        record = state["export_due"]["record"]
        lines.append(f"campaign exports due: {len(record['due']) + len(record['landed'])} (its own email)")
    if problem:
        lines += [quote(line) for line in problem.splitlines() if line.strip()]
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
        ctx.ping(url if clean else _fail_url(url), _outcome_body(ctx, state, problem))
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


# --- export-due alarm --------------------------------------------------------------


def read_cf_state(root: Path) -> dict:
    path = root / CF_STATE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def write_cf_state(ctx: Context, state: dict) -> None:
    _write_atomic(ctx.root / CF_STATE, json.dumps(_scrub_tree(state, ctx.env), indent=2, sort_keys=True) + "\n")


def _campaign_sources(root: Path) -> list[dict]:
    try:
        doc = yaml.safe_load((root / CF_REGISTRY).read_text(encoding="utf-8"))
        sources = doc["sources"]
        if not isinstance(sources, list) or not all(isinstance(s, dict) for s in sources):
            raise TypeError("sources is not a list of mappings")
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise cf_export_due.ConfigError(f"{CF_REGISTRY.as_posix()} is unreadable ({type(exc).__name__}: {exc})")
    return sources


def _alarm_url(ctx: Context) -> tuple[str | None, str | None]:
    url = ctx.env.get(EXPORT_DUE_ENV, "").strip()
    if not url:
        return None, f"{EXPORT_DUE_ENV} is not set; the export-due check is never pinged"
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
        return None, f"{EXPORT_DUE_ENV} is not an http(s) URL"
    return url, None


def judge_export_due(ctx: Context, cache: dict, extra: list | None = None) -> cf_export_due.Verdict:
    """Today's verdict for every campaign source; raises ConfigError when the registry is unreadable."""
    api = cf_export_due.NetFileApi(ctx.netfile_fetch, sleep=ctx.sleep, monotonic=ctx.monotonic)
    return cf_export_due.evaluate(ctx.root / "data" / "raw", _campaign_sources(ctx.root), ctx.now(), cache, api,
                                  extra or [])


def _cf_step(ctx: Context, run_id: str, name: str, cmd: list[str]) -> cf_prepare.StepResult:
    result = _step(ctx, run_id, f"cf-{name}", cmd)
    return cf_prepare.StepResult(result.returncode, result.output, result.timed_out_after is not None)


def run_campaign_preparation(ctx: Context, state: dict | None) -> cf_prepare.Outcome | None:
    """Prepare landed campaign exports, after the week's loads, under the lock. Never raises; None when the
    graph is not settled (a load stopped partway) or the registry is unreadable (the alarm reports that)."""
    if not ctx.prepare_campaign_exports or state is None or state["status"] == "load_failed" \
            or _unresolved_load(ctx.root):
        return None
    try:
        sources = _campaign_sources(ctx.root)
        today = cf_export_due.pacific_today(ctx.now())
        usable = [s for s in sources if not cf_export_due.check_sources([s], today)]
        if len(usable) != len(sources) or not usable:
            return None  # a source the alarm cannot judge is never left out of a bundle (its flows would retire)
        cf_state = read_cf_state(ctx.root)
        try:
            inventories = cf_inventory(ctx.root / "data" / "raw", usable, today, cf_state.setdefault("validated", {}))
        except cf_export_due.ConfigError:
            return None
        if ctx.free_bytes(ctx.root) < MIN_FREE_BYTES:
            outcome = cf_prepare.Outcome("transient", "not enough free disk for a preparation",
                                         problems=["campaign preparation: not enough free disk"])
        else:
            staging = Path(ctx.env.get(CF_STAGING_ENV) or Path.home() / "open-marin-staging" / "cf-refresh")
            outcome = cf_prepare.prepare(cf_prepare.Prep(
                root=ctx.root, step=lambda name, cmd: _cf_step(ctx, state["run_id"], name, cmd), python=ctx.python,
                run_id=state["run_id"], today=today, at=ctx.now().isoformat(timespec="seconds"), staging=staging,
                sources=usable, inventories=inventories, state=cf_state))
        cf_state["last_preparation"] = {"run_id": state["run_id"], "status": outcome.status,
                                        "message": outcome.message}
        write_cf_state(ctx, cf_state)
    except cf_export_due.ConfigError:
        return None
    except Exception as exc:
        _print_crash(ctx)
        outcome = cf_prepare.Outcome("transient", f"crashed: {type(exc).__name__}: {exc}",
                                     problems=[scrub(f"campaign preparation crashed: {type(exc).__name__}: {exc}",
                                                     ctx.env)])
    state["campaign_preparation"] = {"status": outcome.status, "message": outcome.message}
    _persist(ctx, state)
    return outcome


def _due_items(items: list[tuple[str, str, str]]) -> list[cf_export_due.DueItem]:
    return [cf_export_due.DueItem(sid, label, [why]) for sid, label, why in items]


def run_export_due(ctx: Context, state: dict | None, *, persist: bool,
                   prepared: cf_prepare.Outcome | None = None) -> list[str]:
    """Evaluate and ping the export-due check; return the monitoring problems for the main heartbeat. Never raises.

    `persist`: record the verdict in the run (when there is one) and keep the validation cache; without it,
    nothing is written (the lock may be someone else's).
    """
    try:
        problems: list[str] = []
        url, url_problem = _alarm_url(ctx)
        if url_problem:
            problems.append(url_problem)
        cf_state = read_cf_state(ctx.root)
        cache = dict(cf_state.get("validated", {}))
        extra = _due_items(prepared.items if prepared else cf_prepare.standing_items(cf_state))
        try:
            verdict = judge_export_due(ctx, cache, extra)
            problems += verdict.problems
            body, failing = verdict.body(lambda text: scrub(text, ctx.env)), verdict.is_due
        except cf_export_due.ConfigError as exc:
            verdict, body, failing = None, f"Open Marin: the export-due alarm cannot judge: {exc}\n", True
            problems.append(str(exc))
        ping = None
        if url:
            try:
                ctx.ping(_fail_url(url) if failing else url, scrub(body, ctx.env))
                ping = {"ok": True}
            except Exception as exc:
                ping = {"ok": False, "error": scrub(f"{type(exc).__name__}: {exc}", ctx.env)}
                problems.append(f"export-due alarm ping failed ({ping['error']})")
        if persist:
            write_cf_state(ctx, {**cf_state, "validated": cache})
            if state is not None:
                state["export_due"] = {"at": ctx.now().isoformat(timespec="seconds"),
                                       "signal": "fail" if failing else "success", "ping": ping,
                                       "record": verdict.record() if verdict else {"due": [], "landed": [],
                                                                                   "problems": problems}}
                _persist(ctx, state)
        return [p if p.startswith("export-due alarm") else f"export-due alarm: {p}" for p in problems]
    except Exception as exc:
        _print_crash(ctx)
        return [scrub(f"export-due alarm crashed: {type(exc).__name__}: {exc}", ctx.env)]


def export_due(ctx: Context, *, dry_run: bool) -> int:
    """`export-due`: today's verdict against the live API. --dry-run pings and writes nothing."""
    if not dry_run:
        problems = run_export_due(ctx, None, persist=False)
        print(scrub("\n".join(problems) or "export-due: pinged", ctx.env))
        return 1 if problems else 0
    try:
        cf_state = read_cf_state(ctx.root)
        verdict = judge_export_due(ctx, dict(cf_state.get("validated", {})),
                                   _due_items(cf_prepare.standing_items(cf_state)))
    except cf_export_due.ConfigError as exc:
        print(scrub(f"export-due: cannot judge: {exc}", ctx.env))
        return 1
    _, url_problem = _alarm_url(ctx)
    print(verdict.body(lambda text: scrub(text, ctx.env)))
    print(f"would ping: {'fail' if verdict.is_due else 'success'} (dry run: nothing pinged or written)")
    problems = verdict.problems + ([url_problem] if url_problem else [])
    for problem in problems:
        print(scrub(f"monitoring problem: {problem}", ctx.env))
    return 1 if problems else 0


def _join(problem: str | None, more: list[str]) -> str | None:
    lines = ([problem] if problem else []) + more
    return "\n".join(lines) or None


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
        state["backup_sha256"] = {f: _sha256(ctx.root / backup / f) for f in STAGED_FILES
                                  if (ctx.root / backup / f).is_file()}  # what check-loaded binds to
        _persist(ctx, state)
    reports = {sid: _fresh_report_path(ctx.root, run_id, sid)
               for sid, source in accepted.items() if source["kind"] == "meetings"}
    guarded = {sid for sid in reports if {"crosswalk_sha256", "identity"} & set(accepted[sid])
               or _guarded(ctx, accepted[sid], sid)}
    steps = [(sid, meeting_load_cmd(ctx, sid, accepted[sid], reports[sid])) for sid in reports]
    steps += [(sid, [ctx.python, f"scripts/{STAGED_SOURCES[sid].script}", "--load-from", str(staged_root / sid)])
              for sid in refetchers]
    held: list[str] = []
    try:
        for sid, cmd in steps:
            result = _step(ctx, run_id, f"load-{sid}", cmd)
            if result.returncode != 0:
                return _set_status(ctx, state, "load_failed", error=f"load-{sid} {_failure(f'load-{sid}', result)}; "
                                   "nothing was promoted into data/normalized")
            if sid in guarded:
                problem = _take_load_report(state, sid, reports[sid])
                if problem:
                    return _set_status(ctx, state, "load_failed", error=f"load-{sid} exited 0 but {problem}")
                if state["sources"][sid].get("held"):
                    held.append(sid)
                    _persist(ctx, state)
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
    _set_status(ctx, state, "loaded", loaded=[sid for sid in accepted if sid not in held], error=None)
    return _export_and_bake(ctx, state, run_id, reconcile=True)


def meeting_load_cmd(ctx: Context, sid: str, source: dict, report: Path) -> list[str]:
    """The load step of one meeting source: normalize exactly the approved capture, under this run's root."""
    return [ctx.python, "scripts/normalize_meetings.py", "--source", sid,
            "--capture", str(ctx.root / source["capture"]["path"]), "--load",
            "--root", str(ctx.root), "--report", str(report)]


def _fresh_report_path(root: Path, run_id: str, sid: str) -> Path:
    """A report path no earlier attempt of this run used: a leftover can never pass for this load's report."""
    reports = run_dir(root, run_id) / "load-reports"
    attempt = 1
    while (reports / f"{sid}.{attempt}.json").exists():
        attempt += 1
    return reports / f"{sid}.{attempt}.json"


def _guarded(ctx: Context, source: dict, sid: str) -> bool:
    """Whether the registry, as it stands at load time, sends this source through the guarded load."""
    import crosswalk

    config = next((s for s in load_sources(ctx.root / f"registry/{source['registry']}-sources.yaml")
                   if s["id"] == sid), {})
    return crosswalk.guarded(config)


def _take_load_report(state: dict, sid: str, path: Path) -> str | None:
    """Record a crosswalk source's load report in the run; the problem, if it is not this load's own.

    The no-overwrite load (scripts/guarded_load.py) exits 0 whether it loaded or held, so a success
    without a fresh report naming this source, its approved capture and its pinned crosswalk is no
    success. A `held` report fails only this source: nothing of it was written, and the run goes on.
    """
    source = state["sources"][sid]
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"wrote no load report ({path.name})"
    expected = {"source_id": sid, "capture_sha256": source["capture"]["sha256"],
                "crosswalk_sha256": source.get("crosswalk_sha256")}  # none pinned: the report must say none
    wrong = sorted(k for k, v in expected.items() if report.get(k) != v)
    if wrong or report.get("outcome") not in ("loaded", "held"):
        return f"its load report does not match this load ({', '.join(wrong) or 'outcome ' + repr(report.get('outcome'))})"
    source["load_report"] = {"path": path.name, "outcome": report["outcome"], "holds": report.get("holds", [])}
    if report["outcome"] == "held":
        reasons = [f"held, nothing loaded: {h['reason']} "
                   f"{json.dumps({k: v for k, v in h.items() if k != 'reason'}, sort_keys=True)}"
                   for h in report.get("holds", [])] or ["held, nothing loaded"]
        source.update(ok=False, held=True, reasons=reasons)
    return None


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
    # The bake publishes campaign freshness from the first prepared/applied bundle it verifies against its export.
    campaign = [arg for bundle in cf_prepare.bake_bundles(read_cf_state(ctx.root)) for arg in ("--campaign-bundle", bundle)]
    steps += [
        ("export", [ctx.python, "scripts/export_live_graph.py"]),
        ("bake", [ctx.python, "scripts/bake_public_substrate.py", "--source", "live-export", *campaign,
                  "--sqlite", str(staging / PUBLISHED_ARTIFACTS[0]), "--report", str(staging / PUBLISHED_ARTIFACTS[3])]),
    ]
    for name, cmd in steps:
        result = _step(ctx, run_id, name, cmd)
        if result.returncode != 0:
            return _fail(ctx, state, f"{name} {_failure(name, result)}")
        if name == "reconciliation":
            state["reconciled"] = True
            _persist(ctx, state)
        if name == "export":  # the digest's list of minutes to save, from this run's export (never fails the run)
            state["votes_minutes"] = _votes_minutes(ctx)

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


def _votes_minutes(ctx: Context) -> dict:
    """Read-only: the votes refresh's pending minutes as of this run's export (votes_refresh.digest_snapshot)."""
    refresh = Path(ctx.env.get(VOTES_REFRESH_ENV) or votes_refresh.REFRESH_ROOT)
    return votes_refresh.digest_snapshot(ctx.root, ctx.root / EXPORTS / "live-graph-export", refresh,
                                         today=ctx.now().date().isoformat())


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
    git("add", "add", "--", *DATA_LAYERS, *([IDENTITY_DECISIONS] if (repo / IDENTITY_DECISIONS).is_dir() else []))
    changed = git("staged", "diff", "--cached", "--quiet", ok=(0, 1)).returncode == 1
    if changed:
        git("commit", "commit", "-m", f"data: snapshot at publish {run_id}")
    git("push", "push", "origin", DATA_BRANCH)
    return {"commit": git("head", "rev-parse", "--short", "HEAD").output.strip(), "changed": changed}


def snapshot(ctx: Context, state: dict) -> dict:
    """After a publish: commit data/normalized + data/extracted (+ identity/person) to the private repo and push.

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
            prepared = run_campaign_preparation(ctx, state)  # read-only against the graph
            alarm = run_export_due(ctx, state, persist=True, prepared=prepared)  # whatever the run's outcome
            problem = _join(problem, [*(prepared.problems if prepared else []), *alarm])
            clean = heartbeat(ctx, state, problem)
            reported = True
    except RunLockHeld as exc:  # someone else's lock: judge the alarm, but write nothing
        heartbeat(ctx, None, _join(f"not run: the run lock is held ({exc})", run_export_due(ctx, None, persist=False)))
        print(scrub(f"REFUSED: {exc}", ctx.env), file=sys.stderr)
        return 2
    except Exception as exc:  # the lock could not be taken (or released): still tell the monitor
        _print_crash(ctx)
        if not reported:
            alarm = run_export_due(ctx, None, persist=False)
            heartbeat(ctx, None, _join(f"crashed outside the run: {type(exc).__name__}: {exc}", alarm))
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
    lines += _saved_pages_digest(state)
    if state.get("votes_minutes"):
        lines += votes_refresh.render_digest_section(state["votes_minutes"])
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
    alarm = state.get("export_due")
    if alarm:
        record = alarm["record"]
        lines += ["## Campaign export-due alarm", "",
                  f"- {alarm['signal']}: {len(record['due'])} export(s) due, {len(record['landed'])} landed file(s) "
                  f"to fix, {len(record.get('problems', []))} monitoring problem(s)"]
        if alarm["ping"] and not alarm["ping"]["ok"]:
            lines.append(f"- ping FAILED: {alarm['ping']['error']}")
        lines.append("")
    snap = state.get("snapshot")
    if snap:
        lines += ["## Private data snapshot", "",
                  (f"- pushed `{snap['commit']}`{'' if snap['changed'] else ' (no new data)'}" if snap["ok"]
                   else f"- FAILED: {snap['error']}"), ""]
    lines += ["## Next", "", NEXT_STEP.get(state["status"], "").format(run_id=state["run_id"]), ""]
    return "\n".join(lines)


def _saved_pages_digest(state: dict) -> list[str]:
    pages = sorted((state.get("saved_pages") or {}).items())
    if not pages:
        return []
    lines = ["## Saved pages", "",
             f"robots.txt disallows fetching these listings, so they are saved by hand ({SAVED_PAGE_RUNBOOK}). "
             "None of them fails the run.", "",
             "| Source | Outcome | Newest saved page | Age (days) | Listing to save |", "|---|---|---|---:|---|"]
    lines += [f"| {sid} | {p['outcome']} | {p.get('saved_on', '–')} | {_num(p.get('age_days'))} | {p['url']} |"
              for sid, p in pages]
    due = [(sid, p) for sid, p in pages
           if p["outcome"] in ("missing", "error") or p.get("age_days", 0) > SAVED_PAGE_FRESH_DAYS]
    if due:
        lines.append("")
    lines += [f"- save a fresh page for **{sid}**: open {p['url']} and save it (Page Source / \"HTML Only\") as "
              f"`{(SAVED_PAGE_DIR / state['run_id'][:10] / p['adapter'] / f'{sid}.html').as_posix()}`"
              for sid, p in due]
    return lines + [""]


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
    lines += [f"  {sid}: saved page {p['outcome']}" for sid, p in sorted((state.get("saved_pages") or {}).items())]
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
    sub.add_parser("export-due", help="judge which campaign exports are due, and ping the export-due check").add_argument(
        "--dry-run", action="store_true", help="print the verdict against the live API; ping and write nothing")
    args = parser.parse_args(argv)
    ctx = ctx or Context()

    try:
        if args.command == "status":
            return status(ctx, args.run_id)
        if args.command == "export-due":
            return export_due(ctx, dry_run=args.dry_run)
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
