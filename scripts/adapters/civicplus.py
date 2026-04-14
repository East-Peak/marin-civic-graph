"""CivicPlus AgendaCenter adapter — parsing utilities and adapter."""

from __future__ import annotations

import http.cookiejar
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .base import BaseAdapter

_USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"

# ---------------------------------------------------------------------------
# Month name table (shared with Granicus but redefined here for independence)
# ---------------------------------------------------------------------------

_MONTH_NAMES: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Named-month date: "Month DD, YYYY" or "Mon DD, YYYY" (day may be 1 or 2 digits)
_DATE_RE = re.compile(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b")

# CivicPlus meeting row: <tr … class="catAgendaRow" …>
_ROW_RE = re.compile(r'<tr[^>]+class="catAgendaRow"[^>]*>(.*?)</tr>', re.S)

# aria-label on the <strong> element: "Agenda for April 7, 2026"
_ARIA_LABEL_RE = re.compile(r'<strong[^>]*aria-label="([^"]+)"', re.I)

# Title link inside <p><a …>text</a></p>
_TITLE_LINK_RE = re.compile(
    r'<p[^>]*>\s*<a[^>]+href="(/AgendaCenter/ViewFile/Agenda/[^"]+)"[^>]*>\s*(.*?)\s*</a>',
    re.S,
)

# Agenda URL in the main <p> block (first occurrence is canonical agenda href)
_AGENDA_HREF_RE = re.compile(r'href="(/AgendaCenter/ViewFile/Agenda/[^"?]+)"')

# Minutes URL: in the <td class="minutes"> cell
_MINUTES_HREF_RE = re.compile(r'href="(/AgendaCenter/ViewFile/Minutes/[^"]+)"')

# Packet URL (agenda + ?packet=true)
_PACKET_HREF_RE = re.compile(r'href="(/AgendaCenter/ViewFile/Agenda/[^"]+\?packet=true)"')

# Agenda ID: the numeric suffix after "_MMDDYYYY-" in an AgendaCenter URL
_AGENDA_ID_RE = re.compile(r'/AgendaCenter/ViewFile/(?:Agenda|Minutes)/_\d+-(\d+)')

# Category panel: <div … id="category-panel-{N}" …>
_PANEL_RE = re.compile(r'<div[^>]+id="category-panel-(\d+)"[^>]*>(.*?)(?=<div[^>]+id="category-panel-\d+"|$)', re.S)

# Category heading: <div … id="cat{N}" …><h2 …>Name</h2>
_CAT_HEADING_RE = re.compile(r'id="cat(\d+)"[^>]*>.*?<h2[^>]*>([^<]+)</h2>', re.S)

# Category checkbox: <input … name="chkCategoryID" … value="{N}" …>
_CHECKBOX_RE = re.compile(r'<input[^>]*name="chkCategoryID"[^>]*value="(\d+)"', re.I)

# changeYear(YEAR, catID, ...) calls in anchor hrefs
_CHANGE_YEAR_RE = re.compile(r'changeYear\((\d{4}),\s*(\d+)')

# Strip HTML tags
_TAG_RE = re.compile(r'<[^>]+>')


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    from html import unescape
    text = _TAG_RE.sub(" ", html)
    return " ".join(unescape(text).split())


def _artifact(url: str | None) -> dict:
    return {"available": url is not None, "url": url}


# ---------------------------------------------------------------------------
# Public parsing utilities
# ---------------------------------------------------------------------------

def parse_civicplus_date(text: str) -> str | None:
    """Extract a "Month DD, YYYY" date from *text* and return ISO-8601.

    Handles:
    - Full month names: "April 7, 2026" → "2026-04-07"
    - Abbreviated months: "Apr 7, 2026" → "2026-04-07"
    - aria-label prefix: "Agenda for April 7, 2026" → "2026-04-07"

    Returns ``None`` when no recognisable date is found.
    """
    if not text:
        return None

    m = _DATE_RE.search(text)
    if not m:
        return None

    month_raw = m.group(1).lower()
    day = int(m.group(2))
    year = int(m.group(3))

    month_num = _MONTH_NAMES.get(month_raw) or _MONTH_NAMES.get(month_raw[:3])
    if month_num is None:
        return None

    return f"{year}-{month_num:02d}-{day:02d}"


def extract_categories(html: str) -> list[dict]:
    """Return a list of ``{id, name}`` dicts for every CivicPlus category.

    Categories are discovered by pairing ``<input name="chkCategoryID" …>``
    checkboxes with their corresponding ``<div id="cat{N}"><h2>`` headings.
    The order follows the heading appearance in the document.
    """
    # Build id→name from headings (preserves document order).
    heading_map: dict[str, str] = {}
    for cat_id, name in _CAT_HEADING_RE.findall(html):
        heading_map[cat_id] = name.strip()

    # Collect checkbox IDs to confirm which IDs are present.
    checkbox_ids: set[str] = set(_CHECKBOX_RE.findall(html))

    categories: list[dict] = []
    for cat_id, name in heading_map.items():
        if cat_id in checkbox_ids:
            categories.append({"id": cat_id, "name": name})

    return categories


def extract_years_for_category(html: str, category_id: str) -> list[int]:
    """Return a sorted-descending list of years available for *category_id*.

    Scans all ``changeYear(YYYY, catID, …)`` calls (both year-tab ``<ul>``
    links and the "View More" dropdown) for the given *category_id*.
    """
    cat_int = int(category_id)
    years: set[int] = set()
    for year_str, cid_str in _CHANGE_YEAR_RE.findall(html):
        if int(cid_str) == cat_int:
            years.add(int(year_str))
    return sorted(years, reverse=True)


def parse_meeting_rows(
    html: str,
    base_url: str = "",
    backfill_from: str = "2019-01-01",
) -> list[dict]:
    """Parse all ``<tr class="catAgendaRow">`` entries from *html*.

    Attempts to associate each row with its parent ``category-panel-{N}`` div.
    Uses ``urllib.parse.urljoin`` to build absolute artifact URLs from
    *base_url*.

    Args:
        html:           Full HTML source of a CivicPlus AgendaCenter page.
        base_url:       Base URL of the site (e.g. "https://www.ci.corte-madera.ca.us").
        backfill_from:  ISO-8601 cutoff; rows whose date is earlier are excluded.

    Returns:
        List of meeting dicts ordered by document position.
    """
    # Build category map: panel_id → category name
    cats_by_id: dict[str, str] = {c["id"]: c["name"] for c in extract_categories(html)}

    # Build row_id → category_name by scanning category panels
    row_to_category: dict[str, str] = {}
    for panel_id, panel_html in _PANEL_RE.findall(html):
        cat_name = cats_by_id.get(panel_id, "")
        for tr_id_match in re.finditer(r'<tr[^>]+id="([^"]+)"[^>]+class="catAgendaRow"', panel_html):
            row_to_category[tr_id_match.group(1)] = cat_name

    meetings: list[dict] = []
    row_number = 0

    for row_match in _ROW_RE.finditer(html):
        row_number += 1
        row_html = row_match.group(0)
        row_body = row_match.group(1)

        # --- Row identity ---
        tr_id_m = re.search(r'<tr[^>]+id="([^"]+)"', row_html)
        row_id = tr_id_m.group(1) if tr_id_m else ""

        # --- Date ---
        aria_m = _ARIA_LABEL_RE.search(row_body)
        date_text = aria_m.group(1) if aria_m else ""
        date = parse_civicplus_date(date_text)

        # Apply backfill cutoff
        if date and date < backfill_from:
            continue

        # --- Title ---
        title_m = _TITLE_LINK_RE.search(row_body)
        title = _strip_tags(title_m.group(2)) if title_m else ""

        # --- Artifact URLs ---
        # Agenda: first occurrence of an Agenda href (the <p> link)
        agenda_hrefs = _AGENDA_HREF_RE.findall(row_body)
        # Remove packet URLs from plain agenda list
        plain_agenda = [h for h in agenda_hrefs if "packet=true" not in h]
        agenda_rel = plain_agenda[0] if plain_agenda else None

        minutes_m = _MINUTES_HREF_RE.search(row_body)
        minutes_rel = minutes_m.group(1) if minutes_m else None

        packet_m = _PACKET_HREF_RE.search(row_body)
        packet_rel = packet_m.group(1) if packet_m else None

        # Build absolute URLs
        def _abs(rel: str | None) -> str | None:
            if rel is None:
                return None
            return urllib.parse.urljoin(base_url, rel) if base_url else rel

        agenda_url = _abs(agenda_rel)
        minutes_url = _abs(minutes_rel)
        packet_url = _abs(packet_rel)

        # --- Agenda ID ---
        agenda_id_m = _AGENDA_ID_RE.search(row_body)
        agenda_id = agenda_id_m.group(1) if agenda_id_m else None

        # --- Category ---
        category = row_to_category.get(row_id, "")

        meetings.append({
            "date": date,
            "title": title,
            "category": category,
            "meeting_type": "regular",
            "artifacts": {
                "agenda": _artifact(agenda_url),
                "minutes": _artifact(minutes_url),
                "packet": _artifact(packet_url),
            },
            "source_row_number": row_number,
            "agenda_id": agenda_id,
        })

    return meetings


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class CivicPlusAdapter(BaseAdapter):
    """CivicPlus AgendaCenter adapter.

    Fetches the AgendaCenter landing page, optionally fetches additional
    year pages for each category, parses all meeting rows, filters by the
    optional ``categories`` config list, and returns the capture envelope.
    """

    def _fetch_page(self, url: str) -> str:
        """GET *url* with a cookie jar, return response HTML.

        Uses a shared cookie jar so the session cookie set on the first
        request is replayed on subsequent POST requests.
        """
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with opener.open(req) as resp:
            charset = resp.headers.get_content_charset("utf-8")
            self._cookie_jar = jar
            return resp.read().decode(charset, errors="replace")

    def _fetch_year(self, base_url: str, category_id: str, year: int, cookies: object) -> str:
        """POST to the UpdateCategoryList endpoint for *category_id* / *year*.

        Returns the HTML fragment (may be empty if the endpoint is
        unavailable or the test stub overrides this method).
        """
        parsed = urllib.parse.urlparse(base_url)
        endpoint = urllib.parse.urlunparse(
            parsed._replace(path="/AgendaCenter/UpdateCategoryList")
        )
        payload = urllib.parse.urlencode({
            "categoryID": category_id,
            "year": str(year),
            "catID": category_id,
        }).encode()
        jar = getattr(self, "_cookie_jar", None) or http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            with opener.open(req, timeout=15) as resp:
                charset = resp.headers.get_content_charset("utf-8")
                return resp.read().decode(charset, errors="replace")
        except Exception:  # noqa: BLE001
            return ""

    def capture(self) -> dict:
        """Fetch, parse, and return a capture envelope for this source."""
        # --- Fetch landing page ---
        html = self._fetch_page(self.url)
        captured_at = self.utc_now_iso()

        # --- Write raw HTML ---
        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "source.html"
        raw_path.write_text(html, encoding="utf-8", errors="replace")

        # --- Parse base URL (scheme + host only) ---
        parsed = urllib.parse.urlparse(self.url)
        base_url = urllib.parse.urlunparse(parsed._replace(path="", query="", fragment=""))

        # --- Parse meetings from the landing page ---
        meetings = parse_meeting_rows(html, base_url=base_url, backfill_from=self.backfill_from)

        # --- Discover categories ---
        categories = extract_categories(html)
        category_names = [c["name"] for c in categories]

        # --- Apply optional category filter from config ---
        allowed: list[str] | None = self.config.get("categories")
        if allowed is not None:
            allowed_set = set(allowed)
            meetings = [m for m in meetings if m.get("category") in allowed_set]

        # --- Stamp institution_id and meeting_id onto each meeting ---
        slug = self.source_id
        for m in meetings:
            m["institution_id"] = self.institution_id
            if m.get("agenda_id"):
                m["meeting_id"] = f"meeting-{slug}-{m['agenda_id']}"
            elif m.get("date"):
                row = m["source_row_number"]
                m["meeting_id"] = f"meeting-{slug}-{m['date']}-row-{row}"
            else:
                m["meeting_id"] = f"meeting-{slug}-row-{m['source_row_number']}"

        # --- Compute artifact counts ---
        artifact_counts: dict[str, int] = {}
        for m in meetings:
            for art_name, art in m.get("artifacts", {}).items():
                if art.get("available"):
                    artifact_counts[art_name] = artifact_counts.get(art_name, 0) + 1

        # --- Build record_refs ---
        record_refs = [
            {
                "id": f"record-{self.source_id}-agenda-center-{captured_at[:10]}",
                "record_type": "agenda_center_page",
                "source_id": self.source_id,
                "artifact_path": str(raw_path.relative_to(self.root)),
                "captured_at": captured_at,
            }
        ]

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
            "categories": category_names,
            "meetings": meetings,
            "record_refs": record_refs,
            "errors": [],
        }
