"""Tests for scripts/drift_report.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import drift_report as dr  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _case(case_id: str, status: str) -> dict:
    return {"case_id": case_id, "current_ledger_status": status}


def test_drift_report_counts_newly_requeued_pairs_and_stale_confidence(tmp_path, capsys):
    before = tmp_path / "before.jsonl"
    after = tmp_path / "after.jsonl"
    confidence = tmp_path / "confidence.jsonl"
    out = tmp_path / "report.md"
    _write_jsonl(before, [_case("attach|a|vendor-a", "none"), _case("attach|b|vendor-b", "requeued")])
    _write_jsonl(
        after,
        [
            _case("attach|a|vendor-a", "requeued"),
            _case("attach|b|vendor-b", "requeued"),
            _case("attach|c|vendor-c", "requeued"),
        ],
    )
    _write_jsonl(confidence, [{"id": "conf-a", "status": "stale"}, {"id": "conf-b", "status": "active"}])

    code = dr.main(
        [
            "--before-read-model",
            str(before),
            "--after-read-model",
            str(after),
            "--confidence",
            str(confidence),
            "--out",
            str(out),
            "--date",
            "2026-07-07",
        ]
    )

    assert code == 0
    printed = capsys.readouterr().out
    report = out.read_text(encoding="utf-8")
    assert "newly_requeued_pairs: 2" in printed
    assert "stale_confidence_records: 1" in printed
    assert printed == report
    assert "# Reconciliation Drift Report - 2026-07-07" in report


def test_drift_report_appends_to_existing_daily_report(tmp_path):
    before = tmp_path / "before.jsonl"
    after = tmp_path / "after.jsonl"
    confidence = tmp_path / "confidence.jsonl"
    out = tmp_path / "report.md"
    _write_jsonl(before, [])
    _write_jsonl(after, [])
    _write_jsonl(confidence, [])
    out.write_text("existing\n", encoding="utf-8")

    dr.main(
        [
            "--before-read-model",
            str(before),
            "--after-read-model",
            str(after),
            "--confidence",
            str(confidence),
            "--out",
            str(out),
            "--date",
            "2026-07-07",
        ]
    )

    assert out.read_text(encoding="utf-8").startswith("existing\n# Reconciliation Drift Report")


def test_drift_report_redaction_scans_markdown_before_write(tmp_path):
    before = tmp_path / "before.jsonl"
    after = tmp_path / "after.jsonl"
    confidence = tmp_path / "REDACT_ME_STREET-confidence.jsonl"
    out = tmp_path / "report.md"
    _write_jsonl(before, [])
    _write_jsonl(after, [])
    _write_jsonl(confidence, [])

    with pytest.raises(ValueError, match="redaction"):
        dr.main(
            [
                "--before-read-model",
                str(before),
                "--after-read-model",
                str(after),
                "--confidence",
                str(confidence),
                "--out",
                str(out),
                "--date",
                "2026-07-07",
            ]
        )
