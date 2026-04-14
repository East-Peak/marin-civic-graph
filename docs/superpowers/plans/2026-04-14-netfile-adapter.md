# NetFile Campaign Finance Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a NetFile adapter for the `/pub2/` campaign finance export portal, covering Marin County and Novato — year-based ZIP exports with Excel workbooks.

**Architecture:** The adapter follows the BaseAdapter contract. It performs: GET initial page (extract __VIEWSTATE + available years), then POST per year with the export button target to download ZIP files containing Excel workbooks. Extracts sheet metadata from the workbooks. Strict red/green TDD.

**Tech Stack:** Python 3, pytest, urllib (stdlib), zipfile (stdlib), io (stdlib)

**Prerequisite:** Ingestion adapter framework with BaseAdapter, runner, and registry.

---

## File Structure

```
scripts/
  adapters/
    netfile.py                      # NetFile /pub2/ campaign finance adapter (NEW)
    __init__.py                     # Add netfile to registry (MODIFY)
registry/
  netfile-sources.yaml              # NetFile source configs (NEW)
tests/
  test_netfile_adapter.py           # Unit + integration tests (NEW)
```

---

### Task 1: NetFile ASP.NET form-post utilities + adapter

**Files:**
- Create: `scripts/adapters/netfile.py`
- Create: `tests/test_netfile_adapter.py`
- Modify: `scripts/adapters/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_netfile_adapter.py`:

```python
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.netfile import (
    extract_hidden_field,
    extract_year_options,
    extract_sheet_names_from_zip,
    NetFileAdapter,
)


class TestRegistry:
    def test_netfile_registered(self):
        cls = get_adapter_class("netfile")
        assert issubclass(cls, BaseAdapter)


class TestExtractHiddenField:
    def test_extracts_viewstate(self):
        html = '<input name="__VIEWSTATE" value="abc123" />'
        assert extract_hidden_field(html, "__VIEWSTATE") == "abc123"

    def test_extracts_viewstate_generator(self):
        html = '<input name="__VIEWSTATEGENERATOR" value="DEADBEEF" />'
        assert extract_hidden_field(html, "__VIEWSTATEGENERATOR") == "DEADBEEF"

    def test_returns_empty_for_missing(self):
        assert extract_hidden_field("<html></html>", "__VIEWSTATE") == ""

    def test_handles_double_quotes(self):
        html = '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="xyz" />'
        assert extract_hidden_field(html, "__VIEWSTATE") == "xyz"


class TestExtractYearOptions:
    def test_extracts_years(self):
        html = '''
        <select>
            <option value="2026">2026</option>
            <option value="2025">2025</option>
            <option value="2024">2024</option>
            <option value="2019">2019</option>
        </select>
        '''
        years = extract_year_options(html)
        assert 2026 in years
        assert 2019 in years
        assert years == sorted(years, reverse=True)

    def test_ignores_non_year_options(self):
        html = '<option value="All">All Years</option><option value="2024">2024</option>'
        years = extract_year_options(html)
        assert years == [2024]


class TestExtractSheetNames:
    def test_extracts_from_xlsx_zip(self):
        # Create a minimal XLSX (which is itself a ZIP) inside an outer ZIP
        xlsx_buf = io.BytesIO()
        with zipfile.ZipFile(xlsx_buf, "w") as xlsx:
            xlsx.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Sheet1"/><sheet name="Contributions"/></sheets></workbook>')
        xlsx_bytes = xlsx_buf.getvalue()

        outer_buf = io.BytesIO()
        with zipfile.ZipFile(outer_buf, "w") as outer:
            outer.writestr("export.xlsx", xlsx_bytes)
        zip_bytes = outer_buf.getvalue()

        sheets = extract_sheet_names_from_zip(zip_bytes)
        assert "Sheet1" in sheets
        assert "Contributions" in sheets

    def test_returns_empty_for_invalid_zip(self):
        assert extract_sheet_names_from_zip(b"not a zip") == []


class TestNetFileAdapterCapture:
    def _make_adapter(self, source_id, tmp_path, mock_html, mock_exports):
        config = {
            "id": source_id,
            "adapter": "netfile",
            "url": f"https://public.netfile.com/pub2/?aid=TEST",
            "jurisdiction_id": "place-test",
            "institution_id": "org-test",
            "backfill_from": "2024-01-01",
            "export_target": "ctl00$phBody$GetExcelAmend",
        }
        adapter = NetFileAdapter(config, tmp_path)
        adapter._fetch_page = lambda url: mock_html
        adapter._post_export = lambda url, form_data: mock_exports.get(
            form_data.get("ctl00$phBody$DateSelect", ""), b""
        )
        return adapter

    @pytest.fixture
    def mock_html(self):
        return '''
        <html>
        <input name="__VIEWSTATE" value="fakestate" />
        <input name="__VIEWSTATEGENERATOR" value="fakegen" />
        <select>
            <option value="2025">2025</option>
            <option value="2024">2024</option>
            <option value="2023">2023</option>
        </select>
        </html>
        '''

    @pytest.fixture
    def mock_zip(self):
        """Create a minimal XLSX-in-ZIP export."""
        xlsx_buf = io.BytesIO()
        with zipfile.ZipFile(xlsx_buf, "w") as xlsx:
            xlsx.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Transactions"/></sheets></workbook>')
        xlsx_bytes = xlsx_buf.getvalue()
        outer_buf = io.BytesIO()
        with zipfile.ZipFile(outer_buf, "w") as outer:
            outer.writestr("campaign_2024.xlsx", xlsx_bytes)
        return outer_buf.getvalue()

    def test_capture_returns_dict(self, tmp_path, mock_html, mock_zip):
        adapter = self._make_adapter("test-cf", tmp_path, mock_html, {"2024": mock_zip, "2025": mock_zip})
        result = adapter.capture()
        assert isinstance(result, dict)

    def test_capture_has_required_fields(self, tmp_path, mock_html, mock_zip):
        adapter = self._make_adapter("test-cf", tmp_path, mock_html, {"2024": mock_zip, "2025": mock_zip})
        result = adapter.capture()
        for field in ["capture_id", "source_id", "captured_at", "institution_id",
                      "jurisdiction_id", "meeting_count", "exports", "record_refs", "errors"]:
            assert field in result, f"Missing: {field}"
        assert result["adapter"] == "netfile"

    def test_capture_exports_filtered_by_backfill(self, tmp_path, mock_html, mock_zip):
        adapter = self._make_adapter("test-cf", tmp_path, mock_html, {"2024": mock_zip, "2025": mock_zip})
        result = adapter.capture()
        years = [e["year"] for e in result["exports"]]
        assert 2024 in years
        assert 2025 in years
        assert 2023 not in years

    def test_capture_writes_raw_artifacts(self, tmp_path, mock_html, mock_zip):
        adapter = self._make_adapter("test-cf", tmp_path, mock_html, {"2024": mock_zip, "2025": mock_zip})
        adapter.capture()
        raw_files = list((tmp_path / "data" / "raw").rglob("*.zip"))
        assert len(raw_files) == 2

    def test_capture_exports_have_sheet_names(self, tmp_path, mock_html, mock_zip):
        adapter = self._make_adapter("test-cf", tmp_path, mock_html, {"2024": mock_zip})
        result = adapter.capture()
        assert result["exports"][0]["sheet_names"] == ["Transactions"]

    def test_capture_record_refs_present(self, tmp_path, mock_html, mock_zip):
        adapter = self._make_adapter("test-cf", tmp_path, mock_html, {"2024": mock_zip})
        result = adapter.capture()
        assert len(result["record_refs"]) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_netfile_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement netfile.py**

Create `scripts/adapters/netfile.py`:

```python
"""NetFile /pub2/ campaign finance export adapter.

Captures year-based amended-only Excel exports as ZIP files from
public.netfile.com/pub2/ portals (Marin County, Novato).
"""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from pathlib import Path

from .base import BaseAdapter

USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"
YEAR_OPTION_RE = re.compile(r'<option value="(\d{4})">')
SHEET_NAME_RE = re.compile(r'<sheet name="([^"]+)"')


def extract_hidden_field(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
    return match.group(1) if match else ""


def extract_year_options(html: str) -> list[int]:
    years = sorted(set(int(y) for y in YEAR_OPTION_RE.findall(html)), reverse=True)
    return years


def extract_sheet_names_from_zip(zip_bytes: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith((".xlsx", ".xls")):
                    wb_bytes = zf.read(name)
                    try:
                        with zipfile.ZipFile(io.BytesIO(wb_bytes)) as wb:
                            for wb_name in wb.namelist():
                                if "workbook.xml" in wb_name:
                                    xml = wb.read(wb_name).decode("utf-8", "ignore")
                                    return SHEET_NAME_RE.findall(xml)
                    except (zipfile.BadZipFile, KeyError):
                        pass
    except zipfile.BadZipFile:
        pass
    return []


class NetFileAdapter(BaseAdapter):
    """NetFile /pub2/ campaign finance export adapter."""

    def _fetch_page(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read().decode("utf-8", "ignore")

    def _post_export(self, url: str, form_data: dict) -> bytes:
        encoded = urllib.parse.urlencode(form_data).encode("utf-8")
        request = urllib.request.Request(
            url, data=encoded,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()

    def capture(self) -> dict:
        import urllib.parse

        html = self._fetch_page(self.url)
        captured_at = self.utc_now_iso()

        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.html").write_text(html, encoding="utf-8")

        viewstate = extract_hidden_field(html, "__VIEWSTATE")
        viewstate_gen = extract_hidden_field(html, "__VIEWSTATEGENERATOR")
        export_target = self.config.get("export_target", "ctl00$phBody$GetExcelAmend")
        available_years = extract_year_options(html)

        backfill_year = int(self.backfill_from[:4])
        target_years = [y for y in available_years if y >= backfill_year]

        exports = []
        errors = []
        record_refs = [
            {
                "id": f"record-{self.source_id}-portal-page-{captured_at[:10]}",
                "record_type": "netfile_portal_page",
                "source_id": self.source_id,
                "artifact_path": f"data/raw/{self.source_id}/{captured_at[:10]}/source.html",
                "captured_at": captured_at,
            }
        ]

        for year in target_years:
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
                if not zip_bytes:
                    errors.append(f"Empty response for year {year}")
                    continue

                zip_filename = f"{year}-amended.zip"
                zip_path = raw_dir / zip_filename
                zip_path.write_bytes(zip_bytes)

                sheet_names = extract_sheet_names_from_zip(zip_bytes)

                exports.append({
                    "year": year,
                    "export_mode": "amended_only",
                    "zip_path": str(zip_path.relative_to(self.root)),
                    "zip_bytes": len(zip_bytes),
                    "sheet_names": sheet_names,
                    "sheet_count": len(sheet_names),
                })

                record_refs.append({
                    "id": f"record-{self.source_id}-export-{year}",
                    "record_type": "campaign_finance_export",
                    "source_id": self.source_id,
                    "artifact_path": str(zip_path.relative_to(self.root)),
                    "captured_at": captured_at,
                    "year": year,
                })

            except Exception as e:
                errors.append(f"Failed to export year {year}: {e}")

        return {
            "capture_id": self.capture_id(),
            "source_id": self.source_id,
            "adapter": "netfile",
            "captured_at": captured_at,
            "url": self.url,
            "jurisdiction_id": self.jurisdiction_id,
            "institution_id": self.institution_id,
            "raw_artifact": f"data/raw/{self.source_id}/{captured_at[:10]}/source.html",
            "available_years": available_years,
            "captured_years": [e["year"] for e in exports],
            "export_count": len(exports),
            "meeting_count": 0,  # NetFile doesn't have meetings — this is for interface compat
            "exports": exports,
            "record_refs": record_refs,
            "errors": errors,
        }
```

- [ ] **Step 4: Register the adapter**

Add to `scripts/adapters/__init__.py`:

```python
from .netfile import NetFileAdapter
# In registry dict:
"netfile": NetFileAdapter,
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_netfile_adapter.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v`
Expected: All 232+ tests PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/adapters/netfile.py scripts/adapters/__init__.py tests/test_netfile_adapter.py
git commit -m "feat: add NetFile campaign finance adapter (/pub2/ year-based ZIP exports)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Source registry and live smoke test

**Files:**
- Create: `registry/netfile-sources.yaml`

- [ ] **Step 1: Create the source registry**

Create `registry/netfile-sources.yaml`:

```yaml
sources:
  - id: marin-county-campaign-finance
    adapter: netfile
    url: https://public.netfile.com/pub2/?aid=CMAR
    jurisdiction_id: place-marin-county
    institution_id: org-marin-county-campaign-finance
    backfill_from: "2019-01-01"
    schedule: quarterly
    export_target: "ctl00$phBody$GetExcelAmend"

  - id: novato-campaign-finance
    adapter: netfile
    url: https://public.netfile.com/pub2/?AID=NVO
    jurisdiction_id: place-novato
    institution_id: org-novato-campaign-finance
    backfill_from: "2019-01-01"
    schedule: quarterly
    export_target: "ctl00$phBody$GetExcelAmend"
```

- [ ] **Step 2: Live capture Marin County campaign finance**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source marin-county-campaign-finance --registry registry/netfile-sources.yaml`
Expected: ZIP exports for 2019-2026, with sheet names extracted

- [ ] **Step 3: Live capture Novato campaign finance**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source novato-campaign-finance --registry registry/netfile-sources.yaml`
Expected: ZIP exports for 2019-2026

- [ ] **Step 4: Verify output**

Run:
```bash
for f in data/extracted/marin-county-campaign*/$(date +%Y-%m-%d).json data/extracted/novato-campaign*/$(date +%Y-%m-%d).json; do
  [ -f "$f" ] || continue
  echo "=== $(basename $(dirname $f)) ==="
  python3 -c "
import json
d = json.load(open('$f'))
print(f'  source: {d[\"source_id\"]}')
print(f'  exports: {d[\"export_count\"]}')
print(f'  years: {d[\"captured_years\"]}')
print(f'  record_refs: {len(d[\"record_refs\"])}')
print(f'  errors: {d[\"errors\"]}')
for e in d['exports'][:3]:
    print(f'    {e[\"year\"]}: {e[\"zip_bytes\"]} bytes, sheets={e[\"sheet_names\"]}')
"
done
```

- [ ] **Step 5: Commit and push**

```bash
git add registry/netfile-sources.yaml
git commit -m "feat: NetFile adapter live — Marin County and Novato campaign finance captured

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

git push
```

---

## Build Verification

1. `python -m pytest tests/ -v` — all tests pass
2. `python scripts/ingest.py --source marin-county-campaign-finance --registry registry/netfile-sources.yaml` — exports captured
3. `python scripts/ingest.py --source novato-campaign-finance --registry registry/netfile-sources.yaml` — exports captured
4. Both outputs have: capture_id, record_refs per year, sheet_names, ZIP files on disk
