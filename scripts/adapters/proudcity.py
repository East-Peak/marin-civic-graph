"""ProudCity (WordPress) meeting adapter.

Covers Fairfax, Belvedere, and San Rafael. Two-phase capture:
1. Scrape meeting list/archive pages for /meetings/{slug}/ or /event/{slug}/ URLs
2. Visit each detail page to extract GCS PDF artifact URLs from tab sections

Tab sections on detail pages use id="tab-agenda", "tab-agenda-packet",
"tab-minutes", "tab-video". PDFs are hosted on GCS:
  storage.googleapis.com/proudcity/{city}ca/...
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

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Match /meetings/{slug}/ or /event/{slug}/ links (relative or absolute)
MEETING_LINK_RE = re.compile(
    r'<a\s[^>]*href="((?:https?://[^"]*)?/(?:meetings|event)/[^"]+/)"[^>]*>(.*?)</a>',
    re.S | re.I,
)

# Match month name + day + year in titles: "January 8, 2025" or "January 8 2025"
DATE_IN_TITLE_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})"
)

# Match any PDF URL in an href attribute
PDF_HREF_RE = re.compile(r'href="(https?://[^"]*\.pdf)"', re.I)

# Tab section anchor IDs we look for in detail pages
TAB_IDS = {
    "agenda": "tab-agenda",
    "packet": "tab-agenda-packet",
    "minutes": "tab-minutes",
    "video": "tab-video",
}

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

# Next-tab marker — used to bound a section when scanning forward
_NEXT_TAB_RE = re.compile(
    r'<div[^>]+id="tab-(?:agenda-packet|agenda|minutes|video)"', re.I
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


# ---------------------------------------------------------------------------
# Public parsing functions
# ---------------------------------------------------------------------------

def parse_meeting_date_from_title(title: str) -> str | None:
    """Extract a date from a meeting title.

    Handles forms like:
      - "Town Council Meeting: January 8, 2025"
      - "City Council - April 6, 2026"
      - "Planning Commission Meeting: December 15, 2023"

    Returns an ISO-8601 date string "YYYY-MM-DD" or None.
    """
    match = DATE_IN_TITLE_RE.search(title)
    if not match:
        return None
    month_str, day_str, year_str = match.groups()
    month = MONTH_NAMES.get(month_str.lower())
    if not month:
        return None
    return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"


def extract_meeting_urls(html: str, base_url: str) -> list[dict]:
    """Extract meeting URLs and titles from a ProudCity list/archive page.

    Handles both /meetings/{slug}/ and /event/{slug}/ link patterns
    used across ProudCity sites. Deduplicates by URL.

    Returns a list of dicts with keys: url, title, slug, date.
    """
    meetings: list[dict] = []
    seen_urls: set[str] = set()

    for href, title_html in MEETING_LINK_RE.findall(html):
        # href may be relative or absolute — normalise to absolute
        if href.startswith("http"):
            full_url = href
        else:
            full_url = urljoin(base_url, href)

        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = _strip_tags(title_html)
        if not title:
            continue

        # Slug is the last non-empty path segment
        slug = href.rstrip("/").split("/")[-1]

        meetings.append({
            "url": full_url,
            "title": title,
            "slug": slug,
            "date": parse_meeting_date_from_title(title),
        })

    return meetings


def extract_artifacts_from_detail(html: str) -> dict:
    """Extract artifact PDF URLs from a ProudCity meeting detail page.

    Searches each known tab section (agenda, packet, minutes, video) for
    PDF href links. Bounds each section search at the next tab marker so
    that a PDF in one section is not attributed to another.

    Returns a dict keyed by artifact type with values {"available": bool, "url": str|None}.
    """
    artifacts: dict[str, dict] = {}

    # Build an ordered list of (art_type, start_pos) for tab sections found
    tab_positions: list[tuple[str, int]] = []
    for art_type, tab_id in TAB_IDS.items():
        marker = f'id="{tab_id}"'
        pos = html.find(marker)
        if pos != -1:
            tab_positions.append((art_type, pos))

    # Sort by position in document
    tab_positions.sort(key=lambda x: x[1])

    for i, (art_type, start_pos) in enumerate(tab_positions):
        # Section runs from here to the next tab section (or 8 KB ahead)
        if i + 1 < len(tab_positions):
            end_pos = tab_positions[i + 1][1]
        else:
            end_pos = start_pos + 8192

        section = html[start_pos:end_pos]
        pdf_urls = PDF_HREF_RE.findall(section)
        if pdf_urls:
            artifacts[art_type] = {"available": True, "url": pdf_urls[0]}
        else:
            artifacts[art_type] = {"available": False, "url": None}

    # Ensure all four keys are always present
    for art_type in TAB_IDS:
        if art_type not in artifacts:
            artifacts[art_type] = {"available": False, "url": None}

    return artifacts


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ProudCityAdapter(BaseAdapter):
    """ProudCity WordPress meeting adapter.

    Two-phase capture:
    1. Fetch list page (and any archive_pages configured) to collect meeting URLs.
    2. Visit each meeting detail page to extract PDF artifact URLs from tab sections.
    """

    _request_delay: float = 1.0

    def _fetch_page(self, url: str) -> str:
        """Fetch a URL and return HTML. Extracted as method for test monkey-patching."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "ignore")

    def capture(self) -> dict:
        captured_at = self.utc_now_iso()
        base_url = self.url.rstrip("/")
        # Strip trailing path segment to get domain root for resolving relative URLs
        if "/meetings" in base_url:
            base_url = base_url.rsplit("/meetings", 1)[0]
        elif "/departments" in base_url:
            base_url = base_url.rsplit("/departments", 1)[0]

        # ------------------------------------------------------------------ #
        # Phase 1: Fetch list page(s) and collect meeting URLs
        # ------------------------------------------------------------------ #
        list_html = self._fetch_page(self.url)

        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.html").write_text(list_html, encoding="utf-8")

        all_meetings = extract_meeting_urls(list_html, base_url)

        # Fetch additional archive pages if configured
        for archive_url in self.config.get("archive_pages", []):
            if self._request_delay:
                time.sleep(self._request_delay)
            try:
                archive_html = self._fetch_page(archive_url)
            except Exception:
                continue
            seen = {m["url"] for m in all_meetings}
            for entry in extract_meeting_urls(archive_html, base_url):
                if entry["url"] not in seen:
                    all_meetings.append(entry)
                    seen.add(entry["url"])

        # Apply backfill_from filter (meetings with no date are kept)
        backfill = self.backfill_from
        all_meetings = [
            m for m in all_meetings
            if not m["date"] or m["date"] >= backfill
        ]

        # ------------------------------------------------------------------ #
        # Phase 2: Visit each meeting detail page for artifact URLs
        # ------------------------------------------------------------------ #
        meetings: list[dict] = []
        errors: list[str] = []

        for i, entry in enumerate(all_meetings):
            if self._request_delay and i > 0:
                time.sleep(self._request_delay)
            try:
                detail_html = self._fetch_page(entry["url"])
                artifacts = extract_artifacts_from_detail(detail_html)
            except Exception as exc:
                errors.append(f"Failed to fetch {entry['url']}: {exc}")
                artifacts = {k: {"available": False, "url": None} for k in TAB_IDS}

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

        # Compute per-artifact-type availability counts
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
