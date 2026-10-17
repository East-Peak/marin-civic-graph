"""Votes refresh, increment c: roster-change signals and holds. Fictional names and documents only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import votes_refresh_ledger as rl  # noqa: E402
from votes_text import CanonicalText  # noqa: E402

NOV, BOS = "novato-city-council", "marin-county-bos"


def _ct(*paragraphs):
    return CanonicalText.from_lines([line for p in paragraphs for line in (p, "")])


def _kinds(body, *paragraphs):
    return [(s["kind"], s["certainty"]) for s in rl.roster_signals(_ct(*paragraphs), body)]


class TestSignals:
    @pytest.mark.parametrize("text,kind", [
        ("Council appointed Morgan Alder to the council.", "appointment"),
        ("Morgan Alder resigned from the City Council effective June 1.", "resignation"),
        ("Morgan Alder was sworn in as a councilmember.", "oath"),
        ("The Council voted to appoint Morgan Alder as the City Councilmember for District 5.", "appointment"),
        ("The City Council appointed Morgan Alder to the council following resignation from the advisory "
         "commission.", "appointment"),
        ("The Council declared a vacancy on the City Council.", "vacancy"),
        ("Reorganization of the Council and oath of office for the newly elected councilmember Morgan Alder.",
         "oath"),
    ])
    def test_novato_changes_are_signals(self, text, kind):
        assert (kind, "certain") in _kinds(NOV, text)

    def test_codex_c_r1_cases(self):
        assert ("vacancy", "certain") in _kinds(NOV, "Morgan Alder vacated her City Council seat.")
        assert ("resignation", "uncertain") in _kinds(NOV, "Parks Commission report.", "Morgan Alder resigned.")
        assert _kinds(BOS, "Request to adopt a resolution to purchase the vacant land at B Street.") == []
        assert _kinds(BOS, "Request to appoint Pat Doe to the Golden Gate Bridge District.") == []
        assert _kinds(BOS, "M/s Supervisor Alder - Supervisor Birch to appoint Pat Doe, incumbent (At-Large), "
                           "and Lee Roe (District 2) to the First 5 Marin Children and Families Commission.") == []

    def test_codex_c_r2_cases(self):
        assert ("election", "uncertain") in _kinds(NOV, "Parks Commission report.", "Morgan Alder was elected.")
        assert ("resignation", "uncertain") in _kinds(NOV, "Appointments", "Morgan Alder resigned.")
        assert ("resignation", "certain") in _kinds(
            NOV, "Councilmember Morgan Alder resigned to take a job as director.")
        assert _kinds(NOV, "Morgan Alder resigned as director of the Parks Commission.") == []

    def test_codex_c_r3_cases(self):
        assert ("appointment", "uncertain") in _kinds(BOS, "Appointments", "Morgan Alder was appointed.")
        assert ("resignation", "uncertain") in _kinds(BOS, "Appointments",
                                                      "One vacancy due to the resignation of Morgan Alder.")
        assert ("appointment", "uncertain") in _kinds(NOV, "Parks Commission report.", "Morgan Alder was appointed.")
        assert ("resignation", "certain") in _kinds(
            NOV, "Councilmember Morgan Alder resigned after receiving an offer from the Parks Commission.")

    def test_codex_c_r4_case(self):
        assert ("resignation", "uncertain") in _kinds(BOS, "Appointments", "One vacancy due to the resignation of "
                                                      "Morgan Alder after receiving an offer from the Parks Commission.")
        text = CanonicalText.from_lines(["c. Appointments", "i. FCZ #4 One vacancy due to the resignation of Pat Doe.",
                                         "d. Next item."])
        assert rl.roster_signals(text, BOS, "html") == []

    def test_codex_c_r5_case(self):
        kinds = _kinds(BOS, "Appointments", "Morgan Alder received an offer from the Parks Commission. Discussion "
                       "followed. One vacancy due to the resignation of Morgan Alder.")
        assert ("resignation", "uncertain") in kinds and ("vacancy", "uncertain") in kinds

    def test_an_appointments_section_lists_other_bodies_seats(self):
        text = CanonicalText.from_lines([
            "CA-1. Board of Supervisors", "c. Appointments",
            "i. Integrated Pest Management One vacancy due to the resignation of Pat Doe (District 4).",
            "ii. Pat Roe was appointed.", "d. Request from Supervisor Alder to adopt a resolution.",
            "Morgan Alder was appointed."])
        got = [(x["kind"], x["certainty"], x["span"]["line_start"]) for x in rl.roster_signals(text, BOS, "html")]
        # the sub-item naming another body is that body's seat; "ii. Pat Roe was appointed." names none: held
        assert got == [("appointment", "uncertain", 4), ("appointment", "uncertain", 6)]

    def test_the_council_context_carries_into_the_next_sentence(self):
        assert ("appointment", "certain") in _kinds(
            NOV, "The City Council considered the vacant seat. Morgan Alder was appointed.")

    @pytest.mark.parametrize("paragraphs", [
        ("The City Council received reports. The Parks Commission appointed Morgan Alder.",),
        ("Morgan Alder resigned from the Parks Commission.",),
        ("The City Council heard the item. Morgan Alder resigned from the Library Committee.",),
        ("Staff reported a vacancy in the district 4 seat of the Sanitary District.",),
        ("The Council appointed Morgan Alder to the Parks Commission.",),
        ("Councilmember Alder was sworn in as Mayor.",),
        ("Approve the minutes of the meeting at which Morgan Alder resigned from the City Council.",),
        ("Public comment: Pat Speaker read a letter. “I resigned from the City Council in protest. It was the "
         "right thing to do.”",),
        ("Correspondence received. A resident wrote that Councilmember Alder should resign from the council.",),
    ])
    def test_unrelated_quoted_or_minutes_approval_text_is_not_a_signal(self, paragraphs):
        assert _kinds(NOV, *paragraphs) == []

    def test_quoted_resignation_spanning_two_sentences_is_not_a_signal(self):
        assert _kinds(NOV, "“Today I resign. I leave the City Council with gratitude,” the letter said.") == []

    def test_board_changes(self):
        assert ("oath", "certain") in _kinds(BOS, "Supervisor Alder (District 2) was sworn in.")
        assert _kinds(BOS, "The Board appointed Morgan Alder to the Commission on Aging.") == []
        assert ("resignation", "certain") in _kinds(BOS, "Supervisor Elm resigned from the Board of Supervisors.")
        assert ("resignation", "certain") in _kinds(BOS, "Morgan Alder resigned from the County Board of Supervisors.")
        assert _kinds(BOS, "Morgan Alder resigned from the Design Review Board.") == []

    def test_a_signal_with_no_resolvable_office_is_uncertain(self):
        assert _kinds(NOV, "Morgan Alder was appointed.") == [("appointment", "uncertain")]

    def test_signals_carry_their_excerpt_and_lines(self):
        s = rl.roster_signals(_ct("Item 4.", "Morgan Alder resigned from the City Council."), NOV)[0]
        assert s["excerpt"] == "Morgan Alder resigned from the City Council."
        assert s["span"]["line_start"] == 3


def _ev(eid, date, keys, status="named", roster=None):
    cats = {"aye": [{"name": k} for k in keys], "no": [], "absent": [], "recused": [], "abstain": []}
    return {"event_id": eid, "body": NOV, "meeting_id": "meeting-x", "date": date, "status": status,
            "categories": cats, "attendance": {"roster": roster if roster is not None else list(keys)},
            "doc_sha256": "d" * 64}


class _Resolver:
    terms = {(NOV, "ALDER"): ("2020-01-01", None), (NOV, "BIRCH"): ("2020-01-01", "2030-01-01")}

    def resolve(self, body, key, date):
        t = self.terms.get((body, key))
        if t is None:
            return ("held", "unknown_key")
        return ("ok", "p", "d") if t[0] <= date and (t[1] is None or date < t[1]) else ("held", "out_of_term")


class TestNameHolds:
    def test_a_roll_call_name_with_no_confirmed_term_is_a_hold(self):
        holds = rl.name_holds([_ev("e1", "2030-04-08", ["ALDER", "CEDAR"])], _Resolver(), NOV)
        assert [(h["kind"], h["key"], h["from_date"]) for h in holds] == [("name_without_term", "CEDAR", "2030-04-08")]

    def test_out_of_term_and_held_events_count_too(self):
        holds = rl.name_holds([_ev("e1", "2030-02-01", ["BIRCH"], status="held")], _Resolver(), NOV)
        assert [(h["key"], h["reason"]) for h in holds] == [("BIRCH", "out_of_term")]

    def test_attendance_roster_names_count(self):
        holds = rl.name_holds([_ev("e1", "2030-04-08", ["ALDER"], roster=["ALDER", "DOGWOOD"])], _Resolver(), NOV)
        assert [h["key"] for h in holds] == ["DOGWOOD"]


class TestEnforce:
    HOLD = {"hold_id": "hold-1", "body": NOV, "from_date": "2030-05-01"}

    def test_every_event_of_the_body_on_or_after_the_from_date_is_held(self):
        evs = [_ev("before", "2030-04-30", ["ALDER"]), _ev("on", "2030-05-01", ["ALDER"]),
               _ev("after", "2030-06-01", ["ALDER"]), {**_ev("bos", "2030-06-01", ["ALDER"]), "body": BOS}]
        assert rl.enforce_holds(evs, [self.HOLD]) == [
            {"event_id": "after", "reason": "hold-1", "rule": "roster_hold"},
            {"event_id": "on", "reason": "hold-1", "rule": "roster_hold"}]

    def test_resolved_holds_do_not_hold(self):
        assert rl.enforce_holds([_ev("on", "2030-05-01", ["ALDER"])], [{**self.HOLD, "resolved": True}]) == []


class TestHints:
    def test_a_member_absent_from_every_roll_call_is_a_hint(self):
        traces = {"meeting-x.aaaa": [{"kind": "roll_call", "present_after": ["ALDER"], "certain_after": True}]}
        out = rl.roster_hints(NOV, traces, open_keys=["ALDER", "BIRCH"])
        assert out == {"roll_calls": 1, "absent_from_all": ["BIRCH"], "evidence": "ok"}

    def test_zero_roll_calls_is_insufficient_evidence(self):
        out = rl.roster_hints(NOV, {"meeting-x.aaaa": [{"kind": "arrive", "member": "ALDER"}]}, open_keys=["ALDER"])
        assert out == {"roll_calls": 0, "absent_from_all": [], "evidence": "insufficient evidence"}
