#!/usr/bin/env python3
"""Seed and reset the ingestion run ledger's baselines.

Seeding. Without a baseline, the first scheduled run could only check
rows > 0; a pull that silently lost 90% of a source would become the new
"last good". Seeding from data/extracted/<source>/<date>.json (the April-June
manual captures) lets the very first scheduled run be judged against real
history. A capture is skipped, not trusted, when its filename is not a date
or when it holds categories the source's current ``categories`` config
excludes (it was captured under a wider scope, so its row count is no floor).

Resetting. A rejected run never becomes a baseline, so a source whose scope
legitimately shrank fails its row floor forever. After checking the smaller
pull by hand, the operator resets it:

  python scripts/ingest_baseline.py --reset corte-madera-town-council \\
      --reason "now Town Council only; 252 rows checked against the site"

That appends an audited ``reset`` entry (reason, time, previous baseline) to
data/ingest-runs/ledger.jsonl. ``--rows`` defaults to the source's latest
ledger entry, i.e. the rejected pull the operator just reviewed. The floors
then ignore everything before the reset.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest_guard import RunLedger, Verdict, newest_past_date  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = Path("data") / "ingest-runs" / "ledger.jsonl"


def _capture_day(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def _out_of_scope(source: dict, meetings: list[dict]) -> set[str]:
    allowed = source.get("categories")
    if allowed is None:
        return set()
    return {m["category"] for m in meetings if m.get("category")} - set(allowed)


def seed_ledger(ledger: RunLedger, sources: list[dict], extracted_root: Path) -> list[str]:
    """Add one seed entry per source that has captures but no ledger history.

    Idempotent, and never overrides a real run: sources already in the ledger
    are skipped. Seeds from the newest dated capture whose scope matches the
    current config. Returns the ids seeded.
    """
    seeded: list[str] = []
    for source in sources:
        sid = source["id"]
        if ledger.last_good(sid) is not None:
            continue
        dated = [p for p in (Path(extracted_root) / sid).glob("*.json") if _capture_day(p)]
        for capture in sorted(dated, reverse=True):
            result = json.loads(capture.read_text())
            meetings = result.get("meetings") or []
            extra = _out_of_scope(source, meetings)
            if extra:
                print(f"  {sid}: not seeding from {capture.name}; it holds categories outside the "
                      f"current config ({', '.join(sorted(extra))})", file=sys.stderr)
                continue
            rows = result.get("pulled_rows") or len(meetings) or len(result.get("artifacts") or [])
            newest = newest_past_date(meetings, _capture_day(capture))
            ledger.append(sid, f"seed:{capture.name}", rows, newest, Verdict(ok=True))
            seeded.append(sid)
            break
    return seeded


def _registered_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for registry in (root / "registry").glob("*-sources.yaml"):
        ids.update(s["id"] for s in (yaml.safe_load(registry.read_text()) or {}).get("sources", []))
    return ids


def reset_baseline(ledger: RunLedger, source_id: str, reason: str, rows: int | None) -> dict:
    if rows is None:
        latest = ledger.latest(source_id)
        if latest is None:
            raise ValueError(f"{source_id} has no ledger history; pass --rows")
        rows = latest["rows"]
    return ledger.reset(source_id, rows=rows, reason=reason,
                        run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset a source's ingestion floor baseline")
    parser.add_argument("--reset", metavar="SOURCE_ID", required=True)
    parser.add_argument("--reason", required=True, help="why the old baseline is wrong (audited)")
    parser.add_argument("--rows", type=int, default=None,
                        help="new baseline rows (default: the source's latest ledger entry)")
    args = parser.parse_args(argv)
    if args.reset not in _registered_ids(ROOT):
        print(f"Error: unknown source {args.reset!r} (not in registry/*-sources.yaml)", file=sys.stderr)
        return 1
    ledger = RunLedger(ROOT / LEDGER_PATH)
    try:
        entry = reset_baseline(ledger, args.reset, args.reason, args.rows)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{args.reset}: baseline {entry['previous_baseline']} -> {entry['rows']} ({entry['reset']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
