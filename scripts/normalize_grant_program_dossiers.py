#!/usr/bin/env python3

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "data" / "normalized" / "procurement-sample-basket-01" / "bundle-01.json"
OUTPUT_PATH = ROOT / "data" / "normalized" / "grant-program-dossiers-01" / "bundle-01.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def index_by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def pick(index: dict[str, dict], item_id: str) -> dict:
    if item_id not in index:
        raise KeyError(f"Missing source object: {item_id}")
    return deepcopy(index[item_id])


def main() -> None:
    source = json.loads(SOURCE_PATH.read_text())

    records = index_by_id(source["record_refs"])
    institutions = index_by_id(source["institution_candidates"])
    actors = index_by_id(source["actor_candidates"])
    programs = index_by_id(source["program_candidates"])
    decisions = index_by_id(source["decision_candidates"])
    money_flows = index_by_id(source["money_flow_candidates"])

    record_refs = [
        pick(records, "record-srcc-2022-12-19-library-grants"),
        pick(records, "record-downtown-library-state-grant-acceptance-staff-report"),
        pick(records, "record-csl-building-forward-report-2021-2022"),
    ]
    for record in record_refs:
        record["related_program_ids"] = ["program-csl-building-forward"]

    program = pick(programs, "program-csl-building-forward")
    program["related_decision_ids"] = ["decision-2022-12-19-downtown-carnegie-grant-acceptance"]

    decision = pick(decisions, "decision-2022-12-19-downtown-carnegie-grant-acceptance")

    money_flow = pick(money_flows, "moneyflow-downtown-carnegie-building-forward-grant-2022")
    money_flow["program_id"] = "program-csl-building-forward"

    payload = {
        "case_study_id": "grant-program-dossiers-01",
        "bundle_id": "grant-program-dossiers-01__bundle-01",
        "status": "bounded_grant_program_support",
        "generated_at": iso_now(),
        "scope": {
            "included": [
                "one bounded California State Library program thread",
                "the San Rafael Downtown Library grant-acceptance decision",
                "direct program evidence records and one linked grant award flow",
            ],
            "excluded": [
                "full procurement basket import",
                "general agreement and amendment import",
                "county procurement or SLFRF expansion",
                "project-wide contract lineage beyond the grant-backed program crosswalk",
            ],
        },
        "record_refs": record_refs,
        "institution_candidates": [
            pick(institutions, "inst-california-state-library"),
        ],
        "actor_candidates": [
            pick(actors, "actor-california-state-library"),
        ],
        "program_candidates": [program],
        "decision_candidates": [decision],
        "money_flow_candidates": [money_flow],
        "open_questions": [],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
