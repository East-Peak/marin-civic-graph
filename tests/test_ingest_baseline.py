"""Seed the run ledger from the last manual captures, so the first scheduled
run is judged against real history instead of accepting anything > 0 rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ingest_baseline import seed_ledger  # noqa: E402
from ingest_guard import RunLedger  # noqa: E402


def _capture(root, src, day, n):
    p = root / src / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"meeting_count": n, "meetings": [{"date": day}] * n}))


def test_seeds_each_source_from_its_latest_capture(tmp_path):
    extracted = tmp_path / "extracted"
    _capture(extracted, "novato-city-council", "2026-01-10", 380)
    _capture(extracted, "novato-city-council", "2026-04-14", 409)
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    seeded = seed_ledger(ledger, [{"id": "novato-city-council"}, {"id": "never-captured"}], extracted)
    assert seeded == ["novato-city-council"]
    good = ledger.last_good("novato-city-council")
    assert good["rows"] == 409 and good["newest"] == "2026-04-14"
    assert good["run_at"].startswith("seed:")


def test_seeding_is_idempotent_and_never_overrides_real_runs(tmp_path):
    extracted = tmp_path / "extracted"
    _capture(extracted, "novato-city-council", "2026-04-14", 409)
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    seed_ledger(ledger, [{"id": "novato-city-council"}], extracted)
    assert seed_ledger(ledger, [{"id": "novato-city-council"}], extracted) == []
    assert len(ledger.path.read_text().splitlines()) == 1
