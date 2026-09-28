#!/usr/bin/env python3
"""Ingestion runner — load source registry, dispatch adapters, write output."""

from __future__ import annotations

import argparse
import json
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
# so its historical captures stay attributable.
SCHEDULES = ("weekly", "manual", "retired")


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
) -> tuple[dict, Verdict]:
    """Capture one source and write it ONLY if it passes its floors.

    A failed pull writes nothing, so the previous good capture stays the
    authoritative one, and the verdict is recorded in the run ledger.
    """
    adapter_cls = adapter_cls or get_adapter_class(source_config["adapter"])
    adapter = adapter_cls(source_config, root)
    result = adapter.capture()

    source_id = source_config["id"]
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
    ledger.append(source_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), rows, newest, verdict)
    return result, verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ingestion adapters")
    parser.add_argument("--source", help="Source ID to capture")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Capture all sources")
    parser.add_argument(
        "--registry",
        default="registry/granicus-sources.yaml",
        help="Path to source registry",
    )
    args = parser.parse_args(argv)

    registry_path = ROOT / args.registry
    sources = load_sources(registry_path)

    try:
        targets = resolve_sources(sources, source=args.source, all_sources=args.all_sources)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        with run_lock(ROOT):  # the ledger and identity map are read-modify-write
            return _capture(targets)
    except RunLockHeld as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def _capture(targets: list[dict]) -> int:
    ledger = RunLedger(ROOT / LEDGER_PATH)
    identity = MeetingIdentityMap(ROOT / IDENTITY_PATH)
    # First scheduled run: judge against the last manual captures, not "any > 0".
    for sid in seed_ledger(ledger, targets, ROOT / "data" / "extracted"):
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
        print(f"  URL: {source_config['url']}")

        try:
            result, verdict = run_source(source_config, ROOT, ledger=ledger, today=today, identity=identity)
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
