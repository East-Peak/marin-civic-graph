"""Automatic preparation of landed campaign exports: from "a ZIP is in data/raw" to "a plan is ready to apply".

Runs inside the weekly refresh, under its lock, after the week's loads, and never writes the live graph. Each run
re-verifies what is applied and published against a fresh read-only export and the current published SQLite, builds
a complete replacement bundle across every source and year, and drives it through every gate: normalize, reconcile,
plan (with its candidate verification), baseline and candidate bakes from the same export and a frozen
configuration, and the privacy scan. A gate that fails holds the preparation, named, with the recovery action; the
operator approves a prepared plan by telling Claude "apply". Design: docs/specs/2026-10-06-campaign-export-
freshness-design.md, section 3. Every external step runs through the weekly runner's injected step function.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import yaml

from campaign_ledger import _inside_git_checkout, _protected_dirs
from cf_inventory import SourceInventory
from cf_migration_plan import NETFILE_FLOW_ID

# Everything whose change can change a preparation's result: its fingerprint is part of the no-op key.
CONFIG_FILES = (
    "registry/netfile-sources.yaml", "registry/node-types.json", "registry/contributor-detail-reviewed.json",
    *(f"scripts/{name}" for name in (
        "campaign_ledger.py", "normalize_campaign_finance.py", "contributor_detail.py", "public_exposure.py",
        "public_props.py", "cf_migration_plan.py", "bake_public_substrate.py", "scan_public_substrate.py",
        "cf_freshness.py", "cf_inventory.py", "cf_prepare.py", "export_live_graph.py")),
)
ATTACH_OVERLAY = "data/review/attach"
PUBLISHED_SQLITE = "data/exports/public-substrate.sqlite"
DATA_GATES = ("normalize", "reconcile", "plan", "scan")

RECOVERY = {
    "normalize": "the normalizer rejected the bundle (see {log}); usually a corrupt or unexpected export: download "
                 "that year again into data/raw/<source>/<today>/, or tell Claude",
    "reconcile": "filings did not reconcile (see {detail}); tell Claude: it needs reviewed exception or version "
                 "evidence, never an automatic one",
    "plan": "the migration plan failed its candidate verification (see {detail}); tell Claude",
    "coverage": "land the exports those years came from in data/raw, or tell Claude if those flows should go",
    "freshness": "the candidate bake could not verify its own bundle (see {log}); tell Claude",
    "scan": "the privacy scan did not pass (see {detail}); tell Claude (no exception is ever generated "
            "automatically)",
    "fallback": "a held year leaves no complete bundle: the live graph matches no earlier preparation to keep for "
                "this source. Fix the held file (above); or land the exports the live graph was built from",
}


@dataclass
class StepResult:
    returncode: int
    output: str
    timed_out: bool = False


Step = Callable[[str, list[str]], StepResult]


@dataclass
class Prep:
    """What one preparation run needs from the weekly runner."""
    root: Path
    step: Step  # (name, cmd) -> result, logged under the weekly run's logs/
    python: str
    run_id: str
    today: date
    at: str  # ISO timestamp, for the state
    staging: Path  # $OPEN_MARIN_CF_STAGING
    sources: list[dict]
    inventories: dict[str, SourceInventory]
    state: dict  # the campaign-finance state (mutated in place)


@dataclass
class Outcome:
    status: str  # nothing | noop | applied | applied_awaiting_publish | prepared | held | transient
    message: str
    items: list[tuple[str, str, str]] = field(default_factory=list)  # (source id or "*", label, why) for the alarm
    problems: list[str] = field(default_factory=list)  # for the main heartbeat (transient failures)


class Transient(Exception):
    """An infrastructure failure (timeout, crash, disk): retried next run, reported on the main heartbeat."""


class Held(Exception):
    def __init__(self, gate: str, reason: str, detail: str = "", log: str = ""):
        super().__init__(f"{gate}: {reason}")
        self.gate, self.reason, self.detail, self.log = gate, reason, detail, log

    def action(self) -> str:
        return RECOVERY[self.gate].format(detail=self.detail, log=self.log)


def check_staging(staging: Path, root: Path) -> Path:
    """The staging root, resolved; refused (before anything is written) inside the repo, its data or any checkout."""
    out = Path(staging).expanduser().resolve()
    for protected in _protected_dirs(root):
        if out == protected or protected in out.parents:
            raise Transient(f"the staging root {out} is inside {protected}; set OPEN_MARIN_CF_STAGING elsewhere")
    checkout = _inside_git_checkout(out)
    if checkout is not None:
        raise Transient(f"the staging root {out} is inside the git checkout {checkout}")
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(root: Path) -> str:
    """sha256 over every configuration and code input of a preparation (absent files count as absent)."""
    digest = hashlib.sha256()
    paths = [root / name for name in CONFIG_FILES]
    overlay = root / ATTACH_OVERLAY
    paths += sorted(overlay.rglob("*")) if overlay.is_dir() else []
    for path in paths:
        if path.is_dir():
            continue
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(_sha256(path).encode() if path.is_file() else b"absent")
    return digest.hexdigest()


def _export_sha(export: Path) -> str:
    return hashlib.sha256((_sha256(export / "nodes.jsonl") + _sha256(export / "edges.jsonl")).encode()).hexdigest()


def published_bundle_id(root: Path) -> str | None:
    """The bundle the currently published artifact represents (its campaign_freshness), read-only."""
    path = root / PUBLISHED_SQLITE
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'campaign_freshness'").fetchone()
        return json.loads(row[0]).get("bundle_id") if row else None
    except (sqlite3.Error, ValueError, AttributeError):
        return None


# --- the effective bundle manifest ---------------------------------------------------------------------


def _identity(source: dict) -> list:
    """What a source's manifest says, without where its files happen to sit."""
    return [[year, e["status"], e.get("sha256"), e.get("capture"), bool(e.get("held"))]
            for year, e in sorted(source["years"].items())]


def bundle_id(manifest: dict) -> str:
    rows = [[sid, _identity(source)] for sid, source in sorted(manifest.items())]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def _kept(entry: dict) -> dict:
    """An applied manifest entry reused as is: its file is the immutable staged copy, not data/raw."""
    return {**entry, "file": entry.get("staged", entry.get("file"))}


def _from_inventory(prep: Prep, source: dict, inv: SourceInventory, applied: dict | None) -> dict:
    """One source's manifest from what data/raw offers; years the applied manifest has but data/raw no longer
    offers keep the applied file (absence never means retirement)."""
    kept = (applied or {}).get("years", {})
    years = {year: {**_kept(e), "kept": "outside backfill_from now"}  # a narrower backfill never retires a year
             for year, e in kept.items() if year not in inv.years and e["status"] == "export"}
    for year, entry in inv.years.items():
        if entry.status == "selected":
            ref = entry.selected
            years[year] = {"status": "export", "path": ref.path, "sha256": ref.sha256, "capture": ref.capture,
                           "file": str(prep.root / "data" / "raw" / ref.path), "held": False}
        elif kept.get(year, {}).get("status") == "export":
            years[year] = {**_kept(kept[year]), "held": False, "kept": "no longer in data/raw"}
        elif entry.status == "pinned":
            ref = entry.pinned
            years[year] = {"status": "unavailable", "reason": "only a saved HTML page", "path": ref.path,
                           "sha256": ref.sha256, "capture": ref.capture, "pinned": True,
                           "file": str(prep.root / "data" / "raw" / ref.path), "held": False}
        else:
            reason = "confirmed unavailable" if entry.confirmed else "no export on file"
            years[year] = {"status": "unavailable", "reason": reason, "held": False}
    config = {k: v for k, v in source.items() if k not in ("unavailable_inputs", "confirmed_unavailable", "years")}
    return {"name": source["name"], "jurisdiction_id": source["jurisdiction_id"], "config": config, "years": years}


def effective_manifest(prep: Prep, applied: dict | None) -> tuple[dict, dict[str, Held]]:
    """The complete replacement manifest, and the sources held for want of an applied fallback."""
    manifest, held = {}, {}
    applied_sources = (applied or {}).get("manifest", {})
    for source in prep.sources:
        sid, inv = source["id"], prep.inventories[source["id"]]
        held_years = [y for y, e in inv.years.items() if e.status == "held"]
        if not held_years:
            manifest[sid] = _from_inventory(prep, source, inv, applied_sources.get(sid))
        elif sid in applied_sources:  # keep the applied selection for the whole source until the file is fixed
            kept = json.loads(json.dumps(applied_sources[sid]))
            kept["years"] = {year: _kept(e) for year, e in kept["years"].items()}
            for year in held_years:
                kept["years"].setdefault(year, {"status": "unavailable", "reason": "no export on file"})
                kept["years"][year]["held"] = True
            manifest[sid] = kept
        else:
            held[sid] = Held("fallback", f"{', '.join(held_years)} held, and no applied preparation to keep")
    for sid, source in applied_sources.items():  # a source the registry no longer lists keeps what is applied
        if sid not in manifest and sid not in held:
            manifest[sid] = {**source, "years": {year: _kept(e) for year, e in source["years"].items()}}
    return manifest, held


def changed_sources(manifest: dict, applied: dict | None) -> list[str]:
    before = (applied or {}).get("manifest", {})
    return sorted(sid for sid, source in manifest.items()
                  if sid not in before or _identity(before[sid]) != _identity(source))


# --- one attempt through every gate --------------------------------------------------------------------


def _run(prep: Prep, name: str, cmd: list[str], *, data_gate: str | None = None, detail: str = "",
         evidence: Path | None = None, verdict: str | None = None) -> StepResult:
    """Run a step. A gate's own rejection (it exited 1 having written its verdict file, or printed its verdict
    marker) holds; a timeout, a signal, a traceback or a missing verdict is an infrastructure failure:
    transient, retried next run."""
    result = prep.step(name, cmd)
    if result.timed_out:
        raise Transient(f"{name} timed out (logs/cf-{name}.log)")
    if result.returncode != 0:
        tail = next((ln.strip() for ln in reversed(result.output.splitlines()) if ln.strip()), "")
        crashed = (result.returncode < 0 or "Traceback (most recent call last)" in result.output
                   or (evidence is not None and not evidence.is_file())
                   or (verdict is not None and verdict not in result.output))
        if data_gate and not crashed:
            raise Held(data_gate, f"{name} exited {result.returncode}: {tail}", detail, f"logs/cf-{name}.log")
        raise Transient(f"{name} exited {result.returncode}: {tail} (logs/cf-{name}.log)")
    return result


def _stage_inputs(prep: Prep, manifest: dict, raw: Path, registry: Path, date_dir: str) -> None:
    """Copy each file into one capture dir (re-hashed), and write the staging registry the normalizer reads."""
    configs = {s["id"]: s for s in prep.sources}
    sources = []
    for sid, source in sorted(manifest.items()):
        years, pins = [], []
        for year, entry in sorted(source["years"].items()):
            if "file" not in entry:
                continue
            dest = raw / sid / date_dir / f"{year}.zip"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["file"], dest)
            if _sha256(dest) != entry["sha256"]:
                raise Held("normalize", f"{entry['path']} changed while it was copied", log="")
            entry["staged"] = str(dest)
            years.append(year)
            if entry.get("pinned"):
                pins.append({"capture": date_dir, "file": f"{year}.zip", "sha256": entry["sha256"]})
        if years:  # a source the registry no longer lists stages with the configuration it was applied under
            config = source.get("config") or {k: v for k, v in configs[sid].items()
                                              if k not in ("unavailable_inputs", "confirmed_unavailable")}
            sources.append({**config, "years": years, "unavailable_inputs": pins})
    registry.write_text(yaml.safe_dump({"sources": sources}, sort_keys=True))


def _reconciled(bundle: Path, sid: str) -> None:
    path = bundle / sid / "reconciliation.json"
    recon = json.loads(path.read_text())
    bad = [g for g in recon.get("groups", []) if g.get("status") in ("mismatched", "ambiguous")]
    if recon.get("errors") or bad:
        raise Held("reconcile", f"{sid}: {len(bad)} mismatched/ambiguous filing group(s), "
                                f"{recon.get('errors')} error(s)", detail=str(path))


def uncovered_retirements(export: Path, plan: Path, bundle: Path, manifest: dict) -> list[str]:
    """Campaign flows the plan retires whose date falls in a year no export of their source in this bundle
    covers: retired for missing coverage, not by an amendment. Undated flows, and flows whose filer no filing in
    the bundle names, count as uncovered (fail closed)."""
    retire = set(json.loads((plan / "ops.json").read_text()).get("retire_nodes", []))
    if not retire:
        return []
    years = {sid: {y for y, e in src["years"].items() if e["status"] == "export"} for sid, src in manifest.items()}
    filers: dict[str, set[str]] = {}
    for sid in manifest:
        filings = bundle / sid / "filings.jsonl"
        for line in filings.read_text().splitlines() if filings.is_file() else ():
            filers.setdefault(str(json.loads(line).get("filer_id")), set()).add(sid)
    uncovered = []
    with (export / "nodes.jsonl").open() as fh:
        for line in fh:
            node = json.loads(line)
            if node.get("id") not in retire:
                continue
            day = str((node.get("properties") or {}).get("flow_date") or "")
            match = NETFILE_FLOW_ID.match(node["id"])
            sources = filers.get(match.group(1) if match else "", set())
            if not any(day[:4] in years[sid] for sid in sources):
                uncovered.append(node["id"])
    return sorted(uncovered)


ARTIFACTS = ("bundle/selection.json", "bundle/*/nodes.jsonl", "bundle/*/edges.jsonl", "bundle/*/ledger.jsonl",
             "bundle/*/manifest.json", "bundle/*/reconciliation.json", "bundle/*/filings.jsonl", "plan/ops.json",
             "plan/migration-report.json", "plan/migration-plan.md", "plan/candidate/nodes.jsonl",
             "plan/candidate/edges.jsonl", "scan.json")


def artifacts(dir_: Path) -> dict[str, str]:
    """sha256 of every file a prepared plan stands on: a no-op needs each one unchanged."""
    return {str(path.relative_to(dir_)): _sha256(path) for pattern in ARTIFACTS for path in sorted(dir_.glob(pattern))}


def _summary(run: Path, attempt: Path, manifest: dict) -> str:
    report = json.loads((attempt / "plan" / "migration-report.json").read_text())
    scan = json.loads((attempt / "scan.json").read_text())
    s = report["summary"]
    lines = [f"# Campaign export preparation {run.name}", "",
             "Prepared (NOT applied). Tell Claude \"apply\" to apply the plan; it follows the plan's procedure.", "",
             f"- Plan: `{attempt / 'plan' / 'migration-plan.md'}`",
             f"- MoneyFlows: {s['added_nodes'].get('MoneyFlow', 0)} added, {s['retired_nodes']} retired, "
             f"{s['changed_nodes']} changed",
             f"- New actors: {', '.join(f'{k} {v}' for k, v in sorted(s['added_nodes'].items()) if k != 'MoneyFlow') or 'none'}",
             f"- Edges: {s['added_edges']} added, {s['retired_edges']} retired",
             "", "| flow type | before | after | delta |", "|---|---|---|---|",
             *[f"| {ft} | {a['baseline']} | {a['candidate']} | {a['delta']} |" for ft, a in report["amounts"].items()],
             "", f"- Privacy scan: {'PASS' if scan.get('passed') else 'FAIL'} (gate A {len(scan['gate_a_prohibited_hits'])}, "
             f"gate B {scan['gate_b_unexplained']} unexplained, gate C {len(scan['gate_c_reconciliation_problems'])}; "
             f"records added {len(scan.get('gate_b_added_records', []))}, removed "
             f"{len(scan.get('gate_b_removed_records', []))})", "", "## Files", ""]
    for sid, source in sorted(manifest.items()):
        for year, e in sorted(source["years"].items()):
            what = (f"{e['path']} (downloaded {e['capture']}){' — newer download held' if e.get('held') else ''}"
                    if e["status"] == "export" else f"not available ({e.get('reason')})")
            lines.append(f"- {source['name']} {year}: {what}")
    if s["retired_nodes"] > 25:
        lines += ["", f"**Check before applying:** this plan retires {s['retired_nodes']} MoneyFlows. A large "
                      "retirement usually means data/raw lacks exports the live graph was built from."]
    return "\n".join(lines) + "\n"


def attempt(prep: Prep, export: Path, dir_: Path, manifest: dict, applied: dict | None, config_dir: Path) -> dict:
    """Drive one manifest through every gate. Returns the record; raises Held or Transient."""
    manifest = json.loads(json.dumps(manifest))  # this attempt's own copy: staging records where its files sit
    raw, registry, bundle = dir_ / "raw", dir_ / "registry.yaml", dir_ / "bundle"
    label = dir_.name
    raw.mkdir(parents=True)
    _stage_inputs(prep, manifest, raw, registry, prep.today.isoformat())
    py = prep.python
    _run(prep, f"normalize-{label}", [py, "scripts/normalize_campaign_finance.py", "--all", "--registry",
                                      str(registry), "--input-root", str(raw), "--output-root", str(bundle),
                                      "--reviewed", str(config_dir / "contributor-detail-reviewed.json")],
         data_gate="normalize", verdict="ERROR:")
    for sid in sorted(manifest):
        if (bundle / sid).is_dir():
            _reconciled(bundle, sid)
    bid = bundle_id(manifest)
    selection = {"bundle_id": bid, "sources": manifest}
    (bundle / "selection.json").write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
    record = {"bundle_id": bid, "bundle": str(bundle), "manifest": manifest, "dir": str(dir_)}
    if _run_ok(prep, f"check-live-{label}", [py, "scripts/cf_migration_plan.py", "--check-live", str(export),
                                             "--bundle", str(bundle)]):
        return {**record, "outcome": "applied"}
    plan = dir_ / "plan"
    _run(prep, f"plan-{label}", [py, "scripts/cf_migration_plan.py", "--baseline", str(export), "--bundle",
                                 str(bundle), "--out", str(plan)],
         data_gate="plan", detail=str(plan / "migration-report.json"), evidence=plan / "migration-report.json")
    uncovered = uncovered_retirements(export, plan, bundle, manifest)
    if uncovered:
        raise Held("coverage", f"the plan retires {len(uncovered)} campaign flow(s) dated in years no export in "
                               f"this bundle covers, e.g. {', '.join(uncovered[:5])}", detail=str(plan / "ops.json"))
    bake = [py, "scripts/bake_public_substrate.py", "--source", "live-export", "--attach-overlay-dir",
            str(config_dir / "attach"), "--registry", str(config_dir / "node-types.json")]
    previous = [*(["--campaign-bundle", applied["bundle"]] if applied else [])]
    _run(prep, f"bake-baseline-{label}", [*bake, "--live-export-dir", str(export), *previous,
                                          "--sqlite", str(dir_ / "bake/baseline/public.sqlite"),
                                          "--report", str(dir_ / "bake/baseline/report.json")])
    _run(prep, f"bake-candidate-{label}", [*bake, "--live-export-dir", str(plan / "candidate"),
                                           "--campaign-bundle", str(bundle),
                                           "--sqlite", str(dir_ / "bake/candidate/public.sqlite"),
                                           "--report", str(dir_ / "bake/candidate/report.json")])
    if json.loads((dir_ / "bake/candidate/report.json").read_text()).get(
            "campaign_freshness", {}).get("verified_bundle") != str(bundle):
        raise Held("freshness", "the candidate bake did not verify the bundle it was baked from",
                   log=f"logs/cf-bake-candidate-{label}.log")
    _run(prep, f"scan-{label}", [py, "scripts/scan_public_substrate.py", "--sqlite",
                                 str(dir_ / "bake/candidate/public.sqlite"), "--baseline",
                                 str(dir_ / "bake/baseline/public.sqlite"), "--bundle", str(bundle), "--export",
                                 str(plan / "candidate"), "--out", str(dir_ / "scan.json")],
         data_gate="scan", detail=str(dir_ / "scan.json"), evidence=dir_ / "scan.json")
    return {**record, "outcome": "prepared", "plan": str(plan / "migration-plan.md"), "artifacts": artifacts(dir_)}


def _run_ok(prep: Prep, name: str, cmd: list[str]) -> bool:
    result = prep.step(name, cmd)
    if result.timed_out:
        raise Transient(f"{name} timed out (logs/cf-{name}.log)")
    return result.returncode == 0


# --- the run --------------------------------------------------------------------------------------------


def _freeze_config(prep: Prep, config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    for name in ("registry/node-types.json", "registry/contributor-detail-reviewed.json"):
        shutil.copyfile(prep.root / name, config_dir / Path(name).name)
    overlay = prep.root / ATTACH_OVERLAY
    if overlay.is_dir():
        shutil.copytree(overlay, config_dir / "attach")
    else:
        (config_dir / "attach").mkdir()
        for name in ("nodes.jsonl", "edges.jsonl"):
            (config_dir / "attach" / name).write_text("")


def _verify_applied(prep: Prep, export: Path, export_sha: str) -> dict | None:
    """The bundle the live graph holds now, of the ones the state names (re-checked every run)."""
    state = prep.state
    seen, candidates = set(), []
    for record in (state.get("prepared"), state.get("applied")):
        if record and record.get("bundle") and record["bundle"] not in seen and Path(record["bundle"]).is_dir():
            seen.add(record["bundle"])
            candidates.append(record)
    for i, record in enumerate(candidates):
        if _run_ok(prep, f"check-live-recorded-{i}", [prep.python, "scripts/cf_migration_plan.py", "--check-live",
                                                     str(export), "--bundle", record["bundle"]]):
            applied = {k: record[k] for k in ("bundle_id", "bundle", "manifest")}
            state["applied"] = {**applied, "verified_export_sha256": export_sha, "at": prep.at}
            return state["applied"]
    if state.get("applied"):
        state["applied_unverified"] = {**state["applied"], "unverified_at": prep.at}
        state["applied"] = None
    return None


def _record_published(prep: Prep, applied: dict | None) -> bool:
    published = published_bundle_id(prep.root)
    sqlite = prep.root / PUBLISHED_SQLITE
    if applied and published == applied["bundle_id"]:
        prep.state["published"] = {"bundle_id": published, "sqlite_sha256": _sha256(sqlite), "at": prep.at}
        return True
    prep.state["published"] = ({"bundle_id": published, "sqlite_sha256": _sha256(sqlite), "at": prep.at}
                               if published else None)
    return False


def prepare(prep: Prep) -> Outcome:
    """One preparation run. Never writes the live graph; raises nothing but programming errors."""
    state = prep.state
    try:
        return _prepare(prep)
    except Transient as exc:
        state["prepared"] = {**(state.get("prepared") or {}), "last_transient": str(exc), "transient_at": prep.at}
        return Outcome("transient", str(exc), items=[("*", "preparation", f"preparation stopped: {exc}; "
                                                                          "retried next weekly run")],
                       problems=[f"campaign preparation: {exc}"])


def _prepare(prep: Prep) -> Outcome:
    state = prep.state
    offered = any(e.status in ("selected", "pinned") for inv in prep.inventories.values() for e in inv.years.values())
    if not offered and not state.get("applied") and not state.get("prepared"):
        return Outcome("nothing", "no campaign export has landed yet")

    run = check_staging(prep.staging, prep.root) / prep.run_id
    if run.exists():
        raise Transient(f"{run} already exists")
    config_dir = run / "config"
    config = fingerprint(prep.root)
    _freeze_config(prep, config_dir)
    export = run / "export"
    _run(prep, "export", [prep.python, "scripts/export_live_graph.py", "--backup", "--out-dir", str(export)])
    export_sha = _export_sha(export)

    applied = _verify_applied(prep, export, export_sha)
    published = _record_published(prep, applied)
    manifest, fallback_held = effective_manifest(prep, applied)
    items = [(sid, "preparation", f"held: {h.reason}. Recovery: {h.action()}") for sid, h in fallback_held.items()]
    if fallback_held:
        state["prepared"] = {"outcome": "held", "gate": "fallback", "at": prep.at, "dir": str(run),
                             "sources_held": {sid: h.reason for sid, h in fallback_held.items()}}
        return Outcome("held", "a held year leaves no complete bundle", items=items)

    bid = bundle_id(manifest)
    if applied and applied["bundle_id"] == bid:
        if published:
            return Outcome("noop", "applied and published", items=items)
        return Outcome("applied_awaiting_publish", "applied; the next weekly run publishes it",
                       items=[*items, ("*", "publish", "applied to the graph; the next weekly run publishes it "
                                                       "(nothing to do)")])
    key = [bid, config, export_sha]
    previous = state.get("prepared") or {}
    if (previous.get("outcome") == "prepared" and previous.get("key") == key
            and previous.get("artifacts") and artifacts(Path(previous["dir"])) == previous["artifacts"]):
        return Outcome("noop", "the prepared plan is still valid", items=[*items, _awaiting(previous)])

    # Everything that changed, together; if a data gate holds that and several sources changed, each changed
    # source alone on top of the applied selection, so one bad source never blocks another. The first that passes
    # alone is prepared; another that also passes alone is prepared on a later run, on top of it.
    changed = changed_sources(manifest, applied)
    record, failures, waiting = None, {}, []
    try:
        record = attempt(prep, export, run / "attempt-all", manifest, applied, config_dir)
    except Held as held:
        failures["all"] = held
        for sid in changed if len(changed) > 1 and applied else ():
            try:
                passed = attempt(prep, export, run / f"attempt-{sid}", {**applied["manifest"], sid: manifest[sid]},
                                 applied, config_dir)
            except Held as alone_held:
                failures[sid] = alone_held
                continue
            if record is None:
                record = passed
            else:
                waiting.append(sid)
    if fingerprint(prep.root) != config:
        raise Transient("the configuration changed during the preparation")

    alone = {sid: h for sid, h in failures.items() if sid != "all"}
    held_items = [(sid, "preparation", f"held at {h.gate}: {h.reason}. Recovery: {h.action()}")
                  for sid, h in alone.items()]
    held_items += [(sid, "preparation", "passes alone but not together with the plan below; it is prepared "
                                        "again once that plan is applied") for sid in waiting]
    if record is None and not alone:
        h = failures["all"]
        held_items = [("*", "preparation", f"held at {h.gate}: {h.reason}. Recovery: {h.action()}")]
    if record is None:
        gate = failures["all"].gate
        state["prepared"] = {"outcome": "held", "gate": gate, "reason": failures["all"].reason, "key": key,
                             "at": prep.at, "dir": str(run)}
        return Outcome("held", f"held at {gate}", items=[*items, *held_items])
    if record["outcome"] == "applied":
        state["applied"] = {**{k: record[k] for k in ("bundle_id", "bundle", "manifest")},
                            "verified_export_sha256": export_sha, "at": prep.at}
        state["prepared"] = {**record, "key": key, "at": prep.at}
        published = _record_published(prep, state["applied"])
        if published:
            return Outcome("noop", "applied and published", items=[*items, *held_items])
        return Outcome("applied_awaiting_publish", "already applied; the next weekly run publishes it",
                       items=[*items, *held_items, ("*", "publish", "applied to the graph; the next weekly run "
                                                                    "publishes it (nothing to do)")])
    summary = Path(record["dir"]) / "summary.md"
    summary.write_text(_summary(run, Path(record["dir"]), record["manifest"]))
    state["prepared"] = {**record, "key": key, "summary": str(summary), "at": prep.at,
                         "held_sources": {sid: f"{h.gate}: {h.reason}" for sid, h in alone.items()}}
    return Outcome("prepared", f"plan ready at {record['plan']}",
                   items=[*items, *held_items, _awaiting(state["prepared"])])


def _awaiting(record: dict) -> tuple[str, str, str]:
    return ("*", "plan", f"export processed; plan ready at {record['plan']} (summary: {record.get('summary')}); "
                         "tell Claude 'apply'")


def standing_items(state: dict) -> list[tuple[str, str, str]]:
    """The alarm's items from the recorded state alone (when no preparation ran this time)."""
    prepared, applied, published = state.get("prepared") or {}, state.get("applied"), state.get("published")
    applied_id = (applied or {}).get("bundle_id")
    items = []
    if prepared.get("outcome") == "prepared" and prepared.get("bundle_id") != applied_id:
        items.append(_awaiting(prepared))
    elif applied_id and (published or {}).get("bundle_id") != applied_id:
        items.append(("*", "publish", "applied to the graph; the next weekly run publishes it (nothing to do)"))
    if prepared.get("outcome") == "held":
        items.append(("*", "preparation", f"held at {prepared.get('gate')}: {prepared.get('reason') or ''} "
                                          f"(see {prepared.get('dir')})"))
    return items


def bake_bundles(state: dict) -> list[str]:
    """The bundles the weekly bake may publish freshness from, newest first; the bake verifies each itself."""
    out = []
    for record in (state.get("prepared"), state.get("applied")):
        bundle = (record or {}).get("bundle")
        if bundle and bundle not in out and Path(bundle).is_dir():
            out.append(bundle)
    return out
