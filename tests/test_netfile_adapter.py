"""Tests for the NetFile campaign finance adapter."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

MOCK_HTML = """\
<html>
<input name="__VIEWSTATE" value="fakestate" />
<input name="__VIEWSTATEGENERATOR" value="fakegen" />
<select>
    <option value="2025">2025</option>
    <option value="2024">2024</option>
    <option value="2023">2023</option>
</select>
</html>
"""


def _make_zip_bytes() -> bytes:
    """Return bytes for a ZIP containing a minimal XLSX with one sheet."""
    xlsx_buf = io.BytesIO()
    with zipfile.ZipFile(xlsx_buf, "w") as xlsx:
        xlsx.writestr(
            "xl/workbook.xml",
            '<workbook><sheets><sheet name="Transactions"/></sheets></workbook>',
        )
    xlsx_bytes = xlsx_buf.getvalue()

    outer_buf = io.BytesIO()
    with zipfile.ZipFile(outer_buf, "w") as outer:
        outer.writestr("export.xlsx", xlsx_bytes)
    return outer_buf.getvalue()


def _base_config(**overrides) -> dict:
    defaults = {
        "id": "test-netfile",
        "url": "https://public.netfile.com/pub2/?aid=TEST",
        "jurisdiction_id": "jur-test",
        "institution_id": "inst-test",
        "backfill_from": "2024-01-01",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_netfile_registered(self):
        cls = get_adapter_class("netfile")
        assert cls is not None

    def test_netfile_is_baseadapter_subclass(self):
        cls = get_adapter_class("netfile")
        assert issubclass(cls, BaseAdapter)


# ---------------------------------------------------------------------------
# TestExtractHiddenField
# ---------------------------------------------------------------------------

class TestExtractHiddenField:
    def setup_method(self):
        from adapters.netfile import extract_hidden_field
        self.fn = extract_hidden_field

    def test_extracts_viewstate(self):
        html = '<input name="__VIEWSTATE" value="abc123" />'
        assert self.fn(html, "__VIEWSTATE") == "abc123"

    def test_extracts_viewstategenerator(self):
        html = '<input name="__VIEWSTATEGENERATOR" value="DEADBEEF" />'
        assert self.fn(html, "__VIEWSTATEGENERATOR") == "DEADBEEF"

    def test_missing_field_returns_empty_string(self):
        html = '<input name="__OTHER" value="something" />'
        assert self.fn(html, "__VIEWSTATE") == ""

    def test_empty_html_returns_empty_string(self):
        assert self.fn("", "__VIEWSTATE") == ""

    def test_extracts_from_mock_html(self):
        assert self.fn(MOCK_HTML, "__VIEWSTATE") == "fakestate"
        assert self.fn(MOCK_HTML, "__VIEWSTATEGENERATOR") == "fakegen"


# ---------------------------------------------------------------------------
# TestExtractYearOptions
# ---------------------------------------------------------------------------

class TestExtractYearOptions:
    def setup_method(self):
        from adapters.netfile import extract_year_options
        self.fn = extract_year_options

    def test_extracts_years_sorted_descending(self):
        html = """\
        <option value="2023">2023</option>
        <option value="2025">2025</option>
        <option value="2024">2024</option>
        """
        assert self.fn(html) == [2025, 2024, 2023]

    def test_ignores_non_numeric_values(self):
        html = """\
        <option value="All">All Years</option>
        <option value="2022">2022</option>
        """
        assert self.fn(html) == [2022]

    def test_ignores_three_digit_values(self):
        html = '<option value="999">999</option><option value="2021">2021</option>'
        assert self.fn(html) == [2021]

    def test_empty_html_returns_empty_list(self):
        assert self.fn("") == []

    def test_extracts_from_mock_html(self):
        assert self.fn(MOCK_HTML) == [2025, 2024, 2023]


# ---------------------------------------------------------------------------
# TestExtractSheetNames
# ---------------------------------------------------------------------------

class TestExtractSheetNames:
    def setup_method(self):
        from adapters.netfile import extract_sheet_names_from_zip
        self.fn = extract_sheet_names_from_zip

    def test_extracts_sheet_names(self):
        zip_bytes = _make_zip_bytes()
        names = self.fn(zip_bytes)
        assert names == ["Transactions"]

    def test_multiple_sheets(self):
        xlsx_buf = io.BytesIO()
        with zipfile.ZipFile(xlsx_buf, "w") as xlsx:
            xlsx.writestr(
                "xl/workbook.xml",
                '<workbook><sheets>'
                '<sheet name="Cover"/>'
                '<sheet name="Schedule A"/>'
                '<sheet name="Schedule B"/>'
                "</sheets></workbook>",
            )
        outer_buf = io.BytesIO()
        with zipfile.ZipFile(outer_buf, "w") as outer:
            outer.writestr("export.xlsx", xlsx_buf.getvalue())
        names = self.fn(outer_buf.getvalue())
        assert names == ["Cover", "Schedule A", "Schedule B"]

    def test_invalid_zip_returns_empty_list(self):
        assert self.fn(b"not a zip") == []

    def test_empty_bytes_returns_empty_list(self):
        assert self.fn(b"") == []

    def test_no_xlsx_in_zip_returns_empty_list(self):
        outer_buf = io.BytesIO()
        with zipfile.ZipFile(outer_buf, "w") as outer:
            outer.writestr("readme.txt", "no xlsx here")
        assert self.fn(outer_buf.getvalue()) == []


# ---------------------------------------------------------------------------
# TestNetFileAdapterCapture
# ---------------------------------------------------------------------------

class TestNetFileAdapterCapture:
    """Integration tests using monkey-patched HTTP methods."""

    def _make_adapter(self, tmp_path: Path, **config_overrides) -> object:
        from adapters.netfile import NetFileAdapter

        cfg = _base_config(**config_overrides)
        adapter = NetFileAdapter(cfg, tmp_path)

        zip_bytes = _make_zip_bytes()

        adapter._fetch_page = lambda url: MOCK_HTML  # type: ignore[method-assign]
        adapter._post_export = lambda url, form_data: zip_bytes  # type: ignore[method-assign]

        return adapter

    def test_capture_returns_required_top_level_keys(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()

        required_keys = {
            "capture_id",
            "source_id",
            "adapter",
            "captured_at",
            "url",
            "jurisdiction_id",
            "institution_id",
            "available_years",
            "captured_years",
            "export_count",
            "meeting_count",
            "exports",
            "record_refs",
            "errors",
        }
        assert required_keys.issubset(result.keys())

    def test_adapter_field_is_netfile(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        assert result["adapter"] == "netfile"

    def test_meeting_count_is_zero(self, tmp_path):
        """NetFile has no meetings — meeting_count must always be 0."""
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] == 0

    def test_exports_filtered_by_backfill_from(self, tmp_path):
        # backfill_from = 2024-01-01 → only years >= 2024
        adapter = self._make_adapter(tmp_path, backfill_from="2024-01-01")
        result = adapter.capture()
        captured_years = result["captured_years"]
        assert all(y >= 2024 for y in captured_years)
        # Mock HTML has 2025, 2024, 2023 — expect 2025 and 2024
        assert set(captured_years) == {2025, 2024}

    def test_exports_all_years_when_backfill_covers_all(self, tmp_path):
        adapter = self._make_adapter(tmp_path, backfill_from="2023-01-01")
        result = adapter.capture()
        assert set(result["captured_years"]) == {2025, 2024, 2023}

    def test_zip_files_written_to_raw_dir(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        for export in result["exports"]:
            zip_path = Path(export["zip_path"])
            assert zip_path.exists()
            assert zip_path.suffix == ".zip"

    def test_each_export_has_sheet_names(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        for export in result["exports"]:
            assert "sheet_names" in export
            assert isinstance(export["sheet_names"], list)
            assert len(export["sheet_names"]) > 0

    def test_each_export_has_sheet_count(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        for export in result["exports"]:
            assert export["sheet_count"] == len(export["sheet_names"])

    def test_each_export_has_year_and_export_mode(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        for export in result["exports"]:
            assert "year" in export
            assert "export_mode" in export

    def test_record_refs_present(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        assert len(result["record_refs"]) >= 1

    def test_record_refs_include_portal_page(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        types = [r["record_type"] for r in result["record_refs"]]
        assert "campaign_finance_portal_page" in types

    def test_record_refs_include_year_exports(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        types = [r["record_type"] for r in result["record_refs"]]
        assert "campaign_finance_export" in types

    def test_export_count_matches_exports_list(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        assert result["export_count"] == len(result["exports"])

    def test_available_years_matches_html(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        assert result["available_years"] == [2025, 2024, 2023]

    def test_errors_is_empty_list_on_success(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        assert result["errors"] == []

    def test_failed_export_adds_to_errors(self, tmp_path):
        from adapters.netfile import NetFileAdapter

        cfg = _base_config(backfill_from="2024-01-01")
        adapter = NetFileAdapter(cfg, tmp_path)
        adapter._fetch_page = lambda url: MOCK_HTML  # type: ignore[method-assign]

        def _fail_on_2025(url, form_data):
            if form_data.get("ctl00$phBody$DateSelect") == "2025":
                raise RuntimeError("network timeout")
            return _make_zip_bytes()

        adapter._post_export = _fail_on_2025  # type: ignore[method-assign]
        result = adapter.capture()
        assert len(result["errors"]) == 1
        assert "2025" in result["errors"][0]

    def test_source_id_and_jurisdiction_in_result(self, tmp_path):
        adapter = self._make_adapter(tmp_path)
        result = adapter.capture()
        assert result["source_id"] == "test-netfile"
        assert result["jurisdiction_id"] == "jur-test"
        assert result["institution_id"] == "inst-test"
