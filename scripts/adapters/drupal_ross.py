"""Drupal adapter for the Town of Ross meetings page.

Ross uses Drupal with AHA Consulting's aha_fasttrack_meetings module.
The meetings page presents two views:
  - Upcoming meetings (5-column table): Date, Meeting, Agendas, Staff Reports, Location
  - Past meetings (8-column table): Date, Meeting, Agendas, Minutes, Staff Reports,
    Audio, Video, Details

Dates are encoded in <span content="ISO-8601"> attributes. PDF links point directly
to /sites/default/files/fileattachments/... hosted on townofrossca.gov.
"""

from __future__ import annotations

import re
import urllib.request
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from .base import BaseAdapter

USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Matches the ISO date in <span content="2026-04-02T18:00:00-07:00">
_ISO_CONTENT_RE = re.compile(
    r'<span[^>]+content="(\d{4}-\d{2}-\d{2}T[^"]+)"[^>]*>'
)

# Fallback: display text "MM/DD/YYYY - H:MMam"
_DISPLAY_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

# Table rows: <tr class="..."> ... </tr>
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)

# Table data cells: <td ...> ... </td>
_CELL_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)

# Any href to a PDF in fileattachments
_PDF_HREF_RE = re.compile(r'href="([^"]*fileattachments[^"]*\.pdf)"', re.I)

# Strip HTML tags and normalise whitespace
def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(html))).strip()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def parse_ross_date(value: str) -> str | None:
    """Parse a Ross date string to YYYY-MM-DD.

    Accepts:
      - ISO datetime: "2026-04-02T18:00:00-07:00"  → "2026-04-02"
      - Display text: "04/02/2026 - 6:00pm"          → "2026-04-02"

    Returns None for unrecognised input.
    """
    # ISO form: starts with YYYY-
    if re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]

    # Display form: MM/DD/YYYY
    m = _DISPLAY_DATE_RE.search(value)
    if m:
        mm, dd, yyyy = m.groups()
        return f"{yyyy}-{mm}-{dd}"

    return None


def _extract_pdf_links(cell_html: str, base_url: str) -> list[str]:
    """Return absolute PDF URLs found in a table cell."""
    urls = []
    for href in _PDF_HREF_RE.findall(cell_html):
        if href.startswith("http"):
            urls.append(href)
        else:
            urls.append(urljoin(base_url, href))
    return urls


def _parse_table_rows(table_html: str, base_url: str, col_count: int) -> list[dict]:
    """Parse <tr> rows from a table's HTML fragment.

    col_count == 5: upcoming table (date, title, agendas, staff_reports, location)
    col_count == 8: past table (date, title, agendas, minutes, staff_reports,
                                audio, video, details)
    """
    meetings: list[dict] = []

    for row_match in _ROW_RE.finditer(table_html):
        row_html = row_match.group(1)
        cells = _CELL_RE.findall(row_html)
        if len(cells) < 2:
            continue  # skip header or malformed rows

        # Cell 0: date
        date_val: str | None = None
        iso_match = _ISO_CONTENT_RE.search(cells[0])
        if iso_match:
            date_val = parse_ross_date(iso_match.group(1))
        else:
            date_val = parse_ross_date(_text(cells[0]))

        # Cell 1: title
        title = _text(cells[1])
        if not title:
            continue

        # Agendas (cell 2 in both tables)
        agenda_urls = _extract_pdf_links(cells[2], base_url) if len(cells) > 2 else []

        # Minutes (cell 3 in 8-col table only)
        minutes_urls: list[str] = []
        if col_count == 8 and len(cells) > 3:
            minutes_urls = _extract_pdf_links(cells[3], base_url)

        # Staff reports (cell 3 in 5-col, cell 4 in 8-col)
        staff_idx = 3 if col_count == 5 else 4
        staff_url: str | None = None
        if len(cells) > staff_idx:
            staff_links = re.findall(r'href="([^"]+)"', cells[staff_idx])
            if staff_links:
                href = staff_links[0]
                staff_url = href if href.startswith("http") else urljoin(base_url, href)

        artifacts: dict[str, dict] = {
            "agenda": {
                "available": bool(agenda_urls),
                "url": agenda_urls[0] if agenda_urls else None,
            },
            "minutes": {
                "available": bool(minutes_urls),
                "url": minutes_urls[0] if minutes_urls else None,
            },
            "staff_reports": {
                "available": staff_url is not None,
                "url": staff_url,
            },
        }

        meetings.append({
            "date": date_val,
            "title": title,
            "artifacts": artifacts,
        })

    return meetings


def extract_ross_meetings(html: str, base_url: str) -> list[dict]:
    """Extract all meetings from the Ross meetings page HTML.

    Parses both the upcoming (5-col) and past (8-col) tables.
    Returns a list of meeting dicts with keys: date, title, artifacts.
    """
    meetings: list[dict] = []

    # Find both tables by their cols-N class
    table_re = re.compile(
        r'<table\b[^>]*class="[^"]*views-table[^"]*cols-(\d+)[^"]*"[^>]*>(.*?)</table>',
        re.S | re.I,
    )

    for tbl_match in table_re.finditer(html):
        col_count = int(tbl_match.group(1))
        table_html = tbl_match.group(2)

        # Only process tbody content (skip thead)
        tbody_match = re.search(r"<tbody>(.*?)</tbody>", table_html, re.S | re.I)
        if not tbody_match:
            continue
        tbody_html = tbody_match.group(1)

        rows = _parse_table_rows(tbody_html, base_url, col_count)
        meetings.extend(rows)

    return meetings


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class DrupalRossAdapter(BaseAdapter):
    """Single-page Drupal adapter for townofrossca.gov/meetings.

    Fetches one page and parses both the upcoming and past meeting tables.
    No pagination — the page shows ~19 meetings total.
    """

    def _fetch_page(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "ignore")

    def capture(self) -> dict:
        captured_at = self.utc_now_iso()
        base_url = self.url.rstrip("/").rsplit("/meetings", 1)[0]

        html = self._fetch_page(self.url)

        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.html").write_text(html, encoding="utf-8")

        raw_meetings = extract_ross_meetings(html, base_url)

        # Apply backfill filter (undated meetings are kept)
        raw_meetings = [
            m for m in raw_meetings
            if not m["date"] or m["date"] >= self.backfill_from
        ]

        meetings: list[dict] = []
        for i, m in enumerate(raw_meetings):
            date_slug = m["date"] or "unknown"
            meetings.append({
                "meeting_id": f"meeting-{self.source_id}-{date_slug}-row-{i + 1}",
                "date": m["date"],
                "title": m["title"],
                "meeting_type": "regular",
                "institution_id": self.institution_id,
                "artifacts": m["artifacts"],
                "source_url": self.url,
                "source_row_number": i + 1,
            })

        artifact_counts: dict[str, int] = {}
        for m in meetings:
            for art_name, art in m.get("artifacts", {}).items():
                if art.get("available"):
                    artifact_counts[art_name] = artifact_counts.get(art_name, 0) + 1

        record_refs = [
            {
                "id": f"record-{self.source_id}-meetings-page-{captured_at[:10]}",
                "record_type": "meeting_list_page",
                "source_id": self.source_id,
                "artifact_path": f"data/raw/{self.source_id}/{captured_at[:10]}/source.html",
                "captured_at": captured_at,
            }
        ]

        return {
            "capture_id": self.capture_id(),
            "source_id": self.source_id,
            "adapter": "drupal_ross",
            "captured_at": captured_at,
            "url": self.url,
            "jurisdiction_id": self.jurisdiction_id,
            "institution_id": self.institution_id,
            "raw_artifact": f"data/raw/{self.source_id}/{captured_at[:10]}/source.html",
            "meeting_count": len(meetings),
            "artifact_counts": artifact_counts,
            "meetings": meetings,
            "record_refs": record_refs,
            "errors": [],
        }
