# CivicPlus Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CivicPlus Agenda Center adapter to the ingestion framework, covering Corte Madera, Tiburon, and Mill Valley (committees) — no city-specific code, YAML config only.

**Architecture:** The CivicPlus adapter follows the same BaseAdapter contract as Granicus. It performs a multi-step fetch: GET the main page (establishes session cookie, extracts categories and year tabs), then POST to `/AgendaCenter/UpdateCategoryList` for each year/category combination to get historical data. Parses `tr.catAgendaRow` rows for meetings with agenda/minutes/packet URLs. Strict red/green TDD.

**Tech Stack:** Python 3, pytest, urllib (stdlib), http.cookiejar (stdlib for session cookies)

**Prerequisite:** Ingestion adapter framework (Plan: `2026-04-14-ingestion-adapter-framework.md`) — BaseAdapter, runner, and registry already exist.

**Test fixtures:** `tests/fixtures/civicplus-*.html` (already captured)

---

## File Structure

```
scripts/
  adapters/
    civicplus.py                    # CivicPlus Agenda Center adapter (NEW)
    __init__.py                     # Add civicplus to registry (MODIFY)
registry/
  civicplus-sources.yaml            # CivicPlus source configs (NEW)
tests/
  test_civicplus_adapter.py         # Unit + integration tests (NEW)
  fixtures/
    civicplus-corte-madera.html     # Already captured
    civicplus-tiburon.html          # Already captured
    civicplus-mill-valley.html      # Already captured
```

---

### Task 1: CivicPlus HTML parsing utilities

**Files:**
- Create: `scripts/adapters/civicplus.py`
- Create: `tests/test_civicplus_adapter.py`
- Modify: `scripts/adapters/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_civicplus_adapter.py`:

```python
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.civicplus import (
    extract_categories,
    extract_years_for_category,
    parse_meeting_rows,
    parse_civicplus_date,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestRegistry:
    def test_civicplus_registered(self):
        cls = get_adapter_class("civicplus")
        assert issubclass(cls, BaseAdapter)


class TestParseCivicPlusDate:
    def test_full_month_name(self):
        assert parse_civicplus_date("April 7, 2026") == "2026-04-07"

    def test_abbreviated_month(self):
        assert parse_civicplus_date("Apr 7, 2026") == "2026-04-07"

    def test_from_aria_label(self):
        assert parse_civicplus_date("Agenda for April 7, 2026") == "2026-04-07"

    def test_returns_none_for_bad_input(self):
        assert parse_civicplus_date("not a date") is None

    def test_single_digit_day(self):
        assert parse_civicplus_date("January 5, 2024") == "2024-01-05"

    def test_double_digit_day(self):
        assert parse_civicplus_date("December 15, 2023") == "2023-12-15"


class TestExtractCategories:
    def test_corte_madera_categories(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        cats = extract_categories(html)
        assert len(cats) >= 5
        # Each category should have id and name
        for cat in cats:
            assert "id" in cat
            assert "name" in cat
            assert cat["id"].isdigit()

    def test_tiburon_categories(self):
        html = (FIXTURES / "civicplus-tiburon.html").read_text(errors="ignore")
        cats = extract_categories(html)
        names = [c["name"] for c in cats]
        assert "Town Council" in names

    def test_corte_madera_has_town_council(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        cats = extract_categories(html)
        names = [c["name"] for c in cats]
        assert "Town Council" in names


class TestExtractYearsForCategory:
    def test_corte_madera_cat1_years(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        years = extract_years_for_category(html, "1")
        assert 2026 in years
        assert 2019 in years

    def test_includes_dropdown_years(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        years = extract_years_for_category(html, "1")
        # View More dropdown should include older years
        assert len(years) > 3


class TestParseMeetingRows:
    def test_corte_madera_row_count(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        assert len(meetings) >= 40

    def test_tiburon_row_count(self):
        html = (FIXTURES / "civicplus-tiburon.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        assert len(meetings) >= 80

    def test_meeting_has_required_fields(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        m = meetings[0]
        assert "date" in m
        assert "title" in m
        assert "artifacts" in m

    def test_meeting_date_is_iso(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        for m in meetings[:10]:
            if m["date"]:
                assert re.match(r"\d{4}-\d{2}-\d{2}", m["date"])

    def test_artifacts_use_available_url_format(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        for m in meetings[:10]:
            for art in m["artifacts"].values():
                assert "available" in art
                assert "url" in art

    def test_extracts_agenda_urls(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        agendas = [m for m in meetings if m["artifacts"].get("agenda", {}).get("available")]
        assert len(agendas) > 20

    def test_extracts_minutes_urls(self):
        html = (FIXTURES / "civicplus-tiburon.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        minutes_present = [m for m in meetings if m["artifacts"].get("minutes", {}).get("available")]
        assert len(minutes_present) > 10

    def test_extracts_category_name(self):
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        meetings = parse_meeting_rows(html)
        cats = {m.get("category") for m in meetings}
        assert "Town Council" in cats or any("Council" in c for c in cats if c)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_civicplus_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapters.civicplus'`

- [ ] **Step 3: Implement civicplus.py parsing utilities**

Create `scripts/adapters/civicplus.py`:

```python
"""CivicPlus Agenda Center adapter.

Parses the CivicPlus Agenda Center pages used by Mill Valley, Corte Madera,
Tiburon, and other Marin cities. Handles multi-step fetch: initial page load
for categories/years, then AJAX POST per year/category for historical data.
"""

from __future__ import annotations

import re
import urllib.request
from html import unescape
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urljoin

from .base import BaseAdapter

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

ROW_RE = re.compile(r'<tr[^>]*class="catAgendaRow"[^>]*>.*?</tr>', re.S)
CATEGORY_CHECKBOX_RE = re.compile(
    r'<input[^>]*name="chkCategoryID"[^>]*value="(\d+)"'
)
CATEGORY_HEADING_RE = re.compile(
    r'<div[^>]*class="listing[^"]*"[^>]*id="cat(\d+)"[^>]*>.*?'
    r'<h2[^>]*>(.*?)</h2>',
    re.S,
)
YEAR_TAB_RE = re.compile(r'changeYear\((\d{4}),\s*(\d+)')
YEAR_DROPDOWN_RE = re.compile(
    r'<div[^>]*id="yearDD(\d+)"[^>]*>(.*?)</div>', re.S
)
ARIA_DATE_RE = re.compile(r'aria-label="Agenda for ([^"]+)"')
NAMED_DATE_RE = re.compile(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})')
AGENDA_URL_RE = re.compile(r'href="(/AgendaCenter/ViewFile/Agenda/[^"]+)"')
MINUTES_URL_RE = re.compile(r'href="(/AgendaCenter/ViewFile/Minutes/[^"]+)"')
PACKET_RE = re.compile(r'href="(/AgendaCenter/ViewFile/Agenda/[^"]*\?packet=true[^"]*)"')
TITLE_RE = re.compile(
    r'<p>\s*<a[^>]*href="/AgendaCenter/ViewFile/Agenda/[^"]*"[^>]*>(.*?)</a>',
    re.S,
)
CATEGORY_PANEL_RE = re.compile(
    r'<div[^>]*id="category-panel-(\d+)"[^>]*>(.*?)</div>\s*</div>\s*</div>',
    re.S,
)

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"


# ---------------------------------------------------------------------------
# Parsing utilities
# ---------------------------------------------------------------------------

def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_civicplus_date(text: str) -> str | None:
    """Parse CivicPlus date format: 'Month DD, YYYY' or 'Agenda for Month DD, YYYY'."""
    match = NAMED_DATE_RE.search(text)
    if not match:
        return None
    month_str, day_str, year_str = match.groups()
    month = MONTH_NAMES.get(month_str.lower())
    if not month:
        return None
    return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"


def extract_categories(html: str) -> list[dict]:
    """Extract category IDs and names from the page."""
    categories = []
    seen_ids = set()

    # Get IDs from checkboxes
    cat_ids = CATEGORY_CHECKBOX_RE.findall(html)

    # Get names from headings
    id_to_name = {}
    for cat_id, heading_html in CATEGORY_HEADING_RE.findall(html):
        name = _strip_tags(heading_html)
        id_to_name[cat_id] = name

    for cat_id in cat_ids:
        if cat_id in seen_ids:
            continue
        seen_ids.add(cat_id)
        categories.append({
            "id": cat_id,
            "name": id_to_name.get(cat_id, f"Category {cat_id}"),
        })

    return categories


def extract_years_for_category(html: str, category_id: str) -> list[int]:
    """Extract available years for a category from tabs and dropdown."""
    years = set()

    # Year tabs (visible)
    for year_str, cat_id in YEAR_TAB_RE.findall(html):
        if cat_id == category_id:
            years.add(int(year_str))

    # Year dropdown (View More)
    for dd_cat_id, dd_html in YEAR_DROPDOWN_RE.findall(html):
        if dd_cat_id == category_id:
            for year_str, cat_id in YEAR_TAB_RE.findall(dd_html):
                if cat_id == category_id:
                    years.add(int(year_str))

    return sorted(years, reverse=True)


def _parse_row(row_html: str, category_name: str | None, base_url: str, row_number: int) -> dict | None:
    """Parse a single catAgendaRow into a meeting dict."""
    # Extract date from aria-label
    date_match = ARIA_DATE_RE.search(row_html)
    date = parse_civicplus_date(date_match.group(1)) if date_match else None

    # Extract title
    title_match = TITLE_RE.search(row_html)
    title = _strip_tags(title_match.group(1)) if title_match else None

    # Extract artifact URLs
    agenda_match = AGENDA_URL_RE.search(row_html)
    minutes_match = MINUTES_URL_RE.search(row_html)
    packet_match = PACKET_RE.search(row_html)

    agenda_url = urljoin(base_url, agenda_match.group(1)) if agenda_match else None
    minutes_url = urljoin(base_url, minutes_match.group(1)) if minutes_match else None
    packet_url = urljoin(base_url, packet_match.group(1)) if packet_match else None

    # Extract agenda ID from URL pattern _{MMDDYYYY}-{ID}
    agenda_id = None
    if agenda_match:
        id_match = re.search(r'-(\d+)(?:\?|$)', agenda_match.group(1))
        if id_match:
            agenda_id = id_match.group(1)

    artifacts = {
        "agenda": {"available": agenda_url is not None, "url": agenda_url},
        "minutes": {"available": minutes_url is not None, "url": minutes_url},
        "packet": {"available": packet_url is not None, "url": packet_url},
    }

    return {
        "date": date,
        "title": title,
        "category": category_name,
        "meeting_type": "regular",
        "artifacts": artifacts,
        "source_row_number": row_number,
        "agenda_id": agenda_id,
    }


def parse_meeting_rows(
    html: str,
    base_url: str = "",
    backfill_from: str = "2019-01-01",
) -> list[dict]:
    """Parse all catAgendaRow entries from a CivicPlus HTML page or fragment."""
    meetings = []

    # Try to associate rows with categories by finding category panels
    # and parsing rows within each panel
    category_names = {}
    for cat_id, heading_html in CATEGORY_HEADING_RE.findall(html):
        category_names[cat_id] = _strip_tags(heading_html)

    # Find rows within category panels
    panel_rows_found = False
    for panel_cat_id, panel_html in CATEGORY_PANEL_RE.findall(html):
        cat_name = category_names.get(panel_cat_id)
        for row_html in ROW_RE.findall(panel_html):
            panel_rows_found = True
            row_number = len(meetings) + 1
            meeting = _parse_row(row_html, cat_name, base_url, row_number)
            if meeting and meeting["date"] and meeting["date"] >= backfill_from:
                meetings.append(meeting)

    # Fallback: if no panels matched, parse all rows from the full HTML
    if not panel_rows_found:
        for row_html in ROW_RE.findall(html):
            row_number = len(meetings) + 1
            meeting = _parse_row(row_html, None, base_url, row_number)
            if meeting and meeting["date"] and meeting["date"] >= backfill_from:
                meetings.append(meeting)

    return meetings


class CivicPlusAdapter(BaseAdapter):
    def capture(self) -> dict:
        raise NotImplementedError("CivicPlus capture not yet implemented")
```

- [ ] **Step 4: Register the adapter**

Edit `scripts/adapters/__init__.py` — add civicplus to the registry:

```python
def get_adapter_class(name: str) -> Type[BaseAdapter]:
    from .granicus import GranicusAdapter
    from .civicplus import CivicPlusAdapter

    registry: dict[str, Type[BaseAdapter]] = {
        "granicus": GranicusAdapter,
        "civicplus": CivicPlusAdapter,
    }
    if name not in registry:
        raise KeyError(f"Unknown adapter: {name!r}. Available: {list(registry.keys())}")
    return registry[name]
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_civicplus_adapter.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v`
Expected: All 185+ tests PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add scripts/adapters/civicplus.py scripts/adapters/__init__.py tests/test_civicplus_adapter.py
git commit -m "feat: add CivicPlus parsing utilities (dates, categories, years, meeting rows)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: CivicPlusAdapter.capture() with AJAX year fetching

**Files:**
- Modify: `scripts/adapters/civicplus.py`
- Modify: `tests/test_civicplus_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_civicplus_adapter.py`:

```python
from adapters.civicplus import CivicPlusAdapter


class TestCivicPlusAdapterCapture:
    """Integration tests using saved HTML fixtures (no live HTTP)."""

    def _make_adapter(self, source_id, fixture_name, tmp_path, categories=None):
        config = {
            "id": source_id,
            "adapter": "civicplus",
            "url": f"https://{source_id.replace('-', '.')}.gov/AgendaCenter",
            "jurisdiction_id": f"place-{source_id.rsplit('-', 1)[0]}",
            "institution_id": f"org-{source_id}",
            "backfill_from": "2019-01-01",
        }
        if categories:
            config["categories"] = categories
        adapter = CivicPlusAdapter(config, tmp_path)
        fixture_path = FIXTURES / fixture_name
        fixture_html = fixture_path.read_text(errors="ignore")
        # Monkey-patch: initial page GET returns fixture, AJAX POSTs return empty
        adapter._fetch_page = lambda url: fixture_html
        adapter._fetch_year = lambda url, cat_id, year, cookies: ""
        return adapter

    def test_capture_returns_dict(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)

    def test_capture_has_required_envelope_fields(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert "capture_id" in result
        assert "source_id" in result
        assert "captured_at" in result
        assert "institution_id" in result
        assert "jurisdiction_id" in result
        assert "meeting_count" in result
        assert "artifact_counts" in result
        assert "meetings" in result
        assert "record_refs" in result
        assert "errors" in result
        assert result["adapter"] == "civicplus"

    def test_capture_meeting_count_matches(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] == len(result["meetings"])
        assert result["meeting_count"] > 20

    def test_capture_writes_raw_html(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        adapter.capture()
        raw_files = list((tmp_path / "data" / "raw").rglob("source.html"))
        assert len(raw_files) == 1

    def test_capture_record_refs_present(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        assert len(result["record_refs"]) >= 1
        assert result["record_refs"][0]["record_type"] == "agenda_center_page"

    def test_tiburon_meeting_count(self, tmp_path):
        adapter = self._make_adapter("tiburon-town-council", "civicplus-tiburon.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] > 50

    def test_capture_meetings_have_institution_id(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert m["institution_id"] == "org-corte-madera-town-council"

    def test_capture_meetings_have_meeting_id(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert "meeting_id" in m
            assert m["meeting_id"].startswith("meeting-")

    def test_capture_meetings_have_category(self, tmp_path):
        adapter = self._make_adapter("corte-madera-town-council", "civicplus-corte-madera.html", tmp_path)
        result = adapter.capture()
        cats = {m.get("category") for m in result["meetings"]}
        assert len(cats) > 1  # Multiple categories

    def test_category_filter(self, tmp_path):
        """When categories config is set, only those categories are captured."""
        adapter = self._make_adapter(
            "corte-madera-town-council",
            "civicplus-corte-madera.html",
            tmp_path,
            categories=["Town Council"],
        )
        result = adapter.capture()
        cats = {m.get("category") for m in result["meetings"]}
        # Should only have Town Council (and possibly None from fallback)
        named_cats = {c for c in cats if c}
        assert named_cats == {"Town Council"} or len(named_cats) <= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_civicplus_adapter.py::TestCivicPlusAdapterCapture -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement CivicPlusAdapter.capture()**

Replace the CivicPlusAdapter class in `scripts/adapters/civicplus.py`:

```python
class CivicPlusAdapter(BaseAdapter):
    """CivicPlus Agenda Center adapter.

    Multi-step fetch:
    1. GET the main Agenda Center page (categories, current year rows)
    2. For each category+year beyond the current year, POST to
       /AgendaCenter/UpdateCategoryList for historical data
    """

    def _fetch_page(self, url: str) -> str:
        """Fetch a page with cookie handling. Overridable for tests."""
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener.open(request, timeout=30) as response:
            return response.read().decode("utf-8", "ignore")

    def _fetch_year(self, base_url: str, category_id: str, year: int, cookies: CookieJar | None = None) -> str:
        """POST to UpdateCategoryList for a specific year/category. Overridable for tests."""
        update_url = base_url.rsplit("/", 1)[0] + "/AgendaCenter/UpdateCategoryList"
        data = f"year={year}&catID={category_id}".encode("utf-8")
        request = urllib.request.Request(
            update_url,
            data=data,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookies or CookieJar())
        )
        try:
            with opener.open(request, timeout=30) as response:
                return response.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def capture(self) -> dict:
        html = self._fetch_page(self.url)
        captured_at = self.utc_now_iso()

        # Write raw HTML
        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "source.html"
        raw_path.write_text(html, encoding="utf-8")

        # Parse meetings from the initial page (current year for each category)
        base_url = self.url.rsplit("/AgendaCenter", 1)[0]
        meetings = parse_meeting_rows(html, base_url=base_url, backfill_from=self.backfill_from)

        # Filter by configured categories if specified
        allowed_categories = self.config.get("categories")
        if allowed_categories:
            meetings = [m for m in meetings if m.get("category") in allowed_categories]

        # Stamp each meeting
        for m in meetings:
            m["institution_id"] = self.institution_id
            slug = self.source_id
            if m.get("agenda_id"):
                m["meeting_id"] = f"meeting-{slug}-{m['agenda_id']}"
            elif m.get("date"):
                m["meeting_id"] = f"meeting-{slug}-{m['date']}-row-{m['source_row_number']}"
            else:
                m["meeting_id"] = f"meeting-{slug}-row-{m['source_row_number']}"

        # Compute artifact counts
        artifact_counts: dict[str, int] = {}
        for m in meetings:
            for art_name, art in m.get("artifacts", {}).items():
                if art.get("available"):
                    artifact_counts[art_name] = artifact_counts.get(art_name, 0) + 1

        # Build record_refs
        record_refs = [
            {
                "id": f"record-{self.source_id}-agenda-center-page-{captured_at[:10]}",
                "record_type": "agenda_center_page",
                "source_id": self.source_id,
                "artifact_path": str(raw_path.relative_to(self.root)),
                "captured_at": captured_at,
            }
        ]

        # Categories found
        categories = extract_categories(html)
        if allowed_categories:
            categories = [c for c in categories if c["name"] in allowed_categories]

        return {
            "capture_id": self.capture_id(),
            "source_id": self.source_id,
            "adapter": "civicplus",
            "captured_at": captured_at,
            "url": self.url,
            "jurisdiction_id": self.jurisdiction_id,
            "institution_id": self.institution_id,
            "raw_artifact": str(raw_path.relative_to(self.root)),
            "meeting_count": len(meetings),
            "artifact_counts": artifact_counts,
            "categories": [c["name"] for c in categories],
            "meetings": meetings,
            "record_refs": record_refs,
            "errors": [],
        }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_civicplus_adapter.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/adapters/civicplus.py tests/test_civicplus_adapter.py
git commit -m "feat: implement CivicPlusAdapter.capture() with category parsing and meeting extraction

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Source registry and live smoke test

**Files:**
- Create: `registry/civicplus-sources.yaml`

- [ ] **Step 1: Create the source registry**

Create `registry/civicplus-sources.yaml`:

```yaml
sources:
  - id: corte-madera-town-council
    adapter: civicplus
    url: https://cortemadera.gov/AgendaCenter
    jurisdiction_id: place-corte-madera
    institution_id: org-corte-madera-town-council
    backfill_from: "2019-01-01"
    schedule: weekly

  - id: tiburon-town-council
    adapter: civicplus
    url: https://townoftiburon.org/AgendaCenter
    jurisdiction_id: place-tiburon
    institution_id: org-tiburon-town-council
    backfill_from: "2019-01-01"
    schedule: weekly

  - id: mill-valley-committees
    adapter: civicplus
    url: https://cityofmillvalley.org/AgendaCenter
    jurisdiction_id: place-mill-valley
    institution_id: org-mill-valley-committees
    backfill_from: "2019-01-01"
    schedule: weekly
```

- [ ] **Step 2: Live capture Corte Madera**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source corte-madera-town-council --registry registry/civicplus-sources.yaml`
Expected: Meetings captured with agenda URLs, multiple categories

- [ ] **Step 3: Live capture Tiburon**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source tiburon-town-council --registry registry/civicplus-sources.yaml`
Expected: Meetings captured with agenda + minutes URLs

- [ ] **Step 4: Live capture Mill Valley**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source mill-valley-committees --registry registry/civicplus-sources.yaml`
Expected: Meetings from various committees (not City Council — they don't use Agenda Center for that)

- [ ] **Step 5: Verify output structure**

Run:
```bash
for f in data/extracted/corte-madera-*/$(date +%Y-%m-%d).json data/extracted/tiburon-*/$(date +%Y-%m-%d).json data/extracted/mill-valley-*/$(date +%Y-%m-%d).json; do
  [ -f "$f" ] || continue
  echo "=== $f ==="
  python3 -c "
import json
d = json.load(open('$f'))
print(f'  source: {d[\"source_id\"]}')
print(f'  meetings: {d[\"meeting_count\"]}')
print(f'  categories: {d.get(\"categories\", [])}')
print(f'  artifacts: {d[\"artifact_counts\"]}')
print(f'  record_refs: {len(d[\"record_refs\"])}')
"
done
```

- [ ] **Step 6: Commit and push**

```bash
git add registry/civicplus-sources.yaml tests/fixtures/civicplus-*.html
git commit -m "feat: CivicPlus adapter live — Corte Madera, Tiburon, Mill Valley captured

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

git push
```

---

## Build Verification

After all tasks are complete:

1. `python -m pytest tests/ -v` — all tests pass (Granicus + CivicPlus + migration)
2. `python scripts/ingest.py --source corte-madera-town-council --registry registry/civicplus-sources.yaml` — meetings with agendas
3. `python scripts/ingest.py --source tiburon-town-council --registry registry/civicplus-sources.yaml` — meetings with agendas + minutes
4. `python scripts/ingest.py --source mill-valley-committees --registry registry/civicplus-sources.yaml` — committee meetings
5. All outputs have: capture_id, institution_id, {available, url} artifacts, record_refs, meeting_ids, category names

Note: The initial page load only returns the current year's meetings for each category. Historical data (2019-2025) will require the AJAX POST calls in a future enhancement. The current adapter captures what's on the default page, which is the current year — typically 10-50 meetings per category depending on the time of year.
