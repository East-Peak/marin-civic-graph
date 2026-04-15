"""Tests for extract_decisions.py — vote/decision parsing from meeting minutes PDFs.

Run: pytest tests/test_extract_decisions.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from extract_decisions import (
    build_decision_node,
    extract_ordinance_numbers,
    extract_resolution_numbers,
    parse_novato_votes,
)


SAMPLE_MINUTES = """
COUNCIL ACTION: Upon motion by Eklund and seconded
by O'Connor, the City Council voted 5-0 via roll call to
approve the Final Agenda with Council and City Manager Reports
moved to the end of the agenda.
AYES: EKLUND, KARKAL, O'CONNOR, JACOBS, FARAC
NOES: NONE

Motion carried.

G. CONSENT CALENDAR
COUNCIL ACTION: Upon motion by Eklund and seconded
by O'Connor, the City Council voted 5-0 via roll call to
approve the Consent Calendar, with Item G.8 removed for
separate discussion.
AYES: EKLUND, KARKAL, O'CONNOR, JACOBS, FARAC
NOES: NONE

Motion carried.

I.1 Tenant Protections Ordinance
COUNCIL ACTION: Upon motion by O'Connor and seconded
by Karkal, the City Council voted 3-0-2 via roll call to
introduce the red lined ordinance amending provisions of
the Novato Municipal Code relating to tenant protections.
AYES: KARKAL, O'CONNOR, JACOBS
NOES: NONE
RECUSED: EKLUND, FARAC

Motion carried.

J.1 Council Compensation
COUNCIL MOTION: Upon motion by Eklund there was no
second and the motion failed.

COUNCIL ACTION: Upon motion by O'Connor and seconded
by Jacobs, the City Council voted 4-1 via roll call to
introduce Ordinance No. 1733 amending provisions related
to City Council compensation.
AYES: KARKAL, O'CONNOR, JACOBS, FARAC
NOES: EKLUND

Motion carried.

Resolution No. 2026-021 was adopted.
"""


class TestParseNovatoVotes:
    def test_finds_all_votes(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        assert len(votes) >= 4

    def test_vote_has_required_fields(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        v = votes[0]
        assert "mover" in v
        assert "seconder" in v
        assert "tally" in v
        assert "ayes" in v
        assert "noes" in v
        assert "outcome" in v

    def test_unanimous_vote(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        v = votes[0]  # 5-0 agenda approval
        assert v["tally"] == "5-0"
        assert len(v["ayes"]) == 5
        assert v["noes"] == []
        assert v["outcome"] == "carried"

    def test_split_vote(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        split = [v for v in votes if v["tally"] == "4-1"]
        assert len(split) == 1
        assert "EKLUND" in split[0]["noes"]

    def test_recusal(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        recusal = [v for v in votes if v.get("recused")]
        assert len(recusal) >= 1
        assert "EKLUND" in recusal[0]["recused"]
        assert "FARAC" in recusal[0]["recused"]

    def test_motion_text(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        v = votes[0]
        assert "approve the Final Agenda" in v["motion_text"]

    def test_failed_motion(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        failed = [v for v in votes if v["outcome"] == "failed"]
        assert len(failed) >= 1

    def test_mover_captured(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        assert votes[0]["mover"] == "EKLUND"

    def test_seconder_captured(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        assert votes[0]["seconder"] == "O'CONNOR"

    def test_failed_motion_has_mover(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        failed = [v for v in votes if v["outcome"] == "failed"]
        assert failed[0]["mover"] == "EKLUND"

    def test_failed_motion_no_seconder(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        failed = [v for v in votes if v["outcome"] == "failed"]
        assert failed[0].get("seconder") is None

    def test_abstention_tally(self):
        """3-0-2 tally (ayes-noes-abstain/recused) is parsed correctly."""
        votes = parse_novato_votes(SAMPLE_MINUTES)
        three_oh_two = [v for v in votes if v["tally"] == "3-0-2"]
        assert len(three_oh_two) == 1

    def test_ayes_are_uppercase_list(self):
        votes = parse_novato_votes(SAMPLE_MINUTES)
        for v in votes:
            if v["ayes"]:
                for name in v["ayes"]:
                    assert name == name.upper()


class TestExtractResolutionNumbers:
    def test_finds_resolution(self):
        nums = extract_resolution_numbers(SAMPLE_MINUTES)
        assert "2026-021" in nums

    def test_returns_list(self):
        nums = extract_resolution_numbers(SAMPLE_MINUTES)
        assert isinstance(nums, list)

    def test_empty_text(self):
        nums = extract_resolution_numbers("")
        assert nums == []

    def test_multiple_resolutions(self):
        text = "Resolution No. 2026-001 and Resolution No. 2026-002 were adopted."
        nums = extract_resolution_numbers(text)
        assert "2026-001" in nums
        assert "2026-002" in nums


class TestExtractOrdinanceNumbers:
    def test_finds_ordinance(self):
        nums = extract_ordinance_numbers(SAMPLE_MINUTES)
        assert "1733" in nums

    def test_returns_list(self):
        nums = extract_ordinance_numbers(SAMPLE_MINUTES)
        assert isinstance(nums, list)

    def test_empty_text(self):
        nums = extract_ordinance_numbers("")
        assert nums == []

    def test_ordinance_no_format(self):
        text = "Ordinance No. 1731 was introduced."
        nums = extract_ordinance_numbers(text)
        assert "1731" in nums

    def test_ordinance_bare_format(self):
        text = "introduce Ordinance 1730 amending"
        nums = extract_ordinance_numbers(text)
        assert "1730" in nums


class TestBuildDecisionNode:
    def test_node_structure(self):
        vote = {
            "mover": "EKLUND",
            "seconder": "O'CONNOR",
            "tally": "5-0",
            "ayes": ["EKLUND", "KARKAL", "O'CONNOR", "JACOBS", "FARAC"],
            "noes": [],
            "recused": [],
            "motion_text": "approve the Final Agenda",
            "outcome": "carried",
        }
        node = build_decision_node(vote, "meeting-2026-01-14-novato-city-council", "novato-city-council", 0)
        assert node["id"].startswith("decision-")
        assert "2026-01-14" in node["id"]
        assert node["node_type"] == "Decision"
        assert "properties" in node
        props = node["properties"]
        assert props["tally"] == "5-0"
        assert props["outcome"] == "carried"
        assert props["mover"] == "EKLUND"
        assert "meeting_id" in props

    def test_node_id_includes_vote_index(self):
        vote = {
            "mover": "EKLUND",
            "seconder": "O'CONNOR",
            "tally": "5-0",
            "ayes": [],
            "noes": [],
            "recused": [],
            "motion_text": "approve something",
            "outcome": "carried",
        }
        node = build_decision_node(vote, "meeting-2026-01-14-novato-city-council", "novato-city-council", 3)
        assert node["id"].endswith("-vote-3")
