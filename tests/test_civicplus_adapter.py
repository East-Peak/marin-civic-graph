"""Tests for CivicPlus parsing utilities and adapter registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.civicplus import (
    CivicPlusAdapter,
    extract_categories,
    extract_years_for_category,
    parse_civicplus_date,
    parse_meeting_rows,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures — load HTML once per session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def corte_madera_html():
    return (FIXTURES / "civicplus-corte-madera.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def tiburon_html():
    return (FIXTURES / "civicplus-tiburon.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def mill_valley_html():
    return (FIXTURES / "civicplus-mill-valley.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_civicplus_registered(self):
        cls = get_adapter_class("civicplus")
        assert cls is not None

    def test_civicplus_is_baseadapter_subclass(self):
        cls = get_adapter_class("civicplus")
        assert issubclass(cls, BaseAdapter)


# ---------------------------------------------------------------------------
# TestParseCivicPlusDate
# ---------------------------------------------------------------------------

class TestParseCivicPlusDate:
    def test_full_month_name(self):
        assert parse_civicplus_date("April 7, 2026") == "2026-04-07"

    def test_abbreviated_month(self):
        assert parse_civicplus_date("Apr 7, 2026") == "2026-04-07"

    def test_aria_label_prefix(self):
        assert parse_civicplus_date("Agenda for April 7, 2026") == "2026-04-07"

    def test_two_digit_day(self):
        assert parse_civicplus_date("March 17, 2026") == "2026-03-17"

    def test_january(self):
        assert parse_civicplus_date("January 1, 2020") == "2020-01-01"

    def test_december(self):
        assert parse_civicplus_date("December 31, 2019") == "2019-12-31"

    def test_bad_input_returns_none(self):
        assert parse_civicplus_date("no date here") is None

    def test_empty_string_returns_none(self):
        assert parse_civicplus_date("") is None

    def test_none_like_garbage_returns_none(self):
        assert parse_civicplus_date("Posted Mar 13, 2026 10:33 AM") is None or \
               parse_civicplus_date("Posted Mar 13, 2026 10:33 AM") == "2026-03-13"
        # We only require it not to crash; ISO format if something extracted is a bonus


# ---------------------------------------------------------------------------
# TestExtractCategories
# ---------------------------------------------------------------------------

class TestExtractCategories:
    def test_corte_madera_returns_at_least_five(self, corte_madera_html):
        cats = extract_categories(corte_madera_html)
        assert len(cats) >= 5

    def test_returns_list_of_dicts_with_id_and_name(self, corte_madera_html):
        cats = extract_categories(corte_madera_html)
        for cat in cats:
            assert "id" in cat
            assert "name" in cat
            assert isinstance(cat["id"], str)
            assert isinstance(cat["name"], str)
            assert cat["name"].strip()

    def test_corte_madera_has_town_council(self, corte_madera_html):
        cats = extract_categories(corte_madera_html)
        names = [c["name"] for c in cats]
        assert any("Town Council" in n for n in names)

    def test_tiburon_has_town_council(self, tiburon_html):
        cats = extract_categories(tiburon_html)
        names = [c["name"] for c in cats]
        assert any("Town Council" in n for n in names)

    def test_tiburon_returns_five_categories(self, tiburon_html):
        cats = extract_categories(tiburon_html)
        assert len(cats) == 5

    def test_corte_madera_returns_ten_categories(self, corte_madera_html):
        cats = extract_categories(corte_madera_html)
        assert len(cats) == 10

    def test_ids_are_strings_of_digits(self, corte_madera_html):
        cats = extract_categories(corte_madera_html)
        for cat in cats:
            assert cat["id"].isdigit()


# ---------------------------------------------------------------------------
# TestExtractYearsForCategory
# ---------------------------------------------------------------------------

class TestExtractYearsForCategory:
    def test_corte_madera_cat1_has_2026(self, corte_madera_html):
        years = extract_years_for_category(corte_madera_html, "1")
        assert 2026 in years

    def test_corte_madera_cat1_has_2019(self, corte_madera_html):
        years = extract_years_for_category(corte_madera_html, "1")
        assert 2019 in years

    def test_corte_madera_cat1_has_more_than_three(self, corte_madera_html):
        # Includes dropdown years
        years = extract_years_for_category(corte_madera_html, "1")
        assert len(years) > 3

    def test_years_are_sorted_descending(self, corte_madera_html):
        years = extract_years_for_category(corte_madera_html, "1")
        assert years == sorted(years, reverse=True)

    def test_years_are_integers(self, corte_madera_html):
        years = extract_years_for_category(corte_madera_html, "1")
        for y in years:
            assert isinstance(y, int)
            assert 2000 <= y <= 2100


# ---------------------------------------------------------------------------
# TestParseMeetingRows
# ---------------------------------------------------------------------------

class TestParseMeetingRowsCorteMadera:
    @pytest.fixture(scope="class")
    def meetings(self, corte_madera_html):
        return parse_meeting_rows(
            corte_madera_html,
            base_url="https://www.ci.corte-madera.ca.us",
            backfill_from="2019-01-01",
        )

    def test_at_least_40_rows(self, meetings):
        assert len(meetings) >= 40

    def test_meetings_have_required_fields(self, meetings):
        required = {"date", "title", "category", "meeting_type", "artifacts",
                    "source_row_number", "agenda_id"}
        for m in meetings:
            for field in required:
                assert field in m, f"Missing field {field!r} in meeting {m}"

    def test_dates_are_iso_format(self, meetings):
        import re
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for m in meetings:
            if m["date"] is not None:
                assert iso_re.match(m["date"]), f"Bad date: {m['date']!r}"

    def test_artifacts_structure(self, meetings):
        for m in meetings:
            arts = m["artifacts"]
            for key in ("agenda", "minutes", "packet"):
                assert key in arts, f"Missing artifact key {key!r}"
                assert "available" in arts[key]
                assert "url" in arts[key]

    def test_more_than_20_agenda_urls(self, meetings):
        agenda_urls = [m["artifacts"]["agenda"]["url"] for m in meetings
                       if m["artifacts"]["agenda"]["available"]]
        assert len(agenda_urls) > 20

    def test_agenda_urls_are_absolute(self, meetings):
        for m in meetings:
            url = m["artifacts"]["agenda"]["url"]
            if url:
                assert url.startswith("http"), f"Non-absolute URL: {url!r}"

    def test_category_names_populated(self, meetings):
        cats_with_names = [m for m in meetings if m["category"]]
        assert len(cats_with_names) > 0

    def test_meeting_type_is_string(self, meetings):
        for m in meetings:
            assert isinstance(m["meeting_type"], str)


class TestParseMeetingRowsTiburon:
    @pytest.fixture(scope="class")
    def meetings(self, tiburon_html):
        # Tiburon fixture contains 2016–2017 data; use an early cutoff to test all rows.
        return parse_meeting_rows(
            tiburon_html,
            base_url="https://www.townoftiburon.org",
            backfill_from="2015-01-01",
        )

    def test_at_least_80_rows(self, meetings):
        assert len(meetings) >= 80

    def test_minutes_urls_more_than_10(self, meetings):
        minutes_urls = [m["artifacts"]["minutes"]["url"] for m in meetings
                        if m["artifacts"]["minutes"]["available"]]
        assert len(minutes_urls) > 10

    def test_dates_are_iso_format(self, meetings):
        import re
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for m in meetings:
            if m["date"] is not None:
                assert iso_re.match(m["date"]), f"Bad date: {m['date']!r}"

    def test_more_than_20_agenda_urls(self, meetings):
        agenda_urls = [m["artifacts"]["agenda"]["url"] for m in meetings
                       if m["artifacts"]["agenda"]["available"]]
        assert len(agenda_urls) > 20


class TestParseMeetingRowsMillValley:
    @pytest.fixture(scope="class")
    def meetings(self, mill_valley_html):
        return parse_meeting_rows(
            mill_valley_html,
            base_url="https://www.cityofmillvalley.org",
            backfill_from="2019-01-01",
        )

    def test_at_least_40_rows(self, meetings):
        assert len(meetings) >= 40

    def test_meetings_have_required_fields(self, meetings):
        required = {"date", "title", "category", "meeting_type", "artifacts",
                    "source_row_number", "agenda_id"}
        for m in meetings:
            for field in required:
                assert field in m, f"Missing field {field!r}"



class TestCivicPlusAdapterCapture:
    def _make_adapter(self, source_id, fixture_name, tmp_path, categories=None):
        config = {
            "id": source_id,
            "adapter": "civicplus",
            "url": f"https://example.gov/AgendaCenter",
            "jurisdiction_id": f"place-{source_id.rsplit('-', 1)[0]}",
            "institution_id": f"org-{source_id}",
            "backfill_from": "2015-01-01",
        }
        if categories:
            config["categories"] = categories
        adapter = CivicPlusAdapter(config, tmp_path)
        fixture_path = FIXTURES / fixture_name
        fixture_html = fixture_path.read_text(errors="ignore")
        adapter._fetch_page = lambda url: fixture_html
        adapter._fetch_year = lambda url, cat_id, year, cookies: ""
        return adapter

    def test_capture_returns_dict(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)

    def test_capture_has_required_envelope_fields(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        for field in ["capture_id", "source_id", "captured_at", "institution_id",
                      "jurisdiction_id", "meeting_count", "artifact_counts",
                      "meetings", "record_refs", "errors"]:
            assert field in result, f"Missing field: {field}"
        assert result["adapter"] == "civicplus"

    def test_capture_meeting_count_matches(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] == len(result["meetings"])
        assert result["meeting_count"] > 20

    def test_capture_writes_raw_html(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        adapter.capture()
        raw_files = list((tmp_path / "data" / "raw").rglob("source.html"))
        assert len(raw_files) == 1

    def test_capture_record_refs_present(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert len(result["record_refs"]) >= 1
        assert result["record_refs"][0]["record_type"] == "agenda_center_page"

    def test_tiburon_meeting_count(self, tmp_path):
        adapter = self._make_adapter("tiburon-town", "civicplus-tiburon.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] > 50

    def test_capture_meetings_have_institution_id(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert m["institution_id"] == "org-corte-madera-town"

    def test_capture_meetings_have_meeting_id(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert "meeting_id" in m
            assert m["meeting_id"].startswith("meeting-")

    def test_capture_has_categories_list(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert "categories" in result
        assert len(result["categories"]) > 1

    def test_category_filter(self, tmp_path):
        adapter = self._make_adapter(
            "corte-madera-town", "civicplus-corte-madera.html", tmp_path,
            categories=["Town Council"],
        )
        result = adapter.capture()
        named_cats = {m.get("category") for m in result["meetings"] if m.get("category")}
        assert named_cats.issubset({"Town Council"})
