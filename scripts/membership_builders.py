"""membership_builders.py — pure Membership node/edge builders (M2a).

COI spec §4.1: a Membership reifies a person↔org affiliation (board / officer /
staff) as a node with prefix `membership-`, connected by MEMBER → Person,
MEMBER_OF_ORG → Organization, and the universal EVIDENCED_BY → Record for its
`evidence_record_ids[]` provenance.

Modeled on ingest_form700's build_* helpers: pure data shapers in the graph
ontology envelope ({id, node_type, labels, display_label, properties} /
{source_id, target_id, relationship_type, properties}), no Neo4j connection.
The M2b IRS 990 ingestor consumes these to emit membership-* nodes into
load_neo4j_v2 — Membership is ingestor-sourced, never projected.
"""
from __future__ import annotations

import re
from typing import Any


def slugify(value: str) -> str:
    """Convert a string to a lowercase URL-safe slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def build_membership_node(
    *,
    person_id: str,
    person_name: str,
    organization_id: str,
    organization_name: str,
    role: str,
    confidence: float,
    source_basis: str,
    evidence_record_ids: list[str],
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict[str, Any]:
    """Build a Membership node dict from §4.1 fields.

    The id is deterministic: person + organization + role (+ started_at when
    known, so consecutive terms of the same role are distinct memberships).
    person_name / organization_name are denormalized into properties because
    the entity-facts and browse surfaces render them directly.
    """
    slug_parts = [
        person_id.removeprefix("person-"),
        organization_id.removeprefix("organization-"),
        slugify(role),
        started_at or "",
    ]
    node_id = "membership-" + "-".join(p for p in slug_parts if p)

    props: dict[str, Any] = {
        "person_id": person_id,
        "organization_id": organization_id,
        "person_name": person_name,
        "organization_name": organization_name,
        "role": role,
        "confidence": confidence,
        "source_basis": source_basis,
        "evidence_record_ids": evidence_record_ids,
    }
    # Open-ended tenure: omit the key (entity-temporal returns null cleanly).
    if started_at:
        props["started_at"] = started_at
    if ended_at:
        props["ended_at"] = ended_at

    return {
        "id": node_id,
        "node_type": "Membership",
        "labels": ["Membership"],
        "display_label": f"{person_name} — {role}, {organization_name}",
        "properties": props,
    }


def build_member_edge(membership_id: str, person_id: str) -> dict[str, Any]:
    """Build a MEMBER edge from a Membership node to its Person."""
    return {
        "source_id": membership_id,
        "target_id": person_id,
        "relationship_type": "MEMBER",
        "properties": {},
    }


def build_member_of_org_edge(membership_id: str, organization_id: str) -> dict[str, Any]:
    """Build a MEMBER_OF_ORG edge from a Membership node to its Organization."""
    return {
        "source_id": membership_id,
        "target_id": organization_id,
        "relationship_type": "MEMBER_OF_ORG",
        "properties": {},
    }


def build_evidenced_by_edge(membership_id: str, record_id: str) -> dict[str, Any]:
    """Build the universal EVIDENCED_BY edge from a Membership node to a Record."""
    return {
        "source_id": membership_id,
        "target_id": record_id,
        "relationship_type": "EVIDENCED_BY",
        "properties": {},
    }
