"""Votes Part A, increment b: vote blocks parsed from the minutes text into vote events.

Every fixture is fictional (members Alder, Birch, Cedar, Dogwood, Elm, Fir). Shapes follow the
real minutes: Novato `COUNCIL ACTION:` headers with AYES/NOES/ABSENT/RECUSED/ABSTAIN lines, and the
Board's `M/s Supervisor X - Supervisor Y to …` motions with `AYES: ALL` or `Vote:` + named blocks.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_blocks import parse_document, split_names  # noqa: E402
from votes_text import CanonicalText  # noqa: E402

NOVATO = "novato-city-council"
BOS = "marin-county-bos"


def _parse(body, lines, doc_sha="d" * 64, meeting="meeting-x-1"):
    ct = CanonicalText.from_lines(lines)
    return ct, parse_document(ct, body=body, meeting_id=meeting, doc_sha256=doc_sha)


def _names(ev, cat):
    return [n["name"] for n in ev["categories"][cat]]


def _excerpt(ct, loc):
    return ct.text[loc["start"]:loc["end"]]


# ---------------------------------------------------------------------------------------------
class TestSplitNames:
    @pytest.mark.parametrize("raw,names,flags", [
        ("ALDER, BIRCH, CEDAR", ["ALDER", "BIRCH", "CEDAR"], []),
        ("ALDER; BIRCH; CEDAR", ["ALDER", "BIRCH", "CEDAR"], []),
        ("ALDER, BIRCH and CEDAR", ["ALDER", "BIRCH", "CEDAR"], []),
        ("ALDER & BIRCH", ["ALDER", "BIRCH"], []),
        ("ALDER, BIRCH CEDAR, DOGWOOD", ["ALDER", "BIRCH", "CEDAR", "DOGWOOD"], ["delimiter_repaired"]),
        ("ALDER, BIRCH,", ["ALDER", "BIRCH"], []),
        ("ALDER , BIRCH", ["ALDER", "BIRCH"], []),
        ("O'ELM, FIR", ["O'ELM", "FIR"], []),
        ("Supervisor Alder, Supervisor Birch-Cedar", ["ALDER", "BIRCH-CEDAR"], []),
        ("Supervisor Alder; Supervisor Birch", ["ALDER", "BIRCH"], []),
        ("Councilmember Alder and Mayor Pro Tem Birch", ["ALDER", "BIRCH"], []),
        ("Superrvisor Alder", ["ALDER"], []),
        ("Supervisor Eric Alder", ["ALDER"], []),
        ("Alder", ["ALDER"], []),
        ("Mayor Pro Tem / Board Member Alder", ["ALDER"], []),
        ("Board Member Alder", ["ALDER"], []),
    ])
    def test_lists(self, raw, names, flags):
        got, got_flags = split_names(raw)
        assert [n["name"] for n in got] == names
        assert got_flags == flags

    def test_each_name_carries_its_offset_within_the_raw_value(self):
        raw = "Supervisor Alder, BIRCH"
        got, _ = split_names(raw)
        assert [raw[n["start"]:n["end"]] for n in got] == ["Alder", "BIRCH"]


# ---------------------------------------------------------------------------------------------
NOVATO_BASIC = [
    "D.   APPROVAL OF THE FINAL AGENDA",
    "",
    "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
    "     Mayor Pro Tem Birch, the City Council voted 4-1 via roll call to approve the Final",
    "     Agenda.",
    "",
    "     AYES:          ALDER, BIRCH, CEDAR, DOGWOOD",
    "     NOES:          ELM",
    "",
    "     Motion carried.",
    "",
    "E.   REPORTS",
]


class TestNovatoBasics:
    def test_named_event_with_every_field(self):
        ct, events = _parse(NOVATO, NOVATO_BASIC)
        [ev] = events
        assert ev["status"] == "named"
        assert ev["motion"]["kind"] == "main"
        assert ev["motion"]["mover"] == "ALDER" and ev["motion"]["seconder"] == "BIRCH"
        assert ev["motion"]["text"] == "approve the Final Agenda."
        assert ev["outcome"] == "carried"
        assert ev["tally"]["printed"] == "4-1"
        assert _names(ev, "aye") == ["ALDER", "BIRCH", "CEDAR", "DOGWOOD"]
        assert _names(ev, "no") == ["ELM"]
        assert ev["item"]["top"] == "D" and ev["item"]["title"].startswith("APPROVAL OF THE FINAL")

    def test_every_name_span_points_at_the_name_and_lies_in_its_category_span(self):
        ct, [ev] = _parse(NOVATO, NOVATO_BASIC)
        for cat, names in ev["categories"].items():
            if not names:
                continue
            cspan = ev["category_spans"][cat]
            assert _excerpt(ct, cspan).split(":")[0].strip() in ("AYES", "NOES")
            for n in names:
                assert _excerpt(ct, n["span"]) == n["raw"]
                assert cspan["start"] <= n["span"]["start"] < n["span"]["end"] <= cspan["end"]

    def test_locator_and_consumed_spans(self):
        ct, [ev] = _parse(NOVATO, NOVATO_BASIC)
        assert ev["block"]["line_start"] == 7 and ev["block"]["line_end"] == 10
        consumed = {_excerpt(ct, c).strip().split()[0] for c in ev["consumed"]}
        assert {"COUNCIL", "AYES:", "NOES:", "Motion"} <= consumed
        assert ev["event_id"] == "vev-x-1-dddddddd-L3"

    @pytest.mark.parametrize("value,sentinel", [("None.", "NONE"), ("NONE.", "NONE"), ("None", "NONE"),
                                                ("NONE", "NONE")])
    def test_none_sentinels_empty_the_category(self, value, sentinel):
        lines = NOVATO_BASIC[:6] + ["     AYES:   ALDER, BIRCH, CEDAR, DOGWOOD, ELM",
                                    f"     NOES:   {value}", "", "     Motion carried."]
        lines[3] = lines[3].replace("4-1", "5-0")
        _, [ev] = _parse(NOVATO, lines)
        assert ev["categories"]["no"] == [] and ev["status"] == "named"
        assert ev["sentinels"][0]["token"] == sentinel and ev["sentinels"][0]["category"] == "no"

    def test_absent_recused_abstain_and_three_part_tally(self):
        lines = ["G.   CONSENT", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 3-0-2 via roll call to approve.",
                 "     AYES:     ALDER, BIRCH, CEDAR", "     NOES:     None", "     RECUSED:  DOGWOOD",
                 "     ABSTAINED: ELM", "     Motion carried."]
        _, [ev] = _parse(NOVATO, lines)
        assert _names(ev, "recused") == ["DOGWOOD"] and _names(ev, "abstain") == ["ELM"]
        assert ev["status"] == "named"

    def test_three_part_tally_counts_absences_too(self):
        lines = ["G.   CONSENT", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 4-0-1 via roll call to approve.",
                 "     AYES:     ALDER, BIRCH, CEDAR, ELM", "     NOES:     None", "     ABSENT:   DOGWOOD",
                 "     The motion carried."]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "named" and _names(ev, "absent") == ["DOGWOOD"]
        assert ev["outcome"] == "carried"

    def test_a_blank_category_is_empty_and_the_tally_still_guards_it(self):
        lines = NOVATO_BASIC[:6] + ["     AYES:   ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES:",
                                    "     Motion carried."]
        lines[3] = lines[3].replace("4-1", "5-0")
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "named" and ev["categories"]["no"] == []
        assert ev["sentinels"][0]["token"] == "BLANK"
        lines[6] = "     AYES:"
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "held" and "tally_mismatch" in ev["hold_reasons"]

    def test_tally_mismatch_is_held(self):
        lines = list(NOVATO_BASIC)
        lines[3] = lines[3].replace("4-1", "5-0")
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "held" and "tally_mismatch" in ev["hold_reasons"]

    def test_unanimously_wording_and_recuse_label(self):
        lines = ["H.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted unanimously 4-0 via roll call to adopt.",
                 "     AYES: ALDER, BIRCH, CEDAR, ELM", "     NOES: None", "     RECUSE: DOGWOOD",
                 "     Motion carried."]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["tally"]["printed"] == "4-0" and _names(ev, "recused") == ["DOGWOOD"]
        assert ev["status"] == "named"

    def test_merged_names_are_repaired_and_flagged(self):
        lines = list(NOVATO_BASIC)
        lines[6] = "     AYES:          ALDER, BIRCH CEDAR, DOGWOOD"
        _, [ev] = _parse(NOVATO, lines)
        assert _names(ev, "aye") == ["ALDER", "BIRCH", "CEDAR", "DOGWOOD"]
        assert "delimiter_repaired" in ev["flags"]

    def test_failed_motion_with_votes(self):
        lines = ["I.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Elm and seconded by",
                 "     Councilmember Fir, the City Council voted 2-3 via roll call to deny.",
                 "     AYES: ELM, FIR", "     NOES: ALDER, BIRCH, CEDAR", "     Motion failed."]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["outcome"] == "failed" and ev["status"] == "named"

    def test_failed_for_lack_of_a_second(self):
        lines = ["I.   ITEM", "     COUNCIL ACTION: Councilmember Elm made a motion to deny the request.",
                 "     The motion failed for lack of a second.", "J.   NEXT"]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["motion"]["kind"] == "failed_no_second" and ev["motion"]["mover"] == "ELM"
        assert ev["outcome"] == "failed" and ev["status"] == "named"
        assert all(v == [] for v in ev["categories"].values())

    def test_council_motion_no_second_wording(self):
        lines = ["I.   ITEM", "     COUNCIL MOTION: Upon motion by Councilmember Elm there was no",
                 "     second and the motion failed."]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["motion"]["kind"] == "failed_no_second"

    def test_a_restated_motion_after_a_failed_one_is_its_own_event_linked_back(self):
        lines = ["I.   ITEM", "     COUNCIL ACTION: Councilmember Elm made a motion to rename the item.",
                 "     The motion failed for lack of a second.",
                 "     COUNCIL ACTION: Councilmember Elm restated her motion to rename the item next month.",
                 "     The motion was seconded by Councilmember Fir and the City Council voted 5-0 via roll call.",
                 "     AYES: ALDER, BIRCH, CEDAR, ELM, FIR", "     NOES: None", "     Motion carried.", "J.   NEXT"]
        _, events = _parse(NOVATO, lines)
        assert [e["motion"]["kind"] for e in events] == ["failed_no_second", "restated"]
        assert events[1]["motion"]["restates"] == events[0]["event_id"]
        assert events[1]["motion"]["mover"] == "ELM" and events[1]["status"] == "named"

    def test_a_motion_without_a_roll_call_is_held_not_dropped(self):
        lines = ["I.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch to move this item to a later date.", "     Discussion ensued.",
                 "J.   NEXT"]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "held" and ev["hold_reasons"] == ["no_vote_recorded"]

    @pytest.mark.parametrize("header,kind", [
        ("COUNCIL ACTION: Upon substitute motion made by Councilmember Alder and seconded by", "substitute"),
        ("SUBSTITUTE MOTION: Upon motion by Councilmember Alder and seconded by", "substitute"),
        ("COUNCIL ACTION: Substitute motion by Councilmember Alder and seconded by", "substitute"),
        ("COUNCIL ACTION: A substitute motion was made by Councilmember Alder and seconded by", "substitute"),
        ("COUNCIL ACTION ON MAIN MOTION: Upon motion by Councilmember Alder and seconded by", "main"),
    ])
    def test_motion_kinds(self, header, kind):
        lines = ["I.   ITEM", "     " + header,
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to approve.",
                 "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None", "     Motion carried."]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["motion"]["kind"] == kind and ev["motion"]["mover"] == "ALDER"
        assert ev["motion"]["seconder"] == "BIRCH"

    def test_amendment(self):
        lines = ["I.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to amend the motion to",
                 "     add a condition.", "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None",
                 "     Motion carried."]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["motion"]["kind"] == "amendment"

    def test_group_scoped_consent_votes_are_separate_events_and_hold_on_the_shared_tally(self):
        lines = ["G.   CONSENT CALENDAR",
                 "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to approve the",
                 "     Consent Calendar, except particular items became 4-0-1.",
                 "     (G.1 and G.4)",
                 "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None", "", "     Motion carried.",
                 "", "     (G.2 and G.3)", "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD", "     NOES: None",
                 "     ABSTAINED: ELM", "", "     Motion carried.", "", "     G.1.  Waive reading",
                 "     G.2.  Approve minutes", "     G.3.  Approve other minutes", "     G.4.  Adopt resolution"]
        _, events = _parse(NOVATO, lines)
        assert len(events) == 2
        assert [e["item"]["scope"] for e in events] == [["G.1", "G.4"], ["G.2", "G.3"]]
        assert _names(events[1], "abstain") == ["ELM"]
        assert all(e["status"] == "held" and "tally_scope_ambiguous" in e["hold_reasons"] for e in events)
        assert events[0]["motion"]["group_of"] == events[1]["motion"]["group_of"]
        assert events[0]["consent"] is True

    def test_inline_block_on_one_line(self):
        lines = ["C. GENERAL BUSINESS",
                 "C.1. Authorize the agreement. COUNCIL ACTION: Upon motion by Councilmember Alder and "
                 "seconded by Councilmember Birch, the City Council voted 5-0 via roll call to authorize the "
                 "agreement. AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM NOES: NONE Motion carried.",
                 "D. ADJOURNMENT"]
        ct, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "named" and _names(ev, "aye")[-1] == "ELM"
        assert _excerpt(ct, ev["category_spans"]["no"]).strip() == "NOES: NONE"
        assert ev["item"]["sub"] == "C.1"

    def test_category_value_continues_across_a_page_break(self):
        lines = ["I.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to approve.",
                 "     AYES: ALDER, BIRCH, CEDAR,", "", "                     3", "\f",
                 "     DOGWOOD, ELM", "     NOES: None", "     Motion carried."]
        _, [ev] = _parse(NOVATO, lines)
        assert _names(ev, "aye") == ["ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM"]
        assert ev["status"] == "named"

    def test_unparsed_category_value_is_held(self):
        lines = list(NOVATO_BASIC)
        lines[7] = "     NOES:          the member who left early"
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "held" and "unparsed_block" in ev["hold_reasons"]

    def test_a_name_in_two_categories_is_held(self):
        lines = list(NOVATO_BASIC)
        lines[7] = "     NOES:          DOGWOOD"
        lines[3] = lines[3].replace("4-1", "4-1")
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "held" and "name_in_two_categories" in ev["hold_reasons"]

    def test_a_recusal_belongs_to_the_motion_after_the_previous_vote(self):
        lines = ["E.   REPORTS",
                 "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to add an urgency item.",
                 "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None", "     Motion carried.",
                 "     Councilmember Birch introduced the urgency item.",
                 "     Mayor Elm recused himself from this item due to a conflict.",
                 "     COUNCIL ACTION: Upon motion by Councilmember Birch and seconded by",
                 "     Councilmember Cedar, the City Council voted 4-0 via roll call to adopt it.",
                 "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD", "     NOES: None", "     RECUSED: ELM",
                 "     Motion carried.", "F.   NEXT"]
        _, events = _parse(NOVATO, lines)
        assert [e["status"] for e in events] == ["named", "named"]
        assert events[0]["item_exceptions"] == []
        assert [x["name"] for x in events[1]["item_exceptions"]] == ["ELM"]

    def test_votes_with_no_motion_are_held(self):
        lines = ["I.   ITEM", "     The Council discussed the matter.", "     AYES: ALDER, BIRCH",
                 "     NOES: None", "J.   NEXT"]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["status"] == "held" and ev["hold_reasons"] == ["vote_without_motion"]
        assert ev["motion"] is None

    def test_event_ids_are_document_qualified(self):
        _, [a] = _parse(NOVATO, NOVATO_BASIC, doc_sha="a" * 64)
        _, [b] = _parse(NOVATO, NOVATO_BASIC, doc_sha="b" * 64)
        assert a["event_id"] != b["event_id"]

    def test_parse_is_deterministic(self):
        assert _parse(NOVATO, NOVATO_BASIC)[1] == _parse(NOVATO, NOVATO_BASIC)[1]


# ---------------------------------------------------------------------------------------------
BOS_DOC = [
    "REGULAR MEETING OF THE FICTIONAL BOARD OF SUPERVISORS",
    "Roll Call",
    "Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood; Supervisor Elm",
    "1.",
    "Administrators Report",
    "Urgency Item The administrator requested an urgency finding.",
    "M/s Supervisor Alder - Supervisor Birch to determine that the need to take action arose subsequent "
    "to the agenda being posted.",
    "AYES:",
    "ALL",
    "The director addressed the Board regarding the impact on the community.",
    "M/s Supervisor Birch - Supervisor Cedar to execute the grant agreement in the amount of $10.",
    "The administrator briefly commented on the item.",
    "Thereafter, the vote on the pending motion was",
    "AYES:",
    "ALL",
    "2.",
    "Consent Calendar A (Items CA-1 through CA-2) (\"Consent Calendar A\" reflects items with prior approval.)",
    "M/s Supervisor Cedar - Supervisor Dogwood to approve Consent Calendar A (Items CA-1 through CA-2) as "
    "presented.",
    "CA-1. Board of Supervisors",
    "a.",
    "Request to adjourn in memory of a resident.",
    "CA-2. Public Works Request to approve an agreement.",
    "CA2 - STAFF REPORT",
    "AYES: ALL",
    "3.",
    "Consent Calendar B (Items CB-1) (\"Consent Calendar B\" reflects items requiring a 4/5 vote.)",
    "M/s Supervisor Dogwood - Supervisor Elm to approve Consent Calendar B (Item CB-1) as presented.",
    "CB-1. Finance Request to approve budget adjustments.",
    "Vote: Motion carried 4-0",
    "AYES: Supervisor Alder, Supervisor Birch, Supervisor Dogwood, Supervisor Elm",
    "ABSENT: Supervisor Cedar",
    "4.",
    "Request to adopt an ordinance.",
    "Supervisor Elm recused himself from this item due to a conflict.",
    "M/s Supervisor Alder - Supervisor Birch to adopt the ordinance.",
    "Vote: Motion carried 3-0 Abstain:1",
    "AYES: Supervisor Alder, Supervisor Birch, Superrvisor Dogwood",
    "Abstain: Supervisor Cedar",
    "RECUSE: Supervisor Elm",
    "5.",
    "Request to approve a lease.",
    "M/s Supervisor Cedar - Supervisor Alder to approve the lease.",
    "Vote: Motion carried 3-2",
    "AYES: Supervisor Alder, Supervisor Cedar, Supervisor Dogwood",
    "NOES: Supervisor Birch, Supervisor Elm",
    "Adjourn as the Fictional Board of Supervisors",
]


class TestBoardOfSupervisors:
    def test_six_vote_blocks_six_events_in_order(self):
        _, events = _parse(BOS, BOS_DOC)
        assert [(e["item"]["top"], e["motion"]["mover"]) for e in events] == [
            ("1", "ALDER"), ("1", "BIRCH"), ("2", "CEDAR"), ("3", "DOGWOOD"), ("4", "ALDER"), ("5", "CEDAR")]

    def test_all_sentinel_needs_attendance_and_is_not_named(self):
        ct, events = _parse(BOS, BOS_DOC)
        ev = events[0]
        assert ev["status"] == "needs_attendance"
        assert ev["sentinels"] == [{"token": "ALL", "category": "aye", "span": ev["sentinels"][0]["span"]}]
        assert _excerpt(ct, ev["sentinels"][0]["span"]) == "ALL"
        assert ev["categories"]["aye"] == []

    def test_pending_motion_vote_joins_its_motion(self):
        _, events = _parse(BOS, BOS_DOC)
        assert events[1]["motion"]["text"].startswith("execute the grant agreement")
        assert events[1]["status"] == "needs_attendance"

    def test_consent_vote_after_its_subitems_belongs_to_the_section(self):
        _, events = _parse(BOS, BOS_DOC)
        ev = events[2]
        assert ev["consent"] is True and ev["item"]["top"] == "2" and ev["item"]["sub"] is None

    def test_vote_line_tally_and_named_block(self):
        _, events = _parse(BOS, BOS_DOC)
        ev = events[3]
        assert ev["status"] == "named" and ev["tally"]["printed"] == "4-0"
        assert _names(ev, "absent") == ["CEDAR"] and len(_names(ev, "aye")) == 4
        assert ev["outcome"] == "carried"

    def test_keyed_tally_and_title_typo(self):
        _, events = _parse(BOS, BOS_DOC)
        ev = events[4]
        assert ev["tally"]["keyed"] == {"abstain": 1}
        assert _names(ev, "aye") == ["ALDER", "BIRCH", "DOGWOOD"]
        assert _names(ev, "abstain") == ["CEDAR"] and _names(ev, "recused") == ["ELM"]
        assert ev["status"] == "named"

    def test_prose_exception_is_recorded_for_the_item(self):
        ct, events = _parse(BOS, BOS_DOC)
        ev = events[4]
        [exc] = ev["item_exceptions"]
        assert exc["name"] == "ELM" and exc["kind"] == "recused"
        assert "recused himself" in _excerpt(ct, exc["span"])

    def test_split_vote(self):
        _, events = _parse(BOS, BOS_DOC)
        ev = events[5]
        assert _names(ev, "no") == ["BIRCH", "ELM"] and ev["status"] == "named"

    def test_keyed_tally_mismatch_is_held(self):
        lines = list(BOS_DOC)
        lines[35] = "Vote: Motion carried 3-0 Abstain:2"
        _, events = _parse(BOS, lines)
        assert events[4]["status"] == "held" and "tally_mismatch" in events[4]["hold_reasons"]

    def test_unrecognized_tally_is_held_never_null(self):
        lines = list(BOS_DOC)
        lines[42] = "Vote: Motion carried by a show of hands"
        _, events = _parse(BOS, lines)
        assert events[5]["status"] == "held" and "tally_unrecognized" in events[5]["hold_reasons"]

    def test_a_restatement_of_the_pending_motion_is_one_vote(self):
        lines = ["1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to adopt the plan.",
                 "The Board discussed the conditions.", "The motion was restated as follows:",
                 "M/s Supervisor Alder - Supervisor Birch to adopt the plan with the conditions.", "AYES: ALL",
                 "2.", "Next item."]
        ct, events = _parse(BOS, lines)
        [ev] = events
        assert ev["motion"]["text"] == "adopt the plan with the conditions."
        assert ev["motion"]["kind"] == "restated"
        first = ct.text.index("M/s")
        assert ev["motion"]["restates_span"]["start"] == first
        assert any(c["start"] == first for c in ev["consumed"])

    def test_moved_by_wording(self):
        lines = ["1.", "Special item.",
                 "Motion to approve the plan moved by Supervisor Alder and seconded by Supervisor Birch.",
                 "Votes:", "AYES: ALL", "NOES: NONE", "Motion passed."]
        _, [ev] = _parse(BOS, lines)
        assert ev["motion"]["mover"] == "ALDER" and ev["motion"]["seconder"] == "BIRCH"
        assert ev["outcome"] == "carried" and ev["status"] == "needs_attendance"

    @pytest.mark.parametrize("line,text,behalf", [
        ("M/s Supervisor Alder - Supervisor Birch on behalf of Supervisor Cedar to reappoint a resident.",
         "reappoint a resident.", "CEDAR"),
        ("M/s Supervisor Alder - Supervisor Birch on behalf of Supervisor Cedar, to adopt the rate.",
         "adopt the rate.", "CEDAR"),
        ("M/s Supervisor Alder - Supervisor Birch on behalf of Supervisor Cedar reappoint a resident.",
         "reappoint a resident.", "CEDAR"),
        ("M/s Supervisor Alder - Supervisor Birch Recommended action: Approve.",
         "Recommended action: Approve.", None),
        ("M/s Supervisor Alder - Supervisor Birch concur in and adopt response.",
         "concur in and adopt response.", None),
        ("M/s Supervisor Alder - Supervisor Birch (a) adopt the budget; and (b) accept the plan.",
         "(a) adopt the budget; and (b) accept the plan.", None),
    ])
    def test_ms_variants(self, line, text, behalf):
        _, [ev] = _parse(BOS, ["1.", "Item.", line, "AYES: ALL"])
        assert ev["motion"]["mover"] == "ALDER" and ev["motion"]["seconder"] == "BIRCH"
        assert ev["motion"]["text"] == text
        assert ev["motion"].get("on_behalf_of") == behalf
        assert ev["status"] == "needs_attendance"

    @pytest.mark.parametrize("line,mover,seconder,text", [
        ("M/s Supervisor Ann Alder - Supervisor Bea Birch to adopt the budget.", "ALDER", "BIRCH",
         "adopt the budget."),
        ("M/s Supervisor Ann Alder - Supervisor Bea Birch-Cedar to adopt the budget.", "ALDER", "BIRCH-CEDAR",
         "adopt the budget."),
        ("M/s Ann Alder - Bea Birch to approve the district budget.", "ALDER", "BIRCH",
         "approve the district budget."),
        ("M/s Supervisor Alder - 0 to appoint a resident.", "ALDER", None, "appoint a resident."),
        ("M/s Supervisor Alder - Supervisor Birch Recommended action: Approve.", "ALDER", "BIRCH",
         "Recommended action: Approve."),
    ])
    def test_given_names_missing_titles_and_a_garbled_seconder(self, line, mover, seconder, text):
        _, [ev] = _parse(BOS, ["1.", "Item.", line, "AYES: ALL"])
        assert (ev["motion"]["mover"], ev["motion"]["seconder"], ev["motion"]["text"]) == (mover, seconder, text)

    def test_all_caps_titles(self):
        _, [ev] = _parse(BOS, ["1.", "Item.", "M/s SUPERVISOR ALDER - SUPERVISOR BIRCH-CEDAR to approve it.",
                               "AYES: ALL"])
        assert ev["motion"]["mover"] == "ALDER" and ev["motion"]["seconder"] == "BIRCH-CEDAR"

    def test_a_numbered_list_inside_an_item_is_not_a_new_item(self):
        lines = ["15.", "Request to adopt an ordinance.",
                 "M/s Supervisor Alder - Supervisor Birch to adopt the ordinance as revised.",
                 "Staff summarized the direction, incorporated into the motion, as follows:",
                 "1. Revise one section.", "2. Revise another section.",
                 "Thereafter, the vote on the pending motion was", "AYES: ALL", "16.", "Closed Session"]
        _, [ev] = _parse(BOS, lines)
        assert ev["item"]["top"] == "15" and ev["status"] == "needs_attendance"
        assert ev["motion"]["mover"] == "ALDER"

    def test_novato_sections_must_advance(self):
        lines = ["H.   PUBLIC HEARINGS", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch to adopt with these conditions:", "     A.  First condition.",
                 "     B.  Second condition.", "     The City Council voted 5-0 via roll call.",
                 "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None", "     Motion carried."]
        _, [ev] = _parse(NOVATO, lines)
        assert ev["item"]["top"] == "H" and ev["status"] == "named"

    def test_all_in_a_non_aye_category_is_unparsed(self):
        lines = ["1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.", "AYES: NONE",
                 "NOES: ALL"]
        _, [ev] = _parse(BOS, lines)
        assert ev["status"] == "held" and "unparsed_block" in ev["hold_reasons"]

    def test_prose_after_all_is_not_a_name(self):
        _, events = _parse(BOS, BOS_DOC)
        assert all(e["categories"]["aye"] == [] for e in events[:3])

    def test_unanimous_sentinel(self):
        lines = ["1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.", "AYES: UNANIMOUS"]
        _, [ev] = _parse(BOS, lines)
        assert ev["sentinels"][0]["token"] == "UNANIMOUS" and ev["status"] == "needs_attendance"


class TestTranscripts:
    def test_a_verbatim_transcript_is_not_parsed(self):
        lines = ["SPECIAL JOINT MEETING OF THE FICTIONAL BOARD",
                 "ALDER SMITH: GOOD EVENING, EVERYONE.", "BIRCH JONES: THANK YOU.",
                 "CLERK: SUPERVISOR ALDER.", "ALDER SMITH: HERE.", "CEDAR LEE: MOVED BY ALDER. ALL IN FAVOR?",
                 "DOGWOOD KAY: AYE.", "ELM ROE: AYE.", "FIR DOE: OKAY."]
        ct = CanonicalText.from_lines(lines)
        from votes_blocks import is_transcript
        assert is_transcript(ct)
        assert parse_document(ct, body=BOS, meeting_id="meeting-x-1", doc_sha256="d" * 64) == []

    def test_minutes_are_not_transcripts(self):
        from votes_blocks import is_transcript
        assert not is_transcript(CanonicalText.from_lines(BOS_DOC))
        assert not is_transcript(CanonicalText.from_lines(NOVATO_BASIC))
