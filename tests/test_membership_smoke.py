"""M2a smoke tests (Python) — the Membership branches EXECUTE.

Parity proves every surface has a Membership key; these prove the entries
behave: outbound eligibility + egress synthesis (against builder-produced
sample nodes — zero live instances is the expected state until M2b's 990
ingestor runs), and the search-properties exclusion (searchable=false).
No Neo4j connection, no vendor calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_search_properties as bsp  # noqa: E402
from membership_builders import build_membership_node  # noqa: E402
from outbound_policy import (  # noqa: E402
    TYPE_ELIGIBILITY,
    is_eligible,
    synthesize_outbound_text,
)


def _outbound_shape(node: dict) -> dict:
    """Map a builder envelope to the outbound-policy node shape."""
    return {
        "id": node["id"],
        "type": node["node_type"],
        "label": node["display_label"],
        **node["properties"],
    }


SAMPLE = build_membership_node(
    person_id="person-jane-doe",
    person_name="Jane Doe",
    organization_id="organization-marin-community-foundation",
    organization_name="Marin Community Foundation",
    role="Board Chair",
    started_at="2023-07-01",
    confidence=0.95,
    source_basis="irs_990_2023",
    evidence_record_ids=["record-990-mcf-2023"],
)


class TestOutboundEligibility:
    def test_membership_is_an_explicit_eligibility_key(self):
        # Present in the map (not reliant on any default) and eligible — same
        # flags as the MoneyFlow/SeatService connective analogs.
        assert TYPE_ELIGIBILITY["Membership"] is True
        assert is_eligible("Membership")


class TestOutboundEgressSmoke:
    def test_membership_node_synthesizes_sensible_text(self):
        text = synthesize_outbound_text(_outbound_shape(SAMPLE), neighbors=[])
        assert "Membership" in text
        assert "Jane Doe — Board Chair, Marin Community Foundation" in text
        assert "Board Chair" in text  # role line

    def test_sparse_membership_node_does_not_throw(self):
        # Degenerate node (no props beyond id/type) must still egress safely —
        # the embedding/constellation surfaces can't break on sparse data.
        text = synthesize_outbound_text(
            {"id": "membership-x", "type": "Membership"}, neighbors=[]
        )
        assert isinstance(text, str)
        assert "Membership" in text

    def test_membership_neighbors_pass_eligibility_filtering(self):
        text = synthesize_outbound_text(
            _outbound_shape(SAMPLE),
            neighbors=[
                {"id": "person-jane-doe", "type": "Person", "label": "Jane Doe"},
                {"id": "x-1", "type": "CriminalRecord", "label": "must not appear"},
            ],
        )
        assert "Jane Doe" in text
        assert "must not appear" not in text


class TestSearchExclusion:
    def test_membership_absent_from_indexed_types(self):
        # searchable=false: you search People/Orgs and find their Memberships
        # through the graph, never a membership directly. Count stays 14.
        assert "Membership" not in bsp.INDEXED_TYPES
        assert len(bsp.INDEXED_TYPES) == 14

    def test_membership_absent_from_all_searchable_types(self):
        assert "Membership" not in bsp.ALL_SEARCHABLE_TYPES

    def test_membership_has_no_search_weight(self):
        assert "Membership" not in bsp.TYPE_WEIGHT
