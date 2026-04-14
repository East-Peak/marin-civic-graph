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

    nov_17_base_record_ids = [
        "record-2025-11-17-san-rafael-city-council-page",
        "record-2025-11-17-san-rafael-city-council-minutes",
        "record-2025-11-17-350-merrydale-staff-report",
        "record-2025-11-17-san-rafael-city-council-agenda-packet",
    ]
    nov_17_child_record_ids = [
        "record-2025-11-17-350-merrydale-resolution-county-grant-and-affordable-housing",
        "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
    ]
    feb_17_base_record_ids = [
        "record-2026-02-17-san-rafael-city-council-page",
        "record-2026-02-17-san-rafael-city-council-minutes",
        "record-2026-02-17-350-merrydale-staff-report",
        "record-2026-02-17-san-rafael-city-council-agenda-packet",
    ]
    feb_17_child_record_ids = [
        "record-2026-02-17-350-merrydale-resolution-project-services",
        "record-2026-02-17-350-merrydale-swinerton-psa",
        "record-2026-02-17-350-merrydale-lca-amendment",
    ]

    record_refs = [
        with_related_project_ref(pick(backbone_records, "record-2024-11-04-san-rafael-city-council-special-page")),
        with_related_project_ref(pick(decision_records, "record-2024-11-04-san-rafael-city-council-special-minutes")),
        with_related_project_ref(pick(backbone_records, "record-2025-11-17-san-rafael-city-council-page")),
        with_related_project_ref(pick(decision_records, "record-2025-11-17-san-rafael-city-council-minutes")),
        {
            "id": "record-2025-11-17-350-merrydale-staff-report",
            "record_class": "meeting_record",
            "record_type": "staff_report",
            "source_id": "san-rafael-350-merrydale-staff-report-2025-11-17",
            "artifact_path": "data/raw/san-rafael-350-merrydale-staff-report-2025-11-17/2026-04-13/staff-report.pdf",
            "related_project_ids": [PROJECT_ID],
        },
        {
            "id": "record-2025-11-17-san-rafael-city-council-agenda-packet",
            "record_class": "meeting_record",
            "record_type": "agenda_packet",
            "source_id": "san-rafael-city-council-2025-11-17-agenda-packet",
            "artifact_path": "data/raw/san-rafael-city-council-2025-11-17-agenda-packet/2026-04-13/agenda-packet.pdf",
            "related_project_ids": [PROJECT_ID],
        },
        {
            "id": "record-2025-11-17-350-merrydale-resolution-county-grant-and-affordable-housing",
            "record_class": "administrative_record",
            "record_type": "resolution",
            "source_id": "san-rafael-city-council-2025-11-17-agenda-packet",
            "artifact_path": "data/raw/san-rafael-city-council-2025-11-17-agenda-packet/2026-04-13/agenda-packet.pdf",
            "source_record_id": "record-2025-11-17-san-rafael-city-council-agenda-packet",
            "title": "Resolution regarding county grant and affordable housing agreements for 350 Merrydale Road",
            "decision_ids": [
                "decision-2025-11-17-350-merrydale-county-grant-approval",
            ],
            "related_moneyflow_ids": [
                "moneyflow-2025-11-17-350-merrydale-county-grant",
            ],
            "related_project_ids": [PROJECT_ID],
        },
        {
            "id": "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
            "record_class": "administrative_record",
            "record_type": "resolution",
            "source_id": "san-rafael-city-council-2025-11-17-agenda-packet",
            "artifact_path": "data/raw/san-rafael-city-council-2025-11-17-agenda-packet/2026-04-13/agenda-packet.pdf",
            "source_record_id": "record-2025-11-17-san-rafael-city-council-agenda-packet",
            "title": "Resolution regarding purchase of 350 Merrydale Road and brokerage agreement",
            "decision_ids": [
                "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            ],
            "related_moneyflow_ids": [
                "moneyflow-2025-11-17-350-merrydale-property-acquisition",
                "moneyflow-2025-11-17-350-merrydale-brokerage-services",
            ],
            "related_project_ids": [PROJECT_ID],
        },
        with_related_project_ref(pick(backbone_records, "record-2025-12-01-san-rafael-city-council-page")),
        with_related_project_ref(pick(decision_records, "record-2025-12-01-san-rafael-city-council-minutes")),
        with_related_project_ref(pick(backbone_records, "record-2026-02-17-san-rafael-city-council-page")),
        with_related_project_ref(pick(decision_records, "record-2026-02-17-san-rafael-city-council-minutes")),
        {
            "id": "record-2026-02-17-350-merrydale-staff-report",
            "record_class": "meeting_record",
            "record_type": "staff_report",
            "source_id": "san-rafael-350-merrydale-staff-report-2026-02-17",
            "artifact_path": "data/raw/san-rafael-350-merrydale-staff-report-2026-02-17/2026-04-13/staff-report.pdf",
            "related_project_ids": [PROJECT_ID],
        },
        {
            "id": "record-2026-02-17-san-rafael-city-council-agenda-packet",
            "record_class": "meeting_record",
            "record_type": "agenda_packet",
            "source_id": "san-rafael-city-council-2026-02-17-agenda-packet",
            "artifact_path": "data/raw/san-rafael-city-council-2026-02-17-agenda-packet/2026-04-13/agenda-packet.pdf",
            "related_project_ids": [PROJECT_ID],
        },
        {
            "id": "record-2026-02-17-350-merrydale-resolution-project-services",
            "record_class": "administrative_record",
            "record_type": "resolution",
            "source_id": "san-rafael-city-council-2026-02-17-agenda-packet",
            "artifact_path": "data/raw/san-rafael-city-council-2026-02-17-agenda-packet/2026-04-13/agenda-packet.pdf",
            "source_record_id": "record-2026-02-17-san-rafael-city-council-agenda-packet",
            "title": "Resolution regarding Merrydale project services and ERF-3 appropriation",
            "decision_ids": [
                "decision-2026-02-17-350-merrydale-project-services-authorization",
            ],
            "related_moneyflow_ids": [
                "moneyflow-2026-02-17-350-merrydale-swinerton-services",
                "moneyflow-2026-02-17-350-merrydale-lca-design-amendment",
            ],
            "related_project_ids": [PROJECT_ID],
        },
        {
            "id": "record-2026-02-17-350-merrydale-swinerton-psa",
            "record_class": "administrative_record",
            "record_type": "agreement_attachment",
            "source_id": "san-rafael-city-council-2026-02-17-agenda-packet",
            "artifact_path": "data/raw/san-rafael-city-council-2026-02-17-agenda-packet/2026-04-13/agenda-packet.pdf",
            "source_record_id": "record-2026-02-17-san-rafael-city-council-agenda-packet",
            "title": "Swinerton Management and Consulting professional services agreement for 350 Merrydale Road Interim Shelter Project",
            "decision_ids": [
                "decision-2026-02-17-350-merrydale-project-services-authorization",
            ],
            "related_moneyflow_ids": [
                "moneyflow-2026-02-17-350-merrydale-swinerton-services",
            ],
            "related_project_ids": [PROJECT_ID],
        },
        {
            "id": "record-2026-02-17-350-merrydale-lca-amendment",
            "record_class": "administrative_record",
            "record_type": "amendment_attachment",
            "source_id": "san-rafael-city-council-2026-02-17-agenda-packet",
            "artifact_path": "data/raw/san-rafael-city-council-2026-02-17-agenda-packet/2026-04-13/agenda-packet.pdf",
            "source_record_id": "record-2026-02-17-san-rafael-city-council-agenda-packet",
            "title": "LCA Architects amendment to professional services agreement for 350 Merrydale Road Interim Shelter Project",
            "decision_ids": [
                "decision-2026-02-17-350-merrydale-project-services-authorization",
            ],
            "related_moneyflow_ids": [
                "moneyflow-2026-02-17-350-merrydale-lca-design-amendment",
            ],
            "related_project_ids": [PROJECT_ID],
        },
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
            "record-2025-11-17-350-merrydale-staff-report",
            "record-2025-11-17-san-rafael-city-council-agenda-packet",
            "record-2025-11-17-350-merrydale-resolution-county-grant-and-affordable-housing",
            "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
            "record-2025-12-01-san-rafael-city-council-page",
            "record-2025-12-01-san-rafael-city-council-minutes",
            "record-2026-02-17-san-rafael-city-council-page",
            "record-2026-02-17-san-rafael-city-council-minutes",
            "record-2026-02-17-350-merrydale-staff-report",
            "record-2026-02-17-san-rafael-city-council-agenda-packet",
            "record-2026-02-17-350-merrydale-resolution-project-services",
            "record-2026-02-17-350-merrydale-swinerton-psa",
            "record-2026-02-17-350-merrydale-lca-amendment",
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
        "evidence_summary": "This bounded project slice is anchored in official San Rafael meeting pages, official minutes, and direct city PDF staff reports and agenda packets covering ERF-3/County collaboration, November 2025 site acquisition actions, February 2026 design and construction-management authorizations, and the March 2026 operational-framework update.",
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
            "title": "350 Merrydale county grant and affordable housing agreement resolution",
            "decision_type": "grant_and_housing_agreement_authorization",
            "status": "adopted",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2025-11-17-san-rafael-city-council",
            "effective_date": "2025-11-17",
            "project_id": PROJECT_ID,
            "resolution_numbers": ["15479"],
            "related_decision_id": "decision-2025-11-17-san-rafael-city-council-6v-resolution-adoption-15478-15479-15480",
            "record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-county-grant-and-affordable-housing",
            ],
        },
        {
            "id": "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            "title": "350 Merrydale purchase and brokerage resolution",
            "decision_type": "property_acquisition_authorization",
            "status": "adopted",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2025-11-17-san-rafael-city-council",
            "effective_date": "2025-11-17",
            "project_id": PROJECT_ID,
            "resolution_numbers": ["15480"],
            "related_decision_id": "decision-2025-11-17-san-rafael-city-council-6v-resolution-adoption-15478-15479-15480",
            "record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
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
            "title": "350 Merrydale project services resolution",
            "decision_type": "project_services_authorization",
            "status": "adopted",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2026-02-17-san-rafael-city-council",
            "effective_date": "2026-02-17",
            "project_id": PROJECT_ID,
            "record_ids": feb_17_base_record_ids + feb_17_child_record_ids,
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
            "id": "agreement-350-merrydale-county-grant",
            "name": "350 Merrydale county grant agreement",
            "agreement_type": "grant_agreement",
            "institution_id": "inst-city-of-san-rafael",
            "project_id": PROJECT_ID,
            "authorized_amount": 8000000,
            "effective_date": "2025-11-17",
            "evidence_record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-county-grant-and-affordable-housing",
            ],
        },
        {
            "id": "agreement-350-merrydale-affordable-housing",
            "name": "350 Merrydale affordable housing agreement",
            "agreement_type": "affordable_housing_agreement",
            "institution_id": "inst-city-of-san-rafael",
            "project_id": PROJECT_ID,
            "effective_date": "2025-11-17",
            "evidence_record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-county-grant-and-affordable-housing",
            ],
        },
        {
            "id": "agreement-350-merrydale-purchase-and-sale",
            "name": "350 Merrydale purchase and sale agreement",
            "agreement_type": "purchase_and_sale_agreement",
            "institution_id": "inst-city-of-san-rafael",
            "project_id": PROJECT_ID,
            "authorized_amount": 6700000,
            "effective_date": "2025-11-17",
            "evidence_record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
            ],
        },
        {
            "id": "agreement-350-merrydale-swinerton-project-management",
            "name": "350 Merrydale Swinerton project and construction management agreement",
            "agreement_type": "professional_services_agreement",
            "institution_id": "inst-city-of-san-rafael",
            "counterparty_actor_id": "actor-swinerton-management-and-consulting",
            "project_id": PROJECT_ID,
            "authorized_amount": 229703,
            "effective_date": "2026-02-17",
            "evidence_record_ids": feb_17_base_record_ids + [
                "record-2026-02-17-350-merrydale-resolution-project-services",
                "record-2026-02-17-350-merrydale-swinerton-psa",
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
            "evidence_record_ids": feb_17_base_record_ids + [
                "record-2026-02-17-350-merrydale-resolution-project-services",
                "record-2026-02-17-350-merrydale-lca-amendment",
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
            "evidence_record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
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
            "evidence_record_ids": feb_17_base_record_ids + [
                "record-2026-02-17-350-merrydale-resolution-project-services",
                "record-2026-02-17-350-merrydale-lca-amendment",
            ],
        }
    ]

    money_flow_candidates = [
        {
            "id": "moneyflow-2025-11-17-350-merrydale-county-grant",
            "flow_type": "grant_award",
            "amount": 8000000,
            "currency": "USD",
            "institution_id": "inst-city-of-san-rafael",
            "related_institution_id": "inst-marin-county",
            "agreement_id": "agreement-350-merrydale-county-grant",
            "decision_id": "decision-2025-11-17-350-merrydale-county-grant-approval",
            "project_id": PROJECT_ID,
            "evidence_record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-county-grant-and-affordable-housing",
            ],
        },
        {
            "id": "moneyflow-2025-11-17-350-merrydale-property-acquisition",
            "flow_type": "property_acquisition_authorization",
            "amount": 6700000,
            "currency": "USD",
            "institution_id": "inst-city-of-san-rafael",
            "agreement_id": "agreement-350-merrydale-purchase-and-sale",
            "decision_id": "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            "project_id": PROJECT_ID,
            "evidence_record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
            ],
        },
        {
            "id": "moneyflow-2025-11-17-350-merrydale-brokerage-services",
            "flow_type": "contract_authorization",
            "amount": 201000,
            "currency": "USD",
            "institution_id": "inst-city-of-san-rafael",
            "agreement_id": "agreement-350-merrydale-newmark-brokerage",
            "counterparty_actor_id": "actor-newmark-commercial-brokerage",
            "to_actor_id": "actor-newmark-commercial-brokerage",
            "decision_id": "decision-2025-11-17-350-merrydale-acquisition-and-brokerage-approval",
            "project_id": PROJECT_ID,
            "evidence_record_ids": nov_17_base_record_ids + [
                "record-2025-11-17-350-merrydale-resolution-purchase-and-brokerage",
            ],
        },
        {
            "id": "moneyflow-2026-02-17-350-merrydale-swinerton-services",
            "flow_type": "contract_authorization",
            "amount": 229703,
            "currency": "USD",
            "institution_id": "inst-city-of-san-rafael",
            "agreement_id": "agreement-350-merrydale-swinerton-project-management",
            "counterparty_actor_id": "actor-swinerton-management-and-consulting",
            "to_actor_id": "actor-swinerton-management-and-consulting",
            "decision_id": "decision-2026-02-17-350-merrydale-project-services-authorization",
            "project_id": PROJECT_ID,
            "evidence_record_ids": feb_17_base_record_ids + [
                "record-2026-02-17-350-merrydale-resolution-project-services",
                "record-2026-02-17-350-merrydale-swinerton-psa",
            ],
        },
        {
            "id": "moneyflow-2026-02-17-350-merrydale-lca-design-amendment",
            "flow_type": "amendment_authorization",
            "amount": 207250,
            "currency": "USD",
            "institution_id": "inst-city-of-san-rafael",
            "agreement_id": "agreement-350-merrydale-lca-design-services",
            "counterparty_actor_id": "actor-lca-architects",
            "to_actor_id": "actor-lca-architects",
            "decision_id": "decision-2026-02-17-350-merrydale-project-services-authorization",
            "project_id": PROJECT_ID,
            "evidence_record_ids": feb_17_base_record_ids + [
                "record-2026-02-17-350-merrydale-resolution-project-services",
                "record-2026-02-17-350-merrydale-lca-amendment",
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
                "direct city PDF staff reports and agenda packets linked from those official meeting pages",
                "packet-derived child records for the highest-value November 2025 and February 2026 Merrydale actions",
                "direct project money flows for county grant, acquisition, brokerage, and design/construction-management authorizations",
                "project linkage back to the existing sanctioned-camping program context",
            ],
            "excluded": [
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
                "status": "resolved",
                "question": "The Merrydale thread now uses packet-derived child records and stronger agreement boundaries for the November 17, 2025 and February 17, 2026 actions.",
                "why_it_matters": "The bounded project slice no longer relies on coarse page-plus-minutes custom boundaries alone. Packet-derived child records now carry the highest-value November and February sub-actions without reopening the procurement lane.",
            }
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
