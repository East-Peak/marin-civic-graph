"""Tests for scripts/membership_builders.py — pure Membership builders (M2a).

COI spec §4.1: a Membership is a reified person↔org affiliation node
(`membership-` prefix; person_id / organization_id / role / started_at? /
ended_at? / confidence / source_basis / evidence_record_ids[]) connected by
MEMBER → Person, MEMBER_OF_ORG → Organization, and the universal
EVIDENCED_BY → Record. Builders are modeled on ingest_form700's build_*
helpers: pure data shapers, no Neo4j connection.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from membership_builders import (  # noqa: E402
    build_evidenced_by_edge,
    build_member_edge,
    build_member_of_org_edge,
    build_membership_node,
)

SAMPLE = dict(
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


def test_membership_node_envelope():
    node = build_membership_node(**SAMPLE)
    assert node["id"].startswith("membership-")
    assert node["node_type"] == "Membership"
    assert node["labels"] == ["Membership"]
    assert (
        node["display_label"]
        == "Jane Doe — Board Chair, Marin Community Foundation"
    )
    props = node["properties"]
    assert props["person_id"] == "person-jane-doe"
    assert props["organization_id"] == "organization-marin-community-foundation"
    # person_name / organization_name feed the entity-facts + browse columns.
    assert props["person_name"] == "Jane Doe"
    assert props["organization_name"] == "Marin Community Foundation"
    assert props["role"] == "Board Chair"
    assert props["started_at"] == "2023-07-01"
    assert "ended_at" not in props  # open-ended tenure: key absent, not null
    assert props["confidence"] == 0.95
    assert props["source_basis"] == "irs_990_2023"
    assert props["evidence_record_ids"] == ["record-990-mcf-2023"]


def test_membership_node_id_is_deterministic():
    assert build_membership_node(**SAMPLE)["id"] == build_membership_node(**SAMPLE)["id"]


def test_membership_node_id_distinct_per_role_and_term():
    base = build_membership_node(**SAMPLE)["id"]
    other_role = build_membership_node(**{**SAMPLE, "role": "Treasurer"})["id"]
    other_term = build_membership_node(**{**SAMPLE, "started_at": "2018-07-01"})["id"]
    assert len({base, other_role, other_term}) == 3


def test_membership_node_optional_dates_omitted():
    # No started_at/ended_at → keys absent so entity-temporal returns null cleanly.
    node = build_membership_node(**{k: v for k, v in SAMPLE.items() if k != "started_at"})
    props = node["properties"]
    assert "started_at" not in props
    assert "ended_at" not in props
    assert node["id"].startswith("membership-")


def test_membership_node_ended_at_included_when_given():
    node = build_membership_node(**SAMPLE, ended_at="2025-06-30")
    assert node["properties"]["ended_at"] == "2025-06-30"


def test_member_edge_envelope():
    assert build_member_edge("membership-x", "person-jane-doe") == {
        "source_id": "membership-x",
        "target_id": "person-jane-doe",
        "relationship_type": "MEMBER",
        "properties": {},
    }


def test_member_of_org_edge_envelope():
    assert build_member_of_org_edge("membership-x", "organization-mcf") == {
        "source_id": "membership-x",
        "target_id": "organization-mcf",
        "relationship_type": "MEMBER_OF_ORG",
        "properties": {},
    }


def test_evidenced_by_edge_envelope():
    assert build_evidenced_by_edge("membership-x", "record-990-mcf-2023") == {
        "source_id": "membership-x",
        "target_id": "record-990-mcf-2023",
        "relationship_type": "EVIDENCED_BY",
        "properties": {},
    }


def test_full_membership_fixture_node_plus_three_edges():
    """The condition-5 fixture: one membership → node + MEMBER / MEMBER_OF_ORG /
    EVIDENCED_BY envelopes whose endpoints all agree with the node's properties."""
    node = build_membership_node(**SAMPLE)
    props = node["properties"]
    edges = [
        build_member_edge(node["id"], props["person_id"]),
        build_member_of_org_edge(node["id"], props["organization_id"]),
        *(
            build_evidenced_by_edge(node["id"], rid)
            for rid in props["evidence_record_ids"]
        ),
    ]
    assert [e["relationship_type"] for e in edges] == [
        "MEMBER",
        "MEMBER_OF_ORG",
        "EVIDENCED_BY",
    ]
    assert all(e["source_id"] == node["id"] for e in edges)
    assert edges[0]["target_id"] == "person-jane-doe"
    assert edges[1]["target_id"] == "organization-marin-community-foundation"
    assert edges[2]["target_id"] == "record-990-mcf-2023"
