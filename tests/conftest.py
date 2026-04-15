"""Pytest fixtures for Marin Civic Graph migration tests.

Provides sample graph nodes matching the exact JSONL format from
data/projected/graph-v1/nodes.jsonl for use in migration and loading tests.
"""

import pytest


@pytest.fixture
def sample_actor_person():
    """Actor node with actor_type=person (Kate Colin, canonical seed)."""
    return {
        "id": "actor-kate-colin",
        "node_type": "Actor",
        "display_label": "Kate Colin",
        "promotion_state": "canonical",
        "source_bundle_ids": ["canonical-seeds-san-rafael-01"],
        "source_sections": ["actor_candidates"],
        "source_status": None,
        "properties": {
            "actor_type": "person",
            "name": "Kate Colin",
            "observed_labels": ["Kate Colin", "Councilmember Colin"],
            "seed_status": "canonical_seed",
            "payload_json": '{"actor_type": "person", "id": "actor-kate-colin", "name": "Kate Colin", "observed_labels": ["Kate Colin", "Councilmember Colin"], "seed_status": "canonical_seed"}'
        }
    }


@pytest.fixture
def sample_actor_business():
    """Actor node with actor_type=business (Anedot, promoted)."""
    return {
        "id": "actor-anedot",
        "node_type": "Actor",
        "display_label": "Anedot",
        "promotion_state": "promoted",
        "source_bundle_ids": ["san-rafael-actor-completeness-01__bundle-01"],
        "source_sections": ["actor_candidates"],
        "source_status": "promoted_for_graph_completeness",
        "properties": {
            "actor_type": "business",
            "name": "Anedot",
            "observed_labels": ["Anedot"],
            "evidence_record_ids": [
                "record-san-rafael-campaign-filing-entry-37677",
                "record-san-rafael-campaign-ocr-entry-37677",
                "record-san-rafael-campaign-pdf-entry-37677"
            ],
            "promotion_basis": "recurring_form460_vendor_platform_or_donor",
            "status": "promoted_for_graph_completeness",
            "payload_json": '{"actor_type": "business", "evidence_record_ids": ["record-san-rafael-campaign-filing-entry-37677", "record-san-rafael-campaign-ocr-entry-37677", "record-san-rafael-campaign-pdf-entry-37677"], "id": "actor-anedot", "name": "Anedot", "observed_labels": ["Anedot"], "promotion_basis": "recurring_form460_vendor_platform_or_donor", "status": "promoted_for_graph_completeness"}'
        }
    }


@pytest.fixture
def sample_institution():
    """Institution node (California State Library, state_agency type)."""
    return {
        "id": "inst-california-state-library",
        "node_type": "Institution",
        "display_label": "California State Library",
        "promotion_state": "promoted",
        "source_bundle_ids": [
            "grant-program-dossiers-01__bundle-01",
            "project-dossiers-01__bundle-01"
        ],
        "source_sections": ["institution_candidates"],
        "source_status": None,
        "properties": {
            "institution_type": "state_agency",
            "name": "California State Library",
            "payload_json": '{"id": "inst-california-state-library", "institution_type": "state_agency", "name": "California State Library"}'
        }
    }


@pytest.fixture
def sample_eid():
    """EconomicInterestDisclosure node (Rachel Kertz Form 700)."""
    return {
        "id": "eid-san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council",
        "node_type": "EconomicInterestDisclosure",
        "display_label": "eid-san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council",
        "promotion_state": "promoted",
        "source_bundle_ids": ["san-rafael-officeholder-disclosures-01__bundle-01"],
        "source_sections": ["economic_interest_disclosure_candidates"],
        "source_status": "historical_officeholder_continuity",
        "properties": {
            "base_filing_key": "san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council",
            "department_name": "City Council",
            "disclosure_type": "assuming_office",
            "document_link_count": 0,
            "evidence_record_ids": ["record-san-rafael-form700-export-2026-04-12"],
            "filed_at": "2020-12-23",
            "filer_actor_id": "actor-rachel-kertz",
            "filing_id": "filing-san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council",
            "filing_institution_id": "inst-city-of-san-rafael",
            "position_title": "City Council Member",
            "record_locator": "san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council",
            "seat_id": "seat-san-rafael-city-council-district-4",
            "seat_service_id": "seatservice-rachel-kertz-d4-2020-term",
            "source_filer_name": "Kertz, Rachel",
            "statement_type": "Assuming Office",
            "status": "historical_officeholder_continuity",
            "payload_json": '{"base_filing_key": "san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council", "department_name": "City Council", "disclosure_type": "assuming_office", "document_link_count": 0, "evidence_record_ids": ["record-san-rafael-form700-export-2026-04-12"], "filed_at": "2020-12-23", "filer_actor_id": "actor-rachel-kertz", "filing_id": "filing-san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council", "filing_institution_id": "inst-city-of-san-rafael", "id": "eid-san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council", "position_title": "City Council Member", "record_locator": "san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council", "seat_id": "seat-san-rafael-city-council-district-4", "seat_service_id": "seatservice-rachel-kertz-d4-2020-term", "source_filer_name": "Kertz, Rachel", "statement_type": "Assuming Office", "status": "historical_officeholder_continuity"}'
        }
    }


@pytest.fixture
def sample_case_participation():
    """CaseParticipation node (Boyd case, city defendant)."""
    return {
        "id": "casepart-boyd-city-defendant",
        "node_type": "CaseParticipation",
        "display_label": "casepart-boyd-city-defendant",
        "promotion_state": "promoted",
        "source_bundle_ids": ["legal-precedent-01__bundle-01"],
        "source_sections": ["case_participation_candidates"],
        "source_status": None,
        "properties": {
            "case_id": "case-boyd-v-city-of-san-rafael",
            "institution_id": "inst-city-of-san-rafael",
            "role": "defendant",
            "start_date": "2023-08-11",
            "evidence_record_ids": ["record-san-rafael-boyd-dismissal-order-2024-08-07"],
            "payload_json": '{"case_id": "case-boyd-v-city-of-san-rafael", "evidence_record_ids": ["record-san-rafael-boyd-dismissal-order-2024-08-07"], "id": "casepart-boyd-city-defendant", "institution_id": "inst-city-of-san-rafael", "role": "defendant", "start_date": "2023-08-11"}'
        }
    }


@pytest.fixture
def sample_decision():
    """Decision node (Resolution, city council decision)."""
    return {
        "id": "decision-2010-06-08-san-rafael-library-special-call",
        "node_type": "Decision",
        "display_label": "Call the June 8, 2010 special election for the library parcel-tax measure",
        "promotion_state": "promoted",
        "source_bundle_ids": ["san-rafael-election-records-01__bundle-01"],
        "source_sections": ["decision_candidates"],
        "source_status": "adopted",
        "properties": {
            "decided_at": "2010-02-16",
            "decision_type": "call_special_election",
            "election_id": "election-2010-06-08-san-rafael-library-special",
            "evidence_summary": "Promoted from 1 page-linked election records captured from the public San Rafael election pages.",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2010-02-16-san-rafael-city-council",
            "record_ids": ["record-san-rafael-election-entry-15680"],
            "status": "adopted",
            "title": "Call the June 8, 2010 special election for the library parcel-tax measure",
            "payload_json": '{"decided_at": "2010-02-16", "decision_type": "call_special_election", "election_id": "election-2010-06-08-san-rafael-library-special", "evidence_summary": "Promoted from 1 page-linked election records captured from the public San Rafael election pages.", "id": "decision-2010-06-08-san-rafael-library-special-call", "institution_id": "inst-san-rafael-city-council", "meeting_id": "meeting-2010-02-16-san-rafael-city-council", "record_ids": ["record-san-rafael-election-entry-15680"], "status": "adopted", "title": "Call the June 8, 2010 special election for the library parcel-tax measure"}'
        }
    }


@pytest.fixture
def sample_validation_check():
    """ValidationCheck node (reconciliation check on campaign filing)."""
    return {
        "id": "validationcheck-filing-san-rafael-campaign-entry-28450-schedule-e-itemized-payments-reconciliation-check",
        "node_type": "ValidationCheck",
        "display_label": "validationcheck-filing-san-rafael-campaign-entry-28450-schedule-e-itemized-payments-reconciliation-check",
        "promotion_state": "review",
        "source_bundle_ids": ["san-rafael-city-campaign-form460-schedules-01__bundle-01"],
        "source_sections": ["validation_check_candidates"],
        "source_status": "reconciled",
        "properties": {
            "absolute_delta_value_number": 0.0,
            "check_type": "reconciliation_check",
            "confidence": "high",
            "delta_direction": "equal",
            "delta_value_number": 0.0,
            "derived_from_record_id": "record-san-rafael-campaign-form460-schedule-extract-entry-28450",
            "evidence_record_ids": [
                "record-san-rafael-campaign-filing-entry-28450",
                "record-san-rafael-campaign-ocr-entry-28450",
                "record-san-rafael-campaign-pdf-entry-28450",
                "record-san-rafael-campaign-form460-schedule-extract-entry-28450"
            ],
            "measured_value_label": "extracted_itemized_payments_total",
            "measured_value_number": 1.0,
            "metric_name": "schedule_e_itemized_payments",
            "reference_value_label": "reported_itemized_payments",
            "reference_value_number": 1.0,
            "severity": "info",
            "status": "reconciled",
            "subject_node_id": "filing-san-rafael-campaign-entry-28450",
            "subject_node_type": "Filing",
            "payload_json": '{"absolute_delta_value_number": 0.0, "check_type": "reconciliation_check", "confidence": "high", "delta_direction": "equal", "delta_value_number": 0.0, "derived_from_record_id": "record-san-rafael-campaign-form460-schedule-extract-entry-28450", "evidence_record_ids": ["record-san-rafael-campaign-filing-entry-28450", "record-san-rafael-campaign-ocr-entry-28450", "record-san-rafael-campaign-pdf-entry-28450", "record-san-rafael-campaign-form460-schedule-extract-entry-28450"], "id": "validationcheck-filing-san-rafael-campaign-entry-28450-schedule-e-itemized-payments-reconciliation-check", "measured_value_label": "extracted_itemized_payments_total", "measured_value_number": 1.0, "metric_name": "schedule_e_itemized_payments", "notes": [], "reference_value_label": "reported_itemized_payments", "reference_value_number": 1.0, "severity": "info", "status": "reconciled", "subject_node_id": "filing-san-rafael-campaign-entry-28450", "subject_node_type": "Filing"}'
        }
    }
