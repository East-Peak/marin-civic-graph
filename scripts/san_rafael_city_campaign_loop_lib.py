#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
FILING_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-filings-01" / "bundle-01.json"
)


def current_capture_date() -> str:
    return date.today().isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def load_batch_filing_ids(loop_manifest_path: Path, batch_id: str) -> list[str]:
    manifest = load_json(loop_manifest_path)
    for batch in manifest.get("batches", []):
        if batch.get("batch_id") == batch_id:
            return list(batch.get("target_filing_ids", []))
    raise KeyError(f"unknown batch_id: {batch_id}")


def select_targets_from_filing_ids(filing_ids: list[str]) -> list[dict[str, Any]]:
    filing_bundle = load_json(FILING_BUNDLE_PATH)
    record_refs_by_id = {item["id"]: item for item in filing_bundle["record_refs"]}
    filing_candidates_by_id = {item["id"]: item for item in filing_bundle["filing_candidates"]}

    targets: list[dict[str, Any]] = []
    for filing_id in filing_ids:
        filing_candidate = filing_candidates_by_id[filing_id]
        record_ref = record_refs_by_id[filing_candidate["record_id"]]
        targets.append(
            {
                "entry_id": record_ref["entry_id"],
                "record_id": record_ref["id"],
                "filing_id": filing_candidate["id"],
                "label": record_ref["title"],
                "record_ref": record_ref,
                "filing_candidate": filing_candidate,
            }
        )
    return sorted(targets, key=lambda item: item["entry_id"])


def load_latest_captures_by_entry(base_dir: Path) -> dict[int, dict[str, Any]]:
    captures_by_entry: dict[int, dict[str, Any]] = {}
    for results_path in sorted(base_dir.glob("*/results.json")):
        payload = load_json(results_path)
        capture_date = results_path.parent.name
        for capture in payload.get("captures", []):
            merged = dict(capture)
            merged["capture_date"] = capture_date
            entry_id = merged["target"]["entry_id"]
            captures_by_entry[entry_id] = merged
    return captures_by_entry
