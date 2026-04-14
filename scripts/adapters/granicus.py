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

# Matches numeric date pattern: MM / DD / YYYY (spaces or \xa0 around slashes).
MODERN_NUMERIC_DATE_RE = re.compile(r"(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{4})")

# Matches named-month date: Mon[th] DD[,] YYYY (leading spaces ok for day).
MODERN_NAMED_DATE_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})")

# Matches TabbedPanelsContent divs.  Each panel wraps one year's tbody.
TABBED_CONTENT_RE = re.compile(
    r'<div class="TabbedPanelsContent">(.*?)</div>\s*(?=<div class="TabbedPanelsContent">|</div>\s*</div>)',
    re.S,
)

# Matches the year digit inside a TabbedPanelsTab <li>.
TABBED_TAB_RE = re.compile(r'<li class="TabbedPanelsTab"[^>]*>\s*(\d{4})\s*</li>')


# ---------------------------------------------------------------------------
# Modern parser
# ---------------------------------------------------------------------------

def parse_modern_date(text: str) -> str | None:
    """Parse a modern Granicus date string into ISO-8601 format.

    Handles:
    - ``03 / 24 / 2026`` and ``03\\xa0/\\xa024\\xa0/\\xa02026`` (numeric)
    - ``Apr  7, 2026`` and ``April 14, 2026`` (named month)
    - Optional ``- HH:MM PM`` time suffix (stripped before parsing)

    Returns ``YYYY-MM-DD`` or ``None`` if the text cannot be parsed.
    """
    # Normalise non-breaking spaces and collapse surrounding whitespace.
    normalised = text.replace("\xa0", " ").strip()

    # Strip trailing time suffix (e.g. "- 6:00 PM" or "- 4:01 PM").
    normalised = re.sub(r"\s*-\s*\d{1,2}:\d{2}\s*[AP]M\s*$", "", normalised, flags=re.I).strip()

    # Try numeric pattern first (MM / DD / YYYY).
    m = MODERN_NUMERIC_DATE_RE.search(normalised)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"

    # Try named-month pattern (Mon[th] D[D][,] YYYY).
    m = MODERN_NAMED_DATE_RE.search(normalised)
    if m:
        month_key = m.group(1).lower()
        month_num = MONTH_NAMES.get(month_key) or MONTH_NAMES.get(month_key[:3])
        if month_num is not None:
            return f"{m.group(3)}-{month_num:02d}-{int(m.group(2)):02d}"

    return None


def _parse_modern_row(cells: list[str], row_number: int) -> dict | None:
    """Parse a modern Granicus row.

    Two layouts are handled:

    **Archive row — 6 or 7 cells:**
      0 Name | 1 Date | 2 Duration | 3 Agenda | 4 Minutes | 5 Video [| 6 MP4]

    **Upcoming row — 5 cells:**
      0 Name | 1 Date | 2 AgendaLink | 3 EventLink | 4 eComment

    Rows with fewer than 4 cells are skipped (returns None).
    """
    if len(cells) < 4:
        return None

    title = strip_tags(cells[0])
    date_raw = strip_tags(cells[1])
    date = parse_modern_date(date_raw)

    if len(cells) >= 6:
        # Archive row: Name | Date | Duration | Agenda | Minutes | Video [| MP4]
        agenda_url = extract_href(cells[3])
        minutes_url = extract_href(cells[4])
        video_url = extract_onclick_url(cells[5]) or extract_href(cells[5])
        mp4_url = extract_href(cells[6]) if len(cells) > 6 else None
    else:
        # Upcoming row (5 cells): Name | Date | Agenda | EventLink | eComment
        agenda_url = extract_href(cells[2])
        minutes_url = None
        video_url = None
        mp4_url = None

    artifacts = {
        "agenda": _artifact(agenda_url),
        "minutes": _artifact(minutes_url),
        "video": _artifact(video_url),
        "mp4": _artifact(mp4_url),
    }

    all_urls = [agenda_url, minutes_url, video_url, mp4_url]
    clip_id, event_id = _first_id(*all_urls)

    return {
        "date": date,
        "title": title,
        "meeting_type": classify_meeting(title),
        "artifacts": artifacts,
        "source_row_number": row_number,
        "clip_id": clip_id,
        "event_id": event_id,
        "source_sort_epoch": None,
    }


def parse_modern(html: str, backfill_from: str) -> list[dict]:
    """Parse a modern Granicus archive page (TabbedPanels or flat tbody).

    Attempts the TabbedPanels layout first: if ``<li class="TabbedPanelsTab">``
    year tabs and ``<div class="TabbedPanelsContent">`` panels are found and
    their counts match, each panel is parsed independently.

    Falls back to extracting all ``<tr class="listingRow">`` rows from the
    full document when the tabbed layout is not matched cleanly.

    Args:
        html: Full HTML source of the modern Granicus publisher view.
        backfill_from: ISO-8601 date string (``YYYY-MM-DD``); rows earlier
            than this date are excluded.

    Returns:
        List of meeting dicts in the order they appear in the document.
    """
    meetings: list[dict] = []
    row_counter = 0

    tabs = TABBED_TAB_RE.findall(html)
    panels = TABBED_CONTENT_RE.findall(html)

    if tabs and panels and len(tabs) == len(panels):
        # Tabbed layout: iterate each year panel separately.
        for _year, panel_html in zip(tabs, panels):
            for row_html in ROW_RE.findall(panel_html):
                row_counter += 1
                cells = extract_cells(row_html)
                meeting = _parse_modern_row(cells, row_counter)
                if meeting is None:
                    continue
                if meeting["date"] and meeting["date"] < backfill_from:
                    continue
                meetings.append(meeting)
    else:
        # Flat layout: parse all rows from the full document.
        for row_html in ROW_RE.findall(html):
            row_counter += 1
            cells = extract_cells(row_html)
            meeting = _parse_modern_row(cells, row_counter)
            if meeting is None:
                continue
            if meeting["date"] and meeting["date"] < backfill_from:
                continue
            meetings.append(meeting)

    return meetings


# ---------------------------------------------------------------------------
# Adapter stub
# ---------------------------------------------------------------------------

class GranicusAdapter(BaseAdapter):
    def capture(self) -> dict:
        raise NotImplementedError("Granicus capture not yet implemented")
