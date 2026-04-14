# Ingestion Adapter Framework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a configurable ingestion framework where the Granicus adapter captures meeting archives from Marin County BOS, Novato, and Sausalito using only YAML config differences — no source-specific code.

**Architecture:** A thin runner reads `registry/sources.yaml`, dispatches to the appropriate adapter class, and writes structured JSON output. The Granicus adapter auto-detects legacy vs. modern template variants and uses the corresponding parser. Strict red/green TDD throughout.

**Tech Stack:** Python 3, pytest, urllib (stdlib HTTP), re (stdlib regex)

**Spec:** `docs/specs/2026-04-14-ingestion-adapter-framework-design.md`

**Test fixtures:** `tests/fixtures/granicus-*.html` (already captured from live Granicus pages)

---

## File Structure

```
scripts/
  ingest.py                         # CLI runner: load YAML, dispatch adapter
  adapters/
    __init__.py                     # Adapter registry (name -> class mapping)
    base.py                         # BaseAdapter ABC
    granicus.py                     # Granicus adapter (legacy + modern parsers)
registry/
  sources.yaml                      # Source instance configs
tests/
  test_granicus_adapter.py          # Unit + integration tests for Granicus adapter
  test_ingest_runner.py             # Tests for the runner CLI
  fixtures/
    granicus-marin-county-bos.html         # Legacy template (already captured)
    granicus-novato-city-council.html      # Modern template (already captured)
    granicus-sausalito-city-council.html   # Modern template (already captured)
```

---

### Task 0: Install PyYAML dependency

**Files:**
- Modify: `requirements-migration.txt`

- [ ] **Step 1: Add PyYAML to requirements**

Add `pyyaml>=6.0` to `requirements-migration.txt` (the runner uses `yaml.safe_load` to parse the source registry).

- [ ] **Step 2: Install**

Run: `pip install -r requirements-migration.txt`

- [ ] **Step 3: Commit**

```bash
git add requirements-migration.txt
git commit -m "chore: add PyYAML dependency for source registry parsing

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 1: BaseAdapter and adapter registry

**Files:**
- Create: `scripts/adapters/__init__.py`
- Create: `scripts/adapters/base.py`
- Test: `tests/test_granicus_adapter.py` (initial structure)

- [ ] **Step 1: Write the failing test**

Create `tests/test_granicus_adapter.py`:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter


class TestAdapterRegistry:
    def test_get_granicus_adapter(self):
        cls = get_adapter_class("granicus")
        assert cls is not None
        assert issubclass(cls, BaseAdapter)

    def test_unknown_adapter_raises(self):
        with pytest.raises(KeyError):
            get_adapter_class("nonexistent")


class TestBaseAdapterContract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseAdapter({}, Path("."))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py::TestAdapterRegistry -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapters'`

- [ ] **Step 3: Implement base.py**

Create `scripts/adapters/base.py`:

```python
"""Base adapter contract for all ingestion adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path


class BaseAdapter(ABC):
    """Abstract base for source adapters.

    Subclasses implement capture() which fetches from a source URL
    and returns a structured dict that gets serialized as extracted JSON.
    """

    def __init__(self, source_config: dict, root_dir: Path):
        self.config = source_config
        self.root = root_dir
        self.source_id: str = source_config["id"]
        self.url: str = source_config["url"]
        self.jurisdiction_id: str = source_config["jurisdiction_id"]
        self.institution_id: str = source_config["institution_id"]
        self.backfill_from: str = source_config.get("backfill_from", "2019-01-01")

    @abstractmethod
    def capture(self) -> dict:
        """Fetch and parse the source. Returns the extracted JSON dict."""

    def raw_dir(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.root / "data" / "raw" / self.source_id / today

    def extracted_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.root / "data" / "extracted" / self.source_id / f"{today}.json"

    def capture_id(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self.source_id}__{today}"

    def utc_now_iso(self) -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
```

- [ ] **Step 4: Implement __init__.py**

Create `scripts/adapters/__init__.py`:

```python
"""Adapter registry — maps adapter names to classes."""

from __future__ import annotations

from typing import Type

from .base import BaseAdapter


def get_adapter_class(name: str) -> Type[BaseAdapter]:
    """Look up an adapter class by name. Raises KeyError if not found."""
    # Lazy import to avoid circular deps when more adapters are added
    from .granicus import GranicusAdapter

    registry: dict[str, Type[BaseAdapter]] = {
        "granicus": GranicusAdapter,
    }
    if name not in registry:
        raise KeyError(f"Unknown adapter: {name!r}. Available: {list(registry.keys())}")
    return registry[name]
```

- [ ] **Step 5: Create a minimal granicus.py stub so imports work**

Create `scripts/adapters/granicus.py`:

```python
"""Granicus Publisher View adapter — stub for import resolution."""

from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter


class GranicusAdapter(BaseAdapter):
    def capture(self) -> dict:
        raise NotImplementedError("Granicus capture not yet implemented")
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py -v`
Expected: All 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/adapters/ tests/test_granicus_adapter.py
git commit -m "feat: add BaseAdapter ABC and adapter registry

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Granicus shared parsing utilities

**Files:**
- Modify: `scripts/adapters/granicus.py`
- Modify: `tests/test_granicus_adapter.py`

These are the parsing functions shared by both legacy and modern variants: HTML fetching, tag stripping, URL extraction, meeting classification.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_granicus_adapter.py`:

```python
from adapters.granicus import (
    strip_tags,
    extract_href,
    extract_onclick_url,
    extract_rows,
    classify_meeting,
    detect_variant,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestStripTags:
    def test_removes_html(self):
        assert strip_tags("<b>hello</b> world") == "hello world"

    def test_decodes_entities(self):
        assert strip_tags("03&nbsp;/&nbsp;24") == "03 / 24"

    def test_collapses_whitespace(self):
        assert strip_tags("  hello   world  ") == "hello world"


class TestExtractHref:
    def test_extracts_href(self):
        html = '<a href="https://example.com/agenda">Agenda</a>'
        assert extract_href(html) == "https://example.com/agenda"

    def test_returns_none_for_no_link(self):
        assert extract_href("<td>empty</td>") is None

    def test_ignores_javascript_void(self):
        html = '<a href="javascript:void(0);" onClick="window.open(\'url\')">Video</a>'
        assert extract_href(html) is None


class TestExtractOnclickUrl:
    def test_extracts_window_open_url(self):
        html = """<a href="javascript:void(0);" onClick="window.open('//marin.granicus.com/MediaPlayer.php?view_id=33&event_id=4204','player')">Video</a>"""
        assert extract_onclick_url(html) == "//marin.granicus.com/MediaPlayer.php?view_id=33&event_id=4204"

    def test_returns_none_for_no_onclick(self):
        assert extract_onclick_url('<a href="http://example.com">Link</a>') is None


class TestClassifyMeeting:
    def test_regular(self):
        assert classify_meeting("Regular Meeting") == "regular"

    def test_special(self):
        assert classify_meeting("Special Meeting") == "special"

    def test_budget(self):
        assert classify_meeting("Budget Hearing") == "budget"

    def test_closed_session(self):
        assert classify_meeting("Closed Session") == "closed_session"

    def test_joint(self):
        assert classify_meeting("Joint Meeting with Planning Commission") == "joint_meeting"

    def test_default_other(self):
        assert classify_meeting("Something Unusual") == "other"


class TestDetectVariant:
    def test_legacy_detected(self):
        html = FIXTURES / "granicus-marin-county-bos.html"
        assert detect_variant(html.read_text(errors="ignore")) == "legacy"

    def test_modern_novato_detected(self):
        html = FIXTURES / "granicus-novato-city-council.html"
        assert detect_variant(html.read_text(errors="ignore")) == "modern"

    def test_modern_sausalito_detected(self):
        html = FIXTURES / "granicus-sausalito-city-council.html"
        assert detect_variant(html.read_text(errors="ignore")) == "modern"


class TestExtractRows:
    def test_extracts_rows_from_legacy(self):
        html = FIXTURES / "granicus-marin-county-bos.html"
        rows = extract_rows(html.read_text(errors="ignore"))
        assert len(rows) > 300

    def test_extracts_rows_from_modern(self):
        html = FIXTURES / "granicus-novato-city-council.html"
        rows = extract_rows(html.read_text(errors="ignore"))
        assert len(rows) > 300

    def test_each_row_is_html_string(self):
        html = FIXTURES / "granicus-marin-county-bos.html"
        rows = extract_rows(html.read_text(errors="ignore"))
        assert rows[0].startswith("<tr")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py::TestStripTags -v`
Expected: FAIL — `ImportError: cannot import name 'strip_tags'`

- [ ] **Step 3: Implement shared utilities in granicus.py**

Replace `scripts/adapters/granicus.py`:

```python
"""Granicus Publisher View adapter.

Handles two template variants:
- Legacy (Marin County BOS): year comment sections, 9-column layout, 2-digit dates
- Modern (Novato, Sausalito): TabbedPanels, 6-7 column layout, 4-digit dates
"""

from __future__ import annotations

import re
import urllib.request
from html import unescape
from pathlib import Path

from .base import BaseAdapter

# ---------------------------------------------------------------------------
# Shared regex patterns
# ---------------------------------------------------------------------------

ROW_RE = re.compile(r"<tr class=\"listingRow\">.*?</tr>", re.S)
TD_RE = re.compile(r"<td class=\"listItem\"[^>]*>(.*?)</td>", re.S)
HREF_RE = re.compile(r"href=(['\"])(.*?)\1", re.S | re.I)
ONCLICK_URL_RE = re.compile(r"window\.open\('([^']+)'", re.I)
YEAR_COMMENT_RE = re.compile(r"<!--\s*(20\d{2})\s+Start\s*-->", re.I)
TABBED_PANEL_RE = re.compile(r'class="TabbedPanels"', re.I)

USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"


# ---------------------------------------------------------------------------
# Shared utility functions
# ---------------------------------------------------------------------------

def strip_tags(value: str) -> str:
    """Remove HTML tags, decode entities, collapse whitespace."""
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def extract_href(html: str) -> str | None:
    """Extract the first non-javascript href from an HTML fragment."""
    match = HREF_RE.search(html)
    if match:
        url = match.group(2)
        if not url.startswith("javascript:"):
            return url
    return None


def extract_onclick_url(html: str) -> str | None:
    """Extract URL from a window.open() onclick handler."""
    match = ONCLICK_URL_RE.search(html)
    return match.group(1) if match else None


def extract_rows(html: str) -> list[str]:
    """Extract all <tr class="listingRow">...</tr> from the HTML."""
    return ROW_RE.findall(html)


def extract_cells(row_html: str) -> list[str]:
    """Extract <td class="listItem"> cell contents from a row."""
    return TD_RE.findall(row_html)


def classify_meeting(title: str) -> str:
    """Classify a meeting by its title text."""
    t = title.lower()
    if "closed session" in t or "closed_session" in t:
        return "closed_session"
    if "special" in t:
        return "special"
    if "budget" in t:
        return "budget"
    if "joint" in t:
        return "joint_meeting"
    if "retreat" in t:
        return "retreat"
    if "workshop" in t or "study session" in t:
        return "workshop"
    if "regular" in t or t.strip() in ("", "meeting"):
        return "regular"
    return "other"


def detect_variant(html: str) -> str:
    """Detect whether a Granicus page uses legacy or modern template.

    Legacy: has <!-- YYYY Start --> HTML comments.
    Modern: has TabbedPanels widget or no year comments.
    """
    if YEAR_COMMENT_RE.search(html):
        return "legacy"
    return "modern"


def fetch_html(url: str) -> str:
    """Fetch a URL and return decoded HTML."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


class GranicusAdapter(BaseAdapter):
    def capture(self) -> dict:
        raise NotImplementedError("Granicus capture not yet implemented")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py -v`
Expected: All tests PASS (shared utilities + registry + base contract)

- [ ] **Step 5: Commit**

```bash
git add scripts/adapters/granicus.py tests/test_granicus_adapter.py
git commit -m "feat: add Granicus shared parsing utilities (strip_tags, extract_href, classify, detect_variant)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Legacy Granicus parser (Marin County BOS)

**Files:**
- Modify: `scripts/adapters/granicus.py`
- Modify: `tests/test_granicus_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_granicus_adapter.py`:

```python
from adapters.granicus import parse_legacy, parse_legacy_date


class TestParseLegacyDate:
    def test_two_digit_year(self):
        assert parse_legacy_date("04/14/26") == "2026-04-14"

    def test_with_time(self):
        assert parse_legacy_date("07/08/25 - 09:00 AM") == "2025-07-08"

    def test_returns_none_for_bad_input(self):
        assert parse_legacy_date("not a date") is None


class TestParseLegacy:
    @pytest.fixture
    def legacy_html(self):
        return (FIXTURES / "granicus-marin-county-bos.html").read_text(errors="ignore")

    def test_returns_meetings_list(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        assert isinstance(meetings, list)
        assert len(meetings) > 200

    def test_meeting_has_required_fields(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        m = meetings[0]
        assert "date" in m
        assert "title" in m
        assert "meeting_type" in m
        assert "artifacts" in m
        assert "source_row_number" in m

    def test_meeting_date_is_iso(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        for m in meetings[:10]:
            if m["date"]:
                assert re.match(r"\d{4}-\d{2}-\d{2}", m["date"])

    def test_respects_backfill_from(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2024-01-01")
        for m in meetings:
            if m["date"]:
                assert m["date"] >= "2024-01-01"

    def test_artifacts_use_available_url_format(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        for m in meetings[:10]:
            for art_name, art in m["artifacts"].items():
                assert "available" in art
                assert "url" in art

    def test_extracts_agenda_urls(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        agendas = [m for m in meetings if m["artifacts"].get("agenda", {}).get("available")]
        assert len(agendas) > 100

    def test_extracts_video_urls(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        videos = [m for m in meetings if m["artifacts"].get("video", {}).get("available")]
        assert len(videos) > 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py::TestParseLegacy -v`
Expected: FAIL — `ImportError: cannot import name 'parse_legacy'`

- [ ] **Step 3: Implement parse_legacy and parse_legacy_date**

Add to `scripts/adapters/granicus.py`:

```python
# ---------------------------------------------------------------------------
# Legacy-specific patterns
# ---------------------------------------------------------------------------

LEGACY_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")
HIDDEN_EPOCH_RE = re.compile(r"<span[^>]*>\s*(\d{10})\s*</span>")
YEAR_SECTION_RE = re.compile(
    r"<!--\s*(20\d{2})\s+Start\s*-->(.*?)(?=<!--\s*20\d{2}\s+Start\s*-->|$)",
    re.S,
)


def parse_legacy_date(text: str) -> str | None:
    """Parse legacy date format: MM/DD/YY -> YYYY-MM-DD."""
    match = LEGACY_DATE_RE.search(text)
    if not match:
        return None
    mm, dd, yy = match.groups()
    year = 2000 + int(yy)
    return f"{year:04d}-{int(mm):02d}-{int(dd):02d}"


def _parse_legacy_row(cells: list[str], row_number: int) -> dict | None:
    """Parse a legacy 9-column row into a meeting dict.

    Columns: Month | Name | Date | Agenda | Minutes | Video | Captions | MP3 | MP4
    """
    if len(cells) < 6:
        return None

    # Column 1 = name, Column 2 = date
    title = strip_tags(cells[1]).strip()
    date_cell = cells[2]
    date = parse_legacy_date(strip_tags(date_cell))

    # Extract hidden epoch for sort ordering
    epoch_match = HIDDEN_EPOCH_RE.search(date_cell)
    epoch = int(epoch_match.group(1)) if epoch_match else None

    meeting_type = classify_meeting(title)

    # Build artifact dict
    artifacts = {}
    artifact_map = [
        (3, "agenda"),
        (4, "minutes"),
        (5, "video"),
    ]
    if len(cells) > 6:
        artifact_map.append((6, "captions"))
    if len(cells) > 7:
        artifact_map.append((7, "mp3"))
    if len(cells) > 8:
        artifact_map.append((8, "mp4"))

    for col_idx, art_name in artifact_map:
        if col_idx >= len(cells):
            artifacts[art_name] = {"available": False, "url": None}
            continue
        cell = cells[col_idx]
        if art_name == "video":
            url = extract_onclick_url(cell)
        else:
            url = extract_href(cell)
        artifacts[art_name] = {"available": url is not None, "url": url}

    # Extract clip_id or event_id from any artifact URL
    clip_id = None
    for art in artifacts.values():
        if art["url"]:
            id_match = re.search(r"(?:clip_id|event_id)=(\d+)", art["url"])
            if id_match:
                clip_id = id_match.group(1)
                break

    return {
        "date": date,
        "title": title if title else None,
        "meeting_type": meeting_type,
        "artifacts": artifacts,
        "source_row_number": row_number,
        "clip_id": clip_id,
        "source_sort_epoch": epoch,
    }


def parse_legacy(html: str, backfill_from: str = "2019-01-01") -> list[dict]:
    """Parse a legacy Granicus page (year-comment sections, 9-column layout)."""
    meetings = []
    row_number = 0

    for year_str, section_html in YEAR_SECTION_RE.findall(html):
        year = int(year_str)
        if year < int(backfill_from[:4]):
            continue

        for row_html in ROW_RE.findall(section_html):
            row_number += 1
            cells = extract_cells(row_html)
            meeting = _parse_legacy_row(cells, row_number)
            if meeting is None:
                continue
            if meeting["date"] and meeting["date"] < backfill_from:
                continue
            meetings.append(meeting)

    return meetings
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py::TestParseLegacy tests/test_granicus_adapter.py::TestParseLegacyDate -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/adapters/granicus.py tests/test_granicus_adapter.py
git commit -m "feat: add legacy Granicus parser (year-comment sections, 9-column layout)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Modern Granicus parser (Novato, Sausalito)

**Files:**
- Modify: `scripts/adapters/granicus.py`
- Modify: `tests/test_granicus_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_granicus_adapter.py`:

```python
from adapters.granicus import parse_modern, parse_modern_date


class TestParseModernDate:
    def test_numeric_with_nbsp(self):
        assert parse_modern_date("03\xa0/\xa024\xa0/\xa02026") == "2026-03-24"

    def test_numeric_with_spaces(self):
        assert parse_modern_date("03 / 24 / 2026") == "2026-03-24"

    def test_month_name(self):
        assert parse_modern_date("Apr\xa0 7,\xa02026") == "2026-04-07"

    def test_month_name_with_spaces(self):
        assert parse_modern_date("April 14, 2026") == "2026-04-14"

    def test_returns_none_for_bad_input(self):
        assert parse_modern_date("not a date") is None

    def test_handles_time_suffix(self):
        assert parse_modern_date("Apr\xa0 7,\xa02026 - 4:01\xa0PM") == "2026-04-07"


class TestParseModern:
    @pytest.fixture
    def novato_html(self):
        return (FIXTURES / "granicus-novato-city-council.html").read_text(errors="ignore")

    @pytest.fixture
    def sausalito_html(self):
        return (FIXTURES / "granicus-sausalito-city-council.html").read_text(errors="ignore")

    def test_returns_meetings_from_novato(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        assert isinstance(meetings, list)
        assert len(meetings) > 200

    def test_returns_meetings_from_sausalito(self, sausalito_html):
        meetings = parse_modern(sausalito_html, backfill_from="2019-01-01")
        assert isinstance(meetings, list)
        assert len(meetings) > 100

    def test_meeting_has_required_fields(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        m = meetings[0]
        assert "date" in m
        assert "title" in m
        assert "meeting_type" in m
        assert "artifacts" in m

    def test_meeting_date_is_iso(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        for m in meetings[:10]:
            if m["date"]:
                assert re.match(r"\d{4}-\d{2}-\d{2}", m["date"])

    def test_artifacts_use_available_url_format(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        for m in meetings[:10]:
            for art in m["artifacts"].values():
                assert "available" in art
                assert "url" in art

    def test_respects_backfill_from(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2024-01-01")
        for m in meetings:
            if m["date"]:
                assert m["date"] >= "2024-01-01"

    def test_extracts_agenda_urls_novato(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        agendas = [m for m in meetings if m["artifacts"].get("agenda", {}).get("available")]
        assert len(agendas) > 100

    def test_extracts_minutes_urls_sausalito(self, sausalito_html):
        meetings = parse_modern(sausalito_html, backfill_from="2019-01-01")
        minutes = [m for m in meetings if m["artifacts"].get("minutes", {}).get("available")]
        assert len(minutes) > 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py::TestParseModern -v`
Expected: FAIL — `ImportError: cannot import name 'parse_modern'`

- [ ] **Step 3: Implement parse_modern and parse_modern_date**

Add to `scripts/adapters/granicus.py`:

```python
# ---------------------------------------------------------------------------
# Modern-specific patterns
# ---------------------------------------------------------------------------

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MODERN_NUMERIC_DATE_RE = re.compile(r"(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{4})")
MODERN_NAMED_DATE_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})"
)
TABBED_CONTENT_RE = re.compile(
    r'<div class="TabbedPanelsContent">(.*?)</div>\s*(?=<div class="TabbedPanelsContent">|</div>\s*</div>)',
    re.S,
)
TABBED_TAB_RE = re.compile(
    r'<li class="TabbedPanelsTab"[^>]*>\s*(\d{4})\s*</li>'
)


def parse_modern_date(text: str) -> str | None:
    """Parse modern date formats:
    - 'MM / DD / YYYY' (with optional &nbsp;)
    - 'Mon DD, YYYY' or 'Month DD, YYYY'
    Strips time suffixes like '- 4:01 PM'.
    """
    # Normalize: replace &nbsp; (xa0) with space
    text = text.replace("\xa0", " ")
    # Strip time suffix
    text = re.sub(r"\s*-\s*\d{1,2}:\d{2}\s*[AP]M.*", "", text, flags=re.I)

    # Try numeric first: MM / DD / YYYY
    match = MODERN_NUMERIC_DATE_RE.search(text)
    if match:
        mm, dd, yyyy = match.groups()
        return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"

    # Try named: Mon DD, YYYY
    match = MODERN_NAMED_DATE_RE.search(text)
    if match:
        month_str, day_str, year_str = match.groups()
        month = MONTH_NAMES.get(month_str.lower())
        if month:
            return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"

    return None


def _parse_modern_row(cells: list[str], row_number: int) -> dict | None:
    """Parse a modern 6-7 column row into a meeting dict.

    Columns: Name | Date | Duration | Agenda | Minutes | Video [| MP4]
    """
    if len(cells) < 4:
        return None

    title = strip_tags(cells[0]).strip()
    date = parse_modern_date(strip_tags(cells[1]))
    meeting_type = classify_meeting(title)

    # Build artifact dict — column positions shifted (no Month column, has Duration)
    artifacts = {}
    artifact_map = [
        (3, "agenda"),
        (4, "minutes"),
        (5, "video"),
    ]
    if len(cells) > 6:
        artifact_map.append((6, "mp4"))

    for col_idx, art_name in artifact_map:
        if col_idx >= len(cells):
            artifacts[art_name] = {"available": False, "url": None}
            continue
        cell = cells[col_idx]
        if art_name == "video":
            url = extract_onclick_url(cell) or extract_href(cell)
        elif art_name == "mp4":
            url = extract_href(cell)
        else:
            url = extract_href(cell)
        artifacts[art_name] = {"available": url is not None, "url": url}

    # Extract clip_id or event_id
    clip_id = None
    for art in artifacts.values():
        if art["url"]:
            id_match = re.search(r"(?:clip_id|event_id)=(\d+)", art["url"])
            if id_match:
                clip_id = id_match.group(1)
                break

    return {
        "date": date,
        "title": title if title else None,
        "meeting_type": meeting_type,
        "artifacts": artifacts,
        "source_row_number": row_number,
        "clip_id": clip_id,
        "source_sort_epoch": None,
    }


def parse_modern(html: str, backfill_from: str = "2019-01-01") -> list[dict]:
    """Parse a modern Granicus page (TabbedPanels or flat tbody)."""
    meetings = []
    row_number = 0

    # Try to find tabbed year sections
    tabs = TABBED_TAB_RE.findall(html)
    panels = TABBED_CONTENT_RE.findall(html)

    if tabs and panels and len(tabs) == len(panels):
        # Tabbed layout: each panel corresponds to a year tab
        for year_str, panel_html in zip(tabs, panels):
            year = int(year_str)
            if year < int(backfill_from[:4]):
                continue
            for row_html in ROW_RE.findall(panel_html):
                row_number += 1
                cells = extract_cells(row_html)
                meeting = _parse_modern_row(cells, row_number)
                if meeting is None:
                    continue
                if meeting["date"] and meeting["date"] < backfill_from:
                    continue
                meetings.append(meeting)
    else:
        # Flat layout: all rows in one section, no year partitioning
        for row_html in extract_rows(html):
            row_number += 1
            cells = extract_cells(row_html)
            meeting = _parse_modern_row(cells, row_number)
            if meeting is None:
                continue
            if meeting["date"] and meeting["date"] < backfill_from:
                continue
            meetings.append(meeting)

    return meetings
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/adapters/granicus.py tests/test_granicus_adapter.py
git commit -m "feat: add modern Granicus parser (TabbedPanels, 6-7 column layout, multi-format dates)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: GranicusAdapter.capture() — full integration

**Files:**
- Modify: `scripts/adapters/granicus.py`
- Modify: `tests/test_granicus_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_granicus_adapter.py`:

```python
class TestGranicusAdapterCapture:
    """Integration tests using saved HTML fixtures (no live HTTP)."""

    def _make_adapter(self, source_id, fixture_name, tmp_path):
        """Create a GranicusAdapter that reads from a fixture instead of HTTP."""
        config = {
            "id": source_id,
            "adapter": "granicus",
            "url": "https://example.granicus.com/ViewPublisher.php?view_id=1",
            "jurisdiction_id": f"place-{source_id.split('-')[0]}",
            "institution_id": f"org-{source_id}",
            "backfill_from": "2019-01-01",
        }
        adapter = GranicusAdapter(config, tmp_path)
        # Monkey-patch fetch_html to read from fixture
        fixture_path = FIXTURES / fixture_name
        adapter._fetch = lambda url: fixture_path.read_text(errors="ignore")
        return adapter

    def test_legacy_capture_returns_dict(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["source_id"] == "marin-county-bos"
        assert result["variant"] == "legacy"

    def test_modern_capture_returns_dict(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["variant"] == "modern"

    def test_capture_has_required_envelope_fields(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
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

    def test_capture_meeting_count_matches(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] == len(result["meetings"])
        assert result["meeting_count"] > 200

    def test_capture_writes_raw_html(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        adapter.capture()
        raw_files = list((tmp_path / "data" / "raw" / "marin-county-bos").rglob("source.html"))
        assert len(raw_files) == 1

    def test_capture_record_refs_present(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        result = adapter.capture()
        assert len(result["record_refs"]) >= 1
        ref = result["record_refs"][0]
        assert "id" in ref
        assert "record_type" in ref
        assert ref["record_type"] == "meeting_archive_page"

    def test_novato_meeting_count_reasonable(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] > 200

    def test_sausalito_meeting_count_reasonable(self, tmp_path):
        adapter = self._make_adapter("sausalito-city-council", "granicus-sausalito-city-council.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] > 100

    def test_capture_meetings_have_institution_id(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert m["institution_id"] == "org-novato-city-council"

    def test_capture_meetings_have_meeting_id(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert "meeting_id" in m
            assert m["meeting_id"].startswith("meeting-")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py::TestGranicusAdapterCapture -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement GranicusAdapter.capture()**

Replace the `GranicusAdapter` class in `scripts/adapters/granicus.py`:

```python
class GranicusAdapter(BaseAdapter):
    """Granicus Publisher View adapter.

    Auto-detects legacy vs modern template and dispatches to the
    appropriate parser.
    """

    def _fetch(self, url: str) -> str:
        """Fetch HTML from URL. Extracted as method for test monkey-patching."""
        return fetch_html(url)

    def capture(self) -> dict:
        html = self._fetch(self.url)
        variant = detect_variant(html)
        captured_at = self.utc_now_iso()

        # Write raw HTML
        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "source.html"
        raw_path.write_text(html, encoding="utf-8")

        # Parse meetings using the detected variant
        if variant == "legacy":
            meetings = parse_legacy(html, backfill_from=self.backfill_from)
        else:
            meetings = parse_modern(html, backfill_from=self.backfill_from)

        # Stamp each meeting with institution_id and meeting_id
        for m in meetings:
            m["institution_id"] = self.institution_id
            slug = self.source_id
            if m["clip_id"]:
                m["meeting_id"] = f"meeting-{slug}-{m['clip_id']}"
            elif m["date"]:
                row = m["source_row_number"]
                m["meeting_id"] = f"meeting-{slug}-{m['date']}-row-{row}"
            else:
                m["meeting_id"] = f"meeting-{slug}-row-{m['source_row_number']}"

        # Compute artifact counts
        artifact_counts: dict[str, int] = {}
        for m in meetings:
            for art_name, art in m["artifacts"].items():
                if art["available"]:
                    artifact_counts[art_name] = artifact_counts.get(art_name, 0) + 1

        # Build record_refs for the captured archive page
        record_refs = [
            {
                "id": f"record-{self.source_id}-archive-page-{captured_at[:10]}",
                "record_type": "meeting_archive_page",
                "source_id": self.source_id,
                "artifact_path": str(raw_path.relative_to(self.root)),
                "captured_at": captured_at,
            }
        ]

        return {
            "capture_id": self.capture_id(),
            "source_id": self.source_id,
            "adapter": "granicus",
            "variant": variant,
            "captured_at": captured_at,
            "url": self.url,
            "jurisdiction_id": self.jurisdiction_id,
            "institution_id": self.institution_id,
            "raw_artifact": str(raw_path.relative_to(self.root)),
            "meeting_count": len(meetings),
            "artifact_counts": artifact_counts,
            "meetings": meetings,
            "record_refs": record_refs,
            "errors": [],
        }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_granicus_adapter.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/adapters/granicus.py tests/test_granicus_adapter.py
git commit -m "feat: implement GranicusAdapter.capture() with auto-variant detection

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Source registry and runner script

**Files:**
- Create: `registry/sources.yaml`
- Create: `scripts/ingest.py`
- Create: `tests/test_ingest_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_runner.py`:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest import load_sources, resolve_sources


@pytest.fixture
def sample_registry(tmp_path):
    yaml_content = """sources:
  - id: test-source-1
    adapter: granicus
    url: https://example.com/1
    jurisdiction_id: place-test1
    institution_id: org-test1
    backfill_from: "2019-01-01"
    schedule: weekly
  - id: test-source-2
    adapter: granicus
    url: https://example.com/2
    jurisdiction_id: place-test2
    institution_id: org-test2
    backfill_from: "2020-01-01"
    schedule: monthly
"""
    path = tmp_path / "sources.yaml"
    path.write_text(yaml_content)
    return path


class TestLoadSources:
    def test_loads_all_sources(self, sample_registry):
        sources = load_sources(sample_registry)
        assert len(sources) == 2
        assert sources[0]["id"] == "test-source-1"

    def test_source_has_required_fields(self, sample_registry):
        sources = load_sources(sample_registry)
        s = sources[0]
        assert "id" in s
        assert "adapter" in s
        assert "url" in s


class TestResolveSources:
    def test_resolve_by_source_id(self, sample_registry):
        sources = load_sources(sample_registry)
        resolved = resolve_sources(sources, source="test-source-1")
        assert len(resolved) == 1
        assert resolved[0]["id"] == "test-source-1"

    def test_resolve_all(self, sample_registry):
        sources = load_sources(sample_registry)
        resolved = resolve_sources(sources, all_sources=True)
        assert len(resolved) == 2

    def test_resolve_unknown_raises(self, sample_registry):
        sources = load_sources(sample_registry)
        with pytest.raises(ValueError):
            resolve_sources(sources, source="nonexistent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_ingest_runner.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create sources.yaml**

Create `registry/sources.yaml`:

```yaml
sources:
  - id: marin-county-bos
    adapter: granicus
    url: https://marin.granicus.com/ViewPublisher.php?view_id=33
    jurisdiction_id: place-marin-county
    institution_id: org-marin-county-board-of-supervisors
    backfill_from: "2019-01-01"
    schedule: weekly

  - id: novato-city-council
    adapter: granicus
    url: https://novato.granicus.com/ViewPublisher.php?view_id=7
    jurisdiction_id: place-novato
    institution_id: org-novato-city-council
    backfill_from: "2019-01-01"
    schedule: weekly

  - id: sausalito-city-council
    adapter: granicus
    url: https://sausalito.granicus.com/ViewPublisher.php?view_id=6
    jurisdiction_id: place-sausalito
    institution_id: org-sausalito-city-council
    backfill_from: "2019-01-01"
    schedule: weekly
```

- [ ] **Step 4: Implement ingest.py**

Create `scripts/ingest.py`:

```python
#!/usr/bin/env python3
"""Ingestion runner — load source registry, dispatch adapters, write output."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import get_adapter_class

ROOT = Path(__file__).resolve().parent.parent


def load_sources(registry_path: Path) -> list[dict]:
    """Load source configs from a YAML registry file."""
    with open(registry_path) as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def resolve_sources(
    sources: list[dict],
    source: str | None = None,
    all_sources: bool = False,
) -> list[dict]:
    """Filter sources by CLI args. Returns matching source configs."""
    if all_sources:
        return list(sources)
    if source:
        matches = [s for s in sources if s["id"] == source]
        if not matches:
            available = [s["id"] for s in sources]
            raise ValueError(f"Unknown source: {source!r}. Available: {available}")
        return matches
    raise ValueError("Specify --source <id> or --all")


def run_source(source_config: dict, root: Path) -> dict:
    """Run a single source capture. Returns the extracted dict."""
    adapter_cls = get_adapter_class(source_config["adapter"])
    adapter = adapter_cls(source_config, root)
    result = adapter.capture()

    # Write extracted JSON
    out_path = adapter.extracted_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ingestion adapters")
    parser.add_argument("--source", help="Source ID to capture")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Capture all sources")
    parser.add_argument("--registry", default="registry/sources.yaml", help="Path to source registry")
    args = parser.parse_args()

    registry_path = ROOT / args.registry
    sources = load_sources(registry_path)

    try:
        targets = resolve_sources(sources, source=args.source, all_sources=args.all_sources)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    for i, source_config in enumerate(targets):
        if i > 0:
            print("  (waiting 2s between sources)")
            time.sleep(2)

        source_id = source_config["id"]
        print(f"\nCapturing: {source_id}")
        print(f"  Adapter: {source_config['adapter']}")
        print(f"  URL: {source_config['url']}")

        try:
            result = run_source(source_config, ROOT)
            print(f"  Variant: {result.get('variant', 'unknown')}")
            print(f"  Meetings: {result['meeting_count']}")
            for art, count in sorted(result.get("artifact_counts", {}).items()):
                print(f"    {art}: {count}")
            if result.get("errors"):
                print(f"  Errors: {len(result['errors'])}")
                for err in result["errors"]:
                    print(f"    - {err}")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_ingest_runner.py -v`
Expected: All PASS

- [ ] **Step 6: Run all tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v`
Expected: All PASS (migration tests + adapter tests + runner tests)

- [ ] **Step 7: Commit**

```bash
git add registry/sources.yaml scripts/ingest.py tests/test_ingest_runner.py
git commit -m "feat: add source registry and ingestion runner CLI

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Live smoke test — all three Granicus sources

**Files:**
- No new files — this task runs the pipeline against live data

- [ ] **Step 1: Run all unit tests first**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Capture Marin County BOS (legacy)**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source marin-county-bos`
Expected output:
```
Capturing: marin-county-bos
  Adapter: granicus
  Variant: legacy
  Meetings: 300+
    agenda: 250+
    minutes: 250+
    video: 250+
```

- [ ] **Step 3: Verify BOS output**

Run: `python -c "import json; d=json.load(open('data/extracted/marin-county-bos/$(date +%Y-%m-%d).json')); print(f'Meetings: {d[\"meeting_count\"]}, Variant: {d[\"variant\"]}')"``

Verify: meeting_count > 300, variant == "legacy"

- [ ] **Step 4: Capture Novato (modern)**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source novato-city-council`
Expected: Variant: modern, Meetings: 250+

- [ ] **Step 5: Capture Sausalito (modern)**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/ingest.py --source sausalito-city-council`
Expected: Variant: modern, Meetings: 100+

- [ ] **Step 6: Verify all three have correct structure**

Run:
```bash
for f in data/extracted/*/$(date +%Y-%m-%d).json; do
  echo "=== $f ==="
  python -c "import json; d=json.load(open('$f')); print(f'  source: {d[\"source_id\"]}'); print(f'  variant: {d[\"variant\"]}'); print(f'  meetings: {d[\"meeting_count\"]}'); print(f'  artifacts: {d[\"artifact_counts\"]}'); print(f'  record_refs: {len(d[\"record_refs\"])}'); print(f'  capture_id: {d[\"capture_id\"]}')"
done
```

Verify: all three have capture_id, record_refs, artifact counts, correct variant detection.

- [ ] **Step 7: Commit test fixtures and push**

```bash
git add tests/fixtures/granicus-*.html registry/sources.yaml
git commit -m "feat: add Granicus HTML fixtures and source registry — live smoke test passing

Three Granicus sources validated:
- Marin County BOS (legacy template): 300+ meetings
- Novato City Council (modern template): 250+ meetings
- Sausalito City Council (modern template): 100+ meetings

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

git push
```

---

## Build Verification

After all tasks are complete:

1. `python -m pytest tests/ -v` — all tests pass (migration + adapter + runner)
2. `python scripts/ingest.py --source marin-county-bos` — legacy variant, 300+ meetings
3. `python scripts/ingest.py --source novato-city-council` — modern variant, 250+ meetings
4. `python scripts/ingest.py --source sausalito-city-council` — modern variant, 100+ meetings
5. `python scripts/ingest.py --all` — captures all three with 2s delay between sources
6. All outputs have: capture_id, institution_id at envelope, {available, url} artifacts, record_refs, variant field
