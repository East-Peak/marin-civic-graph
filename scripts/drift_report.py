"""Counts-only reconciliation drift report.

Diffs read-model ledger statuses before/after an operator refresh and reports
only aggregate drift counts. It does not mutate ledgers or the graph.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from enrich_casos_keys import scan_for_forbidden


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _case_key(row: dict[str, Any]) -> str:
    case_id = row.get("case_id")
    if isinstance(case_id, str) and case_id:
        return case_id
    joins = row.get("candidate_joins") or []
    if joins:
        join = joins[0]
        left = join.get("left_ref", {}).get("local_id", "")
        right = join.get("right_ref", {}).get("local_id", "")
        if left or right:
            return f"{right}|{left}"
    raise ValueError("read-model row missing case_id and candidate refs")


def _status_by_case(path: str | Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for row in _read_jsonl(path):
        status = row.get("current_ledger_status")
        if not isinstance(status, str) or not status:
            raise ValueError(f"read-model row has invalid current_ledger_status: {_case_key(row)}")
        statuses[_case_key(row)] = status
    return statuses


def count_newly_requeued(before_path: str | Path, after_path: str | Path) -> int:
    before = _status_by_case(before_path)
    after = _status_by_case(after_path)
    return sum(
        1
        for case_id, status in after.items()
        if status == "requeued" and before.get(case_id) != "requeued"
    )


def count_stale_confidence(confidence_path: str | Path) -> int:
    return sum(1 for row in _read_jsonl(confidence_path) if row.get("status") == "stale")


def render_report(
    *,
    date: str,
    before_read_model: str | Path,
    after_read_model: str | Path,
    confidence: str | Path,
) -> str:
    newly_requeued = count_newly_requeued(before_read_model, after_read_model)
    stale_confidence = count_stale_confidence(confidence)
    report = (
        f"# Reconciliation Drift Report - {date}\n\n"
        f"- newly_requeued_pairs: {newly_requeued}\n"
        f"- stale_confidence_records: {stale_confidence}\n"
        f"- before_read_model: {before_read_model}\n"
        f"- after_read_model: {after_read_model}\n"
        f"- confidence: {confidence}\n\n"
    )
    violations = scan_for_forbidden(report)
    if violations:
        raise ValueError(f"drift report failed redaction gate: {violations}")
    return report


def append_report(report: str, out: str | Path) -> None:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if path.exists() else "w"
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a counts-only reconciliation drift report.")
    parser.add_argument("--before-read-model", required=True)
    parser.add_argument("--after-read-model", required=True)
    parser.add_argument("--confidence", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args(argv)

    report = render_report(
        date=args.date,
        before_read_model=args.before_read_model,
        after_read_model=args.after_read_model,
        confidence=args.confidence,
    )
    append_report(report, args.out)
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
