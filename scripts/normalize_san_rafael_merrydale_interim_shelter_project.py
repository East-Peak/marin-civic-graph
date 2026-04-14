#!/usr/bin/env python3

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COUNCIL_BACKBONE_PATH = ROOT / "data" / "normalized" / "san-rafael-city-council-backbone-01" / "bundle-01.json"
COUNCIL_DECISIONS_PATH = ROOT / "data" / "normalized" / "san-rafael-city-council-decisions-01" / "bundle-01.json"
LEGAL_LOCAL_PATH = ROOT / "data" / "normalized" / "legal-precedent-01" / "bundle-01.json"
OUTPUT_PATH = (
    ROOT
    / "data"
    / "normalized"
    / "san-rafael-merrydale-interim-shelter-project-01"
    / "bundle-01.json"
)

PROJECT_ID = "project-san-rafael-350-merrydale-interim-shelter"


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


def with_project_ref(item: dict) -> dict:
    item["project_id"] = PROJECT_ID
    return item


def main() -> None:
    council_backbone = json.loads(COUNCIL_BACKBONE_PATH.read_text())
    council_decisions = json.loads(COUNCIL_DECISIONS_PATH.read_text())
    legal_local = json.loads(LEGAL_LOCAL_PATH.read_text())

    backbone_records = index_by_id(council_backbone["record_refs"])
    decision_records = index_by_id(council_decisions["record_refs"])
    decisions = index_by_id(council_decisions["decision_candidates"])
    legal_records = index_by_id(legal_local["record_refs"])

    record_refs = [
        with_related_project_ref(pick(backbone_records, "record-2024-11-04-san-rafael-city-council-special-page")),
        with_related_project_ref(pick(decision_records, "record-2024-11-04-san-rafael-city-council-special-minutes")),
        with_related_project_ref(pick(backbone_records, "record-2025-11-17-san-rafael-city-council-page")),
        with_related_project_ref(pick(decision_records, "record-2025-11-17-san-rafael-city-council-minutes")),
        with_related_project_ref(pick(backbone_records, "record-2025-12-01-san-rafael-city-council-page")),
        with_related_project_ref(pick(decision_records, "record-2025-12-01-san-rafael-city-council-minutes")),
        with_related_project_ref(pick(backbone_records, "record-2026-02-17-san-rafael-city-council-page")),
        with_related_project_ref(pick(decision_records, "record-2026-02-17-san-rafael-city-council-minutes")),
        with_related_project_ref(pick(backbone_records, "record-2026-03-16-san-rafael-city-council-page")),
        with_related_project_ref(pick(decision_records, "record-2026-03-16-san-rafael-city-council-minutes")),
        with_related_project_ref(pick(legal_records, "record-san-rafael-sanctioned-camping-area-page")),
    ]

    project_candidate = {
        "id": PROJECT_ID,
        "name": "350 Merrydale Interim Shelter Project",
        "project_type": "interim_shelter_project",
        "primary_place_id": "place-350-merrydale-road",
        "jurisdiction_place_id": "place-san-rafael",
        "status": "active",
        "record_ids": [
            "record-2024-11-04-san-rafael-city-council-special-page",
            "record-2024-11-04-san-rafael-city-council-special-minutes",
            "record-2025-11-17-san-rafael-city-council-page",
            "record-2025-11-17-san-rafael-city-council-minutes",
            "record-2025-12-01-san-rafael-city-council-page",
            "record-2025-12-01-san-rafael-city-council-minutes",
            "record-2026-02-17-san-rafael-city-council-page",
            "record-2026-02-17-san-rafael-city-council-minutes",
            "record-2026-03-16-san-rafael-city-council-page",
            "record-2026-03-16-san-rafael-city-council-minutes",
            "record-san-rafael-sanctioned-camping-area-page",
        ],
        "related_program_ids": [
            "program-san-rafael-sanctioned-camping",
        ],
        "related_decision_ids": [
            "decision-2024-11-04-san-rafael-city-council-special-7a-motion-approval",
            "decision-2025-11-17-350-merrydale-county-grant-approval",
            "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            "decision-2025-12-01-san-rafael-city-council-4b-approval-approved-final-adoption-of-ordinance-2057",
            "decision-2026-02-17-350-merrydale-project-services-authorization",
            "decision-2026-03-16-san-rafael-city-council-4a-direction-or-receipt-received-the-project-update-and-provided-direction-regarding-the-operational-fra",
        ],
        "evidence_summary": "This bounded project slice is anchored in official San Rafael meeting pages and official minutes covering ERF-3/County collaboration, November 2025 site acquisition actions, February 2026 design and construction-management authorizations, and the March 2026 operational-framework update.",
    }

    decision_candidates = [
        with_project_ref(
            pick(
                decisions,
                "decision-2024-11-04-san-rafael-city-council-special-7a-motion-approval",
            )
        ),
        {
            "id": "decision-2025-11-17-350-merrydale-county-grant-approval",
            "title": "350 Merrydale county grant and affordable housing agreement approval",
            "decision_type": "grant_and_housing_agreement_authorization",
            "status": "adopted",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2025-11-17-san-rafael-city-council",
            "effective_date": "2025-11-17",
            "project_id": PROJECT_ID,
            "record_ids": [
                "record-2025-11-17-san-rafael-city-council-page",
                "record-2025-11-17-san-rafael-city-council-minutes",
            ],
        },
        {
            "id": "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            "title": "350 Merrydale acquisition and brokerage approval",
            "decision_type": "property_acquisition_authorization",
            "status": "adopted",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2025-11-17-san-rafael-city-council",
            "effective_date": "2025-11-17",
            "project_id": PROJECT_ID,
            "record_ids": [
                "record-2025-11-17-san-rafael-city-council-page",
                "record-2025-11-17-san-rafael-city-council-minutes",
            ],
        },
        with_project_ref(
            pick(
                decisions,
                "decision-2025-12-01-san-rafael-city-council-4b-approval-approved-final-adoption-of-ordinance-2057",
            )
        ),
        {
            "id": "decision-2026-02-17-350-merrydale-project-services-authorization",
            "title": "350 Merrydale project services authorization",
            "decision_type": "project_services_authorization",
            "status": "adopted",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2026-02-17-san-rafael-city-council",
            "effective_date": "2026-02-17",
            "project_id": PROJECT_ID,
            "record_ids": [
                "record-2026-02-17-san-rafael-city-council-page",
                "record-2026-02-17-san-rafael-city-council-minutes",
            ],
        },
        with_project_ref(
            pick(
                decisions,
                "decision-2026-03-16-san-rafael-city-council-4a-direction-or-receipt-received-the-project-update-and-provided-direction-regarding-the-operational-fra",
            )
        ),
    ]

    agreement_candidates = [
        {
            "id": "agreement-350-merrydale-swinerton-project-management",
            "name": "350 Merrydale Swinerton project and construction management agreement",
            "agreement_type": "professional_services_agreement",
            "institution_id": "inst-city-of-san-rafael",
            "counterparty_actor_id": "actor-swinerton-management-and-consulting",
            "project_id": PROJECT_ID,
            "authorized_amount": 229703,
            "effective_date": "2026-02-17",
            "evidence_record_ids": [
                "record-2026-02-17-san-rafael-city-council-page",
                "record-2026-02-17-san-rafael-city-council-minutes",
            ],
        },
        {
            "id": "agreement-350-merrydale-lca-design-services",
            "name": "350 Merrydale LCA design services agreement",
            "agreement_type": "professional_services_agreement",
            "institution_id": "inst-city-of-san-rafael",
            "counterparty_actor_id": "actor-lca-architects",
            "project_id": PROJECT_ID,
            "authorized_amount": 280750,
            "effective_date": "2026-02-17",
            "evidence_record_ids": [
                "record-2026-02-17-san-rafael-city-council-page",
                "record-2026-02-17-san-rafael-city-council-minutes",
            ],
        },
        {
            "id": "agreement-350-merrydale-newmark-brokerage",
            "name": "350 Merrydale Newmark brokerage services agreement",
            "agreement_type": "professional_services_agreement",
            "institution_id": "inst-city-of-san-rafael",
            "counterparty_actor_id": "actor-newmark-commercial-brokerage",
            "project_id": PROJECT_ID,
            "authorized_amount": 201000,
            "effective_date": "2025-11-17",
            "evidence_record_ids": [
                "record-2025-11-17-san-rafael-city-council-page",
                "record-2025-11-17-san-rafael-city-council-minutes",
            ],
        },
    ]

    amendment_candidates = [
        {
            "id": "amendment-350-merrydale-lca-design-services-2026-02-17",
            "name": "350 Merrydale LCA design services amendment",
            "amendment_type": "contract_amendment",
            "agreement_id": "agreement-350-merrydale-lca-design-services",
            "project_id": PROJECT_ID,
            "authorized_amount": 207250,
            "effective_date": "2026-02-17",
            "evidence_record_ids": [
                "record-2026-02-17-san-rafael-city-council-page",
                "record-2026-02-17-san-rafael-city-council-minutes",
            ],
        }
    ]

    money_flow_candidates = [
        {
            "id": "moneyflow-2025-11-17-350-merrydale-county-grant",
            "flow_type": "grant_award",
            "amount": 8000000,
            "currency": "USD",
            "related_institution_id": "inst-marin-county",
            "related_decision_id": "decision-2025-11-17-350-merrydale-county-grant-approval",
            "project_id": PROJECT_ID,
            "evidence_record_ids": [
                "record-2025-11-17-san-rafael-city-council-page",
                "record-2025-11-17-san-rafael-city-council-minutes",
            ],
        },
        {
            "id": "moneyflow-2025-11-17-350-merrydale-property-acquisition",
            "flow_type": "property_acquisition_authorization",
            "amount": 6700000,
            "currency": "USD",
            "related_decision_id": "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            "project_id": PROJECT_ID,
            "evidence_record_ids": [
                "record-2025-11-17-san-rafael-city-council-page",
                "record-2025-11-17-san-rafael-city-council-minutes",
            ],
        },
        {
            "id": "moneyflow-2025-11-17-350-merrydale-brokerage-services",
            "flow_type": "contract_authorization",
            "amount": 201000,
            "currency": "USD",
            "to_actor_id": "actor-newmark-commercial-brokerage",
            "related_decision_id": "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            "project_id": PROJECT_ID,
            "evidence_record_ids": [
                "record-2025-11-17-san-rafael-city-council-page",
                "record-2025-11-17-san-rafael-city-council-minutes",
            ],
        },
        {
            "id": "moneyflow-2026-02-17-350-merrydale-swinerton-services",
            "flow_type": "contract_authorization",
            "amount": 229703,
            "currency": "USD",
            "to_actor_id": "actor-swinerton-management-and-consulting",
            "related_decision_id": "decision-2026-02-17-350-merrydale-project-services-authorization",
            "project_id": PROJECT_ID,
            "evidence_record_ids": [
                "record-2026-02-17-san-rafael-city-council-page",
                "record-2026-02-17-san-rafael-city-council-minutes",
            ],
        },
        {
            "id": "moneyflow-2026-02-17-350-merrydale-lca-design-amendment",
            "flow_type": "amendment_authorization",
            "amount": 207250,
            "currency": "USD",
            "to_actor_id": "actor-lca-architects",
            "related_decision_id": "decision-2026-02-17-350-merrydale-project-services-authorization",
            "project_id": PROJECT_ID,
            "evidence_record_ids": [
                "record-2026-02-17-san-rafael-city-council-page",
                "record-2026-02-17-san-rafael-city-council-minutes",
            ],
        },
    ]

    payload = {
        "case_study_id": "san-rafael-merrydale-interim-shelter-project-01",
        "bundle_id": "san-rafael-merrydale-interim-shelter-project-01__bundle-01",
        "status": "bounded_local_project_support",
        "generated_at": iso_now(),
        "scope": {
            "included": [
                "one bounded 350 Merrydale interim shelter project thread",
                "existing official San Rafael council meeting pages and minutes already captured in the repo",
                "direct project money flows for county grant, acquisition, brokerage, and design/construction-management authorizations",
                "project linkage back to the existing sanctioned-camping program context",
            ],
            "excluded": [
                "new raw-source ingestion outside the already captured council corpus",
                "seller-side counterparty inference where the official meeting pages do not name the seller",
                "full county housing or procurement expansion",
                "direct case linkage beyond the existing sanctioned-camping program context",
            ],
        },
        "record_refs": record_refs,
        "actor_candidates": [
            {
                "id": "actor-swinerton-management-and-consulting",
                "name": "Swinerton Management & Consulting",
                "actor_type": "business",
            },
            {
                "id": "actor-lca-architects",
                "name": "LCA Architects",
                "actor_type": "business",
            },
            {
                "id": "actor-newmark-commercial-brokerage",
                "name": "Cornish and Carey Commercial (d/b/a Newmark)",
                "actor_type": "business",
            },
        ],
        "project_candidates": [project_candidate],
        "decision_candidates": decision_candidates,
        "agreement_candidates": agreement_candidates,
        "amendment_candidates": amendment_candidates,
        "money_flow_candidates": money_flow_candidates,
        "open_questions": [
            {
                "id": "OQ-037",
                "status": "watch",
                "question": "When should the 350 Merrydale project stop relying on page-backed custom decision objects for the November 17, 2025 and February 17, 2026 actions and move to packet/staff-report-level extraction?",
                "why_it_matters": "The current bounded project slice is strong enough for pressure ranking and dossier generation, but the custom decision objects still reflect official meeting-page language because the citywide minutes parser did not preserve the 2025-11-17 sub-action titles or the 2026-02-17 item-specific decision node.",
            }
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
