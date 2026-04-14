"""NetFile /pub2/ campaign finance adapter.

Downloads year-based ZIP exports from the NetFile public portal and extracts
sheet names from the inner Excel workbooks.
"""

from __future__ import annotations

import io
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .base import BaseAdapter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"

# Matches: name="FIELD_NAME" value="VALUE"  (single or double quotes, attrs
# may appear in either order, so we match the value attribute that follows the
# name attribute anywhere in the same <input … /> tag).
_HIDDEN_FIELD_RE_TMPL = r'name="{name}"[^>]*value="([^"]*)"'
_HIDDEN_FIELD_RE_TMPL_ALT = r'value="([^"]*)"[^>]*name="{name}"'

# Matches <option value="YYYY"> where YYYY is exactly 4 digits.
_YEAR_OPTION_RE = re.compile(r'<option\s+value="(\d{4})"')

# Matches sheet name="…" in xl/workbook.xml.
_SHEET_NAME_RE = re.compile(r'<sheet\s[^>]*name="([^"]+)"')


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def extract_hidden_field(html: str, name: str) -> str:
    """Return the value of the hidden form field *name* from *html*.

    Tries both attribute orderings (name before value, value before name).
    Returns ``""`` if the field is not found.
    """
    for tmpl in (_HIDDEN_FIELD_RE_TMPL, _HIDDEN_FIELD_RE_TMPL_ALT):
        pattern = tmpl.format(name=re.escape(name))
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    return ""


def extract_year_options(html: str) -> list[int]:
    """Return year integers from ``<option value="YYYY">`` elements, sorted descending."""
    return sorted(
        {int(v) for v in _YEAR_OPTION_RE.findall(html)},
        reverse=True,
    )


def extract_sheet_names_from_zip(zip_bytes: bytes) -> list[str]:
    """Extract Excel sheet names from a ZIP-in-ZIP export bundle.

    The outer ZIP contains an ``.xlsx`` file; the inner ``.xlsx`` is itself a
    ZIP containing ``xl/workbook.xml`` which lists sheet names.

    Returns an empty list if *zip_bytes* is not a valid ZIP or contains no
    ``.xlsx`` entry.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as outer:
            xlsx_names = [n for n in outer.namelist() if n.lower().endswith(".xlsx")]
            if not xlsx_names:
                return []
            xlsx_bytes = outer.read(xlsx_names[0])
    except (zipfile.BadZipFile, Exception):
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as inner:
            if "xl/workbook.xml" not in inner.namelist():
                return []
            workbook_xml = inner.read("xl/workbook.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, Exception):
        return []

    return _SHEET_NAME_RE.findall(workbook_xml)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class NetFileAdapter(BaseAdapter):
    """NetFile /pub2/ campaign finance portal adapter.

    Fetches the portal landing page, discovers available filing years, and
    POSTs a form request for each year to download a ZIP export.
    """

    def _fetch_page(self, url: str) -> str:
        """GET *url* and return the decoded HTML body. Overridable in tests."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=90) as resp:
            charset = resp.headers.get_content_charset("utf-8")
            return resp.read().decode(charset, errors="replace")

    def _post_export(self, url: str, form_data: dict) -> bytes:
        """POST URL-encoded *form_data* to *url* and return the raw bytes.

        Overridable in tests.
        """
        encoded = urllib.parse.urlencode(form_data).encode("ascii")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.read()

    def capture(self) -> dict:
        """Orchestrate the full NetFile capture flow.

        1. Fetch portal page and extract hidden ViewState fields + year list.
        2. For each year >= backfill_from year, POST form and save ZIP.
        3. Return structured capture dict.
        """
        captured_at = self.utc_now_iso()
        export_target: str = self.config.get(
            "export_target", "ctl00$phBody$GetExcelAmend"
        )
        cutoff_year = int(self.backfill_from[:4])

        # -- Fetch portal page --------------------------------------------------
        html = self._fetch_page(self.url)

        viewstate = extract_hidden_field(html, "__VIEWSTATE")
        viewstate_gen = extract_hidden_field(html, "__VIEWSTATEGENERATOR")
        available_years = extract_year_options(html)

        years_to_capture = [y for y in available_years if y >= cutoff_year]

        # -- Prepare output directories ----------------------------------------
        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)

        # -- Download one ZIP per year -----------------------------------------
        exports: list[dict] = []
        errors: list[str] = []

        for year in years_to_capture:
            form_data = {
                "__EVENTTARGET": export_target,
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": viewstate_gen,
                "ctl00$phBody$DateSelect": str(year),
            }
            try:
                zip_bytes = self._post_export(self.url, form_data)
            except Exception as exc:
                errors.append(f"year {year}: {exc}")
                continue

            zip_path = raw_dir / f"{year}.zip"
            zip_path.write_bytes(zip_bytes)

            sheet_names = extract_sheet_names_from_zip(zip_bytes)
            exports.append(
                {
                    "year": year,
                    "export_mode": "zip_excel",
                    "zip_path": str(zip_path),
                    "zip_bytes": zip_bytes,
                    "sheet_names": sheet_names,
                    "sheet_count": len(sheet_names),
                }
            )

        # -- Build record_refs -------------------------------------------------
        record_refs: list[dict] = [
            {
                "id": f"record-{self.source_id}-portal-page-{captured_at[:10]}",
                "record_type": "campaign_finance_portal_page",
                "source_id": self.source_id,
                "url": self.url,
                "captured_at": captured_at,
            }
        ]
        for exp in exports:
            record_refs.append(
                {
                    "id": f"record-{self.source_id}-export-{exp['year']}-{captured_at[:10]}",
                    "record_type": "campaign_finance_export",
                    "source_id": self.source_id,
                    "year": exp["year"],
                    "artifact_path": str(
                        Path(exp["zip_path"]).relative_to(self.root)
                    ),
                    "captured_at": captured_at,
                }
            )

        return {
            "capture_id": self.capture_id(),
            "source_id": self.source_id,
            "adapter": "netfile",
            "captured_at": captured_at,
            "url": self.url,
            "jurisdiction_id": self.jurisdiction_id,
            "institution_id": self.institution_id,
            "available_years": available_years,
            "captured_years": [e["year"] for e in exports],
            "export_count": len(exports),
            "meeting_count": 0,
            "exports": exports,
            "record_refs": record_refs,
            "errors": errors,
        }
