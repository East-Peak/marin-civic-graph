#!/usr/bin/env python3

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "data" / "normalized" / "procurement-sample-basket-01" / "bundle-01.json"
OUTPUT_PATH = ROOT / "data" / "normalized" / "project-dossiers-01" / "bundle-01.json"
PROJECT_ID = "project-downtown-library-renovation"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def index_by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def pick(index: dict[str, dict], item_id: str) -> dict:
    if item_id not in index:
        raise KeyError(f"Missing source object: {item_id}")
    return deepcopy(index[item_id])


def with_project_ref(item: dict) -> dict:
    item["project_id"] = PROJECT_ID
    return item


def with_related_project_ref(record: dict) -> dict:
    record["related_project_ids"] = [PROJECT_ID]
    return record


def main() -> None:
    source = json.loads(SOURCE_PATH.read_text())

    records = index_by_id(source["record_refs"])
    institutions = index_by_id(source["institution_candidates"])
    actors = index_by_id(source["actor_candidates"])
    places = index_by_id(source["place_candidates"])
    projects = index_by_id(source["project_candidates"])
    programs = index_by_id(source["program_candidates"])
    decisions = index_by_id(source["decision_candidates"])
    agreements = index_by_id(source["agreement_candidates"])
    amendments = index_by_id(source["amendment_candidates"])
    money_flows = index_by_id(source["money_flow_candidates"])

    record_refs = [
        with_related_project_ref(pick(records, "record-downtown-library-project-page")),
        with_related_project_ref(pick(records, "record-downtown-library-renovation-rfp")),
        with_related_project_ref(pick(records, "record-downtown-library-reopening")),
        with_related_project_ref(pick(records, "record-srcc-2022-12-19-library-grants")),
        with_related_project_ref(pick(records, "record-downtown-library-state-grant-acceptance-staff-report")),
        with_related_project_ref(pick(records, "record-csl-building-forward-report-2021-2022")),
        with_related_project_ref(pick(records, "record-csl-lds-annual-update-2023-2024")),
        with_related_project_ref(pick(records, "record-srcc-2023-09-18-downtown-library")),
        with_related_project_ref(pick(records, "record-downtown-library-first-amendment-staff-report")),
        with_related_project_ref(pick(records, "record-srcc-2024-09-16-downtown-library")),
        with_related_project_ref(pick(records, "record-downtown-library-construction-award-staff-report")),
        with_related_project_ref(pick(records, "record-srcc-2024-09-16-agenda-packet")),
        with_related_project_ref(pick(records, "record-srcc-2025-04-07-downtown-library")),
        with_related_project_ref(pick(records, "record-downtown-library-second-amendment-staff-report")),
    ]

    project = pick(projects, PROJECT_ID)
    project["related_program_ids"] = [
        "program-csl-building-forward",
        "program-csl-targeted-grants",
    ]
    project["related_decision_ids"] = [
        "decision-2022-12-19-downtown-carnegie-grant-acceptance",
        "decision-2023-09-18-noll-tam-first-amendment",
        "decision-2024-09-16-unger-award",
        "decision-2024-09-16-unico-approval",
        "decision-2025-04-07-noll-tam-second-amendment",
        "decision-2025-04-07-unger-second-amendment",
    ]

    decision_candidates = [
        with_project_ref(pick(decisions, "decision-2022-12-19-downtown-carnegie-grant-acceptance")),
        with_project_ref(pick(decisions, "decision-2023-09-18-noll-tam-first-amendment")),
        with_project_ref(pick(decisions, "decision-2024-09-16-unger-award")),
        with_project_ref(pick(decisions, "decision-2024-09-16-unico-approval")),
        with_project_ref(pick(decisions, "decision-2025-04-07-noll-tam-second-amendment")),
        with_project_ref(pick(decisions, "decision-2025-04-07-unger-second-amendment")),
    ]

    agreement_candidates = [
        pick(agreements, "agreement-noll-and-tam-downtown-library"),
        pick(agreements, "agreement-unger-downtown-library-construction"),
        pick(agreements, "agreement-unico-downtown-library-construction-management"),
        pick(agreements, "agreement-csl-downtown-carnegie-building-forward"),
        pick(agreements, "agreement-csl-downtown-carnegie-targeted-design-grant"),
    ]

    amendment_candidates = [
        with_project_ref(pick(amendments, "amendment-noll-and-tam-first")),
        with_project_ref(pick(amendments, "amendment-noll-and-tam-second")),
        with_project_ref(pick(amendments, "amendment-unger-second")),
    ]

    money_flow_candidates = [
        with_project_ref(pick(money_flows, "moneyflow-downtown-carnegie-building-forward-grant-2022")),
        with_project_ref(pick(money_flows, "moneyflow-downtown-carnegie-targeted-design-grant")),
        with_project_ref(pick(money_flows, "moneyflow-unger-contract-2024")),
        with_project_ref(pick(money_flows, "moneyflow-unger-contingency-2024")),
        with_project_ref(pick(money_flows, "moneyflow-unico-construction-management-2024")),
    ]

    payload = {
        "case_study_id": "project-dossiers-01",
        "bundle_id": "project-dossiers-01__bundle-01",
        "status": "bounded_project_support",
        "generated_at": iso_now(),
        "scope": {
            "included": [
                "one bounded Downtown Library project thread",
                "linked grant, contract, amendment, decision, and money-flow objects",
                "direct project evidence records and project-related support records",
            ],
            "excluded": [
                "full procurement basket import",
                "county procurement expansion",
                "invoice-level or deliverable-level project activity",
                "generic project modeling outside the Downtown Library support slice",
            ],
        },
        "record_refs": record_refs,
        "institution_candidates": [
            pick(institutions, "inst-san-rafael-city-council"),
            pick(institutions, "inst-california-state-library"),
        ],
        "actor_candidates": [
            pick(actors, "actor-noll-and-tam-architects"),
            pick(actors, "actor-unger-construction-co"),
            pick(actors, "actor-unico-engineering"),
            pick(actors, "actor-california-state-library"),
        ],
        "place_candidates": [
            pick(places, "place-downtown-library-1100-e-st"),
        ],
        "project_candidates": [project],
        "program_candidates": [
            pick(programs, "program-csl-building-forward"),
            pick(programs, "program-csl-targeted-grants"),
        ],
        "decision_candidates": decision_candidates,
        "agreement_candidates": agreement_candidates,
        "amendment_candidates": amendment_candidates,
        "money_flow_candidates": money_flow_candidates,
        "open_questions": [],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
