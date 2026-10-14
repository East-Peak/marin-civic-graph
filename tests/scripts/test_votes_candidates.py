"""Votes Part A, increment c: an independent, deliberately broad scan for vote-bearing text, and
the rule that every candidate ends in exactly one disposition (named / expanded / held / excluded).

The scanner never imports the parser: it decides what *might* be a vote on its own, so the parser's
blind spots show up as held orphans instead of disappearing."""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_candidates import (  # noqa: E402
    CLASSES,
    check_partition,
    dispose,
    events_to_hold,
    scan,
)
from votes_text import CanonicalText  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _ct(lines):
    return CanonicalText.from_lines(lines)


def _kinds(cands):
    return [(c["kind"], c["text"]) for c in cands]


def _span(ct, needle, nth=0):
    start = -1
    for _ in range(nth + 1):
        start = ct.text.index(needle, start + 1)
    return ct.locate(start, start + len(needle))


def _event(event_id, status, consumed, block=None):
    return {"event_id": event_id, "status": status, "consumed": consumed, "block": block}


class TestIndependence:
    def test_the_scanner_never_imports_the_parser(self):
        tree = ast.parse((SCRIPTS / "votes_candidates.py").read_text())
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert "votes_blocks" not in imported and "votes_attendance" not in imported


class TestScan:
    def test_labels_motions_outcomes_and_narrative_words(self):
        ct = _ct(["M/s Supervisor Alder - Supervisor Birch to approve.", "Vote: Motion carried 4-0",
                  "AYES: Supervisor Alder", "NOES: none", "ABSENT: Supervisor Cedar", "Abstain: Supervisor Elm",
                  "RECUSED: Supervisor Fir", "The motion was moved by one member and seconded by another.",
                  "The council voted after a roll call; the vote was unanimous.", "There was no second."])
        kinds = [c["kind"] for c in scan(ct)]
        assert kinds == ["ms", "vote_label", "motion_outcome", "aye_label", "no_label", "absent_label",
                         "abstain_label", "recuse_label", "moved_by", "seconded_by", "vote_word", "roll_call",
                         "vote_word", "unanimous", "no_second"]

    def test_words_that_only_look_like_votes_are_not_candidates(self):
        ct = _ct(["The voters, a devoted volunteer and the Ayers family attended."])
        assert scan(ct) == []

    def test_candidates_carry_span_line_and_a_stable_id(self):
        ct = _ct(["first line", "AYES: ALDER"])
        [c] = scan(ct, doc_sha256="ab" * 32)
        assert ct.text[c["span"]["start"]:c["span"]["end"]] == "AYES"
        assert c["span"]["line_start"] == 2
        assert c["cand_id"] == f"cand-abababab-{c['span']['start']}-aye_label"

    def test_bare_absent_and_abstained_words_are_narrative_kinds(self):
        ct = _ct(["Supervisor Alder was absent.", "Supervisor Birch abstained.", "Supervisor Cedar recused herself."])
        assert [c["kind"] for c in scan(ct)] == ["absent_word", "abstain_word", "recuse_word"]


class TestDispose:
    def test_a_candidate_in_an_events_consumed_span_takes_the_events_class(self):
        ct = _ct(["AYES: ALDER, BIRCH", "NOES: None"])
        ev = _event("vev-1", "named", [_span(ct, "AYES: ALDER, BIRCH"), _span(ct, "NOES: None")])
        out = dispose(ct, scan(ct), [ev], attendance_spans=[])
        assert [(d["class"], d["event_id"]) for d in out] == [("named", "vev-1"), ("named", "vev-1")]

    def test_expanded_and_held_events_pass_their_class_on(self):
        ct = _ct(["AYES: ALL", "AYES: ALDER"])
        evs = [_event("vev-1", "expanded", [_span(ct, "AYES: ALL")]),
               _event("vev-2", "held", [_span(ct, "AYES: ALDER")])]
        out = dispose(ct, scan(ct), evs, attendance_spans=[])
        assert [(d["class"], d["event_id"]) for d in out] == [("expanded", "vev-1"), ("held", "vev-2")]

    def test_an_unconsumed_label_is_a_held_orphan(self):
        ct = _ct(["Item.", "AYES: ALDER"])
        [d] = dispose(ct, scan(ct), [], attendance_spans=[])
        assert (d["class"], d["reason"], d["event_id"]) == ("held", "unconsumed_label", None)

    def test_an_unconsumed_label_inside_an_events_block_holds_that_event(self):
        ct = _ct(["AYES: ALDER", "AYES: BIRCH"])
        ev = _event("vev-1", "named", [_span(ct, "AYES: ALDER")], block=ct.locate(0, len(ct.text)))
        assert events_to_hold(scan(ct), [ev]) == {"vev-1": "unconsumed_vote_label"}

    def test_attendance_statements_are_excluded_with_their_trace_span(self):
        ct = _ct(["Roll Call", "Present: Supervisor Alder; Supervisor Birch", "Absent: Supervisor Cedar",
                  "Supervisor Cedar was absent for the closed session."])
        att = [ct.locate(0, ct.text.index("Absent: Supervisor Cedar") + len("Absent: Supervisor Cedar")),
               _span(ct, "Supervisor Cedar was absent for the closed session.")]
        out = dispose(ct, scan(ct), [], attendance_spans=att)
        assert [(d["class"], d["reason"]) for d in out] == [("excluded", "roll_call_attendance")] * 3
        assert all(d["evidence"] in att for d in out)

    @pytest.mark.parametrize("sentence,reason", [
        ("Consent Calendar B reflects items requiring 4/5 vote of available members.", "vote_requirement"),
        ("The ordinance passed by a majority vote of the Board.", "vote_requirement"),
        ("The measure needs a two-thirds vote of the electorate.", "vote_requirement"),
        ("The Registrar opened a vote center for voters in the election.", "election_context"),
        ("Residents may vote by mail in the November election.", "election_context"),
        ("The Planning Commission voted to recommend approval.", "other_body_vote"),
        ("On March 3, 2020, the Board voted to approve the first reading.", "earlier_vote"),
        ("The Council previously voted on this matter.", "earlier_vote"),
        ("Designate a voting representative for the league.", "voting_role"),
        ("The administrator noted the need for four affirmative votes for approval.", "vote_requirement"),
    ])
    def test_closed_list_of_non_vote_contexts(self, sentence, reason):
        ct = _ct(["Item.", sentence])
        [d] = [d for d in dispose(ct, scan(ct), [], attendance_spans=[]) if d["kind"] in ("vote_word", "unanimous")]
        assert (d["class"], d["reason"]) == ("excluded", reason)

    @pytest.mark.parametrize("lines", [
        ["Roll Call", "Present: Supervisor Alder"],
        ["A.   CONVENE, PLEDGE OF ALLEGIANCE, AND ROLL CALL", "The meeting began."],
        ["AYES: ALL Roll Call Present: Supervisor Alder; Supervisor Birch"],
    ])
    def test_roll_call_headings_are_excluded(self, lines):
        ct = _ct(lines)
        [d] = [d for d in dispose(ct, scan(ct), [], attendance_spans=[]) if d["kind"] == "roll_call"]
        assert (d["class"], d["reason"]) == ("excluded", "roll_call_heading")

    def test_a_roll_call_vote_in_prose_is_not_a_heading(self):
        ct = _ct(["Item.", "The vote was taken by roll call."])
        [d] = [d for d in dispose(ct, scan(ct), [], attendance_spans=[]) if d["kind"] == "roll_call"]
        assert d["class"] == "held"

    def test_prospective_wording_in_the_description_before_any_motion_is_excluded(self):
        ct = _ct(["1.", "Consider and possibly vote on the ordinance.", "M/s Supervisor Alder - Supervisor Birch",
                  "AYES: ALL"])
        ev = _event("vev-1", "expanded", [_span(ct, "M/s Supervisor Alder - Supervisor Birch"),
                                          _span(ct, "AYES: ALL")])
        out = {d["kind"]: d for d in dispose(ct, scan(ct), [ev], attendance_spans=[])}
        assert (out["vote_word"]["class"], out["vote_word"]["reason"]) == ("excluded", "agenda_description")

    @pytest.mark.parametrize("line", ["Discuss and decide whether to allow the Mayor to cast the city's vote.",
                                      "Discuss and vote on a new procedure for agenda requests."])
    def test_more_prospective_agenda_wording(self, line):
        ct = _ct(["1.", line, "M/s Supervisor Alder - Supervisor Birch", "AYES: ALL"])
        ev = _event("vev-1", "expanded", [_span(ct, "M/s Supervisor Alder - Supervisor Birch"), _span(ct, "AYES: ALL")])
        [d] = [d for d in dispose(ct, scan(ct), [ev], attendance_spans=[]) if d["kind"] == "vote_word"]
        assert (d["class"], d["reason"]) == ("excluded", "agenda_description")

    @pytest.mark.parametrize("sentence", ["(Commissioner Fir absent at 4:30 p.m.)", "Applicant Ann Fir was absent."])
    def test_attendance_of_people_who_are_not_members(self, sentence):
        ct = _ct(["Item.", sentence])
        [d] = dispose(ct, scan(ct), [], attendance_spans=[])
        assert (d["class"], d["reason"]) == ("excluded", "non_member_attendance")

    def test_events_of_one_class_sharing_a_clause_share_the_disposition(self):
        ct = _ct(["COUNCIL ACTION: the council voted via roll call.", "AYES: ALDER", "AYES: BIRCH"])
        clause = ct.locate(0, ct.text.index("\n"))
        evs = [_event("vev-1", "held", [clause, _span(ct, "AYES: ALDER")]),
               _event("vev-2", "held", [clause, _span(ct, "AYES: BIRCH")])]
        out = [d for d in dispose(ct, scan(ct), evs, attendance_spans=[]) if d["kind"] == "vote_word"]
        assert [(d["class"], d["event_id"], d["evidence"]) for d in out] == [("held", "vev-1", ["vev-1", "vev-2"])]

    def test_completed_vote_wording_is_never_excluded_by_position(self):
        ct = _ct(["1.", "The council voted unanimously to reconsider.", "M/s Supervisor Alder - Supervisor Birch",
                  "AYES: ALL"])
        ev = _event("vev-1", "expanded", [_span(ct, "M/s Supervisor Alder - Supervisor Birch"),
                                          _span(ct, "AYES: ALL")])
        out = [d for d in dispose(ct, scan(ct), [ev], attendance_spans=[]) if d["kind"] in ("vote_word", "unanimous")]
        assert {(d["class"], d["reason"]) for d in out} == {("held", "narrative_vote_unaccounted")}

    def test_a_second_unlabelled_vote_in_an_item_with_an_event_is_held(self):
        ct = _ct(["I.  ITEM", "COUNCIL ACTION: approve. AYES: ALDER NOES: None",
                  "The council then voted unanimously to reconsider."])
        ev = _event("vev-1", "named", [ct.locate(0, ct.text.index("None") + 4)])
        out = [d for d in dispose(ct, scan(ct), [ev], attendance_spans=[]) if d["kind"] == "vote_word"]
        assert [(d["class"], d["reason"]) for d in out] == [("held", "narrative_vote_unaccounted")]

    def test_a_transcript_holds_every_candidate(self):
        ct = _ct(["CLERK: ALL IN FAVOR? AYES.", "ALDER SMITH: AYE. I VOTE YES."])
        out = dispose(ct, scan(ct), [], attendance_spans=[], transcript=True)
        assert out and {(d["class"], d["reason"]) for d in out} == {("held", "transcript_document")}


class TestPartition:
    def _world(self):
        ct = _ct(["AYES: ALDER", "NOES: None", "Item.", "AYES: BIRCH"])
        ev = _event("vev-1", "named", [_span(ct, "AYES: ALDER"), _span(ct, "NOES: None")])
        cands = scan(ct)
        return ct, cands, [ev], dispose(ct, cands, [ev], attendance_spans=[])

    def test_a_clean_partition_has_no_problems(self):
        _, cands, evs, disp = self._world()
        assert check_partition(cands, disp, evs) == []

    def test_a_missing_or_duplicated_disposition_is_a_problem(self):
        _, cands, evs, disp = self._world()
        assert check_partition(cands, disp[1:], evs)
        assert check_partition(cands, disp + disp[:1], evs)

    def test_an_unknown_class_or_event_or_a_class_mismatch_is_a_problem(self):
        _, cands, evs, disp = self._world()
        bad = [dict(disp[0], **{"class": "maybe"})] + disp[1:]
        assert check_partition(cands, bad, evs)
        bad = [dict(disp[0], event_id="vev-404")] + disp[1:]
        assert check_partition(cands, bad, evs)
        bad = [dict(disp[0], **{"class": "expanded"})] + disp[1:]
        assert check_partition(cands, bad, evs)

    def test_classes(self):
        assert CLASSES == ("named", "expanded", "held", "excluded")
