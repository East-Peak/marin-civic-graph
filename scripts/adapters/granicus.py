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
# Adapter stub
# ---------------------------------------------------------------------------

class GranicusAdapter(BaseAdapter):
    def capture(self) -> dict:
        raise NotImplementedError("Granicus capture not yet implemented")
