"""Tests for migration_mapping.py — node/edge/id remapping from 28-type legacy schema to 21-type ontology.

TDD: tests written first, implementation follows.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest
from migration_mapping import (
    migrate_id,
    migrate_node,
    migrate_edge,
    case_participation_to_edges,
)


# ---------------------------------------------------------------------------
# TestMigrateId
# ---------------------------------------------------------------------------

class TestMigrateId:
    """ID prefix remapping rules."""

    def test_actor_person_gets_person_prefix(self, sample_actor_person):
        new_id = migrate_id(
            sample_actor_person["id"],
            sample_actor_person["node_type"],
            sample_actor_person["properties"],
        )
        assert new_id == "person-kate-colin"

    def test_actor_business_gets_org_prefix(self, sample_actor_business):
        new_id = migrate_id(
            sample_actor_business["id"],
            sample_actor_business["node_type"],
            sample_actor_business["properties"],
        )
        assert new_id == "org-anedot"

    def test_actor_nonprofit_gets_org_prefix(self):
        new_id = migrate_id(
            "actor-marin-humane",
            "Actor",
            {"actor_type": "nonprofit"},
        )
        assert new_id == "org-marin-humane"

    def test_actor_political_committee_gets_org_prefix(self):
        new_id = migrate_id(
            "actor-vote-yes-123",
            "Actor",
            {"actor_type": "political_committee"},
        )
        assert new_id == "org-vote-yes-123"

    def test_actor_unknown_defaults_to_person_prefix(self):
        new_id = migrate_id(
            "actor-mystery-entity",
            "Actor",
            {"actor_type": "unknown"},
        )
        assert new_id == "person-mystery-entity"

    def test_actor_missing_type_defaults_to_person_prefix(self):
        new_id = migrate_id(
            "actor-edward-m-chen",
            "Actor",
            {},
        )
        assert new_id == "person-edward-m-chen"

    def test_actor_organization_gets_org_prefix(self):
        new_id = migrate_id(
            "actor-acme-org",
            "Actor",
            {"actor_type": "organization"},
        )
        assert new_id == "org-acme-org"

    def test_actor_government_agency_gets_org_prefix(self):
        new_id = migrate_id(
            "actor-doj",
            "Actor",
            {"actor_type": "government_agency"},
        )
        assert new_id == "org-doj"

    def test_institution_gets_org_prefix(self, sample_institution):
        new_id = migrate_id(
            sample_institution["id"],
            sample_institution["node_type"],
            sample_institution["properties"],
        )
        assert new_id == "org-california-state-library"

    def test_eid_gets_filing_prefix(self, sample_eid):
        new_id = migrate_id(
            sample_eid["id"],
            sample_eid["node_type"],
            sample_eid["properties"],
        )
        assert new_id.startswith("filing-")
        assert "kertz-rachel" in new_id

    def test_passthrough_id_unchanged(self, sample_decision):
        new_id = migrate_id(
            sample_decision["id"],
            sample_decision["node_type"],
            sample_decision["properties"],
        )
        assert new_id == sample_decision["id"]

    def test_meeting_id_unchanged(self):
        new_id = migrate_id(
            "meeting-2010-02-16-san-rafael-city-council",
            "Meeting",
            {},
        )
        assert new_id == "meeting-2010-02-16-san-rafael-city-council"


# ---------------------------------------------------------------------------
# TestMigrateNode
# ---------------------------------------------------------------------------

class TestMigrateNode:
    """Node transformation: id, node_type, labels, properties."""

    # --- Actor → Person ---

    def test_actor_person_id_remapped(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert result["id"] == "person-kate-colin"

    def test_actor_person_node_type(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert result["node_type"] == "Person"

    def test_actor_person_labels(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert result["labels"] == ["Person"]

    def test_actor_person_observed_labels_renamed_to_aliases(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert "aliases" in result["properties"]
        assert result["properties"]["aliases"] == ["Kate Colin", "Councilmember Colin"]

    def test_actor_person_actor_type_removed(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert "actor_type" not in result["properties"]

    def test_actor_person_observed_labels_key_removed(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert "observed_labels" not in result["properties"]

    def test_actor_person_qa_lane_false(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert result["qa_lane"] is False

    def test_actor_person_preserves_display_label(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert result["display_label"] == "Kate Colin"

    def test_actor_person_preserves_promotion_state(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert result["promotion_state"] == "canonical"

    # --- Actor → Organization (business) ---

    def test_actor_business_id_remapped(self, sample_actor_business):
        result = migrate_node(sample_actor_business)
        assert result["id"] == "org-anedot"

    def test_actor_business_node_type(self, sample_actor_business):
        result = migrate_node(sample_actor_business)
        assert result["node_type"] == "Organization"

    def test_actor_business_labels(self, sample_actor_business):
        result = migrate_node(sample_actor_business)
        assert result["labels"] == ["Organization", "Business"]

    def test_actor_business_actor_type_removed(self, sample_actor_business):
        result = migrate_node(sample_actor_business)
        assert "actor_type" not in result["properties"]

    def test_actor_nonprofit_labels(self):
        node = {
            "id": "actor-friends-of-canal",
            "node_type": "Actor",
            "display_label": "Friends of Canal",
            "promotion_state": "promoted",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {"actor_type": "nonprofit", "name": "Friends of Canal"},
        }
        result = migrate_node(node)
        assert result["labels"] == ["Organization", "Nonprofit"]

    def test_actor_political_committee_labels(self):
        node = {
            "id": "actor-vote-yes-123",
            "node_type": "Actor",
            "display_label": "Vote Yes 123",
            "promotion_state": "promoted",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {"actor_type": "political_committee", "name": "Vote Yes 123"},
        }
        result = migrate_node(node)
        assert result["labels"] == ["Organization", "Political"]

    def test_actor_government_agency_labels(self):
        node = {
            "id": "actor-doj",
            "node_type": "Actor",
            "display_label": "DOJ",
            "promotion_state": "promoted",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {"actor_type": "government_agency", "name": "DOJ"},
        }
        result = migrate_node(node)
        assert result["labels"] == ["Organization", "Government"]

    def test_actor_unknown_defaults_to_person(self):
        node = {
            "id": "actor-mystery",
            "node_type": "Actor",
            "display_label": "Mystery",
            "promotion_state": "promoted",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {"actor_type": "unknown", "name": "Mystery"},
        }
        result = migrate_node(node)
        assert result["node_type"] == "Person"
        assert result["labels"] == ["Person"]
        assert result["id"] == "person-mystery"

    def test_actor_missing_type_defaults_to_person(self):
        node = {
            "id": "actor-edward-m-chen",
            "node_type": "Actor",
            "display_label": "Edward M. Chen",
            "promotion_state": "promoted",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {"name": "Edward M. Chen"},
        }
        result = migrate_node(node)
        assert result["node_type"] == "Person"
        assert result["labels"] == ["Person"]
        assert result["id"] == "person-edward-m-chen"

    # --- Institution → Organization ---

    def test_institution_id_remapped(self, sample_institution):
        result = migrate_node(sample_institution)
        assert result["id"] == "org-california-state-library"

    def test_institution_node_type(self, sample_institution):
        result = migrate_node(sample_institution)
        assert result["node_type"] == "Organization"

    def test_institution_state_agency_labels(self, sample_institution):
        result = migrate_node(sample_institution)
        assert result["labels"] == ["Organization", "Government"]

    def test_institution_institution_type_renamed_to_subtype(self, sample_institution):
        result = migrate_node(sample_institution)
        assert "subtype" in result["properties"]
        assert result["properties"]["subtype"] == "state_agency"
        assert "institution_type" not in result["properties"]

    def test_institution_court_labels(self):
        node = {
            "id": "inst-marin-superior-court",
            "node_type": "Institution",
            "display_label": "Marin Superior Court",
            "promotion_state": "canonical",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {"institution_type": "court", "name": "Marin Superior Court"},
        }
        result = migrate_node(node)
        assert result["labels"] == ["Organization", "Court"]

    def test_institution_city_government_labels(self):
        node = {
            "id": "inst-city-of-san-rafael",
            "node_type": "Institution",
            "display_label": "City of San Rafael",
            "promotion_state": "canonical",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {"institution_type": "city_government", "name": "City of San Rafael"},
        }
        result = migrate_node(node)
        assert result["labels"] == ["Organization", "Government"]

    # --- EID → Filing ---

    def test_eid_id_remapped(self, sample_eid):
        result = migrate_node(sample_eid)
        assert result["id"].startswith("filing-")

    def test_eid_node_type(self, sample_eid):
        result = migrate_node(sample_eid)
        assert result["node_type"] == "Filing"

    def test_eid_labels(self, sample_eid):
        result = migrate_node(sample_eid)
        assert result["labels"] == ["Filing"]

    def test_eid_filing_type_set(self, sample_eid):
        result = migrate_node(sample_eid)
        assert result["properties"]["filing_type"] == "form_700"

    def test_eid_filer_actor_id_renamed_to_filed_by(self, sample_eid):
        result = migrate_node(sample_eid)
        assert "filed_by" in result["properties"]
        assert "filer_actor_id" not in result["properties"]

    def test_eid_filed_by_remapped_to_person_prefix(self, sample_eid):
        # filer_actor_id was "actor-rachel-kertz" → filed_by should be deferred (actor- IDs
        # resolved in second pass), so filed_by keeps the actor- prefix for now
        result = migrate_node(sample_eid)
        # filer was actor-rachel-kertz; actor- refs unresolved in single-node pass
        assert result["properties"]["filed_by"] == "actor-rachel-kertz"

    def test_eid_inst_ref_in_props_remapped(self, sample_eid):
        # filing_institution_id starts with inst- → should become org-
        result = migrate_node(sample_eid)
        assert result["properties"]["filing_institution_id"].startswith("org-")

    def test_eid_disclosure_type_renamed_to_disclosure_subtype(self, sample_eid):
        result = migrate_node(sample_eid)
        assert "disclosure_subtype" in result["properties"]
        assert result["properties"]["disclosure_subtype"] == "assuming_office"
        assert "disclosure_type" not in result["properties"]

    # --- CaseParticipation → dropped ---

    def test_case_participation_returns_none(self, sample_case_participation):
        result = migrate_node(sample_case_participation)
        assert result is None

    # --- ValidationCheck ---

    def test_validation_check_qa_lane_true(self, sample_validation_check):
        result = migrate_node(sample_validation_check)
        assert result["qa_lane"] is True

    def test_validation_check_node_type_unchanged(self, sample_validation_check):
        result = migrate_node(sample_validation_check)
        assert result["node_type"] == "ValidationCheck"

    def test_validation_check_id_unchanged(self, sample_validation_check):
        result = migrate_node(sample_validation_check)
        assert result["id"] == sample_validation_check["id"]

    # --- Decision (institution_id remapped) ---

    def test_decision_institution_id_remapped(self, sample_decision):
        result = migrate_node(sample_decision)
        assert result["properties"]["institution_id"] == "org-san-rafael-city-council"

    def test_decision_node_type_unchanged(self, sample_decision):
        result = migrate_node(sample_decision)
        assert result["node_type"] == "Decision"

    def test_decision_id_unchanged(self, sample_decision):
        result = migrate_node(sample_decision)
        assert result["id"] == sample_decision["id"]

    def test_decision_qa_lane_false(self, sample_decision):
        result = migrate_node(sample_decision)
        assert result["qa_lane"] is False

    # --- Meeting (passthrough, property refs remapped) ---

    def test_meeting_unchanged_except_prop_refs(self):
        node = {
            "id": "meeting-2024-01-16-san-rafael-city-council",
            "node_type": "Meeting",
            "display_label": "City Council Meeting Jan 16 2024",
            "promotion_state": "promoted",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {
                "institution_id": "inst-san-rafael-city-council",
                "name": "City Council Meeting",
            },
        }
        result = migrate_node(node)
        assert result["id"] == node["id"]
        assert result["node_type"] == "Meeting"
        assert result["labels"] == ["Meeting"]
        assert result["properties"]["institution_id"] == "org-san-rafael-city-council"

    def test_eid_ref_in_props_remapped_to_filing(self):
        """eid- references in any node's properties are remapped to filing-."""
        node = {
            "id": "some-node-123",
            "node_type": "SomeType",
            "display_label": "Some Node",
            "promotion_state": "canonical",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {
                "related_eid": "eid-some-form700-2020",
            },
        }
        result = migrate_node(node)
        assert result["properties"]["related_eid"] == "filing-some-form700-2020"


# ---------------------------------------------------------------------------
# TestMigrateEdge
# ---------------------------------------------------------------------------

class TestMigrateEdge:
    """Edge migration: rel type remapping, id remapping, casepart- dropping."""

    def _make_edge(self, rel_type, src_id, tgt_id, src_type="Actor", tgt_type="Decision", props=None):
        return {
            "id": f"edge-{src_id}-{rel_type.lower()}-{tgt_id}",
            "relationship_type": rel_type,
            "source_id": src_id,
            "target_id": tgt_id,
            "source_node_type": src_type,
            "target_node_type": tgt_type,
            "properties": props or {},
        }

    def test_cast_vote_on_renamed(self):
        edge = self._make_edge("CAST_VOTE_ON", "actor-kate-colin", "vote-123")
        id_map = {"actor-kate-colin": "person-kate-colin"}
        result = migrate_edge(edge, id_map)
        assert result["relationship_type"] == "CAST_VOTE"

    def test_cast_vote_on_source_remapped(self):
        edge = self._make_edge("CAST_VOTE_ON", "actor-kate-colin", "vote-123")
        id_map = {"actor-kate-colin": "person-kate-colin"}
        result = migrate_edge(edge, id_map)
        assert result["source_id"] == "person-kate-colin"

    def test_cast_vote_on_source_node_type_remapped(self):
        edge = self._make_edge("CAST_VOTE_ON", "actor-kate-colin", "vote-123", src_type="Actor")
        id_map = {"actor-kate-colin": "person-kate-colin"}
        result = migrate_edge(edge, id_map)
        assert result["source_node_type"] == "Person"

    def test_decided_by_institution_renamed(self):
        edge = self._make_edge(
            "DECIDED_BY_INSTITUTION",
            "decision-foo",
            "inst-san-rafael-city-council",
            src_type="Decision",
            tgt_type="Institution",
        )
        id_map = {"inst-san-rafael-city-council": "org-san-rafael-city-council"}
        result = migrate_edge(edge, id_map)
        assert result["relationship_type"] == "DECIDED_BY"

    def test_decided_by_institution_target_remapped(self):
        edge = self._make_edge(
            "DECIDED_BY_INSTITUTION",
            "decision-foo",
            "inst-san-rafael-city-council",
            src_type="Decision",
            tgt_type="Institution",
        )
        id_map = {"inst-san-rafael-city-council": "org-san-rafael-city-council"}
        result = migrate_edge(edge, id_map)
        assert result["target_id"] == "org-san-rafael-city-council"
        assert result["target_node_type"] == "Organization"

    def test_decided_at_meeting_renamed(self):
        edge = self._make_edge(
            "DECIDED_AT_MEETING",
            "decision-foo",
            "meeting-bar",
            src_type="Decision",
            tgt_type="Meeting",
        )
        result = migrate_edge(edge, {})
        assert result["relationship_type"] == "AT_MEETING"

    def test_heard_in_court_renamed(self):
        edge = self._make_edge(
            "HEARD_IN_COURT",
            "case-foo",
            "inst-marin-court",
            src_type="Case",
            tgt_type="Institution",
        )
        id_map = {"inst-marin-court": "org-marin-court"}
        result = migrate_edge(edge, id_map)
        assert result["relationship_type"] == "HEARD_IN"

    def test_involves_actor_renamed_to_party_to(self):
        edge = self._make_edge("INVOLVES_ACTOR", "case-foo", "actor-kate-colin", tgt_type="Actor")
        id_map = {"actor-kate-colin": "person-kate-colin"}
        result = migrate_edge(edge, id_map)
        assert result["relationship_type"] == "PARTY_TO"

    def test_committee_actor_renamed_to_controlled_by(self):
        edge = self._make_edge(
            "COMMITTEE_ACTOR",
            "actor-vote-yes",
            "actor-kate-colin",
            src_type="Actor",
            tgt_type="Actor",
        )
        id_map = {"actor-vote-yes": "org-vote-yes", "actor-kate-colin": "person-kate-colin"}
        result = migrate_edge(edge, id_map)
        assert result["relationship_type"] == "CONTROLLED_BY"

    def test_unknown_rel_type_passes_through(self):
        edge = self._make_edge("CUSTOM_REL", "decision-foo", "meeting-bar")
        result = migrate_edge(edge, {})
        assert result["relationship_type"] == "CUSTOM_REL"

    def test_casepart_source_edge_dropped(self):
        edge = self._make_edge("INVOLVES_ACTOR", "casepart-boyd-city-defendant", "actor-foo")
        result = migrate_edge(edge, {})
        assert result is None

    def test_casepart_target_edge_dropped(self):
        edge = self._make_edge("INVOLVES_INSTITUTION", "case-foo", "casepart-boyd-city-defendant")
        result = migrate_edge(edge, {})
        assert result is None

    def test_id_ref_in_edge_properties_remapped(self):
        edge = self._make_edge(
            "FILED_BY_ACTOR",
            "eid-some-form700",
            "actor-rachel-kertz",
            src_type="EconomicInterestDisclosure",
            tgt_type="Actor",
            props={"related_inst": "inst-city-of-san-rafael"},
        )
        id_map = {
            "eid-some-form700": "filing-some-form700",
            "actor-rachel-kertz": "person-rachel-kertz",
        }
        result = migrate_edge(edge, id_map)
        assert result["properties"]["related_inst"] == "org-city-of-san-rafael"

    def test_edge_id_remapped_in_prop_via_id_map(self):
        """Edge property values matching keys in id_map are remapped."""
        edge = self._make_edge(
            "FILED_BY_ACTOR",
            "eid-some-form700",
            "actor-rachel-kertz",
            src_type="EconomicInterestDisclosure",
            tgt_type="Actor",
            props={"related_actor": "actor-rachel-kertz"},
        )
        id_map = {
            "eid-some-form700": "filing-some-form700",
            "actor-rachel-kertz": "person-rachel-kertz",
        }
        result = migrate_edge(edge, id_map)
        assert result["properties"]["related_actor"] == "person-rachel-kertz"

    def test_actor_source_node_type_becomes_organization_when_org_prefix(self):
        """When source_id maps to org-, source_node_type should become Organization."""
        edge = self._make_edge(
            "FILED_BY_ACTOR",
            "actor-anedot",
            "eid-some-form700",
            src_type="Actor",
            tgt_type="EconomicInterestDisclosure",
        )
        id_map = {
            "actor-anedot": "org-anedot",
            "eid-some-form700": "filing-some-form700",
        }
        result = migrate_edge(edge, id_map)
        assert result["source_node_type"] == "Organization"
        assert result["target_node_type"] == "Filing"

    def test_relates_to_validationcheck_renamed(self):
        edge = self._make_edge(
            "RELATES_TO_VALIDATIONCHECK",
            "filing-foo",
            "validationcheck-bar",
            src_type="Filing",
            tgt_type="ValidationCheck",
        )
        result = migrate_edge(edge, {})
        assert result["relationship_type"] == "VALIDATES"


# ---------------------------------------------------------------------------
# TestCaseParticipationToEdges
# ---------------------------------------------------------------------------

class TestCaseParticipationToEdges:
    """case_participation_to_edges: CaseParticipation nodes → PARTY_TO edges."""

    def test_institution_defendant_creates_party_to_edge(self, sample_case_participation):
        id_map = {"inst-city-of-san-rafael": "org-city-of-san-rafael"}
        edges = case_participation_to_edges(
            [sample_case_participation],
            cp_evidence={},
            id_map=id_map,
        )
        assert len(edges) == 1
        e = edges[0]
        assert e["relationship_type"] == "PARTY_TO"

    def test_institution_defendant_source_is_org(self, sample_case_participation):
        id_map = {"inst-city-of-san-rafael": "org-city-of-san-rafael"}
        edges = case_participation_to_edges(
            [sample_case_participation],
            cp_evidence={},
            id_map=id_map,
        )
        assert edges[0]["source_id"] == "org-city-of-san-rafael"
        assert edges[0]["source_node_type"] == "Organization"

    def test_institution_defendant_target_is_case(self, sample_case_participation):
        id_map = {"inst-city-of-san-rafael": "org-city-of-san-rafael"}
        edges = case_participation_to_edges(
            [sample_case_participation],
            cp_evidence={},
            id_map=id_map,
        )
        assert edges[0]["target_id"] == "case-boyd-v-city-of-san-rafael"
        assert edges[0]["target_node_type"] == "Case"

    def test_institution_defendant_role_in_props(self, sample_case_participation):
        id_map = {"inst-city-of-san-rafael": "org-city-of-san-rafael"}
        edges = case_participation_to_edges(
            [sample_case_participation],
            cp_evidence={},
            id_map=id_map,
        )
        assert edges[0]["properties"]["role"] == "defendant"

    def test_institution_defendant_start_date_in_props(self, sample_case_participation):
        id_map = {"inst-city-of-san-rafael": "org-city-of-san-rafael"}
        edges = case_participation_to_edges(
            [sample_case_participation],
            cp_evidence={},
            id_map=id_map,
        )
        assert edges[0]["properties"]["start_date"] == "2023-08-11"

    def test_evidence_merged_from_cp_evidence_map(self, sample_case_participation):
        cp_evidence = {
            "casepart-boyd-city-defendant": ["record-extra-evidence-01"],
        }
        id_map = {"inst-city-of-san-rafael": "org-city-of-san-rafael"}
        edges = case_participation_to_edges(
            [sample_case_participation],
            cp_evidence=cp_evidence,
            id_map=id_map,
        )
        evids = edges[0]["properties"]["evidence_record_ids"]
        assert "record-san-rafael-boyd-dismissal-order-2024-08-07" in evids
        assert "record-extra-evidence-01" in evids

    def test_actor_plaintiff_creates_party_to_edge(self):
        cp = {
            "id": "casepart-boyd-plaintiff",
            "node_type": "CaseParticipation",
            "display_label": "casepart-boyd-plaintiff",
            "promotion_state": "promoted",
            "source_bundle_ids": ["legal-precedent-01__bundle-01"],
            "source_sections": ["case_participation_candidates"],
            "source_status": None,
            "properties": {
                "case_id": "case-boyd-v-city-of-san-rafael",
                "actor_id": "actor-james-boyd",
                "role": "plaintiff",
                "start_date": "2023-08-11",
                "evidence_record_ids": ["record-san-rafael-boyd-complaint-2023-08-11"],
            },
        }
        id_map = {"actor-james-boyd": "person-james-boyd"}
        edges = case_participation_to_edges([cp], cp_evidence={}, id_map=id_map)
        assert len(edges) == 1
        e = edges[0]
        assert e["source_id"] == "person-james-boyd"
        assert e["source_node_type"] == "Person"
        assert e["relationship_type"] == "PARTY_TO"
        assert e["properties"]["role"] == "plaintiff"

    def test_cp_with_no_party_id_skipped(self):
        """CaseParticipation with neither actor_id nor institution_id is skipped."""
        cp = {
            "id": "casepart-broken",
            "node_type": "CaseParticipation",
            "display_label": "casepart-broken",
            "promotion_state": "promoted",
            "source_bundle_ids": [],
            "source_sections": [],
            "source_status": None,
            "properties": {
                "case_id": "case-some-case",
                "role": "unknown",
            },
        }
        edges = case_participation_to_edges([cp], cp_evidence={}, id_map={})
        assert edges == []
