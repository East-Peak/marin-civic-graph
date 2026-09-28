"""A run never makes data worse; silence is failure.

docs/specs/2026-09-28-persistent-ingestion-design.md (I1). NetFile's replatform
showed the failure mode: HTTP 200, zero rows, "success", then good data
overwritten with empty files.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ingest_guard import Floors, RunLedger, evaluate, newest_past_date, write_if_ok  # noqa: E402

TODAY = date(2026, 9, 28)


def test_zero_rows_is_a_failure_even_on_first_run():
    v = evaluate(rows=0, newest=None, last_good_rows=None, today=TODAY, floors=Floors())
    assert not v.ok
    assert any("0 rows" in r for r in v.reasons)


def test_a_sharp_drop_versus_the_last_good_run_fails():
    v = evaluate(rows=40, newest=TODAY, last_good_rows=409, today=TODAY, floors=Floors())
    assert not v.ok
    assert any("409" in r for r in v.reasons)


def test_normal_growth_passes():
    v = evaluate(rows=429, newest=date(2026, 9, 22), last_good_rows=409, today=TODAY, floors=Floors())
    assert v.ok, v.reasons


def test_stale_newest_record_fails():
    v = evaluate(rows=429, newest=date(2026, 4, 14), last_good_rows=409, today=TODAY,
                 floors=Floors(max_newest_age_days=45))
    assert not v.ok
    assert any("2026-04-14" in r for r in v.reasons)


def test_floors_are_per_source():
    rolling = Floors(min_ratio=0.5)  # e.g. Ross shows only a rolling window
    assert evaluate(rows=12, newest=TODAY, last_good_rows=19, today=TODAY, floors=rolling).ok
    assert Floors.from_config({"floors": {"min_ratio": 0.5, "max_newest_age_days": 60}}) == Floors(
        min_ratio=0.5, max_newest_age_days=60)
    assert Floors.from_config({}) == Floors()


def test_newest_past_date_ignores_future_and_undated_meetings():
    meetings = [{"date": "2026-10-20"}, {"date": "2026-09-15"}, {"date": None}, {"date": "garbage"}]
    assert newest_past_date(meetings, TODAY) == date(2026, 9, 15)
    assert newest_past_date([], TODAY) is None


def test_failed_verdict_never_touches_existing_output(tmp_path):
    out = tmp_path / "extracted.json"
    out.write_text("GOOD APRIL DATA")
    bad = evaluate(rows=0, newest=None, last_good_rows=409, today=TODAY, floors=Floors())
    assert write_if_ok(out, "EMPTY", bad) is False
    assert out.read_text() == "GOOD APRIL DATA"


def test_ok_verdict_writes_atomically(tmp_path):
    out = tmp_path / "nested" / "extracted.json"
    good = evaluate(rows=10, newest=TODAY, last_good_rows=None, today=TODAY, floors=Floors())
    assert write_if_ok(out, "NEW", good) is True
    assert out.read_text() == "NEW"
    assert list(out.parent.iterdir()) == [out]  # no temp files left behind


def test_ledger_remembers_only_good_runs(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    ok = evaluate(rows=409, newest=TODAY, last_good_rows=None, today=TODAY, floors=Floors())
    bad = evaluate(rows=0, newest=None, last_good_rows=409, today=TODAY, floors=Floors())
    ledger.append("novato-city-council", "2026-09-21T06:00:00Z", 409, TODAY, ok)
    ledger.append("novato-city-council", "2026-09-28T06:00:00Z", 0, None, bad)
    assert ledger.last_good("novato-city-council")["rows"] == 409
    assert ledger.last_good("never-seen") is None
    lines = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [l["ok"] for l in lines] == [True, False]
    assert lines[1]["reasons"]
