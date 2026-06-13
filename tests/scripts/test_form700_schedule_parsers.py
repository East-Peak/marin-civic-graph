"""Tests for scripts/form700_schedule_parsers.py (M4, Unit 4).

Pure schedule parsers over staged Form 700 PDFs (column-cropped pdftotext, the
only process boundary). Each schedule's golden ground truths come from the goal
doc's staging record — never re-derived by reading the PDF and ratifying the
parser. Local-only filings (216262973 Werby, 215754761 Holm) carry residential
addresses/APNs in Schedule B / A-2 part-4 and are gitignored; their golden tests
skipif when the PDF is absent. The ethics scans (street-address/APN absence,
tenant non-extraction) live in the e2e (Unit 6); here we pin counts/types/
counterparties/bands.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from form700_schedule_parsers import (  # noqa: E402
    find_schedule_pages,
    parse_cover,
    parse_schedule_a1,
    parse_schedule_a2,
    parse_schedule_b,
    parse_schedule_c,
    parse_schedule_d,
    parse_schedule_e,
)

INTERIORS = REPO_ROOT / "tests" / "fixtures" / "form700" / "interiors"
JONES = INTERIORS / "216307037" / "document.pdf"
FUSENIG = INTERIORS / "216034157" / "document.pdf"
ALDEN = INTERIORS / "216872504" / "document.pdf"
LARA = INTERIORS / "215774405" / "document.pdf"
WERBY = INTERIORS / "216262973" / "document.pdf"  # local-only
HOLM = INTERIORS / "215754761" / "document.pdf"   # local-only
werby_only = pytest.mark.skipif(not WERBY.is_file(), reason="local-only PDF absent")
holm_only = pytest.mark.skipif(not HOLM.is_file(), reason="local-only PDF absent")


class TestFindSchedulePages:
    def test_jones_schedule_pages(self):
        pages = find_schedule_pages(JONES)
        assert pages["A-1"] == [2]
        assert pages["A-2"] == [3]
        assert pages["C"] == [4]
        assert "B" not in pages and "D" not in pages and "E" not in pages

    @werby_only
    def test_werby_multi_page_schedules(self):
        pages = find_schedule_pages(WERBY)
        assert pages["A-1"] == [2, 3, 4, 5]
        assert pages["A-2"] == [6, 7, 8, 9, 10, 11]
        assert pages["B"] == [12, 13]
        assert pages["C"] == [15, 16, 17, 18]
        assert pages["D"] == [19]


class TestScheduleA1:
    def test_jones_a1_two_investments_in_document_order(self):
        lines = parse_schedule_a1(JONES, [2])
        assert [ln["counterparty_name_raw"] for ln in lines] == [
            "NVidia",
            "Monolithic Power Systems (MPS)",
        ]
        assert all(ln["interest_type"] == "investment" for ln in lines)
        assert lines[0]["amount_band"] == "$2,000 - $10,000"
        assert lines[1]["amount_band"] == "$100,001 - $1,000,000"
        # acquired dates are envelope-only, never on the node.
        assert lines[0]["envelope"].get("acquired") == "08/29/25"

    @werby_only
    def test_werby_a1_21_investments_exact_order_and_bands(self):
        lines = parse_schedule_a1(WERBY, [2, 3, 4, 5])
        names_bands = [(ln["counterparty_name_raw"], ln["amount_band"]) for ln in lines]
        assert names_bands == [
            ("Bank of America", "$2,000 - $10,000"),
            ("Docusign Inc.", "$2,000 - $10,000"),
            ("Amazon", "$10,001 - $100,000"),
            ("Target Corp", "$10,001 - $100,000"),
            ("Manpower Group", "$10,001 - $100,000"),
            ("Mariners Island Investors", "$100,001 - $1,000,000"),
            ("Costco Wholesale Co.", "$10,001 - $100,000"),
            ("Alibaba Group Holding", "$10,001 - $100,000"),
            ("Carillon Associates", "Over $1,000,000"),
            ("Grosvenor Gibraltar Associates", "$100,001 - $1,000,000"),
            ("Tyler Technologies", "$10,001 - $100,000"),
            ("Badger Meter", "$2,000 - $10,000"),
            ("Village Green Associates", "$100,001 - $1,000,000"),
            ("Insperity Inc.", "$10,001 - $100,000"),
            ("Park Hotels and Resorts", "$100,001 - $1,000,000"),
            ("RCM Technologies Inc.", "$10,001 - $100,000"),
            ("Myriad Genetics Inc.", "$10,001 - $100,000"),
            ("Grosvenor Sonoma Associates", "$100,001 - $1,000,000"),
            ("Ventas Inc.", "$100,001 - $1,000,000"),
            ("USO", "$100,001 - $1,000,000"),
            ("General Motors Company", "$100,001 - $1,000,000"),
        ]
        assert len(lines) == 21
        assert all(ln["interest_type"] == "investment" for ln in lines)


class TestScheduleD:
    @werby_only
    def test_werby_d_one_node_per_gift(self):
        lines = parse_schedule_d(WERBY, find_schedule_pages(WERBY)["D"])
        assert [(ln["counterparty_name_raw"], ln["amount"]) for ln in lines] == [
            ("HarbourVest", "20.00"),
            ("HarbourVest", "30.25"),
            ("Aristotle", "20.00"),
            ("Aristotle", "30.25"),
        ]
        assert all(ln["interest_type"] == "gift" for ln in lines)
        assert all(ln["amount_band"] is None for ln in lines)


class TestScheduleE:
    def test_fusenig_e_two_travel_payments(self):
        lines = parse_schedule_e(FUSENIG, find_schedule_pages(FUSENIG)["E"])
        assert [(ln["counterparty_name_raw"], ln["amount"]) for ln in lines] == [
            ("Unchained At Last", "592.00"),
            ("Tahirih Justice Center", "325.00"),
        ]
        assert all(ln["interest_type"] == "travel" for ln in lines)


class TestScheduleC:
    def test_jones_c_income_spouse_gated_no_position(self):
        lines, unparsed = parse_schedule_c(JONES, find_schedule_pages(JONES)["C"])
        assert len(lines) == 1
        ln = lines[0]
        assert ln["counterparty_name_raw"] == "HighGear Ventures Management LLC"
        assert ln["interest_type"] == "income source"
        assert ln["amount_band"] == "OVER $100,000"
        assert ln["position"] is None
        assert ln["is_spouse"] is True  # spouse box → Membership gated off later
        assert unparsed == []

    def test_lara_c_loan_highest_balance(self):
        lines, unparsed = parse_schedule_c(LARA, find_schedule_pages(LARA)["C"])
        assert len(lines) == 1
        ln = lines[0]
        assert ln["counterparty_name_raw"] == "LoanDepot"
        assert ln["interest_type"] == "loan"
        assert ln["amount_band"] == "OVER $100,000"
        assert ln["position"] is None

    @werby_only
    def test_werby_c_seven_income_sources_position_verbatim(self):
        lines, unparsed = parse_schedule_c(WERBY, find_schedule_pages(WERBY)["C"])
        names_bands = [(ln["counterparty_name_raw"], ln["amount_band"]) for ln in lines]
        assert names_bands == [
            ("Grosvenor Gibraltar Associates", "$10,001 - $100,000"),
            ("Grosvenor Sonoma Associates", "$1,001 - $10,000"),
            ("Grosvenor Properties Ltd.", "OVER $100,000"),
            ("Village Green Associates", "$10,001 - $100,000"),
            ("Grosvenor Airport Associates", "OVER $100,000"),
            ("Carillon Associates", "OVER $100,000"),
            ("Mariners Island Investors", "$10,001 - $100,000"),
        ]
        assert all(ln["interest_type"] == "income source" for ln in lines)
        # Position field carries a verbatim entity name on rows 1–2, 4–7 and the
        # title on row 3 (recorded verbatim, never interpreted).
        assert lines[2]["position"] == "President & CEO"
        assert lines[0]["position"] == "Grosvenor Properties Ltd."
        assert all(ln["is_spouse"] is False for ln in lines)


class TestScheduleA2:
    def test_jones_a2_entity_plus_part4_investment_plus_literal_none(self):
        lines, skipped_none = parse_schedule_a2(JONES, find_schedule_pages(JONES)["A-2"])
        names_types = [(ln["counterparty_name_raw"], ln["interest_type"]) for ln in lines]
        assert names_types == [
            ("HighGear Ventures Secondary II GP", "investment"),
            ("HighGear Ventures Secondary II LP", "investment"),  # part-4 INVESTMENT
            ("High Gear Ventures Secondary III GP", "investment"),
        ]
        # cell-1 part-1 position carries the spouse marker verbatim.
        assert lines[0]["position"] == "Managing Director (spouse)"
        # cell-2 part-3 "Names listed below" = literal None → no node, counted.
        assert skipped_none == 1

    @werby_only
    def test_werby_a2_fifteen_nodes_with_subentries_and_city_only(self):
        lines, skipped_none = parse_schedule_a2(WERBY, find_schedule_pages(WERBY)["A-2"])
        rows = [(ln["counterparty_name_raw"], ln["interest_type"], ln["amount_band"])
                for ln in lines]
        assert rows == [
            ("Harbor Drive Associates", "investment", "Over $1,000,000"),
            ("Sausalito", "real property", "Over $1,000,000"),            # part-4
            ("Greene Management Corp.", "investment", "$100,001 - $1,000,000"),
            ("707 C Street Partners", "investment", "$10,001 - $100,000"),
            ("San Rafael", "real property", "Over $1,000,000"),           # part-4
            ("Grosvenor Van Ness Associates", "investment", "Over $1,000,000"),
            ("Grosvenor Airport Associates", "investment", "Over $1,000,000"),
            ("Greene Marin Freeholders", "investment", "$100,001 - $1,000,000"),
            ("TOPA Associates", "investment", "Over $1,000,000"),
            ("Grosvenor Donner Associates", "investment", "Over $1,000,000"),
            ("United Cold Storage", "income source", None),               # part-3, no band
            ("Grosvenor Broad Street LLC", "investment", "Over $1,000,000"),
            ("Casa Capital LLC", "investment", "Over $1,000,000"),
            ("WCAT Associates", "investment", "$100,001 - $1,000,000"),
            ("Grosvenor Properties Ltd.", "investment", "Over $1,000,000"),
        ]
        assert lines[6]["position"] == "Partner"
        assert lines[14]["position"] == "President & CEO"
        # part-4 real-property rows are city only — assert no street/APN shape.
        rp = [ln["counterparty_name_raw"] for ln in lines if ln["interest_type"] == "real property"]
        assert rp == ["Sausalito", "San Rafael"]
        for city in rp:
            assert not re.search(r"\d", city)


class TestScheduleB:
    @werby_only
    def test_werby_b_four_properties_city_only_no_address(self):
        lines = parse_schedule_b(WERBY, find_schedule_pages(WERBY)["B"])
        rows = [(ln["counterparty_name_raw"], ln["amount_band"]) for ln in lines]
        assert rows == [
            ("San Rafael", "Over $1,000,000"),
            ("Sausalito", "Over $1,000,000"),
            ("Novato", "$100,001 - $1,000,000"),
            ("Hillsborough", "Over $1,000,000"),
        ]
        assert all(ln["interest_type"] == "real property" for ln in lines)
        # City-only: no digit (street number / APN) ever appears in counterparty.
        for ln in lines:
            assert not re.search(r"\d", ln["counterparty_name_raw"])


class TestCover:
    def test_fusenig_cover_marks_only_e(self):
        cover = parse_cover(FUSENIG)
        assert cover["schedules_marked"] == ["E"]
        assert cover["none_checked"] is False
        assert cover["cover_filer"] == "Fusenig, Sara"

    def test_alden_cover_only_none_checked(self):
        cover = parse_cover(ALDEN)
        assert cover["schedules_marked"] == []
        assert cover["none_checked"] is True

    def test_jones_cover_marks_a1_a2_c(self):
        cover = parse_cover(JONES)
        assert cover["schedules_marked"] == ["A-1", "A-2", "C"]
        assert cover["none_checked"] is False


class TestHolmGolden:
    @holm_only
    def test_holm_a1_two_investments(self):
        lines = parse_schedule_a1(HOLM, find_schedule_pages(HOLM)["A-1"])
        assert [(ln["counterparty_name_raw"], ln["amount_band"]) for ln in lines] == [
            ("APPLE INC", "$10,001 - $100,000"),
            ("Axon Inc", "$2,000 - $10,000"),
        ]

    @holm_only
    def test_holm_a2_position_literal_none_absent_and_part3_business_income(self):
        lines, skipped = parse_schedule_a2(HOLM, find_schedule_pages(HOLM)["A-2"])
        rows = [(ln["counterparty_name_raw"], ln["interest_type"]) for ln in lines]
        assert rows == [
            ("Schrader Design", "investment"),
            ("Business income", "income source"),  # part-3, verbatim non-name literal
        ]
        # position field is the literal "None" → ABSENT on the node, not a value.
        assert lines[0]["position"] is None

    @holm_only
    def test_holm_b_one_property_city_only(self):
        lines = parse_schedule_b(HOLM, find_schedule_pages(HOLM)["B"])
        assert len(lines) == 1
        assert lines[0]["counterparty_name_raw"] == "San Rafael"
        assert lines[0]["interest_type"] == "real property"
        assert lines[0]["amount_band"] == "Over $1,000,000"
        assert not re.search(r"\d", lines[0]["counterparty_name_raw"])
