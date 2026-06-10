"""Tests for scripts/ingest_usaspending.py — builder unit (M2c, Decisions 3–5).

Envelopes are the ingest_990/form700 shape consumed by load_neo4j_v2. Edge
direction follows the campaign-finance MoneyFlow precedent: agency-org
—FROM_SOURCE→ MoneyFlow —TO_TARGET→ recipient-org; MoneyFlow —EVIDENCED_BY→
Record. FROM_SOURCE is ALWAYS the awarding toptier agency (the obligating
entity, present on every row); funding agency is props only.

Recipient identity is TWO-PASS (Decision 3): group rows by recipient_id,
then the whole group gets `org-usasp-uei-<UEI>` if ANY row carries a UEI,
else `org-usasp-rid-<recipient_id lowercased>`. NO Nonprofit label from
this source — business categories are null on every real row; nonprofit-ness
arrives only via reviewed cross-source 990 resolution.

The dedupe positive case feeds the same REAL parsed rows twice at call level
(test composition); the disagreement case is permitted mutation (c) — a
duplicate-award-id copy of a real row with an altered amount.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from canonical_type import canonical_type  # noqa: E402
from ingest_usaspending import (  # noqa: E402
    build_agency_org_nodes,
    build_award_edges,
    build_award_record_node,
    build_moneyflow_node,
    build_recipient_org_nodes,
    dedupe_awards,
    parse_awards_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usaspending"
GRANTS_P1 = FIXTURES / "spending-by-award-grants-p1.json"
GRANTS_P2 = FIXTURES / "spending-by-award-grants-p2.json"

# Real cross-page recipient: COMMUNITY ACTION MARIN — p1 row 0 + p2 row 1.
CAM_UEI = "JZ9FLAVMPEB9"
CAM_RID = "cf3072ee-ffc8-260e-4fc3-57dc5b893427-C"


def all_grant_awards() -> list[dict]:
    return parse_awards_file(GRANTS_P1) + parse_awards_file(GRANTS_P2)


def cam_awards() -> list[dict]:
    """The two REAL Community Action Marin rows (one per page)."""
    awards = [a for a in all_grant_awards() if a["recipient_id"] == CAM_RID]
    assert len(awards) == 2  # fixture ground truth
    return awards


# ---------------------------------------------------------------------------
# Recipient orgs — envelope + two-pass identity (Decisions 3–4)
# ---------------------------------------------------------------------------


def test_recipient_org_node_envelope():
    nodes, by_award = build_recipient_org_nodes(parse_awards_file(GRANTS_P1)[:1])
    assert nodes == [
        {
            "id": f"org-usasp-uei-{CAM_UEI}",
            "node_type": "Organization",
            "labels": ["Organization"],  # NO Nonprofit label from this source
            "display_label": "Community Action Marin",
            "properties": {
                "name": "Community Action Marin",
                "name_raw": "COMMUNITY ACTION MARIN",
                "uei": CAM_UEI,
                "recipient_id": CAM_RID,
                "source": "usaspending",
            },
        }
    ]
    assert by_award == {"ASST_NON_09CH011669_075": f"org-usasp-uei-{CAM_UEI}"}


def test_cross_page_recipient_collapse_yields_one_node():
    # 20 real rows across both pages → 9 distinct recipients (Buck Institute
    # spans 8 awards on BOTH pages; CAM and Marin Community Clinic repeat
    # across pages too).
    awards = all_grant_awards()
    nodes, by_award = build_recipient_org_nodes(awards)
    assert len(nodes) == 9
    assert len(by_award) == 20
    cam_org_ids = {by_award[a["award_id"]] for a in cam_awards()}
    assert cam_org_ids == {f"org-usasp-uei-{CAM_UEI}"}


def test_uei_on_one_row_only_promotes_the_whole_group():
    # Permitted mutation (a): strip the UEI from ONE of CAM's two REAL rows —
    # pass 2 must still assign the uei-based id to BOTH awards.
    first, second = (copy.deepcopy(a) for a in cam_awards())
    first["uei"] = None
    nodes, by_award = build_recipient_org_nodes([first, second])
    assert len(nodes) == 1
    assert set(by_award.values()) == {f"org-usasp-uei-{CAM_UEI}"}


def test_rid_fallback_when_no_row_in_group_has_a_uei():
    # Permitted mutation (a) on every row of the group → recipient_id
    # fallback, lowercased verbatim (never builtin hash()).
    first, second = (copy.deepcopy(a) for a in cam_awards())
    first["uei"] = None
    second["uei"] = None
    nodes, by_award = build_recipient_org_nodes([first, second])
    assert len(nodes) == 1
    assert nodes[0]["id"] == f"org-usasp-rid-{CAM_RID.lower()}"
    assert "uei" not in nodes[0]["properties"]
    assert nodes[0]["properties"]["recipient_id"] == CAM_RID


# ---------------------------------------------------------------------------
# Agency orgs — slug ids, in-batch dedupe (Decision 3)
# ---------------------------------------------------------------------------


def test_agency_org_nodes_dedupe_to_distinct_slugs():
    awards = all_grant_awards()
    nodes, by_award = build_agency_org_nodes(awards)
    # 4 distinct awarding agencies across the 20 real rows.
    assert sorted(n["id"] for n in nodes) == [
        "org-usasp-agency-agency-for-international-development",
        "org-usasp-agency-department-of-health-and-human-services",
        "org-usasp-agency-department-of-the-treasury",
        "org-usasp-agency-department-of-transportation",
    ]
    assert len(by_award) == 20
    hhs = next(n for n in nodes if n["id"].endswith("health-and-human-services"))
    assert hhs == {
        "id": "org-usasp-agency-department-of-health-and-human-services",
        "node_type": "Organization",
        "labels": ["Organization"],
        "display_label": "Department of Health and Human Services",
        "properties": {
            "name": "Department of Health and Human Services",
            "agency_slug": "department-of-health-and-human-services",
            "source": "usaspending",
        },
    }


# ---------------------------------------------------------------------------
# MoneyFlow + Record — predeclared envelopes incl. coverage honesty
# ---------------------------------------------------------------------------


def test_moneyflow_node_envelope():
    award = parse_awards_file(GRANTS_P1)[0]
    assert build_moneyflow_node(award) == {
        "id": "moneyflow-usasp-asst_non_09ch011669_075",
        "node_type": "MoneyFlow",
        "labels": ["MoneyFlow"],
        "display_label": "federal_award $31949723.20",
        "properties": {
            "amount": 31949723.2,
            "flow_type": "federal_award",
            "award_category": "PROJECT GRANT (B)",
            "award_id": "ASST_NON_09CH011669_075",
            "start_date": "2020-07-01",
            "end_date": "2025-08-31",
            "assistance_listing": "93.600",
            "awarding_agency": "Department of Health and Human Services",
            "awarding_sub_agency": "Administration for Children and Families",
            "funding_agency": "Department of Health and Human Services",
            "funding_sub_agency": "Administration for Children and Families",
            # Award-lifetime total obligation — NEVER a confirmed annual or
            # local-dollar claim (coverage honesty, decision doc §3).
            "coverage_scope": "usaspending_prime_award_total_obligation",
            "source": "usaspending",
        },
    }


def test_moneyflow_null_optionals_are_omitted():
    # EAH INC (p2 row 0) has a REAL null End Date — absent keys are omitted,
    # never null-filled.
    award = parse_awards_file(GRANTS_P2)[0]
    props = build_moneyflow_node(award)["properties"]
    assert "end_date" not in props
    assert props["start_date"] == "2023-10-04"


def test_record_node_envelope():
    award = parse_awards_file(GRANTS_P1)[0]
    assert build_award_record_node(award) == {
        "id": "record-usasp-asst_non_09ch011669_075",
        "node_type": "Record",
        "labels": ["Record"],
        "display_label": "USASpending award ASST_NON_09CH011669_075",
        "properties": {
            "award_id": "ASST_NON_09CH011669_075",
            # Verbatim-case generated_internal_id — the URL is case-sensitive.
            "source_url": (
                "https://www.usaspending.gov/award/ASST_NON_09CH011669_075"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Edges — CF MoneyFlow direction precedent (Decision 5)
# ---------------------------------------------------------------------------


def test_award_edges_directions_and_shape():
    award = parse_awards_file(GRANTS_P1)[0]
    agency_id = "org-usasp-agency-department-of-health-and-human-services"
    recipient_id = f"org-usasp-uei-{CAM_UEI}"
    assert build_award_edges(award, recipient_id, agency_id) == [
        {
            "source_id": agency_id,
            "target_id": "moneyflow-usasp-asst_non_09ch011669_075",
            "relationship_type": "FROM_SOURCE",
            "properties": {},
        },
        {
            "source_id": "moneyflow-usasp-asst_non_09ch011669_075",
            "target_id": recipient_id,
            "relationship_type": "TO_TARGET",
            "properties": {},
        },
        {
            "source_id": "moneyflow-usasp-asst_non_09ch011669_075",
            "target_id": "record-usasp-asst_non_09ch011669_075",
            "relationship_type": "EVIDENCED_BY",
            "properties": {},
        },
    ]


# ---------------------------------------------------------------------------
# In-batch award dedupe — agreement collapses, disagreement fails loud
# ---------------------------------------------------------------------------


def test_duplicate_award_rows_in_agreement_collapse():
    # Call-level repetition of the same REAL parsed rows (test composition,
    # not a fixture mutation) — real pagination never repeats an award id.
    awards = all_grant_awards()
    deduped = dedupe_awards(awards + awards)
    assert len(deduped) == 20
    assert deduped == dedupe_awards(awards)


def test_duplicate_award_id_with_different_amount_fails_loud():
    # Permitted mutation (c): a duplicate-award-id copy of a REAL row with
    # an altered amount — silent overwrite is never acceptable.
    awards = parse_awards_file(GRANTS_P1)
    altered = copy.deepcopy(awards[0])
    altered["amount"] = awards[0]["amount"] + 1.0
    with pytest.raises(ValueError, match="ASST_NON_09CH011669_075"):
        dedupe_awards(awards + [altered])


# ---------------------------------------------------------------------------
# Registry conformance — every emitted id resolves
# ---------------------------------------------------------------------------


def test_every_emitted_id_resolves_via_canonical_type():
    awards = all_grant_awards()
    recipient_nodes, _ = build_recipient_org_nodes(awards)
    agency_nodes, _ = build_agency_org_nodes(awards)
    nodes = recipient_nodes + agency_nodes
    for award in awards:
        nodes.append(build_moneyflow_node(award))
        nodes.append(build_award_record_node(award))
    for node in nodes:
        assert canonical_type(node["labels"], node["id"]) == node["node_type"], (
            node["id"]
        )
