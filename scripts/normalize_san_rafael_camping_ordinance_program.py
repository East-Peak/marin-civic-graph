#!/usr/bin/env python3

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOMELESSNESS_SOURCE_PATH = ROOT / "data" / "normalized" / "san-rafael-homelessness-01" / "bundle-01.json"
LEGAL_LOCAL_SOURCE_PATH = ROOT / "data" / "normalized" / "legal-precedent-01" / "bundle-01.json"
LEGAL_PRECEDENT_SOURCE_PATH = ROOT / "data" / "normalized" / "legal-precedent-02" / "bundle-01.json"
COUNCIL_SOURCE_PATH = ROOT / "data" / "normalized" / "san-rafael-city-council-decisions-01" / "bundle-01.json"
OUTPUT_PATH = ROOT / "data" / "normalized" / "san-rafael-camping-ordinance-program-01" / "bundle-01.json"

PROGRAM_ID = "program-san-rafael-camping-ordinance-implementation"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def index_by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def pick(index: dict[str, dict], item_id: str) -> dict:
    if item_id not in index:
        raise KeyError(f"Missing source object: {item_id}")
    return deepcopy(index[item_id])


def with_related_program_ref(record: dict) -> dict:
    existing = list(record.get("related_program_ids") or [])
    if PROGRAM_ID not in existing:
        existing.append(PROGRAM_ID)
    record["related_program_ids"] = existing
    return record


def with_case_program_ref(case: dict) -> dict:
    existing = list(case.get("related_program_ids") or [])
    if PROGRAM_ID not in existing:
        existing.append(PROGRAM_ID)
    case["related_program_ids"] = existing
    return case


def main() -> None:
    homelessness = json.loads(HOMELESSNESS_SOURCE_PATH.read_text())
    legal_local = json.loads(LEGAL_LOCAL_SOURCE_PATH.read_text())
    legal_precedent = json.loads(LEGAL_PRECEDENT_SOURCE_PATH.read_text())
    council = json.loads(COUNCIL_SOURCE_PATH.read_text())

    homelessness_records = index_by_id(homelessness["document_refs"])
    legal_local_records = index_by_id(legal_local["record_refs"])
    legal_local_cases = index_by_id(legal_local["case_candidates"])
    legal_precedent_cases = index_by_id(legal_precedent["case_candidates"])
    council_records = index_by_id(council["record_refs"])

    record_refs = [
        with_related_program_ref(pick(homelessness_records, "doc-2023-12-14-implementation-plan")),
        with_related_program_ref(pick(homelessness_records, "doc-2024-06-14-homelessness-update")),
        with_related_program_ref(pick(homelessness_records, "doc-2024-06-28-grants-pass-statement")),
        with_related_program_ref(pick(homelessness_records, "doc-2024-08-08-boyd-dismissal-release")),
        with_related_program_ref(pick(homelessness_records, "doc-2025-01-24-homelessness-update")),
        with_related_program_ref(pick(legal_local_records, "record-san-rafael-grants-pass-explainer-2024-09-02")),
        with_related_program_ref(pick(council_records, "record-2023-07-10-san-rafael-city-council-special-minutes")),
        with_related_program_ref(pick(council_records, "record-2023-07-17-san-rafael-city-council-minutes")),
        with_related_program_ref(pick(council_records, "record-2024-04-15-san-rafael-city-council-minutes")),
        with_related_program_ref(pick(council_records, "record-2024-10-07-san-rafael-city-council-special-minutes")),
        with_related_program_ref(pick(council_records, "record-2025-04-07-san-rafael-city-council-special-minutes")),
    ]

    program_candidate = {
        "id": PROGRAM_ID,
        "name": "San Rafael camping ordinance implementation and enforcement",
        "program_type": "camping_ordinance_implementation",
        "institution_id": "inst-city-of-san-rafael",
        "jurisdiction_place_id": "place-san-rafael",
        "status": "active",
        "record_ids": [
            "doc-2023-12-14-implementation-plan",
            "doc-2024-06-14-homelessness-update",
            "doc-2024-06-28-grants-pass-statement",
            "doc-2024-08-08-boyd-dismissal-release",
            "record-san-rafael-grants-pass-explainer-2024-09-02",
            "doc-2025-01-24-homelessness-update",
        ],
        "related_case_ids": [
            "case-boyd-v-city-of-san-rafael",
            "case-city-of-grants-pass-v-johnson",
        ],
        "related_decision_ids": [
            "decision-2023-07-10-san-rafael-city-council-special-4a-motion-approval",
            "decision-2023-07-17-san-rafael-city-council-6a-motion-approval",
            "decision-2024-04-15-san-rafael-city-council-6b-decision-introduced-ordinance-waived-further-reading-of-ordinance-and-referred-to-it-by",
            "decision-2024-08-19-ordinance-2040-introduction",
            "decision-2024-10-07-san-rafael-city-council-special-2i-resolution-adoption-15349",
            "decision-2025-04-07-san-rafael-city-council-special-6b-ordinance-introduction-introduced-the-ordinance-waived-further-reading-of-the-ordinance-and-referred",
        ],
        "place_ids": [
            "place-lindaro-street",
            "place-mahon-creek-path",
            "place-andersen-drive",
            "place-francisco-boulevard-west",
        ],
    }

    case_candidates = [
        with_case_program_ref(pick(legal_local_cases, "case-boyd-v-city-of-san-rafael")),
        with_case_program_ref(pick(legal_precedent_cases, "case-city-of-grants-pass-v-johnson")),
    ]

    payload = {
        "case_study_id": "san-rafael-camping-ordinance-program-01",
        "bundle_id": "san-rafael-camping-ordinance-program-01__bundle-01",
        "status": "bounded_local_legal_pressure_thread_support",
        "generated_at": iso_now(),
        "scope": {
            "included": [
                "one bounded San Rafael camping-ordinance implementation and enforcement thread",
                "existing city updates, legal explainers, and council minutes already captured elsewhere in the repo",
                "existing Boyd and Grants Pass case objects cross-walked to the broader ordinance thread",
            ],
            "excluded": [
                "new raw-source ingestion",
                "new money-flow promotion for encampment enforcement beyond already imported decision-linked flows",
                "county or non-San-Rafael homelessness expansion",
            ],
        },
        "record_refs": record_refs,
        "program_candidates": [program_candidate],
        "case_candidates": case_candidates,
        "open_questions": [],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
