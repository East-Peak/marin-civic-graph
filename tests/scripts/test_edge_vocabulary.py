"""Tests for scripts/edge_vocabulary.py — spec §3 → live AuraDB edge mapping.

Pure data tests; no Neo4j connection required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from edge_vocabulary import (  # noqa: E402
    LEGAL_EDGES_LIVE,
    MONEY_EDGES_LIVE,
    PHASE2_WHITELIST_LIVE,
    SPEC_TO_LIVE,
    UNIVERSAL_EDGES_LIVE,
    spec_to_live,
)


def test_spec_to_live_simple():
    # CAST_VOTE is unchanged.
    assert spec_to_live("CAST_VOTE") == ["CAST_VOTE"]


def test_spec_to_live_split_part_of():
    # PART_OF fans out to PART_OF_MEETING (AgendaItem side) + PART_OF_CASE (Proceeding side).
    live = spec_to_live("PART_OF")
    assert "PART_OF_MEETING" in live
    assert "PART_OF_CASE" in live


def test_spec_to_live_renamed_about_item():
    # ABOUT_ITEM → ABOUT_AGENDA_ITEM.
    assert "ABOUT_AGENDA_ITEM" in spec_to_live("ABOUT_ITEM")


def test_spec_to_live_renamed_disclosed_in():
    # DISCLOSED_IN → DISCLOSED_IN_FILING.
    assert spec_to_live("DISCLOSED_IN") == ["DISCLOSED_IN_FILING"]


def test_spec_to_live_renamed_amends():
    assert spec_to_live("AMENDS") == ["AMENDS_AGREEMENT"]


def test_spec_to_live_renamed_result_of():
    assert spec_to_live("RESULT_OF") == ["RESULT_OF_ELECTION"]


def test_spec_to_live_renamed_by_person():
    assert spec_to_live("BY_PERSON") == ["CANDIDATE_ACTOR"]


def test_spec_to_live_renamed_between():
    assert spec_to_live("BETWEEN") == ["COUNTERPARTY_ACTOR"]


def test_spec_to_live_filed_by_fans_out():
    # FILED_BY → FILED_BY (Person), FILED_BY_COMMITTEE, OFFICIAL_FILER (named filer).
    live = spec_to_live("FILED_BY")
    assert "FILED_BY" in live
    assert "FILED_BY_COMMITTEE" in live
    assert "OFFICIAL_FILER" in live


def test_spec_to_live_controlled_by_fans_out():
    # CONTROLLED_BY → CONTROLLED_BY (Committee→Person/Org), CONTROLLED_BY_COMMITTEE (Candidacy→Committee).
    live = spec_to_live("CONTROLLED_BY")
    assert "CONTROLLED_BY" in live
    assert "CONTROLLED_BY_COMMITTEE" in live


def test_spec_to_live_for_project_is_weak_collapse():
    # FOR_PROJECT has no strong live equivalent; it collapses to RELATES_TO_PROJECT.
    assert spec_to_live("FOR_PROJECT") == ["RELATES_TO_PROJECT"]


def test_spec_to_live_about_project_is_weak_collapse():
    # ABOUT_PROJECT also collapses to RELATES_TO_PROJECT.
    assert spec_to_live("ABOUT_PROJECT") == ["RELATES_TO_PROJECT"]


def test_spec_to_live_about_program_is_weak_collapse():
    assert spec_to_live("ABOUT_PROGRAM") == ["RELATES_TO_PROGRAM"]


def test_spec_to_live_under_agreement_is_weak_collapse():
    assert spec_to_live("UNDER_AGREEMENT") == ["RELATES_TO_AGREEMENT"]


def test_spec_to_live_heard_in_fans_out():
    # HEARD_IN (Case→Court) + HEARD_BY (Proceeding→Court/Judge).
    live = spec_to_live("HEARD_IN")
    assert "HEARD_IN" in live
    assert "HEARD_BY" in live


def test_spec_to_live_in_election_fans_out():
    # IN_ELECTION → FILED_FOR_ELECTION (Filing→Election) + RELATED_TO_ELECTION (Election→Election).
    live = spec_to_live("IN_ELECTION")
    assert "FILED_FOR_ELECTION" in live


def test_spec_to_live_member_edges_unchanged():
    # COI spec §4.1 (M2a): Membership's edges land live under their spec names.
    assert spec_to_live("MEMBER") == ["MEMBER"]
    assert spec_to_live("MEMBER_OF_ORG") == ["MEMBER_OF_ORG"]


def test_spec_to_live_constrains_empty_until_materialized():
    # CONSTRAINS has no live equivalent yet. Empty list is correct behavior.
    assert spec_to_live("CONSTRAINS") == []


def test_spec_to_live_unknown_returns_empty():
    assert spec_to_live("NONEXISTENT_EDGE") == []


def test_phase2_whitelist_is_live_names_only():
    # No spec §3 aliases should leak into the live whitelist.
    aliases = {"ABOUT_ITEM", "DISCLOSED_IN", "PART_OF", "RESULT_OF", "AMENDS",
               "BY_PERSON", "IN_ELECTION", "BETWEEN", "UNDER_AGREEMENT",
               "FOR_PROJECT", "ABOUT_PROJECT", "ABOUT_PROGRAM"}
    for alias in aliases:
        assert alias not in PHASE2_WHITELIST_LIVE, f"spec alias {alias} leaked into PHASE2_WHITELIST_LIVE"


def test_phase2_whitelist_excludes_universal_edges():
    # EVIDENCED_BY / IN_JURISDICTION / RELATES_TO_ISSUE and the weak RELATES_TO_* family
    # (minus the three load-bearing exceptions) stay excluded.
    for universal in UNIVERSAL_EDGES_LIVE:
        assert universal not in PHASE2_WHITELIST_LIVE


def test_phase2_whitelist_keeps_load_bearing_relates_to():
    # RELATES_TO_PROJECT, RELATES_TO_PROGRAM, RELATES_TO_AGREEMENT are the ONLY live
    # variants of spec FOR_PROJECT/ABOUT_PROJECT/ABOUT_PROGRAM/UNDER_AGREEMENT.
    # Without them, Project/Program/Agreement pages would have no neighborhood.
    assert "RELATES_TO_PROJECT" in PHASE2_WHITELIST_LIVE
    assert "RELATES_TO_PROGRAM" in PHASE2_WHITELIST_LIVE
    assert "RELATES_TO_AGREEMENT" in PHASE2_WHITELIST_LIVE


def test_phase2_whitelist_includes_core_governance():
    # Sanity: the six most-trafficked governance edges are all present.
    for edge in ("CAST_VOTE", "AT_MEETING", "DECIDED_BY", "ABOUT_AGENDA_ITEM",
                 "PART_OF_MEETING", "AT_INSTITUTION"):
        assert edge in PHASE2_WHITELIST_LIVE


def test_phase2_whitelist_includes_filing_edges():
    # Form 803-style filings need FILED_WITH / FILED_DURING_SEAT_SERVICE / FILED_FOR_SEAT
    # to reach the receiving agency, holder's tenure, and target seat.
    for edge in ("FILED_BY", "FILED_BY_COMMITTEE", "OFFICIAL_FILER",
                 "FILED_WITH", "FILED_DURING_SEAT_SERVICE", "FILED_FOR_SEAT",
                 "DISCLOSED_IN_FILING"):
        assert edge in PHASE2_WHITELIST_LIVE


def test_phase2_whitelist_includes_program_operator():
    # Program pages need OPERATED_BY to reach the operating institution.
    assert "OPERATED_BY" in PHASE2_WHITELIST_LIVE


def test_phase2_whitelist_includes_membership_edges():
    # M2a: a Membership must be discoverable from a Person/Organization
    # neighborhood, so both its edges are traversable (not universal-excluded).
    assert "MEMBER" in PHASE2_WHITELIST_LIVE
    assert "MEMBER_OF_ORG" in PHASE2_WHITELIST_LIVE
    assert "MEMBER" not in UNIVERSAL_EDGES_LIVE
    assert "MEMBER_OF_ORG" not in UNIVERSAL_EDGES_LIVE


def test_money_edges_live_non_empty():
    # Money-styled edges feed the edge classifier.
    assert "FROM_SOURCE" in MONEY_EDGES_LIVE
    assert "TO_TARGET" in MONEY_EDGES_LIVE
    assert "DISCLOSED_IN_FILING" in MONEY_EDGES_LIVE
    # UNDER_AGREEMENT collapses to RELATES_TO_AGREEMENT — should be a money edge.
    assert "RELATES_TO_AGREEMENT" in MONEY_EDGES_LIVE


def test_legal_edges_live_empty_until_constrains_materializes():
    # CONSTRAINS is not yet in the live graph.
    assert LEGAL_EDGES_LIVE == []


def test_universal_edges_live_includes_core():
    for edge in ("EVIDENCED_BY", "IN_JURISDICTION", "RELATES_TO_ISSUE"):
        assert edge in UNIVERSAL_EDGES_LIVE


def test_universal_edges_live_excludes_load_bearing_relates_to():
    # These three are content edges (weak collapses of spec §3 strong edges) and
    # must NOT appear in UNIVERSAL_EDGES_LIVE or they'd be filtered from Phase 2.
    for edge in ("RELATES_TO_PROJECT", "RELATES_TO_PROGRAM", "RELATES_TO_AGREEMENT"):
        assert edge not in UNIVERSAL_EDGES_LIVE


def test_spec_to_live_dict_exhaustive_for_phase2_whitelist():
    # Every spec §3 name the signature-subgraph builder previously listed
    # must have an entry in SPEC_TO_LIVE (value may be empty list if not materialized).
    phase2_spec_names = {
        "CAST_VOTE", "AT_MEETING", "ABOUT_ITEM", "DECIDED_BY", "PART_OF", "HELD_BY",
        "FOR_SEAT", "RESULT_OF", "AT_INSTITUTION", "FROM_SOURCE", "TO_TARGET",
        "DISCLOSED_IN", "UNDER_AGREEMENT", "AMENDS", "CONTROLLED_BY", "FILED_BY",
        "BY_PERSON", "IN_ELECTION", "FOR_ELECTION", "FOR_PROJECT", "ABOUT_PROJECT",
        "ABOUT_PROGRAM", "PARTY_TO", "CONSTRAINS", "BETWEEN", "HEARD_IN",
        # COI spec §4.1 (M2a) — Membership edges.
        "MEMBER", "MEMBER_OF_ORG",
    }
    for name in phase2_spec_names:
        assert name in SPEC_TO_LIVE, f"spec §3 edge {name} missing from SPEC_TO_LIVE"
