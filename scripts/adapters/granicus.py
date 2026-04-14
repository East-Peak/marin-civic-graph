"""Granicus Publisher View adapter — shared parsing utilities and stub."""

from __future__ import annotations

import re
import urllib.request
from html import unescape
from pathlib import Path

from .base import BaseAdapter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"

# Matches a full <tr class="listingRow"> … </tr> block (non-greedy, DOTALL).
ROW_RE = re.compile(r'<tr class="listingRow">.*?</tr>', re.S)

# Matches a <td class="listItem" …> … </td> block (non-greedy, DOTALL).
TD_RE = re.compile(r'<td class="listItem"[^>]*>(.*?)</td>', re.S)

# Matches href="…" inside an anchor tag.
HREF_RE = re.compile(r'href="([^"]+)"', re.I)

# Matches the URL inside window.open('URL', …).
ONCLICK_URL_RE = re.compile(r"window\.open\('([^']+)'", re.I)

# Matches Granicus legacy year-section comments, e.g. <!-- 2022 Start -->.
YEAR_COMMENT_RE = re.compile(r"<!-- \d{4} Start -->")

# Matches a tabbed-panel pattern present in modern Granicus pages.
TABBED_PANEL_RE = re.compile(r"tabbed-panel|data-view|ng-", re.I)

# ---------------------------------------------------------------------------
# Legacy-specific patterns
# ---------------------------------------------------------------------------

# Matches a 2-digit-year date like 04/14/26 (possibly followed by time).
LEGACY_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")

# Matches a hidden Unix epoch span used in legacy date cells.
HIDDEN_EPOCH_RE = re.compile(r"<span[^>]*>\s*(\d{10})\s*</span>")

# Matches year-comment-delimited sections: <!-- 2024 Start --> … next start.
YEAR_SECTION_RE = re.compile(
    r"<!--\s*(20\d{2})\s+Start\s*-->(.*?)(?=<!--\s*20\d{2}\s+Start\s*-->|$)",
    re.S,
)

# Matches clip_id and event_id query parameters in Granicus URLs.
CLIP_ID_RE = re.compile(r"clip_id=(\d+)")
EVENT_ID_RE = re.compile(r"event_id=(\d+)")


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def strip_tags(value: str) -> str:
    """Remove HTML tags, decode entities, and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    return " ".join(text.split())


def extract_href(html: str) -> str | None:
    """Return the first href in *html*, or None.

    Returns None for javascript: pseudo-URLs.
    """
    match = HREF_RE.search(html)
    if not match:
        return None
    href = match.group(1)
    if href.lower().startswith("javascript:"):
        return None
    return href


def extract_onclick_url(html: str) -> str | None:
    """Return the URL from the first window.open() call in *html*, or None."""
    match = ONCLICK_URL_RE.search(html)
    if not match:
        return None
    return match.group(1)


def extract_rows(html: str) -> list[str]:
    """Return all <tr class="listingRow"> … </tr> HTML strings from *html*."""
    return ROW_RE.findall(html)


def extract_cells(row_html: str) -> list[str]:
    """Return the inner HTML of each <td class="listItem"> in *row_html*."""
    return TD_RE.findall(row_html)


def classify_meeting(title: str) -> str:
    """Map a meeting title string to a canonical meeting-type token."""
    lower = title.lower()
    if "closed session" in lower:
        return "closed_session"
    if "joint" in lower:
        return "joint_meeting"
    if "budget" in lower:
        return "budget"
    if "special" in lower:
        return "special"
    if "regular" in lower:
        return "regular"
    return "other"


def detect_variant(html: str) -> str:
    """Return 'legacy' if the page uses year-comment navigation, else 'modern'."""
    if YEAR_COMMENT_RE.search(html):
        return "legacy"
    return "modern"


def fetch_html(url: str) -> str:
    """Fetch *url* and return the decoded response body."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode(resp.headers.get_content_charset("utf-8"), errors="replace")


# ---------------------------------------------------------------------------
# Legacy parser
# ---------------------------------------------------------------------------

def parse_legacy_date(text: str) -> str | None:
    """Extract MM/DD/YY from *text* and return an ISO-8601 date string.

    Two-digit years are mapped to the 2000s (00–99 → 2000–2099).
    Returns None if no date pattern is found.
    """
    match = LEGACY_DATE_RE.search(text)
    if not match:
        return None
    mm, dd, yy = match.group(1), match.group(2), match.group(3)
    return f"20{yy}-{mm}-{dd}"


def _artifact(url: str | None) -> dict:
    """Return a canonical artifact dict with *available* and *url* keys."""
    return {"available": url is not None, "url": url}


def _first_id(*urls: str | None) -> tuple[str | None, str | None]:
    """Scan *urls* for the first clip_id and first event_id found."""
    clip_id: str | None = None
    event_id: str | None = None
    for url in urls:
        if url is None:
            continue
        if clip_id is None:
            m = CLIP_ID_RE.search(url)
            if m:
                clip_id = m.group(1)
        if event_id is None:
            m = EVENT_ID_RE.search(url)
            if m:
                event_id = m.group(1)
    return clip_id, event_id


def _parse_legacy_row(cells: list[str], row_number: int) -> dict | None:
    """Parse a 9-column legacy Granicus row.

    Column layout:
      0 Month | 1 Name | 2 Date | 3 Agenda | 4 Minutes |
      5 Video | 6 Captions | 7 MP3 | 8 MP4

    Returns a meeting dict, or None if the row has fewer than 6 cells.
    """
    if len(cells) < 6:
        return None

    # Date cell: strip hidden epoch span, then parse the visible text.
    date_cell = cells[2]
    epoch_match = HIDDEN_EPOCH_RE.search(date_cell)
    source_sort_epoch = int(epoch_match.group(1)) if epoch_match else None
    date = parse_legacy_date(strip_tags(date_cell))

    # Title from Name cell (index 1).
    title = strip_tags(cells[1])

    # Artifact URLs.
    agenda_url = extract_href(cells[3])
    minutes_url = extract_href(cells[4])
    video_url = extract_onclick_url(cells[5])
    captions_url = extract_href(cells[6]) if len(cells) > 6 else None
    mp3_url = extract_href(cells[7]) if len(cells) > 7 else None
    mp4_url = extract_href(cells[8]) if len(cells) > 8 else None

    artifacts = {
        "agenda": _artifact(agenda_url),
        "minutes": _artifact(minutes_url),
        "video": _artifact(video_url),
        "captions": _artifact(captions_url),
        "mp3": _artifact(mp3_url),
        "mp4": _artifact(mp4_url),
    }

    # Extract clip_id / event_id from any artifact URL.
    all_urls = [agenda_url, minutes_url, video_url, captions_url, mp3_url, mp4_url]
    clip_id, event_id = _first_id(*all_urls)

    return {
        "date": date,
        "title": title,
        "meeting_type": classify_meeting(title),
        "artifacts": artifacts,
        "source_row_number": row_number,
        "clip_id": clip_id,
        "event_id": event_id,
        "source_sort_epoch": source_sort_epoch,
    }


def parse_legacy(html: str, backfill_from: str) -> list[dict]:
    """Parse a legacy Granicus archive page partitioned by year comments.

    Iterates over ``<!-- YYYY Start -->`` sections, skips years entirely
    before *backfill_from*, parses each ``<tr class="listingRow">`` with
    :func:`_parse_legacy_row`, and filters individual rows whose date falls
    before *backfill_from*.

    Args:
        html: Full HTML source of the legacy Granicus publisher view.
        backfill_from: ISO-8601 date string (``YYYY-MM-DD``); rows earlier
            than this date are excluded.

    Returns:
        List of meeting dicts in the order they appear in the document.
    """
    cutoff_year = int(backfill_from[:4])
    meetings: list[dict] = []
    row_counter = 0

    for year_str, section_html in YEAR_SECTION_RE.findall(html):
        if int(year_str) < cutoff_year:
            continue

        for row_html in ROW_RE.findall(section_html):
            row_counter += 1
            cells = extract_cells(row_html)
            meeting = _parse_legacy_row(cells, row_counter)
            if meeting is None:
                continue
            # Filter rows whose parsed date falls before the cutoff.
            if meeting["date"] and meeting["date"] < backfill_from:
                continue
            meetings.append(meeting)

    return meetings


# ---------------------------------------------------------------------------
# Modern parser stubs (implemented in Task 4)
# ---------------------------------------------------------------------------

def parse_modern_date(text: str) -> str | None:
    """Parse a modern Granicus date string — implemented in Task 4."""
    raise NotImplementedError("parse_modern_date not yet implemented")


def parse_modern(html: str, backfill_from: str) -> list[dict]:
    """Parse a modern Granicus archive page — implemented in Task 4."""
    raise NotImplementedError("parse_modern not yet implemented")


# ---------------------------------------------------------------------------
# Adapter stub
# ---------------------------------------------------------------------------

class GranicusAdapter(BaseAdapter):
    def capture(self) -> dict:
        raise NotImplementedError("Granicus capture not yet implemented")
