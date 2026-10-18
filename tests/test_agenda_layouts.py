"""The `lettered` and `decimal` agenda layouts (scripts/agenda_parsers.py), on fictional fixtures.

`lettered` reads agendas with no CALL TO ORDER: numbered sections `N. Title:` with lettered items `a.` under them
(roman `i.` points are description), or lettered items under ALL-CAPS headings; the body runs from the first entry
to ADJOURNMENT. `decimal` reads `N. HEADING` sections with `N.M` items and `N.MA` sub-items, one or more sessions to
a document, each from `1. ROLL CALL` to its `N. ADJOURN…`. Fixtures: tests/fixtures/agendas/ (invented towns).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agenda_parsers as ap  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "agendas"


def _parse(name, parser):
    return ap.PARSERS[parser].parse((FIXTURES / name).read_text(encoding="utf-8"))


def _items(parsed):
    return [(i["key"], i["heading"], i["title"]) for i in parsed["items"]]


def _reason(parser, text):
    with pytest.raises(ap.Unparseable) as exc:
        ap.PARSERS[parser].parse(text)
    return exc.value.reason


def test_both_layouts_are_registered():
    assert (ap.PARSERS["lettered"].version, ap.PARSERS["decimal"].version) == (2, 1)


# --- lettered ----------------------------------------------------------------------------------------------


def test_lettered_reads_numbered_sections_with_lettered_items():
    parsed = _parse("lettered-regular.txt", "lettered")
    assert parsed["printed_date"] == "2026-03-10" and parsed["notice"] is None
    assert "HARBORVIEW CITY COUNCIL" in parsed["header"] and "OPEN TIME" not in parsed["header"]
    assert _items(parsed) == [
        ("1", "", "City Manager and Councilmember Reports:"),
        ("2a", "Consent Calendar Items", "Approval of Minutes"),
        ("2b", "Consent Calendar Items", "Pier Lane Interim Parking Lot"),
        ("2c", "Consent Calendar Items", "First Amendment to the Professional Services Agreement with Ferris-Blake "
                                         "and Associates, Inc. for Final Design of the Cove Avenue Path"),
        ("2d", "Consent Calendar Items", "Training on Meetings, Records and Conflicts of Interest for Local "
                                         "Officials (CA)"),
        ("3a", "Public Hearings", "Amendments to the Harbor Code Related to Mooring Fees and Dock Permit"),
        ("3b", "Public Hearings", "Appeal of Planning Commission Approval for a Mixed-Use Building on Wharf Street "
                                  "(Also Known As the Old Cannery Project)"),
        ("ha1a", "Consent Calendar", "Successor Agency Quarterly Investment Report"),
    ]
    item = parsed["items"][1]
    assert (item["label"], item["section_number"], item["item_number"]) == ("2.a", "2", "A")
    agency = parsed["items"][-1]
    assert (agency["section_number"], agency["item_number"]) == ("HA1", "A")


def test_lettered_roman_points_are_the_items_description():
    keys = [i["key"] for i in _parse("lettered-regular.txt", "lettered")["items"]]
    assert "3i" not in keys and "3c" not in keys


def test_lettered_ninth_letter_is_a_letter_but_a_roman_list_is_not():
    letters = "".join(f"   {c}. Item {c.upper()}\n" for c in "abcdefgh")
    text = f"AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n1. Consent Calendar Items:\n{letters}" \
           "   i. Item I\n   j. Item J\n2. Other Agenda Items:\n   a. Housing Grants\n      i. Grant one\n" \
           "      ii. Grant two\nADJOURNMENT:\n"
    keys = [i["key"] for i in ap.PARSERS["lettered"].parse(text)["items"]]
    assert keys == [f"1{c}" for c in "abcdefghij"] + ["2a"]


def test_lettered_closed_session_with_a_top_level_leaf():
    parsed = _parse("lettered-closed.txt", "lettered")
    assert parsed["printed_date"] == "2026-04-06"
    assert "OPEN SESSION" not in parsed["header"]  # a heading is body, not header evidence
    assert _items(parsed) == [
        ("1", "", "Mayor Reyes to announce Closed Session items."),
        ("2a", "Closed Session", "CONFERENCE WITH LEGAL COUNSEL – ANTICIPATED LITIGATION, pursuant to "
                                 "Government Code Section 54956.9(d)(2): One potential claim."),
        ("2b", "Closed Session", "CONFERENCE WITH LEGAL COUNSEL—EXISTING LITIGATION, pursuant to "
                                 "Government Code Section 54956.9(d)(1)"),
    ]


def test_lettered_items_under_headings_take_the_headings_abbreviation():
    parsed = _parse("lettered-unnumbered.txt", "lettered")
    assert parsed["printed_date"] == "2020-09-14"
    assert [(i["key"], i["section_number"], i["item_number"], i["heading"]) for i in parsed["items"]] == [
        ("opa", "OP", "A", "Open Session"), ("cla", "CL", "A", "Closed Session"), ("clb", "CL", "B", "Closed Session")]


def test_lettered_items_under_no_heading_are_general():
    parsed = _parse("lettered-study.txt", "lettered")
    assert parsed["printed_date"] == "2021-02-17"
    assert _items(parsed) == [
        ("gea", "", "Training on Legal Matters Affecting Public Officials: Meetings, Records, Conflicts of Interest "
                    "and Compensation"),
        ("geb", "", "Training on the Role of Elected Officials in Disaster Operations"),
        ("gec", "", "City Council Discussion on Councilmember Appointments to Committees"),
    ]


def test_lettered_two_sessions_hold():
    assert _reason("lettered", (FIXTURES / "lettered-two-sessions.txt").read_text()) == "multi_session_agenda"


def test_lettered_a_second_numbered_run_with_items_holds_unless_its_all_none():
    head = "AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n"
    one = f"{head}1. None.\n2. Closed Session: - None.\n3. Reports:\nOTHER BUSINESS\n1. Other Agenda Items:\n" \
          "   a. Budget Study\nADJOURNMENT:\n"
    assert _reason("lettered", one) == "multi_session_agenda"
    fine = f"{head}1. Reports:\nHARBORVIEW SUCCESSOR AGENCY:\n1. Consent Calendar: - None.\nADJOURNMENT:\n"
    assert _items(ap.PARSERS["lettered"].parse(fine)) == [("1", "", "Reports:")]


def test_lettered_letter_only_sessions_on_one_document_hold():
    text = "AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n      SPECIAL MEETING AT 4:00 P.M.\n" \
           "STUDY SESSION\n   a. Waterfront Plan\n                REGULAR MEETING AT 6:00 P.M.\nCONSENT\n" \
           "   a. Minutes\nADJOURNMENT:\n"
    assert _reason("lettered", text) == "multi_session_agenda"


def test_lettered_another_agenda_after_the_end_holds_but_minutes_do_not():
    body = "AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n1. Reports:\nADJOURNMENT:\n"
    assert _reason("lettered", body + "\n                AGENDA\nHARBORVIEW CITY COUNCIL - MAY 5, 2026\n"
                                      "1. Other:\nADJOURNMENT:\n") == "multi_session_agenda"
    minutes = body + "MINUTES\nHARBORVIEW CITY COUNCIL - APRIL 20, 2026\n1. Reports:\n   a. Item\nADJOURNMENT:\n"
    assert [i["key"] for i in ap.PARSERS["lettered"].parse(minutes)["items"]] == ["1"]


def test_lettered_a_ceremony_with_only_bullets_has_no_items():
    text = "AGENDA\nHARBORVIEW CITY COUNCIL SPECIAL MEETING\nWEDNESDAY, MAY 15, 2024 AT 4:30 P.M.\n" \
           "     • 4:30 PM - Community Socializing\n     • 6:00 PM - Awards\nAny records relating to an agenda item.\n"
    parsed = ap.PARSERS["lettered"].parse(text)
    assert parsed["items"] == [] and parsed["notice"] is None and parsed["printed_date"] == "2024-05-15"


def test_lettered_a_document_without_an_agenda_title_is_not_an_agenda():
    report = "                    HARBORVIEW CITY COUNCIL AGENDA REPORT\nMeeting Date: September 8, 2026\n" \
             "OPTIONS:\n   1. Make appointments.\n   2. Continue recruitment.\nADJOURNMENT:\n"
    assert _reason("lettered", report) == "unparseable"
    email = "From: A Resident\nSent: Sunday, May 3, 2026 1:48 PM\nSubject: comment\nHi City Council,\n"
    assert _reason("lettered", email) == "unparseable"


def test_lettered_cancellation_notice_is_a_notice():
    parsed = _parse("cancellation.txt", "lettered")
    assert parsed["notice"] == "cancellation" and parsed["items"] == []


def test_lettered_without_an_adjournment_holds():
    assert _reason("lettered", "AGENDA\nHARBORVIEW CITY COUNCIL - MAY 4, 2026\n1. Reports:\n") == "agenda_end_missing"


# --- decimal -----------------------------------------------------------------------------------------------


def test_decimal_reads_sections_items_and_sub_items():
    parsed = _parse("decimal-regular.txt", "decimal")
    assert parsed["printed_date"] == "2026-02-18" and parsed["notice"] is None and parsed["sessions"] == 1
    assert "Willow Bay City Council" in parsed["header"]
    assert _items(parsed) == [
        ("2", "", "PUBLIC COMMENT (Only for matters not listed on the agenda)"),
        ("41", "Approval Of The Consent Calendar", "Approve warrants."),
        ("42", "Approval Of The Consent Calendar", "Approve minutes of the February 4, 2026, regular meeting."),
        ("43", "Approval Of The Consent Calendar", "Adopt Resolution 10/26 acknowledging receipt of a report made by "
                                                   "the Fire Chief regarding inspection of certain occupancies "
                                                   "(SB 1205)."),
        ("5", "", "CITY MANAGER’S ORAL REPORT"),
        ("6", "", "COUNCILMEMBERS’ ORAL REPORTS AND COMMENTS"),
        ("71a", "Public Hearings", "PARKS SPECIAL EVENT FEES"),
        ("71b", "Public Hearings", "PICNIC AREA FEES"),
        ("72", "Public Hearings", "RESOLUTION 13/26, ADOPTING UPDATED TRAFFIC IMPACT THRESHOLDS, LEVEL OF SERVICE "
                                  "(LOS) to VEHICLE MILES TRAVELLED (VMT) 18.23 (ACCESSORY DWELLING UNITS) AND 18.24 "
                                  "(JUNIOR UNITS)"),
        ("81a", "Business Items", "INTRODUCTION OF ORDINANCE 1101"),
        ("81b", "Business Items", "SECOND READING OF ORDINANCE 1100"),
        ("82", "Business Items", "Review of Fee Policy for Encroachment Permits for Commercial Outdoor Dining Use and "
                                 "direction to staff."),
    ]
    sub = parsed["items"][6]
    assert (sub["label"], sub["section_number"], sub["item_number"]) == ("7.1A", "7", "1A")


def test_decimal_two_sessions_prefix_their_keys_with_the_session():
    parsed = _parse("decimal-two-sessions.txt", "decimal")
    assert parsed["printed_date"] == "2024-02-07" and parsed["sessions"] == 2
    assert _items(parsed) == [
        ("special21", "Closed Session", "CONFERENCE WITH LEGAL COUNSEL – ANTICIPATED LITIGATION"),
        ("regular31", "Closed Session", "CONFERENCE WITH LABOR NEGOTIATORS"),
        ("regular41", "Approval Of The Consent Calendar", "Approve warrants."),
        ("regular42", "Approval Of The Consent Calendar", "Approve minutes of the January 17, 2024, regular meeting."),
    ]


_HEAD = ("SPECIAL MEETING of the Willow Bay City Council\nWednesday, March 18, 2020: 6:00 p.m.\n"
         "SPECIAL MEETING 6:00 P.M.\n1. ROLL CALL\n2. BUSINESS\n   2.1 Hear a report.\n3. ADJOURN\n"
         "Regular Meeting: April 1, 2020\n")


def _second(masthead, kind="REGULAR"):
    return _HEAD + masthead + f"{kind} MEETING 6:30 P.M.\n1. ROLL CALL\n2. PUBLIC COMMENT\n3. ADJOURN\n"


def test_decimal_a_later_masthead_must_print_the_same_date_and_body():
    same = "REGULAR MEETING of the Willow Bay City Council\nWednesday, March 18, 2020: 6:30 p.m.\n"
    parsed = ap.PARSERS["decimal"].parse(_second(same))  # the footer's April 1 is not a masthead
    assert [i["key"] for i in parsed["items"]] == ["special21", "regular2"] and parsed["sessions"] == 2
    other_day = "REGULAR MEETING of the Willow Bay City Council\nWednesday, March 25, 2020: 6:30 p.m.\n"
    assert _reason("decimal", _second(other_day)) == "multi_session_agenda"
    other_body = "REGULAR MEETING of the Willow Bay Planning Commission\nWednesday, March 18, 2020: 6:30 p.m.\n"
    assert _reason("decimal", _second(other_body)) == "multi_session_agenda"


def test_decimal_sessions_must_be_told_apart():
    assert _reason("decimal", _second("", kind="SPECIAL")) == "multi_session_agenda"


def test_decimal_attached_minutes_are_not_a_session():
    minutes = "MINUTES OF THE REGULAR MEETING of the Willow Bay City Council\n1. ROLL CALL\n2. VOTES\n3. ADJOURN\n"
    parsed = ap.PARSERS["decimal"].parse(_HEAD + "Speakers have 3 minutes each.\n" + minutes)
    assert [i["key"] for i in parsed["items"]] == ["21"] and parsed["sessions"] == 1


def test_decimal_a_restart_before_the_adjournment_holds():
    text = "SPECIAL MEETING of the Willow Bay City Council\nMarch 18, 2020\nSPECIAL MEETING\n1. ROLL CALL\n" \
           "2. BUSINESS\nREGULAR MEETING\n1. ROLL CALL\n2. ADJOURN\n"
    assert _reason("decimal", text) == "multi_session_agenda"


def test_decimal_adjourn_to_closed_session_inside_a_session_is_a_leaf():
    text = "REGULAR MEETING of the Willow Bay City Council\nMarch 18, 2020\nREGULAR MEETING\n1. ROLL CALL\n" \
           "2. ADJOURN TO CLOSED SESSION\n3. CLOSED SESSION\n   3.1 CONFERENCE WITH COUNSEL\n4. ADJOURN\n"
    assert [i["key"] for i in ap.PARSERS["decimal"].parse(text)["items"]] == ["31"]


def test_decimal_the_public_comment_preamble_is_header():
    parsed = _parse("decimal-regular.txt", "decimal")
    assert "1. Emailing" in parsed["header"] and all(not i["title"].startswith("Emailing") for i in parsed["items"])


def test_decimal_without_a_session_start():
    assert _parse("cancellation.txt", "decimal")["notice"] == "cancellation"
    assert _reason("decimal", "Willow Bay City Council\nA staff report.\n") == "unparseable"
    assert _reason("decimal", "Wednesday, March 18, 2020\nREGULAR MEETING\n1. ROLL CALL\n2. ITEM\n") \
        == "agenda_end_missing"


def test_decimal_a_capitals_title_stops_before_a_lettered_list():
    text = "REGULAR MEETING of the Willow Bay City Council\nMarch 18, 2020\nREGULAR MEETING\n1. ROLL CALL\n" \
           "2. BUSINESS ITEMS\n   2.1 WINTER STORM PREPARATIONS\n       A. DECLARATION OF LOCAL EMERGENCY\n" \
           "       B. BUDGET IMPACTS\n3. ADJOURN\n"
    assert [i["title"] for i in ap.PARSERS["decimal"].parse(text)["items"]] == ["WINTER STORM PREPARATIONS"]


def test_lettered_unparented_letters_restarting_after_a_session_title_hold():
    text = "AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n   a. First session business\n" \
           "                REGULAR MEETING AT 6:00 P.M.\n   a. Second session business\nADJOURNMENT:\n"
    assert _reason("lettered", text) == "multi_session_agenda"


def test_decimal_a_minutes_document_is_not_an_agenda():
    text = "MINUTES OF THE REGULAR MEETING of the Willow Bay City Council\nWednesday, March 18, 2020\n" \
           "1. ROLL CALL\n2. BUSINESS ITEMS\n   2.1 Approved a contract.\n3. ADJOURN\n"
    assert _reason("decimal", text) == "unparseable"


def test_lettered_an_empty_first_run_does_not_make_a_second_session():
    text = "AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n1. Closed Session: - None.\nREGULAR SESSION\n" \
           "1. Reports:\n   a. Budget Study\nADJOURNMENT:\n"
    assert [i["key"] for i in ap.PARSERS["lettered"].parse(text)["items"]] == ["1a"]


def test_lettered_a_title_stops_before_roman_points():
    text = "AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n1. Public Hearings:\n" \
           "   a. Amendments to the Parking Code\n     i.  Ordinance Repealing Chapter 4.10\n     ii. Ordinance Two\n" \
           "ADJOURNMENT:\n"
    assert [i["title"] for i in ap.PARSERS["lettered"].parse(text)["items"]] == ["Amendments to the Parking Code"]


@pytest.mark.parametrize("parser, text, title", [
    ("decimal", "REGULAR MEETING of the Willow Bay City Council\nMarch 18, 2020\nREGULAR MEETING\n1. ROLL CALL\n"
                "2. HEARINGS\n   2.1 ADOPT ORDINANCE 9 FOR THE PREVENTION OF\n\fSTRUCTURE FIRES\n3. ADJOURN\n",
     "ADOPT ORDINANCE 9 FOR THE PREVENTION OF STRUCTURE FIRES"),
    ("lettered", "AGENDA\nHARBORVIEW CITY COUNCIL - MONDAY, MAY 4, 2026\n1. Consent:\n   a. Contract with Gull and\n"
                 "\f      Tern Builders\nADJOURNMENT:\n", "Contract with Gull and Tern Builders"),
])
def test_a_page_break_is_not_a_blank_line(parser, text, title):
    assert [i["title"] for i in ap.PARSERS[parser].parse(text)["items"]] == [title]



def test_lettered_a_council_masthead_with_a_session_line_is_an_agenda_title():
    parsed = _parse("lettered-council-masthead.txt", "lettered")
    assert parsed["printed_date"] == "2026-10-19" and "Special Closed Session" in parsed["header"]
    assert _items(parsed) == [
        ("1", "", "Mayor Reyes to announce Closed Session items."),
        ("2a", "Closed Session", "CONFERENCE WITH LEGAL COUNSEL—EXISTING LITIGATION, pursuant to Government Code "
                                 "Section 54956.9(d)(1)"),
        ("2b", "Closed Session", "CONFERENCE WITH LEGAL COUNSEL – ANTICIPATED LITIGATION, pursuant to Government "
                                 "Code Section 54956.9(d)(4): one potential case"),
    ]


@pytest.mark.parametrize("head", [
    "HARBORVIEW CITY COUNCIL AGENDA REPORT\nMeeting Date: May 4, 2026\n",  # a staff report
    "HARBORVIEW CITY COUNCIL\nMINUTES\nMonday, May 4, 2026\n",  # minutes under the council's name
    "MINUTES\nHARBORVIEW CITY COUNCIL\nSpecial Closed Session\nMonday, May 4, 2026\n",  # not its first line
    "Harborview City Council\nSpecial Closed Session\nMonday, May 4, 2026\n",  # not in capitals
])
def test_lettered_only_a_councils_capital_masthead_and_session_line_stand_for_an_agenda_title(head):
    assert _reason("lettered", head + "OPEN SESSION\n   1. Announcements.\nADJOURNMENT:\n") == "unparseable"
