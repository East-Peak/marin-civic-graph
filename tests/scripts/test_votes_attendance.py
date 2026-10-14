"""Votes Part A, increment d: who is present, item by item, and when `AYES: ALL` may be expanded.

Fixtures are fictional (Alder, Birch, Cedar, Dogwood, Elm; a five-seat body). The parser supplies
events; this stage tracks attendance through the document and decides, per event, whether an ALL
vote expands to names (citing the attendance evidence) or is held."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_attendance import resolve  # noqa: E402
from votes_blocks import parse_document  # noqa: E402
from votes_text import CanonicalText  # noqa: E402

BOS = "marin-county-bos"
NOVATO = "novato-city-council"
ROLL = "Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood; Supervisor Elm"
FIVE = ["ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM"]


def _run(lines, body=BOS):
    ct = CanonicalText.from_lines(lines)
    events = parse_document(ct, body=body, meeting_id="meeting-x-1", doc_sha256="d" * 64)
    out, trace = resolve(ct, body=body, events=events)
    return ct, out, trace


def _item(n, mover="Alder", seconder="Birch", block=("AYES: ALL",)):
    return [f"{n}.", f"Item {n}.", f"M/s Supervisor {mover} - Supervisor {seconder} to approve item {n}.", *block]


def _ayes(ev):
    return sorted(n["name"] for n in ev["categories"]["aye"])


class TestExpansion:
    def test_all_present_expands_to_the_roll_call(self):
        ct, [ev], _ = _run(["Roll Call", ROLL, *_item(1)])
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE
        assert all(n["inferred"] for n in ev["categories"]["aye"])
        texts = [ct.text[s["start"]:s["end"]] for s in ev["attendance"]["evidence"]]
        assert any(t.startswith("Present:") for t in texts)

    def test_one_absent_at_roll_call(self):
        roll = ["Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood",
                "Absent: Supervisor Elm"]
        _, [ev], _ = _run(["Roll Call", *roll, *_item(1)])
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE[:4]

    def test_an_explicit_absence_in_the_block_is_excluded(self):
        _, [ev], _ = _run(["Roll Call", ROLL, *_item(1, block=("AYES: ALL", "ABSENT: Supervisor Elm"))])
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE[:4]
        assert [n["name"] for n in ev["categories"]["absent"]] == ["ELM"]

    def test_noes_and_recusals_in_the_block_are_excluded(self):
        block = ("AYES: ALL", "NOES: Supervisor Dogwood", "RECUSE: Supervisor Elm")
        _, [ev], _ = _run(["Roll Call", ROLL, *_item(1, block=block)])
        assert ev["status"] == "expanded" and _ayes(ev) == ["ALDER", "BIRCH", "CEDAR"]

    def test_a_placed_late_arrival(self):
        roll = ["Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood",
                "Absent: Supervisor Elm"]
        lines = ["Roll Call", *roll, *_item(1), "(Supervisor Elm present at 10:05 a.m.)", *_item(2)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE[:4], FIVE]

    def test_an_early_departure(self):
        lines = ["Roll Call", ROLL, *_item(1), "(Supervisor Elm absent at 11:30 a.m.)", *_item(2)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE, FIVE[:4]]

    def test_recess_and_reconvene_with_an_attendance_statement(self):
        lines = ["Roll Call", ROLL, *_item(1), "The Board recessed at 10:00 a.m.",
                 "The Board reconvened in open session at 1:30 p.m. Supervisor Elm was absent.", *_item(2)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE, FIVE[:4]]

    def test_recess_and_reconvene_without_a_statement_keeps_the_state(self):
        lines = ["Roll Call", ROLL, *_item(1), "The Board recessed at 10:00 a.m. and reconvened at 10:15 a.m.",
                 *_item(2)]
        _, evs, _ = _run(lines)
        assert [e["status"] for e in evs] == ["expanded", "expanded"]

    def test_all_members_present_after_reconvening_restores_everyone(self):
        lines = ["Roll Call", ROLL, "(Supervisor Elm absent at 10:00 a.m.)", *_item(1),
                 "The Board reconvened at 1:30 p.m. All Supervisors were present.", *_item(2)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE[:4], FIVE]

    def test_sitting_as_another_body_holds_the_vote(self):
        lines = ["Roll Call", ROLL,
                 "The Board recessed at 10:00 a.m. to meet as the Fictional Flood Control District Board.",
                 *_item(1), "Reconvene as the Fictional County Board of Supervisors", *_item(2)]
        _, evs, _ = _run(lines)
        assert [(e["status"], e["hold_reasons"]) for e in evs] == [("held", ["body_unclear"]), ("expanded", [])]

    @pytest.mark.parametrize("sentence", [
        "The Board recessed at 1:35 p.m. to meet as the Fictional Housing Authority and reconvened at 2:34 p.m. "
        "to meet as the Fictional County Board of Supervisors.",
        "The Board adjourned to closed session at 9:08 a.m. and reconvened at 9:47 a.m.",
        "The Board reconvened at 12:00 p.m. to meet in closed session. All Supervisors were present.",
    ])
    def test_the_last_body_clause_of_a_sentence_decides(self, sentence):
        lines = ["Roll Call", ROLL, sentence, *(["Reconvene in Open Session"] if "to meet in closed" in sentence
                                             else []), *_item(1)]
        _, [ev], _ = _run(lines)
        assert ev["status"] == "expanded"

    def test_an_untimed_parenthetical_absence_and_two_members_returning(self):
        lines = ["Roll Call", ROLL, *_item(1), "(Supervisor Elm absent)", *_item(2),
                 "(Supervisor Dogwood absent at 2:00 p.m.)", *_item(3),
                 "Supervisor Dogwood and President Elm returned to the meeting at 3:00 p.m.", *_item(4)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE, FIVE[:4], FIVE[:3], FIVE]

    def test_an_uncertain_statement_holds_until_attendance_is_re_established(self):
        lines = ["Roll Call", ROLL, "The President advised Supervisor Elm would rejoin the meeting soon.",
                 *_item(1), "The Board reconvened at 1:30 p.m. All Supervisors were present.", *_item(2)]
        _, evs, _ = _run(lines)
        assert [(e["status"], e["hold_reasons"]) for e in evs] == [
            ("held", ["ambiguous_attendance"]), ("expanded", [])]

    def test_presentation_prose_never_triggers(self):
        lines = ["Roll Call", ROLL, "Supervisor Elm presented a resolution and the item was approved as presented.",
                 *_item(1)]
        _, [ev], _ = _run(lines)
        assert ev["status"] == "expanded"

    def test_all_present_after_an_incomplete_roll_call_is_uncertain(self):
        roll = "Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood"
        lines = ["Roll Call", roll, "The Board reconvened at 1:30 p.m. All Supervisors were present.", *_item(1)]
        _, [ev], _ = _run(lines)
        assert ev["status"] == "held" and ev["hold_reasons"] == ["ambiguous_attendance"]

    def test_no_roll_call_at_all(self):
        _, [ev], _ = _run(_item(1))
        assert ev["status"] == "held" and ev["hold_reasons"] == ["ambiguous_attendance"]

    def test_a_prose_recusal_excludes_the_member_from_that_item_only(self):
        lines = ["Roll Call", ROLL, "1.", "Item 1.", "Supervisor Elm recused himself from this item.",
                 "M/s Supervisor Alder - Supervisor Birch to approve item 1.", "AYES: ALL", *_item(2)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE[:4], FIVE]

    def test_recusal_and_departure(self):
        lines = ["Roll Call", ROLL, "1.", "Item 1.",
                 "Supervisor Elm recused himself from voting on this item and left the Chambers at 9:40 a.m.",
                 "M/s Supervisor Alder - Supervisor Birch to approve item 1.", "AYES: ALL", *_item(2),
                 "Supervisor Elm returned to the Chambers at 10:10 a.m.", *_item(3)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE[:4], FIVE[:4], FIVE]

    def test_a_wrapped_pdf_roll_call_with_a_hyphen_break(self):
        lines = ["Roll Call", "Present:   Supervisor Alder, Supervisor Birch, Supervisor Cedar, Supervisor Dog-",
                 "           wood, Supervisor Elm", "", *_item(1)]
        _, [ev], _ = _run(lines)
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE

    def test_an_upper_case_roll_call_with_plural_titles(self):
        lines = ["Roll Call", "PRESENT:     Supervisors Alder, Birch and Cedar",
                 "ABSENT:      Supervisors Dogwood and Elm", *_item(1)]
        _, [ev], _ = _run(lines)
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE[:3]

    def test_a_pdf_absent_line_without_a_colon(self):
        lines = ["Roll Call", "Present:   Supervisor Alder, Supervisor Birch, Supervisor Cedar, Supervisor Dogwood",
                 "", "Absent     Supervisor Elm", "", *_item(1)]
        ct, [ev], trace = _run(lines)
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE[:4]
        roll = trace[0]["span"]
        assert "Absent     Supervisor Elm" in ct.text[roll["start"]:roll["end"]]

    def test_timed_statements_without_parentheses_and_for_two_members(self):
        roll = "Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar"
        lines = ["Roll Call", roll, "Absent: Supervisor Dogwood; Supervisor Elm",
                 "(Supervisor Dogwood present at 9:06 a.m. and Supervisor Elm present at 9:15 a.m.)", *_item(1),
                 "Supervisor Elm absent at 11:16 a.m.", *_item(2),
                 "(Supervisors Elm and Dogwood present at 1:41 p.m.)", *_item(3)]
        _, evs, _ = _run(lines)
        assert [_ayes(e) for e in evs] == [FIVE, FIVE[:4], FIVE]

    @pytest.mark.parametrize("sentence", [
        "Supervisor Elm acknowledged the Department of Public Works for its work.",
        "Supervisor Elm briefly commented on attending the screening of a film.",
        "Supervisor Elm requested staff to return to the Board with a timeline.",
        "Purchasing Supervisor Dee Goldfinch provided an update.",
    ])
    def test_ordinary_prose_about_members_is_not_attendance(self, sentence):
        _, [ev], _ = _run(["Roll Call", ROLL, sentence, *_item(1)])
        assert ev["status"] == "expanded"

    @pytest.mark.parametrize("sentence", [
        "Supervisor Alder noted Supervisor Elm is attending a conference out of town.",
        "Supervisor Alder noted that Supervisor Elm was not present this morning.",
        "The President noted that Supervisor Elm is away on County business.",
    ])
    def test_unread_attendance_wording_makes_the_state_uncertain(self, sentence):
        _, [ev], _ = _run(["Roll Call", ROLL, sentence, *_item(1)])
        assert ev["status"] == "held" and ev["hold_reasons"] == ["ambiguous_attendance"]

    def test_tally_is_checked_after_expansion(self):
        block = ("Vote: Motion carried 5-0", "AYES: ALL", "ABSENT: Supervisor Elm")
        _, [ev], _ = _run(["Roll Call", ROLL, *_item(1, block=block)])
        assert ev["status"] == "held" and "tally_mismatch" in ev["hold_reasons"]


class TestRetrospectiveArrival:
    NOV_ROLL = ["A.   CONVENE AND ROLL CALL",
                "     COUNCIL PRESENT: Mayor Ann Alder, Mayor Pro Tempore Bea Birch,",
                "     Councilmember Cy Cedar, and Councilmember Di Dogwood",
                "     COUNCIL EXCUSED TARDINESS: Councilmember Ed Elm arrived at 6:52 p.m.", ""]

    def _motion(self, letter, block):
        return [f"{letter}.   ITEM {letter}", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                "     Councilmember Birch to approve.", *block, "     Motion carried.", ""]

    def test_unplaced_arrival_holds_all_votes_until_the_member_is_seen(self):
        lines = (self.NOV_ROLL
                 + self._motion("B", ["     AYES: ALDER, BIRCH, CEDAR, DOGWOOD", "     NOES: None",
                                      "     ABSENT: ELM"])
                 + self._motion("C", ["     AYES: ALL"])
                 + self._motion("D", ["     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None"])
                 + self._motion("E", ["     AYES: ALL"]))
        _, evs, _ = _run(lines, body=NOVATO)
        assert [(e["status"], e["hold_reasons"]) for e in evs] == [
            ("named", []), ("held", ["pending_transition"]), ("named", []), ("expanded", [])]
        assert _ayes(evs[3]) == FIVE


class TestNamedValidation:
    def test_a_name_outside_the_roster_is_held(self):
        block = ("Vote: Motion carried 4-0", "AYES: Supervisor Alder, Supervisor Birch, Supervisor Cedar, "
                 "Supervisor Fir", "ABSENT: Supervisor Elm")
        _, [ev], _ = _run(["Roll Call", ROLL, *_item(1, block=block)])
        assert ev["status"] == "held" and "name_unknown" in ev["hold_reasons"]

    def test_a_named_member_known_to_be_absent_is_held(self):
        roll = ["Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood",
                "Absent: Supervisor Elm"]
        block = ("Vote: Motion carried 4-0", "AYES: Supervisor Alder, Supervisor Birch, Supervisor Cedar, "
                 "Supervisor Elm", "ABSENT: Supervisor Dogwood")
        _, [ev], _ = _run(["Roll Call", *roll, *_item(1, block=block)])
        assert ev["status"] == "held" and "named_not_present" in ev["hold_reasons"]

    def test_a_valid_named_vote_stays_named_and_re_establishes_attendance(self):
        lines = ["Roll Call", ROLL, "The President advised Supervisor Elm would rejoin the meeting soon.",
                 *_item(1, block=("Vote: Motion carried 4-0", "AYES: Supervisor Alder, Supervisor Birch, "
                                  "Supervisor Cedar, Supervisor Dogwood", "ABSENT: Supervisor Elm")),
                 *_item(2)]
        _, evs, _ = _run(lines)
        assert [e["status"] for e in evs] == ["named", "expanded"]
        assert _ayes(evs[1]) == FIVE[:4]

    def test_a_repaired_list_with_an_unknown_name_is_held(self):
        lines = ["A.   ROLL CALL", "     COUNCIL PRESENT: Councilmember Ann Alder, Councilmember Bea Birch,",
                 "     Councilmember Cy Cedar, Councilmember Di Dogwood, Councilmember Ed Elm", "",
                 "B.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to approve.",
                 "     AYES: ALDER, BIRCH CEDAR, DOGWOOD, ELMO", "     NOES: None", "     Motion carried."]
        _, [ev], _ = _run(lines, body=NOVATO)
        assert ev["status"] == "held" and "name_unknown" in ev["hold_reasons"]

    def test_a_roll_call_name_wrapped_after_its_title(self):
        lines = ["A.   ROLL CALL", "     COUNCIL PRESENT: Mayor Ann Alder, Mayor Pro Tempore Bea Birch,",
                 "     Councilmember Cy Cedar, Councilmember Di Dogwood, and Councilmember", "     Ed Elm", "",
                 "B.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to approve.",
                 "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None", "     Motion carried."]
        _, [ev], _ = _run(lines, body=NOVATO)
        assert ev["status"] == "named" and ev["attendance"]["roster"] == FIVE

    def test_in_person_and_teleconference_lists_are_one_roll_call(self):
        lines = ["A.   ROLL CALL", "     COUNCIL PRESENT: Mayor Ann Alder, Mayor Pro Tempore Bea Birch,",
                 "     and Councilmember Cy Cedar", "",
                 "     COUNCIL PRESENT VIA TELECONFERENCE: Councilmember Di Dogwood", "",
                 "     COUNCIL ABSENT: Councilmember Ed Elm", "", "     STAFF PRESENT: A clerk", "",
                 "B.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 4-0 via roll call to approve.",
                 "     AYES: ALL", "     Motion carried."]
        _, [ev], _ = _run(lines, body=NOVATO)
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE[:4]
        assert ev["attendance"]["roster"] == FIVE

    def test_a_retrospective_arrival_is_a_member_of_the_roster(self):
        lines = ["A.   ROLL CALL", "     COUNCIL PRESENT: Mayor Ann Alder, Mayor Pro Tempore Bea Birch,",
                 "     Councilmember Cy Cedar, and Councilmember Di Dogwood", "",
                 "     Councilmember Ed Elm arrived at 4:06 p.m.", "", "     STAFF PRESENT: A clerk", "",
                 "B.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 5-0 via roll call to approve.",
                 "     AYES: ALDER, BIRCH, CEDAR, DOGWOOD, ELM", "     NOES: None", "     Motion carried."]
        _, [ev], _ = _run(lines, body=NOVATO)
        assert ev["status"] == "named" and ev["attendance"]["roster"] == FIVE

    def test_an_incomplete_roster_is_completed_by_a_named_block_not_failed(self):
        roll = "Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood"
        block = ("Vote: Motion carried 4-0", "AYES: Supervisor Alder, Supervisor Birch, Supervisor Cedar, "
                 "Supervisor Dogwood", "ABSENT: Supervisor Elm")
        _, evs, _ = _run(["Roll Call", roll, *_item(1, block=block), *_item(2)])
        assert [e["status"] for e in evs] == ["named", "expanded"]
        assert _ayes(evs[1]) == FIVE[:4]

    def test_a_vacant_seat_completes_the_roster(self):
        lines = ["A.   ROLL CALL", "     COUNCIL PRESENT: Councilmember Ann Alder, Councilmember Bea Birch,",
                 "     Councilmember Cy Cedar, Councilmember Di Dogwood",
                 "     COUNCIL ABSENT: The District 5 seat was vacant.", "",
                 "B.   ITEM", "     COUNCIL ACTION: Upon motion by Councilmember Alder and seconded by",
                 "     Councilmember Birch, the City Council voted 4-0 via roll call to approve.",
                 "     AYES: ALL", "     Motion carried."]
        _, [ev], _ = _run(lines, body=NOVATO)
        assert ev["status"] == "expanded" and _ayes(ev) == FIVE[:4]


class TestTrace:
    def test_the_trace_lists_every_transition_with_its_span(self):
        lines = ["Roll Call", ROLL, *_item(1), "(Supervisor Elm absent at 11:30 a.m.)", *_item(2)]
        ct, _, trace = _run(lines)
        kinds = [t["kind"] for t in trace]
        assert kinds[0] == "roll_call" and "depart" in kinds
        for t in trace:
            assert ct.text[t["span"]["start"]:t["span"]["end"]].strip()

    def test_resolution_is_deterministic(self):
        lines = ["Roll Call", ROLL, *_item(1), "(Supervisor Elm absent at 11:30 a.m.)", *_item(2)]
        assert _run(lines)[1:] == _run(lines)[1:]
