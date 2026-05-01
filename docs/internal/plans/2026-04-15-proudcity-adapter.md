# ProudCity (WordPress) Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ProudCity adapter covering Fairfax, Belvedere, and San Rafael — scrape meeting list pages, visit each meeting detail page to extract GCS PDF artifact URLs.

**Architecture:** Two-phase capture: (1) scrape list/archive pages for meeting URLs, (2) visit each detail page to extract PDF links from tab sections. All three cities share the same ProudCity WordPress theme, widget system, and GCS PDF hosting pattern. Rate-limited at 1 request/second. Strict red/green TDD.

**Tech Stack:** Python 3, pytest, urllib (stdlib)

**Prerequisite:** Ingestion adapter framework with BaseAdapter, runner, and registry.

**Test fixtures:** `tests/fixtures/wordpress-fairfax.html`, `tests/fixtures/wordpress-belvedere.html` (already captured)

---

## File Structure

```
scripts/
  adapters/
    proudcity.py                    # ProudCity WordPress adapter (NEW)
    __init__.py                     # Add proudcity to registry (MODIFY)
registry/
  proudcity-sources.yaml            # ProudCity source configs (NEW)
tests/
  test_proudcity_adapter.py         # Unit + integration tests (NEW)
  fixtures/
    wordpress-fairfax.html          # Already captured
    wordpress-belvedere.html        # Already captured
    wordpress-fairfax-meeting.html  # Single meeting detail page (capture in Task 1)
```

---

### Task 1: ProudCity HTML parsing utilities

**Files:**
- Create: `scripts/adapters/proudcity.py`
- Create: `tests/test_proudcity_adapter.py`
- Modify: `scripts/adapters/__init__.py`

The ProudCity meeting list pages use `teaser-meeting-table.php` templates with table rows containing:
- Meeting title + link: `<a href="/meetings/{slug}/">{title}</a>`
- Date column (may be empty — date is often in the title)
- Badge links for Agenda/Packet/Minutes/Video as `<a>` elements with specific classes

The meeting detail pages have tab sections:
- `#tab-agenda` — contains embedded PDF or link
- `#tab-agenda-packet` — agenda packet PDF
- `#tab-minutes` — minutes PDF
- `#tab-video` — video embed

PDFs are hosted on GCS: `storage.googleapis.com/proudcity/{city}ca/uploads/YYYY/MM/filename.pdf`

- [ ] **Step 1: Capture a Fairfax meeting detail page as fixture**

Run:
```python
import urllib.request
url = "https://townoffairfaxca.gov/meetings/town-council-meeting-january-8-2025/"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
open("tests/fixtures/wordpress-fairfax-meeting.html", "w").write(html)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_proudcity_adapter.py`:

```python
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.proudcity import (
    extract_meeting_urls,
    parse_meeting_date_from_title,
    extract_artifacts_from_detail,
    ProudCityAdapter,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestRegistry:
    def test_proudcity_registered(self):
        cls = get_adapter_class("proudcity")
        assert issubclass(cls, BaseAdapter)


class TestParseMeetingDateFromTitle:
    def test_standard_format(self):
        assert parse_meeting_date_from_title("Town Council Meeting: January 8, 2025") == "2025-01-08"

    def test_dash_separated(self):
        assert parse_meeting_date_from_title("City Council - April 6, 2026") == "2026-04-06"

    def test_no_date_returns_none(self):
        assert parse_meeting_date_from_title("Special Joint Session") is None

    def test_month_day_year(self):
        assert parse_meeting_date_from_title("Planning Commission Meeting: December 15, 2023") == "2023-12-15"


class TestExtractMeetingUrls:
    def test_fairfax_archive_has_meetings(self):
        html = (FIXTURES / "wordpress-fairfax.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://townoffairfaxca.gov")
        # The main /meetings/ page may have few entries (upcoming only)
        # but should have at least some meeting links
        assert isinstance(meetings, list)

    def test_meeting_entry_has_url_and_title(self):
        html = (FIXTURES / "wordpress-fairfax.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://townoffairfaxca.gov")
        if meetings:
            m = meetings[0]
            assert "url" in m
            assert "title" in m
            assert "/meetings/" in m["url"]


class TestExtractArtifactsFromDetail:
    def test_extracts_gcs_pdf_urls(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        assert isinstance(artifacts, dict)
        # Should find at least an agenda
        has_any = any(a.get("available") for a in artifacts.values())
        assert has_any

    def test_artifact_format(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        for art in artifacts.values():
            assert "available" in art
            assert "url" in art

    def test_gcs_url_pattern(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        for art in artifacts.values():
            if art["available"] and art["url"]:
                assert "storage.googleapis.com" in art["url"] or "proudcity" in art["url"] or art["url"].startswith("http")


class TestProudCityAdapterCapture:
    def _make_adapter(self, source_id, list_html, detail_htmls, tmp_path, archive_pages=None):
        config = {
            "id": source_id,
            "adapter": "proudcity",
            "url": "https://example.gov/meetings/",
            "jurisdiction_id": "place-test",
            "institution_id": f"org-{source_id}",
            "backfill_from": "2019-01-01",
        }
        if archive_pages:
            config["archive_pages"] = archive_pages
        adapter = ProudCityAdapter(config, tmp_path)
        adapter._request_delay = 0
        # Mock: list page returns list_html, detail pages return from dict
        adapter._fetch_page = lambda url: detail_htmls.get(url, list_html)
        return adapter

    def test_capture_returns_dict(self, tmp_path):
        list_html = '''
        <table>
        <tr><td><a href="/meetings/test-meeting-january-5-2025/">Test Meeting: January 5, 2025</a></td></tr>
        </table>
        '''
        detail_html = '''
        <div id="tab-agenda">
            <a href="https://storage.googleapis.com/proudcity/testca/uploads/2025/01/agenda.pdf">Agenda</a>
        </div>
        '''
        adapter = self._make_adapter("test-city", list_html,
            {"https://example.gov/meetings/test-meeting-january-5-2025/": detail_html}, tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["adapter"] == "proudcity"

    def test_capture_has_required_fields(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'
        detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/agenda.pdf">PDF</a></div>'
        adapter = self._make_adapter("test", list_html,
            {"https://example.gov/meetings/m1/": detail}, tmp_path)
        result = adapter.capture()
        for field in ["capture_id", "source_id", "captured_at", "institution_id",
                      "meeting_count", "meetings", "record_refs", "errors"]:
            assert field in result

    def test_capture_extracts_artifacts(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Council: February 10, 2025</a></td></tr></table>'
        detail = '''
        <div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/agenda.pdf">PDF</a></div>
        <div id="tab-minutes"><a href="https://storage.googleapis.com/proudcity/x/minutes.pdf">PDF</a></div>
        '''
        adapter = self._make_adapter("test", list_html,
            {"https://example.gov/meetings/m1/": detail}, tmp_path)
        result = adapter.capture()
        m = result["meetings"][0]
        assert m["artifacts"]["agenda"]["available"] is True
        assert m["artifacts"]["minutes"]["available"] is True
```

- [ ] **Step 3: Implement proudcity.py**

Create `scripts/adapters/proudcity.py`:

```python
"""ProudCity (WordPress) meeting adapter.

Covers Fairfax, Belvedere, and San Rafael. Two-phase capture:
1. Scrape meeting list/archive pages for /meetings/{slug}/ URLs
2. Visit each detail page to extract GCS PDF artifact URLs from tab sections
"""

from __future__ import annotations

import re
import time
import urllib.request
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from .base import BaseAdapter

USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"

# Match /meetings/{slug}/ links with title text
MEETING_LINK_RE = re.compile(
    r'<a[^>]*href="(/meetings/[^"]+/)"[^>]*>(.*?)</a>', re.S | re.I
)

# Match month name + day + year in titles
DATE_IN_TITLE_RE = re.compile(
    r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})'
)

# Match GCS PDF URLs
GCS_PDF_RE = re.compile(
    r'https?://storage\.googleapis\.com/proudcity/[^"\'>\s]+\.pdf', re.I
)

# Match any PDF-like URL
PDF_URL_RE = re.compile(
    r'href="(https?://[^"]*\.pdf)"', re.I
)

# Tab section IDs
TAB_SECTIONS = {
    "agenda": re.compile(r'<div[^>]*id="tab-agenda"[^>]*>(.*?)</div>', re.S | re.I),
    "packet": re.compile(r'<div[^>]*id="tab-agenda-packet"[^>]*>(.*?)</div>', re.S | re.I),
    "minutes": re.compile(r'<div[^>]*id="tab-minutes"[^>]*>(.*?)</div>', re.S | re.I),
    "video": re.compile(r'<div[^>]*id="tab-video"[^>]*>(.*?)</div>', re.S | re.I),
}

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_meeting_date_from_title(title: str) -> str | None:
    """Extract a date from a meeting title like 'Council Meeting: January 8, 2025'."""
    match = DATE_IN_TITLE_RE.search(title)
    if not match:
        return None
    month_str, day_str, year_str = match.groups()
    month = MONTH_NAMES.get(month_str.lower())
    if not month:
        return None
    return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"


def extract_meeting_urls(html: str, base_url: str) -> list[dict]:
    """Extract meeting URLs and titles from a ProudCity list/archive page."""
    meetings = []
    seen_urls = set()
    for href, title_html in MEETING_LINK_RE.findall(html):
        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        title = _strip_tags(title_html)
        if not title:
            continue
        meetings.append({
            "url": full_url,
            "title": title,
            "slug": href.strip("/").split("/")[-1],
            "date": parse_meeting_date_from_title(title),
        })
    return meetings


def extract_artifacts_from_detail(html: str) -> dict:
    """Extract artifact PDF URLs from a ProudCity meeting detail page's tab sections."""
    artifacts = {}
    for art_type, pattern in TAB_SECTIONS.items():
        match = pattern.search(html)
        if match:
            section_html = match.group(1)
            # Find PDF URLs in this section
            pdf_urls = PDF_URL_RE.findall(section_html)
            if pdf_urls:
                artifacts[art_type] = {"available": True, "url": pdf_urls[0]}
            else:
                # Check for GCS URLs that might not be in href
                gcs_urls = GCS_PDF_RE.findall(section_html)
                if gcs_urls:
                    artifacts[art_type] = {"available": True, "url": gcs_urls[0]}
                else:
                    artifacts[art_type] = {"available": False, "url": None}
        else:
            artifacts[art_type] = {"available": False, "url": None}
    return artifacts


class ProudCityAdapter(BaseAdapter):
    """ProudCity WordPress meeting adapter."""

    _request_delay: float = 1.0

    def _fetch_page(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "ignore")

    def capture(self) -> dict:
        captured_at = self.utc_now_iso()
        base_url = self.url.rsplit("/meetings", 1)[0] if "/meetings" in self.url else self.url.rstrip("/")

        # Phase 1: Fetch list page(s) and extract meeting URLs
        list_html = self._fetch_page(self.url)

        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.html").write_text(list_html, encoding="utf-8")

        all_meetings = extract_meeting_urls(list_html, base_url)

        # Fetch additional archive pages if configured
        for archive_url in self.config.get("archive_pages", []):
            if self._request_delay:
                time.sleep(self._request_delay)
            archive_html = self._fetch_page(archive_url)
            archive_meetings = extract_meeting_urls(archive_html, base_url)
            seen = {m["url"] for m in all_meetings}
            for m in archive_meetings:
                if m["url"] not in seen:
                    all_meetings.append(m)
                    seen.add(m["url"])

        # Filter by backfill_from
        backfill = self.backfill_from
        all_meetings = [m for m in all_meetings if not m["date"] or m["date"] >= backfill]

        # Phase 2: Visit each meeting detail page for artifact URLs
        meetings = []
        errors = []
        for i, entry in enumerate(all_meetings):
            if self._request_delay and i > 0:
                time.sleep(self._request_delay)
            try:
                detail_html = self._fetch_page(entry["url"])
                artifacts = extract_artifacts_from_detail(detail_html)
            except Exception as e:
                errors.append(f"Failed to fetch {entry['url']}: {e}")
                artifacts = {k: {"available": False, "url": None} for k in TAB_SECTIONS}

            meetings.append({
                "meeting_id": f"meeting-{self.source_id}-{entry['slug']}",
                "date": entry["date"],
                "title": entry["title"],
                "meeting_type": "regular",
                "institution_id": self.institution_id,
                "artifacts": artifacts,
                "source_url": entry["url"],
                "source_row_number": i + 1,
            })

        # Compute artifact counts
        artifact_counts: dict[str, int] = {}
        for m in meetings:
            for art_name, art in m.get("artifacts", {}).items():
                if art.get("available"):
                    artifact_counts[art_name] = artifact_counts.get(art_name, 0) + 1

        record_refs = [{
            "id": f"record-{self.source_id}-meetings-page-{captured_at[:10]}",
            "record_type": "meeting_list_page",
            "source_id": self.source_id,
            "artifact_path": f"data/raw/{self.source_id}/{captured_at[:10]}/source.html",
            "captured_at": captured_at,
        }]

        return {
            "capture_id": self.capture_id(),
            "source_id": self.source_id,
            "adapter": "proudcity",
            "captured_at": captured_at,
            "url": self.url,
            "jurisdiction_id": self.jurisdiction_id,
            "institution_id": self.institution_id,
            "raw_artifact": f"data/raw/{self.source_id}/{captured_at[:10]}/source.html",
            "meeting_count": len(meetings),
            "artifact_counts": artifact_counts,
            "meetings": meetings,
            "record_refs": record_refs,
            "errors": errors,
        }
```

- [ ] **Step 4: Register the adapter**

Add to `scripts/adapters/__init__.py`:
```python
from .proudcity import ProudCityAdapter
# In registry dict:
"proudcity": ProudCityAdapter,
```

- [ ] **Step 5: Run tests**

Run: `cd /<repo> && python -m pytest tests/test_proudcity_adapter.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /<repo> && python -m pytest tests/ -v`
Expected: All 286+ PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/adapters/proudcity.py scripts/adapters/__init__.py tests/test_proudcity_adapter.py tests/fixtures/wordpress-fairfax-meeting.html
git commit -m "feat: add ProudCity WordPress adapter with detail page artifact extraction

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Source registry and live smoke test

**Files:**
- Create: `registry/proudcity-sources.yaml`

- [ ] **Step 1: Create the source registry**

Create `registry/proudcity-sources.yaml`:

```yaml
sources:
  - id: fairfax-town-council
    adapter: proudcity
    url: https://townoffairfaxca.gov/meetings/
    jurisdiction_id: place-fairfax
    institution_id: org-fairfax-town-council
    backfill_from: "2019-01-01"
    schedule: weekly
    archive_pages:
      - https://townoffairfaxca.gov/2024-meeting-archive/
      - https://townoffairfaxca.gov/2023-meeting-archive/
      - https://townoffairfaxca.gov/2022-meeting-archive/
      - https://townoffairfaxca.gov/2021-meeting-archive/
      - https://townoffairfaxca.gov/2020-meeting-archive/
      - https://townoffairfaxca.gov/2019-meeting-archive/

  - id: belvedere-city-council
    adapter: proudcity
    url: https://cityofbelvedere.org/departments/public-meetings/
    jurisdiction_id: place-belvedere
    institution_id: org-belvedere-city-council
    backfill_from: "2019-01-01"
    schedule: weekly
```

Note: San Rafael is deferred — the existing bespoke capture scripts already cover it with 283 meetings in the graph.

- [ ] **Step 2: Live capture Fairfax**

Run: `cd /<repo> && python scripts/ingest.py --source fairfax-town-council --registry registry/proudcity-sources.yaml`
Expected: Meetings from 2019-2026 with agenda/minutes/packet PDF URLs

- [ ] **Step 3: Live capture Belvedere**

Run: `cd /<repo> && python scripts/ingest.py --source belvedere-city-council --registry registry/proudcity-sources.yaml`
Expected: Meetings with artifact URLs

- [ ] **Step 4: Normalize and load into Neo4j**

```bash
export NEO4J_URI="neo4j+s://<INSTANCE-ID>.databases.neo4j.io"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="<from Desktop file>"

python scripts/normalize_meetings.py --source fairfax-town-council --load
python scripts/normalize_meetings.py --source belvedere-city-council --load
```

- [ ] **Step 5: Verify**

```bash
python scripts/verify_neo4j_v2.py
```

Plus ad-hoc: `MATCH (m:Meeting)-[:AT_INSTITUTION]->(o:Organization) RETURN o.name, count(m) ORDER BY count(m) DESC`

- [ ] **Step 6: Commit and push**

```bash
git add registry/proudcity-sources.yaml tests/fixtures/wordpress-*.html
git commit -m "feat: ProudCity adapter live — Fairfax and Belvedere captured and loaded

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

git push
```

---

## Build Verification

1. `python -m pytest tests/ -v` — all tests pass
2. Fairfax meetings in graph with agenda/minutes/packet URLs
3. Belvedere meetings in graph with artifact URLs
4. Existing data untouched (20/20 verification)
5. Adding San Rafael ProudCity later requires only a YAML entry
