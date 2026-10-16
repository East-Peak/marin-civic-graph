#!/usr/bin/env python3
"""Ingestion runner — load source registry, dispatch adapters, write output."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import get_adapter_class
from ingest_guard import BASELINE_WINDOW, Floors, RunLedger, Verdict, evaluate, newest_past_date, write_if_ok
from meeting_identity import MeetingIdentityMap, merge_duplicate_meetings
from ingest_baseline import seed_ledger
from robots_gate import RobotsGate, RobotsRefused
from run_lock import RunLockHeld, run_lock

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = Path("data") / "ingest-runs" / "ledger.jsonl"
IDENTITY_PATH = Path("data") / "ingest-runs" / "meeting-identity.json"


def load_sources(registry_path: Path) -> list[dict]:
    with open(registry_path) as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


# weekly: runs on the schedule (`--all`). manual: kept for one-off `--source`
# runs (e.g. needs reconciliation first). retired: source is dead; kept only
# so its historical captures stay attributable. saved-page: its host's robots.txt
# disallows us, so it is never fetched; the operator saves the listing page by hand
# and `--saved-page` (or the weekly run, which finds it) parses it.
SCHEDULES = ("weekly", "manual", "retired", "saved-page")
SAVED_PAGE_ADAPTERS = ("granicus",)
SAVED_PAGE_RE = re.compile(r"data/raw/manual/(\d{4}-\d{2}-\d{2})/(?P<adapter>[a-z_]+)/(?P<sid>[^/]+)\.html")


def saved_page_path(root: Path, source_config: dict, path: Path) -> Path:
    """`path`, if it is where this source's saved page belongs: data/raw/manual/<YYYY-MM-DD>/<adapter>/<id>.html."""
    if source_config["adapter"] not in SAVED_PAGE_ADAPTERS:
        raise ValueError(f"{source_config['id']} ({source_config['adapter']}) does not take saved pages")
    path = Path(path).resolve()
    try:
        rel = path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    match = SAVED_PAGE_RE.fullmatch(rel)
    if not (match and match["adapter"] == source_config["adapter"] and match["sid"] == source_config["id"]):
        raise ValueError(f"a saved page for {source_config['id']} goes at data/raw/manual/<YYYY-MM-DD>/"
                         f"{source_config['adapter']}/{source_config['id']}.html under the root, not {path}")
    if not path.is_file():
        raise ValueError(f"no saved page at {path}")
    return path


def resolve_sources(
    sources: list[dict],
    source: str | None = None,
    all_sources: bool = False,
) -> list[dict]:
    if all_sources:
        return [s for s in sources if s.get("schedule") == "weekly"]
    if source:
        matches = [s for s in sources if s["id"] == source]
        if not matches:
            available = [s["id"] for s in sources]
            raise ValueError(f"Unknown source: {source!r}. Available: {available}")
        return matches
    raise ValueError("Specify --source <id> or --all")


def _row_count(result: dict) -> int:
    # Meeting adapters return meetings[]; bundle adapters (NetFile) artifacts[].
    for key in ("meetings", "artifacts"):
        if isinstance(result.get(key), list):
            return len(result[key])
    return 0


def run_source(
    source_config: dict,
    root: Path,
    *,
    ledger: RunLedger,
    today: date,
    adapter_cls=None,
    identity=None,
    gate: RobotsGate | None = None,
    saved_page: Path | None = None,
) -> tuple[dict, Verdict]:
    """Capture one source and write it ONLY if it passes its floors.

    A failed pull writes nothing, so the previous good capture stays the
    authoritative one, and the verdict is recorded in the run ledger. A request
    the robots gate refused ends the source `robots_disallowed` or
    `robots_unavailable`, even when the adapter caught the refusal itself.
    """
    adapter_cls = adapter_cls or get_adapter_class(source_config["adapter"])
    options = {k: v for k, v in (("gate", gate), ("saved_page", saved_page)) if v is not None}
    adapter = adapter_cls(source_config, root, **options)
    source_id = source_config["id"]
    gate = getattr(adapter, "gate", gate)
    already = len(gate.refusals) if gate is not None else 0
    try:
        result = adapter.capture()
    except RobotsRefused as refusal:
        return _refused(ledger, source_id, refusal, {"meetings": [], "errors": [str(refusal)]})
    if gate is not None and len(gate.refusals) > already:
        return _refused(ledger, source_id, gate.refusals[already], result)

    rows = _row_count(result)
    newest = newest_past_date(result.get("meetings") or [], today)
    verdict = evaluate(
        rows=rows,
        newest=newest,
        last_good_rows=ledger.baseline_rows(source_id),
        baseline=f"the max of the last {BASELINE_WINDOW} good runs",
        today=today,
        floors=Floors.from_config(source_config),
        errors=len(result.get("errors") or []),
    )
    # The ledger and the capture header both carry the pre-merge count, so a
    # baseline seeded from a capture matches one recorded by a run.
    result["pulled_rows"] = rows
    if verdict.ok and result.get("meetings"):
        if identity is not None:
            identity.canonicalize(source_id, result["meetings"])
        result["meetings"] = merge_duplicate_meetings(result["meetings"])
        result["meeting_count"] = len(result["meetings"])
    if write_if_ok(adapter.extracted_path(), json.dumps(result, indent=2) + "\n", verdict) and identity:
        identity.save()
    provenance = {k: result[k] for k in ("raw_origin", "raw_sha256") if k in result}
    if result.get("saved_page"):
        provenance["saved_page"] = result["saved_page"]["path"]
    ledger.append(source_id, _now(), rows, newest, verdict, **provenance)
    return result, verdict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _refused(ledger: RunLedger, source_id: str, refusal: RobotsRefused, result: dict) -> tuple[dict, Verdict]:
    """Nothing is written; the ledger names the outcome and the rule (or robots.txt status) behind it."""
    verdict = Verdict(ok=False, reasons=[str(refusal)])
    ledger.append(source_id, _now(), 0, None, verdict, outcome=refusal.outcome, robots=refusal.detail)
    return result, verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ingestion adapters")
    parser.add_argument("--source", help="Source ID to capture")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Capture all sources")
    parser.add_argument(
        "--registry",
        default="registry/granicus-sources.yaml",
        help="Path to source registry (relative to --root)",
    )
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="Repository root every path resolves under (default: this checkout)")
    parser.add_argument("--saved-page", type=Path,
                        help="Parse this saved listing page instead of fetching (needs --source)")
    parser.add_argument("--robots-cache", type=Path, help="robots.txt cache shared by one run's processes")
    parser.add_argument("--request-log", type=Path, help="Append every request decision here (JSONL)")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    sources = load_sources(root / args.registry)

    try:
        if args.saved_page is not None and not args.source:
            raise ValueError("--saved-page needs --source <id>")
        targets = resolve_sources(sources, source=args.source, all_sources=args.all_sources)
        saved_page = None
        if args.saved_page is not None:
            saved_page = saved_page_path(root, targets[0], args.saved_page)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    gate = RobotsGate(cache_path=args.robots_cache, request_log=args.request_log)
    try:
        with run_lock(root):  # the ledger and identity map are read-modify-write
            return _capture(targets, root, gate, saved_page)
    except RunLockHeld as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def _capture(targets: list[dict], root: Path, gate: RobotsGate, saved_page: Path | None = None) -> int:
    ledger = RunLedger(root / LEDGER_PATH)
    identity = MeetingIdentityMap(root / IDENTITY_PATH)
    # First scheduled run: judge against the last manual captures, not "any > 0".
    for sid in seed_ledger(ledger, targets, root / "data" / "extracted"):
        print(f"  baseline seeded from last manual capture: {sid}")
    today = date.today()
    failed: list[str] = []
    for i, source_config in enumerate(targets):
        if i > 0:
            print("  (waiting 2s between sources)")
            time.sleep(2)

        source_id = source_config["id"]
        print(f"\nCapturing: {source_id}")
        print(f"  Adapter: {source_config['adapter']}")
        print(f"  URL: {source_config['url']}" if saved_page is None else f"  Saved page: {saved_page}")

        try:
            result, verdict = run_source(source_config, root, ledger=ledger, today=today, identity=identity,
                                         gate=gate, saved_page=saved_page)
            print(f"  Variant: {result.get('variant', 'unknown')}")
            print(f"  Meetings: {result.get('meeting_count', 'n/a')}")
            for art, count in sorted(result.get("artifact_counts", {}).items()):
                print(f"    {art}: {count}")
            if result.get("errors"):
                print(f"  Errors: {len(result['errors'])}")
                for err in result["errors"]:
                    print(f"    - {err}")
            if not verdict.ok:
                failed.append(source_id)
                print("  REJECTED (previous good capture kept):", file=sys.stderr)
                for reason in verdict.reasons:
                    print(f"    - {reason}", file=sys.stderr)
        except Exception as e:
            failed.append(source_id)
            print(f"  FAILED: {e}", file=sys.stderr)

    if failed:
        print(f"\n{len(failed)} source(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
