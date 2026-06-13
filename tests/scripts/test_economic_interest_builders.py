"""Tests for scripts/economic_interest_builders.py — pure EconomicInterest
builders (M4, COI spec §4.2).

An EconomicInterest reifies a single Form 700 disclosure line as a node
(`economicinterest-` prefix; interest_type / counterparty_name_raw / amount_band
XOR amount / position? / schedule / filing_id / confidence / evidence_record_ids[])
connected by DISCLOSED_AS (Filing → EconomicInterest), INTEREST_IN
(EconomicInterest → Organization, gated elsewhere), and the universal
EVIDENCED_BY (EconomicInterest → Record). Builders are pure data shapers in the
graph ontology envelope, modeled on membership_builders — no Neo4j connection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from economic_interest_builders import (  # noqa: E402
    INTEREST_TYPES,
    build_disclosed_as_edge,
    build_economic_interest_node,
    build_evidenced_by_edge,
    build_interest_in_edge,
)

FILING_ID = (
    "filing-form700-cmar-2025-03-22-werby-todd-annual-"
    "retirement-board-member-retirement-board"
)

SAMPLE = dict(
    filing_id=FILING_ID,
    schedule="A-1",
    line_ordinal=9,
    interest_type="investment",
    counterparty_name_raw="Carillon Associates",
    filer_normalized_name="Todd Werby",
    filed_at="2026-03-22",
    evidence_record_ids=["record-form700-interior-216262973"],
    amount_band="Over $1,000,000",
)


class TestNodeShape:
    def test_node_envelope_and_id_determinism(self):
        node = build_economic_interest_node(**SAMPLE)
        # id = economicinterest-<filing-slug>-<schedule-slug>-<line-ordinal>;
        # filing-slug is the Filing id minus its filing-form700- prefix.
        assert node["id"] == (
            "economicinterest-cmar-2025-03-22-werby-todd-annual-"
            "retirement-board-member-retirement-board-a-1-9"
        )
        assert node["node_type"] == "EconomicInterest"
        assert node["labels"] == ["EconomicInterest"]
        assert build_economic_interest_node(**SAMPLE)["id"] == node["id"]  # stable

    def test_node_properties_banded(self):
        props = build_economic_interest_node(**SAMPLE)["properties"]
        assert props["interest_type"] == "investment"
        assert props["counterparty_name_raw"] == "Carillon Associates"
        assert props["schedule"] == "A-1"
        assert props["filing_id"] == FILING_ID
        assert props["amount_band"] == "Over $1,000,000"
        assert "amount" not in props
        assert "position" not in props
        assert props["confidence"] == 1.0
        assert props["evidence_record_ids"] == ["record-form700-interior-216262973"]

    def test_display_label(self):
        node = build_economic_interest_node(**SAMPLE)
        assert node["display_label"] == (
            "investment — Carillon Associates (Todd Werby, 2026-03-22)"
        )

    def test_exact_amount_node_carries_amount_not_band(self):
        node = build_economic_interest_node(
            **{**SAMPLE, "schedule": "D", "interest_type": "gift",
               "amount_band": None, "amount": "20.00", "line_ordinal": 1}
        )
        assert node["properties"]["amount"] == "20.00"
        assert "amount_band" not in node["properties"]

    def test_position_recorded_when_present(self):
        node = build_economic_interest_node(
            **{**SAMPLE, "schedule": "A-2", "line_ordinal": 15,
               "counterparty_name_raw": "Grosvenor Properties Ltd.",
               "position": "President & CEO"}
        )
        assert node["properties"]["position"] == "President & CEO"

    def test_schedule_slug_lowercases_hyphenated(self):
        node = build_economic_interest_node(**{**SAMPLE, "schedule": "A-2"})
        assert node["id"].endswith("-a-2-9")


class TestVocabularyEnforcement:
    def test_all_seven_interest_types_accepted(self):
        # The full §4.2 vocabulary is enforced at the builder, including
        # `business position` (which M4 parsers never emit — constructed here
        # directly so the builder's vocabulary stays complete for P3/future).
        assert INTEREST_TYPES == frozenset({
            "income source", "investment", "real property",
            "business position", "gift", "loan", "travel",
        })
        for itype in INTEREST_TYPES:
            kwargs = {**SAMPLE, "interest_type": itype}
            # business position carries no money band in the basket; give it one
            # anyway (band-XOR-amount is orthogonal to the type vocabulary).
            node = build_economic_interest_node(**kwargs)
            assert node["properties"]["interest_type"] == itype

    def test_unknown_interest_type_raises(self):
        with pytest.raises(ValueError, match="interest_type"):
            build_economic_interest_node(**{**SAMPLE, "interest_type": "bribe"})


class TestBandXorAmount:
    def test_both_band_and_amount_raises(self):
        with pytest.raises(ValueError, match="amount_band"):
            build_economic_interest_node(
                **{**SAMPLE, "amount": "5000.00"}  # SAMPLE already has a band
            )

    def test_neither_band_nor_amount_raises_for_ordinary_row(self):
        with pytest.raises(ValueError, match="amount_band"):
            build_economic_interest_node(**{**SAMPLE, "amount_band": None})

    def test_a2_income_source_carries_neither(self):
        # The Predeclared 3 carve-out: A-2 part-3 income-source rows disclose
        # only a ≥$10,000 threshold, no verbatim band — neither field is set.
        node = build_economic_interest_node(
            **{**SAMPLE, "schedule": "A-2", "interest_type": "income source",
               "counterparty_name_raw": "United Cold Storage",
               "amount_band": None, "amount": None, "line_ordinal": 11}
        )
        assert "amount_band" not in node["properties"]
        assert "amount" not in node["properties"]

    def test_a2_income_source_with_a_band_raises(self):
        with pytest.raises(ValueError, match="A-2 income"):
            build_economic_interest_node(
                **{**SAMPLE, "schedule": "A-2", "interest_type": "income source",
                   "amount_band": "OVER $100,000", "line_ordinal": 11}
            )

    def test_band_xor_error_names_no_raw_field_value(self):
        # Ethics: fail-loud messages name keys/schedule/ordinal only, never a
        # counterparty name or band string (extends the keys-only rule).
        try:
            build_economic_interest_node(
                **{**SAMPLE, "counterparty_name_raw": "SECRET CO",
                   "amount_band": None, "amount": None}
            )
        except ValueError as exc:
            assert "SECRET CO" not in str(exc)
            assert "A-1" in str(exc) and "9" in str(exc)
        else:  # pragma: no cover - the call must raise
            raise AssertionError("expected ValueError")


class TestEdges:
    def test_disclosed_as_edge_filing_to_interest(self):
        edge = build_disclosed_as_edge("filing-x", "economicinterest-y")
        assert edge == {
            "source_id": "filing-x",
            "target_id": "economicinterest-y",
            "relationship_type": "DISCLOSED_AS",
            "properties": {},
        }

    def test_interest_in_edge_interest_to_org(self):
        edge = build_interest_in_edge("economicinterest-y", "org-z")
        assert edge["source_id"] == "economicinterest-y"
        assert edge["target_id"] == "org-z"
        assert edge["relationship_type"] == "INTEREST_IN"

    def test_evidenced_by_edge_interest_to_record(self):
        edge = build_evidenced_by_edge("economicinterest-y", "record-z")
        assert edge["source_id"] == "economicinterest-y"
        assert edge["target_id"] == "record-z"
        assert edge["relationship_type"] == "EVIDENCED_BY"
