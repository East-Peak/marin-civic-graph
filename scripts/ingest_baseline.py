"""Seed the ingestion run ledger from the last manual captures.

Without a baseline, the first scheduled run could only check rows > 0; a pull
that silently lost 90% of a source would become the new "last good". Seeding
from data/extracted/<source>/<date>.json (the April-June manual captures) lets
the very first scheduled run be judged against real history.
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest_guard import RunLedger, Verdict, newest_past_date
from datetime import date


def seed_ledger(ledger: RunLedger, sources: list[dict], extracted_root: Path) -> list[str]:
    """Add one seed entry per source that has captures but no ledger history.

    Idempotent, and never overrides a real run: sources already in the ledger
    are skipped. Returns the ids seeded.
    """
    seeded: list[str] = []
    for source in sources:
        sid = source["id"]
        if ledger.last_good(sid) is not None:
            continue
        captures = sorted((Path(extracted_root) / sid).glob("*.json"))
        if not captures:
            continue
        latest = captures[-1]
        result = json.loads(latest.read_text())
        meetings = result.get("meetings") or []
        rows = len(meetings) if meetings else len(result.get("artifacts") or [])
        capture_day = date.fromisoformat(latest.stem[:10])
        newest = newest_past_date(meetings, capture_day)
        ledger.append(sid, f"seed:{latest.name}", rows, newest, Verdict(ok=True))
        seeded.append(sid)
    return seeded
