"""Agenda text -> items (scripts/agenda_parsers.py), on fictional fixtures copying the real layouts.

`outline` reads numbered agendas with lettered sub-entries (CivicPlus-style `4.A.`, `3A.`, `4.C.Motion`, indented bare
`A.`/`a.`, and `(1)` under a letter): the body runs from the CALL TO ORDER line to the top-level ADJOURN(MENT);
items are the leaves; a numbered list inside a description is text, not entries. `flat` reads agendas whose items
are numbered under unnumbered headings, several sessions to a document. Titles follow the reviewer brief's
mechanical rule. Fixtures: tests/fixtures/agendas/ (invented towns and people).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agenda_parsers as ap  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "agendas"


def _parse(name, parser="outline"):
    return ap.PARSERS[parser].parse((FIXTURES / name).read_text(encoding="utf-8"))


def _items(parsed):
    return [(i["key"], i["heading"], i["title"]) for i in parsed["items"]]


def test_outline_reads_a_civicplus_agenda():
    parsed = _parse("outline-civicplus.txt")
    assert parsed["printed_date"] == "2019-12-03" and parsed["notice"] is None
    assert "Town Council" in parsed["header"]
    assert _items(parsed) == [
        ("2", "", "OPEN TIME FOR PUBLIC COMMENT"),
        ("4a", "Consent Calendar",
         "Authorize Introduction and/or Adoption of Resolutions and Ordinances by Title Only."),
        ("4b", "Consent Calendar", "Approve Cancellation of January 7, 2020 Regular Town Council Meeting"),
        ("4c", "Consent Calendar", "Approve Annual Listing Of Expiring Terms On Town Boards, Commissions and "
                                   "Committees During 2020"),
        ("5a", "Public Hearings", "Public Hearing to Consider Adoption of Ordinance No. 990 Repealing, Reenacting, "
                                  "and Adding Various Chapters in Title 15 of the Municipal Code"),
        ("6a", "Business Items", "Discussion and Direction to Staff Regarding a Committee on Shoreline Trails"),
        ("7", "", "TOWN MANAGER AND COUNCIL REPORTS"),
        ("8a", "Review Of Draft Agenda For Upcoming Town Council Meeting",
         "Review of Draft Agenda for December 17, 2019 Town Council Meeting"),
    ]
    first = parsed["items"][1]
    assert (first["label"], first["section_number"], first["item_number"]) == ("4.A", "4", "A")
    assert (parsed["items"][0]["section_number"], parsed["items"][0]["item_number"]) == ("2", "")


def test_outline_skips_a_numbered_preamble_and_keeps_an_adjourn_section():
    parsed = _parse("outline-preamble.txt")
    assert parsed["printed_date"] == "2026-06-02"
    assert _items(parsed) == [
        ("2", "", "PUBLIC COMMENT REGARDING CLOSED SESSION ITEM Public Comment Received for item 3.A."),
        ("3a", "Adjourn To Closed Session Regarding The Following Item",
         "CONFERENCE WITH LEGAL COUNSEL—EXISTING LITIGATION Name of case: (Pell v. Town of Lakeport)"),
        ("4", "", "RECONVENE IN OPEN SESSION AND REPORT OUT OF CLOSED SESSION"),
    ]


def test_outline_reads_number_letter_labels_and_ignores_lists_inside_descriptions():
    parsed = _parse("outline-3a.txt")
    assert [i["key"] for i in parsed["items"]] == ["2", "3a", "3b", "3c", "4"]
    assert parsed["items"][1]["title"] == "Review of 2018-2019 Work Plan and Accomplishments"
    assert parsed["items"][2]["title"] == ("The Town Manager will guide the Town Council through discussions to set "
                                           "priorities for projects and workload through the 2020-21 fiscal year "
                                           "Ongoing and anticipated discussion items include:")
    assert parsed["items"][3]["title"] == "Discussion Regarding Councilmember Committee Appointments."


def test_outline_reads_bare_letters_and_a_third_level():
    parsed = _parse("outline-bare-letters.txt")
    assert parsed["printed_date"] == "2026-04-13"
    assert [(i["label"], i["key"]) for i in parsed["items"]] == [
        ("2.A", "2a"), ("2.C.(1)", "2c1"), ("2.C.(2)", "2c2"), ("2.D", "2d"), ("3.A", "3a"), ("3.B", "3b"),
        ("4.A", "4a"), ("4.B", "4b"), ("4.C", "4c"), ("5.A", "5a"), ("6", "6")]
    by = {i["key"]: i for i in parsed["items"]}
    assert by["2c1"]["title"] == "CONFERENCE WITH LABOR NEGOTIATOR (Government Code § 54957.6)"
    assert (by["2c1"]["section_number"], by["2c1"]["item_number"], by["2c1"]["heading"]) == ("2", "C1", "Closed Session")
    assert by["2d"]["title"] == ("RECONVENE IN OPEN SESSION AND ANNOUNCE ACTIONS TAKEN IN CLOSED SESSION, "
                                 "AS REQUIRED")
    assert by["4c"]["title"] == "Motion to Approve the Minutes of the March 9, 2026 Regular City Council Meeting"
    assert by["5a"]["title"] == ("Discussion and Action to Award the Seawall Construction Contract to Gordon "
                                 "N. Ball Construction, Inc. in the Amount of $3,511,621")


def test_outline_reads_indented_lower_case_letters():
    parsed = _parse("outline-ross.txt")
    assert parsed["printed_date"] == "2025-11-13" and "Regular Meeting" in parsed["header"]
    assert [(i["label"], i["title"]) for i in parsed["items"]] == [
        ("2", "Posting of agenda/changes to agenda."),
        ("3", "Disclosure of Ex Parte Communications on Items on this Agenda Councilmembers may disclose any "
              "meetings or correspondence. This is for transparency only."),
        ("4", "Open Time for Public Expression."),
        ("5", "Town Council to receive presentation of the plaque for Age Friendly Lakeport. (Fenn, Doyle)"),
        ("6", "Mayor's Report."),
        ("7.a", "Lakeport Property Owners Association"),
        ("7.b", "Town Manager"),
        ("8.a", "Minutes:"),
        ("8.b", "Demands: September and October 2025 End of Consent Agenda."),
        ("9", "Town Council consideration of the introduction and first reading of Ordinance No. 735 to ban the "
              "sale of tobacco products in the Town of Lakeport. (Garza)"),
        ("10", "Meeting Evaluation."),
    ]
    assert parsed["items"][5]["item_number"] == "A" and parsed["items"][5]["key"] == "7a"


def test_outline_starts_at_an_unnumbered_call_to_order_and_ends_at_an_unnumbered_adjourn():
    parsed = _parse("outline-unnumbered-call.txt")
    assert parsed["printed_date"] == "2021-11-29"
    assert [i["key"] for i in parsed["items"]] == ["1", "2"]


def test_outline_ignores_minutes_attached_after_the_agenda():
    assert [i["key"] for i in _parse("outline-packet-minutes.txt")["items"]] == ["2a"]


def test_outline_holds_a_document_with_two_sessions():
    with pytest.raises(ap.Unparseable) as exc:
        _parse("outline-multi-session.txt")
    assert exc.value.reason == "multi_session_agenda"


def test_outline_holds_an_agenda_without_an_end():
    with pytest.raises(ap.Unparseable) as exc:
        _parse("outline-no-end.txt")
    assert exc.value.reason == "agenda_end_missing"


@pytest.mark.parametrize("parser", ["outline", "flat"])
def test_a_cancellation_notice_is_a_notice(parser):
    parsed = _parse("cancellation.txt", parser)
    assert parsed["notice"] == "cancellation" and parsed["items"] == []


@pytest.mark.parametrize("parser", ["outline", "flat"])
def test_text_without_a_call_to_order_is_unparseable(parser):
    with pytest.raises(ap.Unparseable) as exc:
        ap.PARSERS[parser].parse("RESOLUTION NO. 12\nA resolution of the Town Council adopting a budget.\n")
    assert exc.value.reason == "unparseable"


def test_flat_reads_every_session_with_its_headings():
    parsed = _parse("flat-sessions.txt", "flat")
    assert parsed["printed_date"] == "2022-07-06"
    assert [(i["key"], i["section_number"], i["item_number"], i["heading"]) for i in parsed["items"]] == [
        ("ge1", "GE", "1", ""), ("ge2", "GE", "2", ""), ("pr1", "PR", "1", "Presentations"),
        ("co2", "CO", "2", "Consent Calendar"), ("co3", "CO", "3", "Consent Calendar"),
        ("pu4", "PU", "4", "Public Hearings")]
    assert parsed["items"][0]["title"] == ("Interview applicant Lee Moss and consider her appointment to the Parks "
                                           "and Recreation Commission (PARC) – Town Clerk")
    assert parsed["items"][-1]["title"] == ("Adopt a Resolution Establishing Maximum Rates for Solid Waste Services "
                                            "to be Effective January 1, 2023 – Public Works Director")


def test_flat_reads_the_2026_layout():
    parsed = _parse("flat-2026.txt", "flat")
    assert parsed["printed_date"] == "2026-08-20"
    assert _items(parsed) == [("re1", "Regular Agenda", "Pesticide Ordinance Exemption Request (~30 minutes)")]


def test_flat_holds_an_agenda_without_an_end():
    with pytest.raises(ap.Unparseable) as exc:
        ap.PARSERS["flat"].parse("Thursday, August 20, 2026\n3:00 PM – CALL TO ORDER\nREGULAR AGENDA\n1. Item\n")
    assert exc.value.reason == "agenda_end_missing"


def test_title_rule_stops_at_attachments_recommendations_bullets_and_blank_lines():
    lines = ["Approve the thing", "and the other thing", "", "more"]
    assert ap.title_of(lines, "4.A") == "Approve the thing and the other thing"
    assert ap.title_of(["Approve", "Recommendation: approve"], "4.A") == "Approve"
    assert ap.title_of(["Approve", "4.A. Staff Report and Attachments"], "4.A") == "Approve"
    assert ap.title_of(["Approve", "minutes of May.pdf"], "4.A") == "Approve"
    assert ap.title_of(["Approve", "•   Public Comment 1"], "4.A") == "Approve"
    assert ap.title_of(["Approve  the   minutes "], "4.A") == "Approve the minutes"


def test_every_parser_has_a_version():
    assert {name: p.version for name, p in ap.PARSERS.items()} == {"outline": 2, "flat": 1}


def test_a_list_in_a_description_that_happens_to_continue_the_numbering_is_not_an_entry():
    text = (FIXTURES / "outline-3a.txt").read_text()
    assert "           4. Communication" in text  # deeper than the agenda's own top-level entries
    assert [i["key"] for i in ap.parse_outline(text)["items"]] == ["2", "3a", "3b", "3c", "4"]


def test_a_call_to_order_mentioned_in_an_attached_manual_is_not_a_second_session():
    text = (FIXTURES / "outline-packet-minutes.txt").read_text().split("                              DRAFT MINUTES")[0]
    text += "            TABLE OF CONTENTS\n          6.1 Call to Order ......... 10\n     l. Call to Order and Salute\n"
    assert [i["key"] for i in ap.parse_outline(text)["items"]] == ["2a"]


def test_sub_entries_printed_with_a_parenthesis():
    text = ("Wednesday, June 24, 2026\n1. Call to Order.\n2. Consideration of three matters:\n"
            "   A) The first matter.\n   B) The second matter.\n3. Adjournment.\n")
    assert [(i["label"], i["title"]) for i in ap.parse_outline(text)["items"]] == [
        ("2.A", "The first matter."), ("2.B", "The second matter.")]


def test_a_second_session_starting_inside_the_body_holds():
    with pytest.raises(ap.Unparseable) as exc:
        _parse("outline-two-sessions-one-adjourn.txt")
    assert exc.value.reason == "multi_session_agenda"


def test_an_entry_with_none_on_the_line_below_is_no_item():
    assert [i["key"] for i in _parse("outline-none-below.txt")["items"]] == ["2"]
