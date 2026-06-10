"""Tests for scripts/ingest_990.py — builder unit (M2b).

Org/Filing/Record/Person node builders + the FILED_BY_ORG edge builder, and
Membership assembly THROUGH the M2a `membership_builders` imports (never a
fork). Asserts the full predeclared envelopes (Decision 4), the multi-year
membership dedupe rule (Decision 3: one node, sorted-union evidence_record_ids,
earliest-year source_basis, one EVIDENCED_BY per distinct record), and that
`canonical_type` resolves every emitted id to its intended type.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import ingest_990  # noqa: E402
import membership_builders  # noqa: E402
from canonical_type import canonical_type  # noqa: E402
from ingest_990 import (  # noqa: E402
    build_990_filing_node,
    build_990_person_node,
    build_990_record_node,
    build_filed_by_org_edge,
    build_memberships,
    build_org_node,
    parse_return_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "990"
MCF_2022 = FIXTURES / "202421369349304932.xml"
MCF_2023 = FIXTURES / "202541349349313719.xml"
MALT_2022 = FIXTURES / "202421309349304522.xml"


# ---------------------------------------------------------------------------
# Org node — EIN identity, Organization+Nonprofit labels
# ---------------------------------------------------------------------------


def test_org_node_envelope():
    node = build_org_node(parse_return_file(MCF_2022))
    assert node == {
        "id": "org-990-ein-943007979",
        "node_type": "Organization",
        "labels": ["Organization", "Nonprofit"],
        "display_label": "Marin Community Foundation",
        "properties": {
            "ein": "943007979",
            "legal_name": "Marin Community Foundation",
            "legal_name_raw": "MARIN COMMUNITY FOUNDATION",
            "nonprofit_status": "501c3",
            "source": "irs-990",
        },
    }


def test_org_node_id_collapses_across_years():
    # EIN is the identity — two tax years of the same filer build the SAME id.
    id_2022 = build_org_node(parse_return_file(MCF_2022))["id"]
    id_2023 = build_org_node(parse_return_file(MCF_2023))["id"]
    assert id_2022 == id_2023 == "org-990-ein-943007979"


# ---------------------------------------------------------------------------
# Filing node — year-scoped revenue facts + coverage honesty
# ---------------------------------------------------------------------------


def test_filing_node_envelope_with_gov_grants():
    node = build_990_filing_node(parse_return_file(MALT_2022))
    assert node["id"] == "filing-990-942689383-2022"
    assert node["node_type"] == "Filing"
    assert node["labels"] == ["Filing"]
    props = node["properties"]
    assert props["filing_type"] == "form_990"
    assert props["ein"] == "942689383"
    assert props["tax_year"] == "2022"
    assert props["total_revenue"] == 7362936
    assert props["gov_grants_amount"] == 3150000
    assert props["gov_revenue_share"] == 0.4278
    # Coverage honesty: an aggregate annual fact, never a confirmed local claim.
    assert props["revenue_scope"] == "form_990_aggregate_government_grants"


def test_filing_node_no_gov_grants_omits_share_and_scope():
    props = build_990_filing_node(parse_return_file(MCF_2022))["properties"]
    assert props["total_revenue"] == 232749407
    assert "gov_grants_amount" not in props
    assert "gov_revenue_share" not in props
    assert "revenue_scope" not in props


def test_filing_node_zero_revenue_omits_share_keeps_scope():
    # Degraded variant of the REAL parsed return — share is only computed when
    # revenue > 0, but the coverage prop tracks gov_grants presence.
    parsed = parse_return_file(MALT_2022)
    parsed["total_revenue"] = 0
    props = build_990_filing_node(parsed)["properties"]
    assert "gov_revenue_share" not in props
    assert props["revenue_scope"] == "form_990_aggregate_government_grants"


# ---------------------------------------------------------------------------
# Record node — the return document as provenance
# ---------------------------------------------------------------------------


def test_record_node_envelope():
    node = build_990_record_node(parse_return_file(MALT_2022))
    assert node["id"] == "record-990-942689383-2022"
    assert node["node_type"] == "Record"
    assert node["labels"] == ["Record"]
    props = node["properties"]
    assert props["ein"] == "942689383"
    assert props["tax_year"] == "2022"
    assert props["object_id"] == "202421309349304522"
    assert "source_url" not in props  # only when explicitly known — never derived


# ---------------------------------------------------------------------------
# Person node + FILED_BY_ORG edge
# ---------------------------------------------------------------------------


def test_person_node_envelope():
    parsed = parse_return_file(MALT_2022)
    hicks = next(o for o in parsed["officers"] if o["name_raw"] == "TAMARA HICKS")
    node = build_990_person_node(hicks, parsed["ein"])
    assert node == {
        "id": "person-990-942689383-tamara-hicks",
        "node_type": "Person",
        "labels": ["Person"],
        "display_label": "Tamara Hicks",
        "properties": {
            "name": "Tamara Hicks",
            "name_raw": "TAMARA HICKS",
            "source": "irs-990",
        },
    }


def test_filed_by_org_edge_envelope():
    edge = build_filed_by_org_edge("filing-990-942689383-2022", "org-990-ein-942689383")
    assert edge == {
        "source_id": "filing-990-942689383-2022",
        "target_id": "org-990-ein-942689383",
        "relationship_type": "FILED_BY_ORG",
        "properties": {},
    }


# ---------------------------------------------------------------------------
# Membership assembly — THROUGH membership_builders (never a fork)
# ---------------------------------------------------------------------------


def test_membership_builders_are_imported_not_forked():
    # The completion contract requires the import, not a reimplementation.
    assert ingest_990.build_membership_node is membership_builders.build_membership_node
    assert ingest_990.build_member_edge is membership_builders.build_member_edge
    assert (
        ingest_990.build_member_of_org_edge
        is membership_builders.build_member_of_org_edge
    )
    assert (
        ingest_990.build_evidenced_by_edge
        is membership_builders.build_evidenced_by_edge
    )


def test_memberships_single_return_envelopes():
    parsed = parse_return_file(MALT_2022)
    nodes, edges = build_memberships([parsed])

    persons = [n for n in nodes if n["node_type"] == "Person"]
    memberships = [n for n in nodes if n["node_type"] == "Membership"]
    assert len(persons) == 24
    assert len(memberships) == 24

    hicks = next(
        n for n in memberships if n["properties"]["person_name"] == "Tamara Hicks"
    )
    assert hicks["id"] == (
        "membership-990-942689383-tamara-hicks-org-990-ein-942689383-chair"
    )
    assert hicks["display_label"] == "Tamara Hicks — Chair, Marin Agricultural Land Trust"
    props = hicks["properties"]
    assert props["person_id"] == "person-990-942689383-tamara-hicks"
    assert props["organization_id"] == "org-990-ein-942689383"
    assert props["role"] == "Chair"
    assert props["confidence"] == 0.95
    assert props["source_basis"] == "irs_990_2022"
    assert props["evidence_record_ids"] == ["record-990-942689383-2022"]
    assert "started_at" not in props  # 990s carry no tenure dates — open-ended

    hicks_edges = [e for e in edges if e["source_id"] == hicks["id"]]
    assert {
        (e["relationship_type"], e["target_id"]) for e in hicks_edges
    } == {
        ("MEMBER", "person-990-942689383-tamara-hicks"),
        ("MEMBER_OF_ORG", "org-990-ein-942689383"),
        ("EVIDENCED_BY", "record-990-942689383-2022"),
    }


def test_two_year_same_officer_dedupes_to_one_membership():
    # Decision 3 dedupe rule — Mark Buell is BOARD CHAIR on both MCF returns.
    nodes, edges = build_memberships(
        [parse_return_file(MCF_2022), parse_return_file(MCF_2023)]
    )
    buell = [
        n
        for n in nodes
        if n["node_type"] == "Membership"
        and n["properties"]["person_name"] == "Mark Buell"
    ]
    assert len(buell) == 1
    props = buell[0]["properties"]
    # Sorted UNION of evidence across years.
    assert props["evidence_record_ids"] == [
        "record-990-943007979-2022",
        "record-990-943007979-2023",
    ]
    # Earliest observed year's basis.
    assert props["source_basis"] == "irs_990_2022"

    buell_edges = [e for e in edges if e["source_id"] == buell[0]["id"]]
    evidenced = [e for e in buell_edges if e["relationship_type"] == "EVIDENCED_BY"]
    # One EVIDENCED_BY per DISTINCT record — no duplicates.
    assert sorted(e["target_id"] for e in evidenced) == [
        "record-990-943007979-2022",
        "record-990-943007979-2023",
    ]
    assert len([e for e in buell_edges if e["relationship_type"] == "MEMBER"]) == 1
    assert (
        len([e for e in buell_edges if e["relationship_type"] == "MEMBER_OF_ORG"]) == 1
    )


def test_two_year_dedupe_is_input_order_independent():
    a_nodes, _ = build_memberships(
        [parse_return_file(MCF_2022), parse_return_file(MCF_2023)]
    )
    b_nodes, _ = build_memberships(
        [parse_return_file(MCF_2023), parse_return_file(MCF_2022)]
    )

    def buell_props(nodes):
        return next(
            n["properties"]
            for n in nodes
            if n["node_type"] == "Membership"
            and n["properties"]["person_name"] == "Mark Buell"
        )

    assert buell_props(a_nodes) == buell_props(b_nodes)
    assert buell_props(a_nodes)["source_basis"] == "irs_990_2022"


def test_role_change_yields_distinct_memberships():
    # Mitchell Cohen: DIRECTOR (2022) → BOARD MEMBER (2023). Role is part of
    # the membership identity, so this is two memberships — not a dedupe.
    nodes, _ = build_memberships(
        [parse_return_file(MCF_2022), parse_return_file(MCF_2023)]
    )
    cohen = [
        n
        for n in nodes
        if n["node_type"] == "Membership"
        and n["properties"]["person_name"] == "Mitchell Cohen"
    ]
    assert len(cohen) == 2
    assert {n["properties"]["role"] for n in cohen} == {"Director", "Board Member"}
    assert {n["properties"]["source_basis"] for n in cohen} == {
        "irs_990_2022",
        "irs_990_2023",
    }
    # One Person node feeds both memberships.
    cohen_persons = [
        n for n in nodes if n["id"] == "person-990-943007979-mitchell-cohen"
    ]
    assert len(cohen_persons) == 1


# ---------------------------------------------------------------------------
# canonical_type — every emitted id resolves to its intended type
# ---------------------------------------------------------------------------


def test_canonical_type_resolves_every_emitted_id():
    parsed_returns = [
        parse_return_file(MCF_2022),
        parse_return_file(MCF_2023),
        parse_return_file(MALT_2022),
    ]
    nodes: list[dict] = []
    for parsed in parsed_returns:
        nodes.append(build_org_node(parsed))
        nodes.append(build_990_filing_node(parsed))
        nodes.append(build_990_record_node(parsed))
    membership_nodes, _ = build_memberships(parsed_returns)
    nodes.extend(membership_nodes)

    assert len(nodes) > 9 + 50  # 3 orgs(2 ids)+3 filings+3 records + persons+memberships
    for node in nodes:
        assert canonical_type(node["labels"], node["id"]) == node["node_type"], node["id"]
