#!/usr/bin/env python3

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "data" / "normalized" / "permit-sample-basket-01" / "bundle-01.json"
OUTPUT_PATH = ROOT / "data" / "normalized" / "san-rafael-700-irwin-project-01" / "bundle-01.json"
PROJECT_ID = "project-700-irwin-st"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def index_by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def pick(index: dict[str, dict], item_id: str) -> dict:
    if item_id not in index:
        raise KeyError(f"Missing source object: {item_id}")
    return deepcopy(index[item_id])


def with_related_project_ref(record: dict) -> dict:
    existing = list(record.get("related_project_ids") or [])
    if PROJECT_ID not in existing:
        existing.append(PROJECT_ID)
    record["related_project_ids"] = existing
    return record


def main() -> None:
    source = json.loads(SOURCE_PATH.read_text())

    records = index_by_id(source["record_refs"])
    actors = index_by_id(source["actor_candidates"])
    places = index_by_id(source["place_candidates"])
    projects = index_by_id(source["project_candidates"])

    record_refs = [
        with_related_project_ref(pick(records, "record-700-irwin-project-page")),
        with_related_project_ref(pick(records, "record-700-irwin-public-hearing-notice")),
    ]

    project = pick(projects, PROJECT_ID)
    project["status"] = "application_complete"
    project["evidence_summary"] = (
        "This bounded San Rafael planning-project slice is anchored in the official city project page and the "
        "official public-hearing notice. It preserves the applicant, application number PLAN25-046, project type, "
        "and hearing-notice linkage without importing the broader permit schema into graph-v1."
    )

    payload = {
        "case_study_id": "san-rafael-700-irwin-project-01",
        "bundle_id": "san-rafael-700-irwin-project-01__bundle-01",
        "status": "bounded_project_support",
        "generated_at": iso_now(),
        "scope": {
            "included": [
                "one bounded San Rafael planning-project thread",
                "existing official city project page and hearing notice records",
                "applicant and place joins needed for a low-pressure project baseline",
            ],
            "excluded": [
                "full permit-lane import into graph-v1",
                "application, determination, or appeal node import",
                "planning-commission meeting or decision promotion while the hearing-date mismatch remains open",
                "money-flow or legal-pressure promotion for this thread",
            ],
        },
        "record_refs": record_refs,
        "actor_candidates": [
            pick(actors, "actor-700-irwin-street-partners-llc"),
        ],
        "place_candidates": [
            pick(places, "place-700-irwin-st"),
        ],
        "project_candidates": [project],
        "open_questions": [
            {
                "id": "OQ-001",
                "question": "The hearing notice body says January 13, 2025, but the project timeline strongly suggests January 13, 2026. Which hearing date is correct?",
                "status": "open",
                "note": "This bounded project slice can still enter graph-v1 as a low-pressure planning baseline while the hearing-date mismatch remains unresolved.",
            }
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
