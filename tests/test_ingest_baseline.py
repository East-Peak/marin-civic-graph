"""Seed the run ledger from the last manual captures, so the first scheduled
run is judged against real history instead of accepting anything > 0 rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ingest_baseline import seed_ledger  # noqa: E402
from ingest_guard import RunLedger, Verdict  # noqa: E402


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


def test_seeding_skips_a_stray_non_date_json(tmp_path):
    extracted = tmp_path / "extracted"
    _capture(extracted, "novato-city-council", "2026-04-14", 409)
    (extracted / "novato-city-council" / "notes.json").write_text("{}")
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    assert seed_ledger(ledger, [{"id": "novato-city-council"}], extracted) == ["novato-city-council"]
    assert ledger.last_good("novato-city-council")["run_at"] == "seed:2026-04-14.json"


def test_seeding_skips_captures_scoped_wider_than_the_current_config(tmp_path, capsys):
    # April's corte-madera-town-council capture held every category (903 rows);
    # the source is now Town Council only, so that capture is no baseline.
    extracted = tmp_path / "extracted"
    src = extracted / "corte-madera-town-council"
    src.mkdir(parents=True)
    (src / "2026-04-10.json").write_text(json.dumps({"meetings": [
        {"date": "2026-04-07", "category": "Town Council"}] * 5}))
    (src / "2026-04-15.json").write_text(json.dumps({"meetings": [
        {"date": "2026-04-07", "category": "Town Council"},
        {"date": "2026-04-08", "category": "Planning Commission"}] * 5}))
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    config = {"id": "corte-madera-town-council", "categories": ["Town Council"]}
    assert seed_ledger(ledger, [config], extracted) == ["corte-madera-town-council"]
    good = ledger.last_good("corte-madera-town-council")
    assert good["run_at"] == "seed:2026-04-10.json" and good["rows"] == 5
    assert "2026-04-15.json" in capsys.readouterr().err


def test_seed_uses_the_pre_merge_pulled_rows_when_the_capture_has_them(tmp_path):
    extracted = tmp_path / "extracted"
    p = extracted / "marin-county-bos" / "2026-09-28.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"pulled_rows": 331, "meetings": [{"date": "2026-09-15"}] * 326}))
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    seed_ledger(ledger, [{"id": "marin-county-bos"}], extracted)
    assert ledger.last_good("marin-county-bos")["rows"] == 331


def _reset_world(tmp_path, monkeypatch):
    import ingest_baseline

    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "civicplus-sources.yaml").write_text(
        "sources:\n  - {id: corte-madera-town-council, adapter: civicplus, url: u}\n")
    ledger = RunLedger(tmp_path / "data" / "ingest-runs" / "ledger.jsonl")
    ledger.append("corte-madera-town-council", "seed:2026-04-15.json", 903, None, Verdict(ok=True))
    ledger.append("corte-madera-town-council", "2026-09-28T20:01:39+00:00", 252, None,
                  Verdict(ok=False, reasons=["below 90%"]))
    monkeypatch.setattr(ingest_baseline, "ROOT", tmp_path)
    return ingest_baseline, ledger


def test_reset_cli_appends_an_audited_entry_defaulting_to_the_reviewed_pull(tmp_path, monkeypatch, capsys):
    ingest_baseline, ledger = _reset_world(tmp_path, monkeypatch)
    rc = ingest_baseline.main(["--reset", "corte-madera-town-council",
                               "--reason", "source narrowed to Town Council; 252 checked by hand"])
    assert rc == 0
    entry = ledger.last_good("corte-madera-town-council")
    assert entry["reset"].startswith("source narrowed") and entry["rows"] == 252
    assert entry["previous_baseline"] == 903
    assert ledger.baseline_rows("corte-madera-town-council") == 252
    assert "903 -> 252" in capsys.readouterr().out


def test_reset_cli_refuses_without_a_reason_or_for_an_unknown_source(tmp_path, monkeypatch):
    ingest_baseline, ledger = _reset_world(tmp_path, monkeypatch)
    before = ledger.path.read_text()
    assert ingest_baseline.main(["--reset", "corte-madera-town-council", "--reason", " "]) != 0
    assert ingest_baseline.main(["--reset", "corte-madera-town-counsil", "--reason", "typo",
                                 "--rows", "252"]) != 0
    assert ledger.path.read_text() == before
    assert ingest_baseline.main(["--reset", "corte-madera-town-council", "--reason", "explicit",
                                 "--rows", "260"]) == 0
    assert ledger.baseline_rows("corte-madera-town-council") == 260
