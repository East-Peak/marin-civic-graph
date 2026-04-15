#!/usr/bin/env python3
"""Agenda PDF extraction pipeline for Marin Civic Graph.

Downloads agenda PDFs from captured meeting URLs, extracts text with
pdftotext, parses sections and items, and creates AgendaItem nodes in Neo4j.

Usage:
    python scripts/extract_agenda_items.py --source novato-city-council --limit 5
    python scripts/extract_agenda_items.py --all --limit 10
    python scripts/extract_agenda_items.py --source novato-city-council --limit 3 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

def normalize_agenda_url(url: Optional[str]) -> Optional[str]:
    """Prepend https: to protocol-relative URLs (//host/path)."""
    if url is None:
        return None
    if url.startswith("//"):
        return "https:" + url
    return url


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

# Granicus: letter-first section headers like "A. CONVENE", "G. CONSENT CALENDAR"
_GRANICUS_SECTION_RE = re.compile(r"^\s*([A-Z])\.\s+[A-Z]", re.MULTILINE)
# CivicPlus: number-first section headers like "1. CALL TO ORDER", "4. CONSENT CALENDAR"
_CIVICPLUS_SECTION_RE = re.compile(r"^\s*(\d+)\.\s+[A-Z]", re.MULTILINE)


_BOS_ITEM_RE = re.compile(r"CA\s*-\s*(\d+)\.", re.MULTILINE)
_TIBURON_ITEM_RE = re.compile(r"(?:CC|AI|PH)-(\d+)\.", re.MULTILINE)


def detect_agenda_format(text: str) -> Optional[str]:
    """Return 'granicus', 'civicplus', 'bos', 'tiburon', or None."""
    # Tiburon uses CC-N. / AI-N. / PH-N. pattern
    tiburon_hits = len(_TIBURON_ITEM_RE.findall(text))
    if tiburon_hits >= 2:
        return "tiburon"

    # BOS uses "CA - N." pattern (Consent Agenda items)
    bos_hits = len(_BOS_ITEM_RE.findall(text))
    if bos_hits >= 3:
        return "bos"

    granicus_hits = len(_GRANICUS_SECTION_RE.findall(text))
    civicplus_hits = len(_CIVICPLUS_SECTION_RE.findall(text))

    # Fairfax/ProudCity/general: simple numbered items (1. Description) with section keywords
    fairfax_items = len(re.findall(r"^\s*(\d+)\.\s+(?!CALL|CONSENT|PUBLIC|BUSINESS|REPORT|CLOSED|ADJOURN)[A-Z]", text, re.MULTILINE))
    if fairfax_items >= 1 and bos_hits == 0 and tiburon_hits == 0:
        has_sections = bool(re.search(r"CONSENT CALENDAR|PUBLIC HEARING|APPROVAL OF|ADJOURN", text, re.I))
        if has_sections:
            return "fairfax"

    # Check for actual item patterns to disambiguate
    # CivicPlus items: "N.LETTER" like "3.A Approve..."
    civicplus_item_hits = len(re.findall(r"^\s+(\d+)\.([A-Z])\s+", text, re.MULTILINE))
    # Granicus items: "LETTER.N" like "G.1. Approve..."
    granicus_item_hits = len(re.findall(r"^\s+([A-Z])\.(\d+)\.\s+", text, re.MULTILINE))

    if civicplus_item_hits > granicus_item_hits:
        return "civicplus"
    if granicus_item_hits > 0:
        return "granicus"
    if civicplus_hits > 0:
        return "civicplus"
    if granicus_hits > 0:
        return "granicus"
    return None


# ---------------------------------------------------------------------------
# Granicus parser
# ---------------------------------------------------------------------------

# Section header: "G. CONSENT CALENDAR" (optional leading whitespace, match to end of line)
_GRAN_SECTION_RE = re.compile(r"^\s*([A-Z])\.\s+([A-Z][A-Z /&]+)", re.MULTILINE)
# Item: "   G.1.   Description text" (leading whitespace required)
_GRAN_ITEM_RE = re.compile(r"^\s+([A-Z])\.(\d+)\.\s+(.+)", re.MULTILINE)


def parse_granicus_agenda(text: str) -> tuple[list[dict], list[dict]]:
    """Parse Granicus-format agenda text into sections and items.

    Returns:
        sections: list of {"label": "G", "name": "CONSENT CALENDAR"}
        items: list of {"section": "G", "number": "1", "section_name": "...", "title": "..."}
    """
    if not text.strip():
        return [], []

    # Build label -> name mapping from section headers
    section_map: dict[str, str] = {}
    sections: list[dict] = []
    for m in _GRAN_SECTION_RE.finditer(text):
        label = m.group(1)
        name = m.group(2).strip()
        if label not in section_map:
            section_map[label] = name
            sections.append({"label": label, "name": name})

    items: list[dict] = []
    for m in _GRAN_ITEM_RE.finditer(text):
        section_label = m.group(1)
        number = m.group(2)
        title = m.group(3).strip()
        items.append({
            "section": section_label,
            "number": number,
            "section_name": section_map.get(section_label, ""),
            "title": title,
        })

    return sections, items


# ---------------------------------------------------------------------------
# CivicPlus parser
# ---------------------------------------------------------------------------

# Section header: "4. CONSENT CALENDAR" (optional leading whitespace)
_CP_SECTION_RE = re.compile(r"^\s*(\d+)\.\s+([A-Z][A-Z\s/&]+)", re.MULTILINE)
# Item: "   4.A.   Description text" (leading whitespace required)
_CP_ITEM_RE = re.compile(r"^\s+(\d+)\.([A-Z])\.?\s+(.+)", re.MULTILINE)


def parse_civicplus_agenda(text: str) -> tuple[list[dict], list[dict]]:
    """Parse CivicPlus-format agenda text into sections and items.

    Returns:
        sections: list of {"label": "4", "name": "CONSENT CALENDAR"}
        items: list of {"section": "4", "number": "A", "section_name": "...", "title": "..."}
    """
    if not text.strip():
        return [], []

    # Build section number -> name mapping
    section_map: dict[str, str] = {}
    sections: list[dict] = []
    for m in _CP_SECTION_RE.finditer(text):
        label = m.group(1)
        name = m.group(2).strip()
        if label not in section_map:
            section_map[label] = name
            sections.append({"label": label, "name": name})

    items: list[dict] = []
    for m in _CP_ITEM_RE.finditer(text):
        section_label = m.group(1)
        number = m.group(2)
        title = m.group(3).strip()
        items.append({
            "section": section_label,
            "number": number,
            "section_name": section_map.get(section_label, ""),
            "title": title,
        })

    return sections, items


# ---------------------------------------------------------------------------
# BOS (Board of Supervisors) parser
# ---------------------------------------------------------------------------

_BOS_SECTION_RE = re.compile(
    r"^(Consent Agenda [A-Z]|Public Hearing|Board (?:Action|Business))",
    re.MULTILINE | re.IGNORECASE,
)
_BOS_CA_ITEM_RE = re.compile(
    r"^CA\s*-\s*(\d+)\.\s*(.*)",
    re.MULTILINE,
)


def parse_bos_agenda(text: str) -> tuple[list[dict], list[dict]]:
    """Parse Marin County BOS HTML agenda format.

    BOS uses "CA - N. Department Name" for consent items
    and "Public Hearing" / "Board Action" for other sections.
    """
    sections: list[dict] = []
    items: list[dict] = []

    # Find section headers
    for m in _BOS_SECTION_RE.finditer(text):
        name = m.group(1).strip()
        sections.append({"label": name[:2].upper(), "name": name})

    # Parse CA items
    for m in _BOS_CA_ITEM_RE.finditer(text):
        number = m.group(1)
        title = m.group(2).strip()
        items.append({
            "section": "CA",
            "number": number,
            "section_name": "Consent Agenda",
            "title": title,
        })

    # Parse Public Hearing items (lines after "Public Hearing" that start with "Request")
    ph_start = text.lower().find("public hearing")
    if ph_start > 0:
        ph_text = text[ph_start:ph_start + 2000]
        request_lines = re.findall(r"Request\s+(.+?)(?:\n|$)", ph_text)
        for i, title in enumerate(request_lines, 1):
            items.append({
                "section": "PH",
                "number": str(i),
                "section_name": "Public Hearing",
                "title": title.strip()[:200],
            })

    return sections, items


# ---------------------------------------------------------------------------
# Fairfax / ProudCity parser
# ---------------------------------------------------------------------------

_FAIRFAX_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.+)", re.MULTILINE)
_FAIRFAX_SECTION_KEYWORDS = {
    "consent calendar": "Consent Calendar",
    "public hearing": "Public Hearing",
    "public comment": "Public Comment",
    "closed session": "Closed Session",
    "action item": "Action Items",
    "new business": "New Business",
    "old business": "Old Business",
    "approval of agenda": "Procedural",
    "approval of minutes": "Procedural",
}


def parse_fairfax_agenda(text: str) -> tuple[list[dict], list[dict]]:
    """Parse Fairfax/ProudCity agenda: simple numbered items with section keywords."""
    lines = text.split("\n")
    sections = []
    items = []
    current_section = "General"

    for line in lines:
        stripped = line.strip()
        # Check for section keywords
        for keyword, section_name in _FAIRFAX_SECTION_KEYWORDS.items():
            if keyword in stripped.lower() and len(stripped) < 80:
                current_section = section_name
                if section_name not in [s["name"] for s in sections]:
                    sections.append({"label": section_name[:2].upper(), "name": section_name})
                break

        # Check for numbered items
        match = re.match(r"^\s*(\d+)\.\s+([A-Z].+)", stripped)
        if match:
            number = match.group(1)
            title = match.group(2).strip()
            # Skip section header lines that happen to start with numbers
            if any(kw in title.lower() for kw in ["call to order", "roll call", "adjournment", "pledge"]):
                continue
            items.append({
                "section": current_section[:2].upper(),
                "number": number,
                "section_name": current_section,
                "title": title[:200],
            })

    return sections, items


# ---------------------------------------------------------------------------
# Tiburon parser
# ---------------------------------------------------------------------------

_TIBURON_CC_RE = re.compile(r"^CC-(\d+)\.\s*$", re.MULTILINE)
_TIBURON_AI_RE = re.compile(r"^AI-(\d+)\.\s*$", re.MULTILINE)
_TIBURON_PH_RE = re.compile(r"^PH-(\d+)\.\s*$", re.MULTILINE)


def parse_tiburon_agenda(text: str) -> tuple[list[dict], list[dict]]:
    """Parse Tiburon HTML agenda: CC-N (consent), AI-N (action), PH-N (public hearing)."""
    lines = [l.strip() for l in text.split("\n")]
    sections = []
    items = []

    prefix_map = {"CC": "Consent Calendar", "AI": "Action Items", "PH": "Public Hearings"}
    seen_sections = set()

    for i, line in enumerate(lines):
        for prefix, section_name in prefix_map.items():
            # Match CC-1. or CC-1 with optional trailing text
            match = re.match(rf"^{prefix}-(\d+)\.?\s*(.*)", line)
            if match:
                number = match.group(1)
                # Title from same line or next non-empty line
                title = match.group(2).strip()
                if not title:
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if lines[j] and not re.match(r"^(CC|AI|PH)-\d+", lines[j]):
                            title = lines[j][:200]
                            break

                if prefix not in seen_sections:
                    sections.append({"label": prefix, "name": section_name})
                    seen_sections.add(prefix)

                items.append({
                    "section": prefix,
                    "number": number,
                    "section_name": section_name,
                    "title": title,
                })

    # If no CC/AI/PH items found, try numbered items under section headers
    if not items:
        current_section = "General"
        section_keywords = {
            "consent calendar": "Consent Calendar",
            "action item": "Action Items",
            "public hearing": "Public Hearings",
            "staff briefing": "Staff Briefing",
        }
        for line in lines:
            for kw, sname in section_keywords.items():
                if kw in line.lower() and len(line) < 80:
                    current_section = sname
                    if sname not in [s["name"] for s in sections]:
                        sections.append({"label": sname[:2].upper(), "name": sname})

            match = re.match(r"^(\d+)\.\s+(.+)", line)
            if match and not any(skip in line.lower() for skip in ["email", "attend", "zoom", "call-in"]):
                items.append({
                    "section": current_section[:2].upper(),
                    "number": match.group(1),
                    "section_name": current_section,
                    "title": match.group(2)[:200],
                })

    return sections, items


# ---------------------------------------------------------------------------
# Node builder
# ---------------------------------------------------------------------------

def build_agenda_item_node(
    meeting_id: str,
    section: str,
    number: str,
    section_name: str,
    title: str,
    source_id: str,
) -> dict:
    """Build an AgendaItem node dict from parsed agenda fields.

    ID format: agenda-item-{meeting_id_suffix}-{section}{number}
    where suffix = everything after the first 'meeting-' prefix.
    """
    # Strip the leading 'meeting-' prefix to get the suffix
    suffix = meeting_id.removeprefix("meeting-")
    # Compose a short item key: section + number, lowercased
    item_key = f"{section}{number}".lower()
    node_id = f"agenda-item-{suffix}-{item_key}"

    return {
        "id": node_id,
        "node_type": "AgendaItem",
        "display_label": title[:120],
        "promotion_state": "promoted",
        "properties": {
            "heading": section_name.title() if section_name else f"Section {section}",
            "title": title,
            "section_number": section,
            "item_number": number,
            "meeting_id": meeting_id,
            "source_id": source_id,
            "status": "parsed_from_agenda",
        },
    }


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------

def download_agenda(url: str, dest_dir: Path, meeting_id: str) -> tuple[Optional[Path], str]:
    """Download an agenda (PDF or HTML) and return (path, format).

    Returns (None, "failed") on error.
    Returns (path, "pdf") or (path, "html") on success.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, timeout=30, allow_redirects=True, verify=False)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "pdf" in content_type.lower() or resp.content[:4] == b"%PDF":
            path = dest_dir / f"{meeting_id}.pdf"
            path.write_bytes(resp.content)
            return path, "pdf"
        elif "html" in content_type.lower():
            path = dest_dir / f"{meeting_id}.html"
            path.write_bytes(resp.content)
            return path, "html"
        else:
            log.warning("Unknown content type for %s: %s", url, content_type)
            # Try saving anyway and check magic bytes
            if b"%PDF" in resp.content[:8]:
                path = dest_dir / f"{meeting_id}.pdf"
                path.write_bytes(resp.content)
                return path, "pdf"
            return None, "failed"
    except Exception as exc:
        log.warning("Failed to download %s: %s", url, exc)
        return None, "failed"


def extract_text_from_html(html_path: Path) -> Optional[str]:
    """Strip HTML tags to get plain text from an HTML agenda."""
    import re as _re
    from html import unescape
    try:
        html = html_path.read_text(encoding="utf-8", errors="replace")
        text = _re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
        text = _re.sub(r"\s+", " ", text)
        # Try to preserve line breaks by splitting on common delimiters
        text = text.replace(". ", ".\n").replace("  ", "\n")
        return text
    except Exception as exc:
        log.warning("Failed to read HTML %s: %s", html_path, exc)
        return None


def extract_text(pdf_path: Path) -> Optional[str]:
    """Run pdftotext -layout on pdf_path and return stdout text."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            log.warning("pdftotext failed for %s: %s", pdf_path, result.stderr[:200])
            return None
        return result.stdout
    except Exception as exc:
        log.warning("pdftotext error for %s: %s", pdf_path, exc)
        return None


# ---------------------------------------------------------------------------
# Neo4j interaction
# ---------------------------------------------------------------------------

def get_driver(uri: str, user: str, password: str):
    return GraphDatabase.driver(uri, auth=(user, password))


def fetch_meetings_needing_items(
    driver,
    source_id: Optional[str],
    limit: int,
) -> list[dict]:
    """Return meetings that have agenda URLs but no AgendaItem nodes yet."""
    source_filter = "AND r.source_id = $source_id" if source_id else ""
    query = f"""
        MATCH (m:Meeting)-[:EVIDENCED_BY]->(r:Record)
        WHERE r.record_type IN ['meeting_agenda', 'meeting_packet']
        {source_filter}
        AND NOT exists {{ (m)<-[:PART_OF_MEETING]-(:AgendaItem) }}
        RETURN m.id AS meeting_id,
               r.source_id AS source_id,
               r.source_url AS agenda_url,
               m.meeting_date AS meeting_date
        ORDER BY m.meeting_date DESC
        LIMIT $limit
    """
    params: dict = {"limit": limit}
    if source_id:
        params["source_id"] = source_id

    with driver.session() as session:
        result = session.run(query, params)
        return [dict(row) for row in result]


def write_agenda_items(driver, nodes: list[dict], meeting_id: str) -> None:
    """Write AgendaItem nodes and PART_OF_MEETING edges to Neo4j."""
    query = """
        UNWIND $nodes AS n
        MERGE (a:AgendaItem {id: n.id})
        SET a.display_label       = n.display_label,
            a.promotion_state     = n.promotion_state,
            a.heading             = n.properties.heading,
            a.title               = n.properties.title,
            a.section_number      = n.properties.section_number,
            a.item_number         = n.properties.item_number,
            a.meeting_id          = n.properties.meeting_id,
            a.source_id           = n.properties.source_id,
            a.status              = n.properties.status
        WITH a
        MATCH (m:Meeting {id: a.meeting_id})
        MERGE (a)-[:PART_OF_MEETING]->(m)
    """
    with driver.session() as session:
        session.run(query, {"nodes": nodes})


# ---------------------------------------------------------------------------
# Processing loop
# ---------------------------------------------------------------------------

def process_meeting(
    meeting: dict,
    dry_run: bool,
    driver,
    data_root: Path,
) -> dict:
    """Download, parse, and optionally write one meeting's agenda items."""
    meeting_id = meeting["meeting_id"]
    source_id = meeting["source_id"]
    raw_url = meeting["agenda_url"]
    url = normalize_agenda_url(raw_url)

    if not url:
        return {"meeting_id": meeting_id, "status": "skip_no_url", "items": 0}

    # Destination directory for cached downloads
    agenda_dir = data_root / "data" / "raw" / source_id / "agendas"

    # Check for cached files (PDF or HTML)
    cached_pdf = agenda_dir / f"{meeting_id}.pdf"
    cached_html = agenda_dir / f"{meeting_id}.html"

    if cached_pdf.exists():
        log.info("Using cached PDF: %s", cached_pdf)
        file_path, file_type = cached_pdf, "pdf"
    elif cached_html.exists():
        log.info("Using cached HTML: %s", cached_html)
        file_path, file_type = cached_html, "html"
    else:
        log.info("Downloading %s", url)
        file_path, file_type = download_agenda(url, agenda_dir, meeting_id)
        if file_path is None:
            return {"meeting_id": meeting_id, "status": "download_failed", "items": 0}

    # Extract text based on file type
    if file_type == "pdf":
        text = extract_text(file_path)
    else:
        text = extract_text_from_html(file_path)

    if not text or not text.strip():
        return {"meeting_id": meeting_id, "status": "empty_text", "items": 0}

    # Detect format and parse
    fmt = detect_agenda_format(text)
    if fmt == "granicus":
        sections, parsed_items = parse_granicus_agenda(text)
    elif fmt == "civicplus":
        sections, parsed_items = parse_civicplus_agenda(text)
    elif fmt == "bos":
        sections, parsed_items = parse_bos_agenda(text)
    elif fmt == "tiburon":
        sections, parsed_items = parse_tiburon_agenda(text)
    elif fmt == "fairfax":
        sections, parsed_items = parse_fairfax_agenda(text)
    else:
        log.warning("Unknown agenda format for %s", meeting_id)
        return {"meeting_id": meeting_id, "status": "unknown_format", "items": 0}

    if not parsed_items:
        log.warning("No items parsed from %s (format=%s)", meeting_id, fmt)
        return {"meeting_id": meeting_id, "status": "no_items_parsed", "items": 0}

    # Build nodes
    nodes = [
        build_agenda_item_node(
            meeting_id=meeting_id,
            section=item["section"],
            number=item["number"],
            section_name=item["section_name"],
            title=item["title"],
            source_id=source_id,
        )
        for item in parsed_items
    ]

    log.info(
        "%s: %s items from %d sections (format=%s)",
        meeting_id, len(nodes), len(sections), fmt,
    )

    if dry_run:
        # Print a sample for review
        for node in nodes[:3]:
            props = node["properties"]
            print(
                f"  [{props['section_number']}.{props['item_number']}]"
                f" {props['heading']} — {props['title'][:80]}"
            )
        if len(nodes) > 3:
            print(f"  ... and {len(nodes) - 3} more items")
    else:
        write_agenda_items(driver, nodes, meeting_id)

    return {"meeting_id": meeting_id, "status": "ok", "items": len(nodes), "format": fmt}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Extract agenda items from PDFs into Neo4j")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="Process meetings for a specific source_id")
    group.add_argument("--all", action="store_true", help="Process all sources")
    parser.add_argument("--limit", type=int, default=10, help="Max meetings to process")
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write to Neo4j")
    return parser.parse_args(argv)


def main(argv=None):
    import os
    args = parse_args(argv)

    neo4j_uri = os.environ.get("NEO4J_URI", "")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "")

    if not neo4j_uri or not neo4j_password:
        log.error("NEO4J_URI and NEO4J_PASSWORD must be set")
        sys.exit(1)

    driver = get_driver(neo4j_uri, neo4j_user, neo4j_password)
    source_id = args.source if not args.all else None

    log.info(
        "Fetching meetings needing agenda extraction (source=%s, limit=%d, dry_run=%s)",
        source_id or "ALL", args.limit, args.dry_run,
    )

    meetings = fetch_meetings_needing_items(driver, source_id, args.limit)
    log.info("Found %d meetings to process", len(meetings))

    results = []
    for meeting in meetings:
        result = process_meeting(
            meeting=meeting,
            dry_run=args.dry_run,
            driver=driver,
            data_root=ROOT,
        )
        results.append(result)
        if not args.dry_run:
            time.sleep(1)  # rate limit between downloads

    driver.close()

    # Summary
    ok = sum(1 for r in results if r["status"] == "ok")
    total_items = sum(r.get("items", 0) for r in results)
    errors = [r for r in results if r["status"] != "ok"]
    log.info("Done: %d/%d meetings processed, %d total items", ok, len(results), total_items)
    if errors:
        for err in errors:
            log.warning("  %s: %s", err["meeting_id"], err["status"])


if __name__ == "__main__":
    main()
