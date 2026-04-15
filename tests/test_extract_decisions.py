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
    parse_bos_votes,
    parse_cortemadera_votes,
    parse_novato_votes,
    parse_sausalito_votes,
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

    def test_decision_type_roll_call(self):
        """Carried votes should have decision_type 'roll_call_vote'."""
        vote = {
            "mover": "EKLUND", "seconder": "KARKAL", "tally": "5-0",
            "ayes": [], "noes": [], "recused": [],
            "motion_text": "approve something", "outcome": "carried",
        }
        node = build_decision_node(vote, "meeting-2026-01-14-novato-city-council", "novato-city-council", 0)
        assert node["properties"]["decision_type"] == "roll_call_vote"

    def test_decision_type_failed_motion(self):
        """Failed motions should have decision_type 'failed_motion'."""
        vote = {
            "mover": "EKLUND", "seconder": None, "tally": None,
            "ayes": [], "noes": [], "recused": [],
            "motion_text": "motion failed — no second", "outcome": "failed",
        }
        node = build_decision_node(vote, "meeting-2026-01-14-novato-city-council", "novato-city-council", 0)
        assert node["properties"]["decision_type"] == "failed_motion"


# ---------------------------------------------------------------------------
# Bug regression tests — Unicode, regex variants, new fields
# ---------------------------------------------------------------------------

# U+2019 RIGHT SINGLE QUOTATION MARK versions of the names
_UNICODE_MINUTES = (
    "COUNCIL ACTION: Upon motion by Eklund and seconded\n"
    "by O\u2019Connor, the City Council voted 5-0 via roll call to\n"
    "approve the Final Agenda.\n"
    "AYES: EKLUND, KARKAL, O\u2019CONNOR, JACOBS, FARAC\n"
    "NOES: NONE\n\n"
    "Motion carried.\n"
)

_ON_MAIN_MOTION_MINUTES = (
    "COUNCIL ACTION ON MAIN MOTION: Upon motion by Eklund and seconded\n"
    "by Jacobs, the City Council voted 4-1 via roll call to\n"
    "approve the amended budget.\n"
    "AYES: EKLUND, KARKAL, JACOBS, FARAC\n"
    "NOES: OCONNOR\n\n"
    "Motion carried.\n"
)

_MOTION_MADE_BY_MINUTES = (
    "COUNCIL ACTION: Motion made by Karkal and seconded\n"
    "by Jacobs, the City Council voted 3-2 via roll call to\n"
    "deny the appeal.\n"
    "AYES: KARKAL, JACOBS, FARAC\n"
    "NOES: EKLUND, OCONNOR\n\n"
    "Motion carried.\n"
)

_ABSENT_FIELD_MINUTES = (
    "COUNCIL ACTION: Upon motion by Eklund and seconded\n"
    "by Karkal, the City Council voted 4-0 via roll call to\n"
    "approve the consent calendar.\n"
    "AYES: EKLUND, KARKAL, OCONNOR, FARAC\n"
    "NOES: NONE\n"
    "ABSENT: JACOBS\n\n"
    "Motion carried.\n"
)

_MISSING_TO_MINUTES = (
    "COUNCIL ACTION: Upon motion by Eklund and seconded\n"
    "by Karkal, the City Council voted 4-1 via roll call approve\n"
    "the rezoning request.\n"
    "AYES: EKLUND, KARKAL, OCONNOR, FARAC\n"
    "NOES: JACOBS\n\n"
    "Motion carried.\n"
)

_NO_COMMA_AFTER_SECONDER_MINUTES = (
    "COUNCIL ACTION: Upon motion by Eklund and seconded\n"
    "by Councilmember Karkal the City Council voted 5-0 via roll call to\n"
    "approve the minutes.\n"
    "AYES: EKLUND, KARKAL, OCONNOR, JACOBS, FARAC\n"
    "NOES: NONE\n\n"
    "Motion carried.\n"
)

_AND_NEWLINE_SECONDED_MINUTES = (
    "COUNCIL ACTION: Upon motion by Eklund and\n"
    "seconded by Karkal, the City Council voted 5-0 via roll call to\n"
    "approve the consent calendar.\n"
    "AYES: EKLUND, KARKAL, OCONNOR, JACOBS, FARAC\n"
    "NOES: NONE\n\n"
    "Motion carried.\n"
)


class TestUnicodeApostrophe:
    """Bug 1 — U+2019 RIGHT SINGLE QUOTATION MARK in Novato PDFs."""

    def test_unicode_apostrophe_seconder_matched(self):
        """O\u2019Connor with Unicode apostrophe must be parsed as seconder."""
        votes = parse_novato_votes(_UNICODE_MINUTES)
        assert len(votes) == 1
        assert votes[0]["seconder"] == "O'CONNOR"

    def test_unicode_apostrophe_in_ayes(self):
        """O\u2019CONNOR in AYES list must be normalised to O'CONNOR."""
        votes = parse_novato_votes(_UNICODE_MINUTES)
        assert "O'CONNOR" in votes[0]["ayes"]

    def test_unicode_left_quote_normalised(self):
        """U+2018 LEFT SINGLE QUOTATION MARK is also normalised."""
        text = _UNICODE_MINUTES.replace("\u2019", "\u2018")
        votes = parse_novato_votes(text)
        assert len(votes) == 1


class TestCouncilActionOnMainMotion:
    """Bug 5 — COUNCIL ACTION ON MAIN MOTION: prefix variant."""

    def test_on_main_motion_prefix_parsed(self):
        votes = parse_novato_votes(_ON_MAIN_MOTION_MINUTES)
        assert len(votes) == 1

    def test_on_main_motion_mover(self):
        votes = parse_novato_votes(_ON_MAIN_MOTION_MINUTES)
        assert votes[0]["mover"] == "EKLUND"

    def test_on_main_motion_tally(self):
        votes = parse_novato_votes(_ON_MAIN_MOTION_MINUTES)
        assert votes[0]["tally"] == "4-1"


class TestMotionMadeBy:
    """Bug 6 — 'Motion made by' variant instead of 'Upon motion by'."""

    def test_motion_made_by_parsed(self):
        votes = parse_novato_votes(_MOTION_MADE_BY_MINUTES)
        assert len(votes) == 1

    def test_motion_made_by_mover(self):
        votes = parse_novato_votes(_MOTION_MADE_BY_MINUTES)
        assert votes[0]["mover"] == "KARKAL"

    def test_motion_made_by_tally(self):
        votes = parse_novato_votes(_MOTION_MADE_BY_MINUTES)
        assert votes[0]["tally"] == "3-2"


class TestAbsentField:
    """Bug 9 — ABSENT field should be captured."""

    def test_absent_field_present_in_vote(self):
        votes = parse_novato_votes(_ABSENT_FIELD_MINUTES)
        assert len(votes) == 1
        assert "absent" in votes[0]

    def test_absent_names_parsed(self):
        votes = parse_novato_votes(_ABSENT_FIELD_MINUTES)
        assert "JACOBS" in votes[0]["absent"]

    def test_absent_field_empty_when_none(self):
        """When there is no ABSENT line, absent should be an empty list."""
        votes = parse_novato_votes(_UNICODE_MINUTES)
        assert votes[0].get("absent", []) == []


class TestMissingToAfterRollCall:
    """Bug 4 — 'via roll call approve' (no 'to') should still parse."""

    def test_missing_to_parsed(self):
        votes = parse_novato_votes(_MISSING_TO_MINUTES)
        assert len(votes) == 1

    def test_missing_to_motion_text(self):
        votes = parse_novato_votes(_MISSING_TO_MINUTES)
        assert "rezoning" in votes[0]["motion_text"]


class TestNoCommaAfterSeconder:
    """Bug 7 — no comma after seconder name."""

    def test_no_comma_after_seconder_parsed(self):
        votes = parse_novato_votes(_NO_COMMA_AFTER_SECONDER_MINUTES)
        assert len(votes) == 1

    def test_no_comma_seconder_captured(self):
        votes = parse_novato_votes(_NO_COMMA_AFTER_SECONDER_MINUTES)
        assert votes[0]["seconder"] == "KARKAL"


class TestAndNewlineSeconded:
    """Bug 3 — line break between 'and' and 'seconded'."""

    def test_and_newline_seconded_parsed(self):
        votes = parse_novato_votes(_AND_NEWLINE_SECONDED_MINUTES)
        assert len(votes) == 1

    def test_and_newline_seconder_captured(self):
        votes = parse_novato_votes(_AND_NEWLINE_SECONDED_MINUTES)
        assert votes[0]["seconder"] == "KARKAL"


class TestVoteValueNoe:
    """Bug 8 — CAST_VOTE edges use 'no' not 'noe'."""

    def test_noe_typo_fixed_in_write_decisions(self):
        """write_decisions must use vote='no' for NOES, not vote='noe'."""
        import extract_decisions as ed
        # Inspect the source: the literal string 'noe' must not appear as a
        # vote value assignment in write_decisions.
        import inspect
        source = inspect.getsource(ed.write_decisions)
        # The bug was: vote_edges.append({..., "vote": "noe"})
        # The fix is: "vote": "no"
        assert '"noe"' not in source, (
            'write_decisions still uses vote="noe"; should be vote="no"'
        )


# ---------------------------------------------------------------------------
# Corte Madera CivicPlus format tests
# ---------------------------------------------------------------------------

CORTE_MADERA_SAMPLE = """
MOTION: It was M/S/C (Ravasio/Beckman) to approve Consent Calendar items 4.B. through 4.D.
ROLL CALL VOTE: 5-0 in favor of the motion.

MOTION: It was M/S/C (Casissa/Andrews) to accept the 2026 Staff Work Plan with the changes
mentioned during the meeting.
ROLL CALL VOTE: 4-1 (Ravasio opposed) in favor of the motion.

MOTION: It was M/S/C (Beckman/Casissa) to re-introduce the proposed ordinance at a subsequent
council meeting with the inclusion of a ban on nicotine pouches.
ROLL CALL VOTE: 5-0 in favor of the motion.
"""


class TestParseCorteMaderaVotes:
    def test_finds_all_votes(self):
        votes = parse_cortemadera_votes(CORTE_MADERA_SAMPLE)
        assert len(votes) == 3

    def test_mover_seconder(self):
        votes = parse_cortemadera_votes(CORTE_MADERA_SAMPLE)
        assert votes[0]["mover"] == "Ravasio"
        assert votes[0]["seconder"] == "Beckman"

    def test_unanimous_tally(self):
        votes = parse_cortemadera_votes(CORTE_MADERA_SAMPLE)
        assert votes[0]["tally"] == "5-0"

    def test_split_vote_with_dissenter(self):
        votes = parse_cortemadera_votes(CORTE_MADERA_SAMPLE)
        split = [v for v in votes if v["tally"] == "4-1"]
        assert len(split) == 1
        assert split[0]["noes"] == ["RAVASIO"]

    def test_motion_text(self):
        votes = parse_cortemadera_votes(CORTE_MADERA_SAMPLE)
        assert "Consent Calendar" in votes[0]["motion_text"]

    def test_outcome_always_carried(self):
        votes = parse_cortemadera_votes(CORTE_MADERA_SAMPLE)
        for v in votes:
            assert v["outcome"] == "carried"


# ---------------------------------------------------------------------------
# Sausalito narrative-prose format tests
# ---------------------------------------------------------------------------

SAUSALITO_SAMPLE = """
Councilmember Cox moved, seconded by Vice Mayor Blaustein, and unanimously carried, to
approve the agenda.

Councilmember Sobieski moved, seconded by Mayor Woodside, and unanimously carried,
to receive and file the Fiscal Year 2025-2026 Mid-Year Budget report.

Councilmember Hoffman moved, seconded by Councilmember Cox, and unanimously
carried, to adopt Resolution No. 02-2026, affirming the violations cited in the
Notice of Violation issued to 100 Ebbtide Avenue.

Vice Mayor Blaustein moved, seconded by Councilmember Sobieski, and carried 4-1
(Hoffman dissenting), to approve the contract amendment.
"""


class TestParseSausalitoVotes:
    def test_finds_all_votes(self):
        votes = parse_sausalito_votes(SAUSALITO_SAMPLE)
        assert len(votes) >= 4

    def test_mover_seconder(self):
        votes = parse_sausalito_votes(SAUSALITO_SAMPLE)
        assert votes[0]["mover"] == "Cox"
        assert votes[0]["seconder"] == "Blaustein"

    def test_unanimous(self):
        votes = parse_sausalito_votes(SAUSALITO_SAMPLE)
        assert votes[0]["outcome"] == "carried"
        assert votes[0]["tally"] is None  # unanimous, no numeric tally

    def test_split_vote(self):
        votes = parse_sausalito_votes(SAUSALITO_SAMPLE)
        split = [v for v in votes if v.get("tally") == "4-1"]
        assert len(split) == 1
        assert "HOFFMAN" in split[0]["noes"]

    def test_motion_text(self):
        votes = parse_sausalito_votes(SAUSALITO_SAMPLE)
        assert "approve the agenda" in votes[0]["motion_text"]

    def test_resolution_number(self):
        votes = parse_sausalito_votes(SAUSALITO_SAMPLE)
        res_vote = [v for v in votes if "02-2026" in v.get("motion_text", "")]
        assert len(res_vote) >= 1


# ---------------------------------------------------------------------------
# Marin County BOS format tests
# ---------------------------------------------------------------------------

BOS_REGULAR_SAMPLE = """
M/s Supervisor Moulton-Peters - Supervisor Colbert to approve Consent Calendar A (Items CA-1 through CA-10). AYES: ALL

M/s Supervisor Rodoni - Supervisor Lucan to approve Consent Calendar B (Items CB-1 through CB-7). AYES: ALL

M/s Supervisor Colbert - Supervisor Lucan to approve budget instructions for FY 2026-28. AYES: ALL
"""

BOS_SPECIAL_SAMPLE = """
Motion to approve the First extension of a Local Emergency Proclamation moved
by Supervisor Sackett and seconded by Supervisor Colbert.

Votes:

AYES: ALL

NOES: NONE
Motion passed.
"""


class TestParseBosVotes:
    def test_regular_session_votes(self):
        votes = parse_bos_votes(BOS_REGULAR_SAMPLE)
        assert len(votes) == 3

    def test_regular_mover_seconder(self):
        votes = parse_bos_votes(BOS_REGULAR_SAMPLE)
        assert votes[0]["mover"] == "Moulton-Peters"
        assert votes[0]["seconder"] == "Colbert"

    def test_regular_motion_text(self):
        votes = parse_bos_votes(BOS_REGULAR_SAMPLE)
        assert "Consent Calendar A" in votes[0]["motion_text"]

    def test_ayes_all(self):
        votes = parse_bos_votes(BOS_REGULAR_SAMPLE)
        assert votes[0]["ayes"] == ["ALL"]

    def test_special_session_votes(self):
        votes = parse_bos_votes(BOS_SPECIAL_SAMPLE)
        assert len(votes) >= 1

    def test_special_mover_seconder(self):
        votes = parse_bos_votes(BOS_SPECIAL_SAMPLE)
        assert votes[0]["mover"] == "Sackett"
        assert votes[0]["seconder"] == "Colbert"

    def test_hyphenated_name(self):
        votes = parse_bos_votes(BOS_REGULAR_SAMPLE)
        assert votes[0]["mover"] == "Moulton-Peters"
