#!/usr/bin/env python3
"""Meeting minutes vote/decision extraction pipeline for Marin Civic Graph.

Downloads minutes PDFs from captured meeting URLs, extracts text with
pdftotext, parses vote records with regex, and creates Decision nodes
linked to Meeting + Person nodes in Neo4j.

Usage:
    python scripts/extract_decisions.py --source novato-city-council --limit 5 --dry-run
    python scripts/extract_decisions.py --source novato-city-council --limit 30 --load
    python scripts/extract_decisions.py --all --limit 10 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
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
# Regex patterns — Novato Granicus minutes format
# ---------------------------------------------------------------------------

# Optional title prefix before a name: "Councilmember", "Mayor Pro Tem", "Mayor", "Vice Mayor", etc.
# We use a non-capturing group to skip optional titles, then capture the final name word.
_NAME_TITLE_PREFIX = r"(?:(?:Mayor\s+Pro\s+Tem|Vice\s+Mayor|Mayor|Councilmember|Councilwoman|Councilman)\s+)?"
# Name: optional-title WORD (supports apostrophes and hyphens within name, e.g. O'Connor)
_NAME_PAT = _NAME_TITLE_PREFIX + r"(\w+(?:['\-]\w+)*)"

# "COUNCIL ACTION[...]: [Upon motion by | Motion made by] [Title] X and seconded\nby [Title] Y, the City Council voted N-N via roll call [to]\n<action text>"
_COUNCIL_ACTION_RE = re.compile(
    r"COUNCIL ACTION(?:\s+ON\s+MAIN\s+MOTION)?:\s*"
    r"(?:Upon motion by|Motion made by|Upon substitute motion (?:made )?by)\s+" + _NAME_PAT
    + r"\s+and\s+seconded\s*\n?\s*"
    r"by\s+" + _NAME_PAT + r",?\s+the City Council voted\s+(\d+-\d+(?:-\d+)?)\s+via roll call\s+(?:to\s+)?"
    r"\s*\n?\s*(.+?)(?=\n\s*AYES:)",
    re.S | re.I,
)

# "COUNCIL MOTION: Upon motion by [Title] X there was no\nsecond and the motion failed."
_FAILED_MOTION_RE = re.compile(
    r"COUNCIL MOTION:\s*Upon motion by\s+" + _NAME_PAT + r"\s+there was no\s*\n?\s*second",
    re.S | re.I,
)

_AYES_RE = re.compile(r"AYES:\s*(.+)", re.I)
_NOES_RE = re.compile(r"NOES:\s*(.+)", re.I)
_RECUSED_RE = re.compile(r"RECUSED:\s*(.+)", re.I)
_ABSENT_RE = re.compile(r"ABSENT:\s*(.+)", re.I)
_OUTCOME_RE = re.compile(r"Motion (carried|failed)\.", re.I)

_RESOLUTION_RE = re.compile(r"Resolution No\.\s*([\d-]+)", re.I)
_ORDINANCE_RE = re.compile(r"Ordinance(?:\s+No\.?)?\s+(\d+)", re.I)


# ---------------------------------------------------------------------------
# Regex patterns — Corte Madera CivicPlus minutes format
# ---------------------------------------------------------------------------

# MOTION: It was M/S/C (Mover/Seconder) to <action text>
# Followed immediately by a ROLL CALL VOTE line.
_CM_MOTION_RE = re.compile(
    r"MOTION:\s+It was M/S/C\s+\((\w+(?:['\-]\w+)*)/(\w+(?:['\-]\w+)*)\)\s+to\s+(.+?)(?=\nROLL CALL VOTE:)",
    re.S | re.I,
)

# ROLL CALL VOTE: N-N in favor  or  N-N (Name opposed) in favor
_CM_ROLL_CALL_RE = re.compile(
    r"ROLL CALL VOTE:\s+(\d+-\d+)\s*(?:\((\w+(?:['\-]\w+)*)\s+opposed\))?\s+in favor",
    re.I,
)


# ---------------------------------------------------------------------------
# Regex patterns — Sausalito narrative-prose minutes format
# ---------------------------------------------------------------------------

# "[Title] Name moved, seconded by [Title] Name, and [unanimously] carried [N-M] [(Name dissenting)]"
_SAU_VOTE_RE = re.compile(
    r"(?:(?:Mayor\s+Pro\s+Tem|Vice\s+Mayor|Mayor|Councilmember|Councilwoman|Councilman)\s+)?"
    r"(\w+(?:['-]\w+)*)\s+moved,\s+seconded\s+by\s+"
    r"(?:(?:Mayor\s+Pro\s+Tem|Vice\s+Mayor|Mayor|Councilmember|Councilwoman|Councilman)\s+)?"
    r"(\w+(?:['-]\w+)*),\s+and\s+(?:unanimously\s+)?carried"
    r"(?:\s+(\d+-\d+))?(?:\s*\((\w+(?:['-]\w+)*)\s+dissenting\))?"
    r",?\s+to\s+(.+?)(?=\n\n|\Z)",
    re.S | re.I,
)


# ---------------------------------------------------------------------------
# Regex patterns — Marin County BOS minutes format
# ---------------------------------------------------------------------------

# Regular session: "M/s Supervisor X - Supervisor Y to <action>. AYES: ALL"
_BOS_MS_RE = re.compile(
    r"M/s\s+Supervisor\s+(\w+(?:['-]\w+)*)\s+-\s+Supervisor\s+(\w+(?:['-]\w+)*)\s+to\s+(.+?)\.\s*AYES:\s*(\w+)",
    re.S | re.I,
)

# Special session: "Motion to <action> moved by Supervisor X and seconded by Supervisor Y"
_BOS_MOVED_RE = re.compile(
    r"(?:Motion\s+to\s+)?(.+?)moved\s+by\s+Supervisor\s+(\w+(?:['-]\w+)*)\s+and\s+seconded\s+by\s+Supervisor\s+(\w+(?:['-]\w+)*)",
    re.S | re.I,
)

_BOS_OUTCOME_RE = re.compile(r"Motion\s+(passed|failed)\.", re.I)


# ---------------------------------------------------------------------------
# Name parsing helpers
# ---------------------------------------------------------------------------

def _parse_name_list(raw: str) -> list[str]:
    """Split a comma-separated name string; return empty list for 'NONE'."""
    raw = raw.strip()
    if raw.upper() == "NONE" or not raw:
        return []
    return [n.strip().upper() for n in raw.split(",") if n.strip()]


# ---------------------------------------------------------------------------
# Core parsers
# ---------------------------------------------------------------------------

def parse_novato_votes(text: str) -> list[dict]:
    """Parse all vote records from Novato-format meeting minutes.

    Handles:
    - COUNCIL ACTION blocks (roll-call votes with AYES/NOES/RECUSED)
    - COUNCIL MOTION blocks (failed motions with no second)

    Returns a list of vote dicts ordered by position in the document, each
    containing: mover, seconder (optional), tally (optional), motion_text,
    ayes, noes, recused, outcome ("carried" | "failed")
    """
    # Normalize Unicode quotes to ASCII so patterns match Novato PDFs (Bug 1)
    text = text.replace('\u2019', "'").replace('\u2018', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')

    # Collect all events as (position, vote_dict) then sort by position.
    events: list[tuple[int, dict]] = []

    # --- Failed motions (no second) ---
    for m in _FAILED_MOTION_RE.finditer(text):
        events.append((m.start(), {
            "mover": m.group(1).upper(),
            "seconder": None,
            "tally": None,
            "motion_text": "motion failed — no second",
            "ayes": [],
            "noes": [],
            "recused": [],
            "absent": [],
            "outcome": "failed",
        }))

    # --- Roll-call votes (COUNCIL ACTION blocks) ---
    for m in _COUNCIL_ACTION_RE.finditer(text):
        mover = m.group(1).upper()
        seconder = m.group(2).upper()
        tally = m.group(3)
        raw_motion = m.group(4)
        # Collapse internal whitespace / line breaks in motion text
        motion_text = re.sub(r"\s+", " ", raw_motion).strip()

        # Search for AYES/NOES/RECUSED/outcome in the text after this match,
        # up to the next COUNCIL ACTION block or ~20 lines.
        search_start = m.end()
        search_end = _find_block_end(text, search_start)
        block = text[search_start:search_end]

        ayes: list[str] = []
        noes: list[str] = []
        recused: list[str] = []
        absent: list[str] = []
        outcome = "unknown"

        am = _AYES_RE.search(block)
        if am:
            ayes = _parse_name_list(am.group(1))

        nm = _NOES_RE.search(block)
        if nm:
            noes = _parse_name_list(nm.group(1))

        rm = _RECUSED_RE.search(block)
        if rm:
            recused = _parse_name_list(rm.group(1))

        abm = _ABSENT_RE.search(block)
        if abm:
            absent = _parse_name_list(abm.group(1))

        om = _OUTCOME_RE.search(block)
        if om:
            outcome = om.group(1).lower()

        events.append((m.start(), {
            "mover": mover,
            "seconder": seconder,
            "tally": tally,
            "motion_text": motion_text,
            "ayes": ayes,
            "noes": noes,
            "recused": recused,
            "absent": absent,
            "outcome": outcome,
        }))

    events.sort(key=lambda x: x[0])
    return [vote for _, vote in events]


def _find_block_end(text: str, start: int) -> int:
    """Find the end of a vote block — stops at the next COUNCIL ACTION/MOTION
    header or after 40 lines, whichever comes first."""
    next_block = re.search(r"\nCOUNCIL (ACTION|MOTION):", text[start:], re.I)
    if next_block:
        return start + next_block.start()
    # Fall back: 40 lines worth of text
    lines = text[start:].split("\n")
    chars = sum(len(l) + 1 for l in lines[:40])
    return start + chars


def parse_cortemadera_votes(text: str) -> list[dict]:
    """Parse all vote records from Corte Madera CivicPlus-format meeting minutes.

    Handles:
    - MOTION: It was M/S/C (Mover/Seconder) to <action> blocks
    - ROLL CALL VOTE: N-N in favor  or  N-N (Name opposed) in favor

    Returns a list of vote dicts ordered by position in the document.  Each
    dict matches the structure used by parse_novato_votes: mover, seconder,
    tally, motion_text, ayes, noes, recused, absent, outcome.

    Note: Corte Madera minutes do not list every voter, so ayes and recused
    are always empty lists.  noes contains the dissenter's last name (upper)
    when one is named; otherwise it is also empty.
    """
    votes: list[dict] = []

    for motion_m in _CM_MOTION_RE.finditer(text):
        mover = motion_m.group(1)
        seconder = motion_m.group(2)
        raw_motion = motion_m.group(3)
        motion_text = re.sub(r"\s+", " ", raw_motion).strip()

        # The ROLL CALL VOTE line starts immediately after the MOTION block.
        roll_start = motion_m.end()
        roll_m = _CM_ROLL_CALL_RE.search(text, roll_start)
        if roll_m is None:
            continue

        tally = roll_m.group(1)
        dissenter = roll_m.group(2)  # None when unanimous

        noes: list[str] = [dissenter.upper()] if dissenter else []

        votes.append({
            "mover": mover,
            "seconder": seconder,
            "tally": tally,
            "motion_text": motion_text,
            "ayes": [],
            "noes": noes,
            "recused": [],
            "absent": [],
            "outcome": "carried",
        })

    return votes


def parse_sausalito_votes(text: str) -> list[dict]:
    """Parse vote records from Sausalito narrative-prose meeting minutes.

    TODO: implement Sausalito format parser.
    """
    raise NotImplementedError("parse_sausalito_votes is not yet implemented")


def parse_bos_votes(text: str) -> list[dict]:
    """Parse vote records from Marin County Board of Supervisors meeting minutes.

    TODO: implement BOS format parser.
    """
    raise NotImplementedError("parse_bos_votes is not yet implemented")


def extract_resolution_numbers(text: str) -> list[str]:
    """Return all resolution numbers found in text (e.g. '2026-021')."""
    return [m.group(1) for m in _RESOLUTION_RE.finditer(text)]


def extract_ordinance_numbers(text: str) -> list[str]:
    """Return all ordinance numbers found in text (e.g. '1733')."""
    return [m.group(1) for m in _ORDINANCE_RE.finditer(text)]


# ---------------------------------------------------------------------------
# Regex patterns — Sausalito narrative-prose minutes format
# ---------------------------------------------------------------------------

# "{Title} {Name} moved, seconded by {Title} {Name}, and {outcome}, to {action}"
# Outcome: "unanimously carried" | "carried N-M[(dissent)]"
_SAU_VOTE_RE = re.compile(
    r"(?:Councilmember|Vice Mayor|Mayor)\s+(\w+(?:['\-]\w+)*)\s+moved,\s+seconded by\s+"
    r"(?:Councilmember|Vice Mayor|Mayor)\s+(\w+(?:['\-]\w+)*),\s+and\s+"
    r"(unanimously carried|carried\s+\d+-\d+(?:\s*\([^)]+\))?)",
    re.S | re.I,
)

# Motion text: everything after ", to " following the outcome clause, up to paragraph end
_SAU_MOTION_TEXT_RE = re.compile(
    r"(?:unanimously carried|carried\s+\d+-\d+(?:\s*\([^)]+\))?)\s*,\s+to\s+(.+?)(?=\n\n|\Z)",
    re.S | re.I,
)

# Dissenter from "(Hoffman dissenting)"
_SAU_DISSENTER_RE = re.compile(r"\((\w+)\s+dissenting\)", re.I)

# Numeric tally from "carried 4-1"
_SAU_TALLY_RE = re.compile(r"carried\s+(\d+-\d+)", re.I)


def parse_sausalito_votes(text: str) -> list[dict]:
    """Parse all vote records from Sausalito narrative-prose minutes.

    Format: "{Title} {Name} moved, seconded by {Title} {Name}, and {outcome}, to {action}"

    Handles "unanimously carried" (tally=None) and "carried N-M (Name dissenting)".
    Only produces results when text is extractable (returns [] for blank input).
    """
    # Normalize Unicode smart quotes — same fix applied to Novato PDFs
    text = text.replace('’', "'").replace('‘', "'")
    text = text.replace('“', '"'').replace('”', '"'')

    votes: list[dict] = []
    for m in _SAU_VOTE_RE.finditer(text):
        mover = m.group(1)
        seconder = m.group(2)
        outcome_clause = m.group(3)

        tally_m = _SAU_TALLY_RE.search(outcome_clause)
        tally = tally_m.group(1) if tally_m else None

        dissenter_m = _SAU_DISSENTER_RE.search(outcome_clause)
        noes = [dissenter_m.group(1).upper()] if dissenter_m else []

        # Motion text lives in a ~500-char window starting at this match
        search_window = text[m.start() : m.start() + 500]
        motion_m = _SAU_MOTION_TEXT_RE.search(search_window)
        if motion_m:
            motion_text = re.sub(r"\s+", " ", motion_m.group(1)).strip().rstrip(".")
        else:
            motion_text = ""

        votes.append({
            "mover": mover,
            "seconder": seconder,
            "tally": tally,
            "motion_text": motion_text,
            "ayes": [],
            "noes": noes,
            "recused": [],
            "absent": [],
            "outcome": "carried",
        })
    return votes


# ---------------------------------------------------------------------------
# Node builder
# ---------------------------------------------------------------------------

def build_decision_node(
    vote: dict,
    meeting_id: str,
    source_id: str,
    vote_index: int,
) -> dict:
    """Build a Decision node dict in settled-ontology format.

    ID: decision-{meeting_id_suffix}-vote-{N}
    """
    suffix = meeting_id.removeprefix("meeting-")
    node_id = f"decision-{suffix}-vote-{vote_index}"

    motion_text = vote.get("motion_text", "")
    display_label = (motion_text[:120] if motion_text else node_id)
    outcome = vote.get("outcome", "unknown")
    decision_type = "failed_motion" if outcome == "failed" and not vote.get("tally") else "roll_call_vote"

    return {
        "id": node_id,
        "node_type": "Decision",
        "display_label": display_label,
        "promotion_state": "promoted",
        "properties": {
            "meeting_id": meeting_id,
            "source_id": source_id,
            "mover": vote.get("mover"),
            "seconder": vote.get("seconder"),
            "tally": vote.get("tally"),
            "motion_text": motion_text,
            "ayes": vote.get("ayes", []),
            "noes": vote.get("noes", []),
            "recused": vote.get("recused", []),
            "absent": vote.get("absent", []),
            "outcome": outcome,
            "decision_type": decision_type,
            "status": outcome,
        },
    }


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

def normalize_minutes_url(url: Optional[str]) -> Optional[str]:
    """Prepend https: to protocol-relative URLs (//host/path)."""
    if url is None:
        return None
    if url.startswith("//"):
        return "https:" + url
    return url


# ---------------------------------------------------------------------------
# PDF / text extraction
# ---------------------------------------------------------------------------

def download_minutes(url: str, dest_dir: Path, meeting_id: str) -> Optional[Path]:
    """Download a minutes PDF; return path or None on failure."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, timeout=30, allow_redirects=True, verify=False)
        resp.raise_for_status()
        if b"%PDF" in resp.content[:8] or "pdf" in resp.headers.get("content-type", "").lower():
            path = dest_dir / f"{meeting_id}.pdf"
            path.write_bytes(resp.content)
            return path
        log.warning("Minutes URL did not return PDF for %s: %s", meeting_id, url)
        return None
    except Exception as exc:
        log.warning("Failed to download minutes %s: %s", url, exc)
        return None


def extract_text(pdf_path: Path) -> Optional[str]:
    """Run pdftotext on pdf_path and return extracted text."""
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


def fetch_meetings_needing_decisions(
    driver,
    source_id: Optional[str],
    limit: int,
) -> list[dict]:
    """Return meetings that have minutes URLs but no linked Decision nodes."""
    source_filter = "AND r.source_id = $source_id" if source_id else ""
    query = f"""
        MATCH (m:Meeting)-[:EVIDENCED_BY]->(r:Record)
        WHERE r.record_type IN ['meeting_minutes', 'meeting_minutes_pdf']
        {source_filter}
        AND NOT exists {{ (m)<-[:DECIDED_AT]-(:Decision) }}
        RETURN m.id AS meeting_id,
               r.source_id AS source_id,
               r.source_url AS minutes_url,
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


def fetch_persons_for_source(driver, source_id: str) -> dict[str, str]:
    """Return {LAST_NAME_UPPER: person_id} for all persons linked to this source."""
    query = """
        MATCH (p:Person)-[:HOLDS|HELD]->(s:Seat)-[:SEAT_OF]->(i:Institution)
        WHERE i.source_id = $source_id OR p.source_id = $source_id
        RETURN p.id AS person_id, p.last_name AS last_name, p.name AS name
        UNION
        MATCH (p:Person)
        WHERE p.source_id = $source_id
        RETURN p.id AS person_id, p.last_name AS last_name, p.name AS name
    """
    with driver.session() as session:
        result = session.run(query, {"source_id": source_id})
        mapping: dict[str, str] = {}
        for row in result:
            if row["last_name"]:
                mapping[row["last_name"].upper()] = row["person_id"]
            elif row["name"]:
                # Derive last name from full name (last word)
                last = row["name"].strip().split()[-1].upper()
                mapping[last] = row["person_id"]
        return mapping


def write_decisions(driver, nodes: list[dict], meeting_id: str, person_map: dict[str, str]) -> int:
    """Write Decision nodes and DECIDED_AT + CAST_VOTE edges to Neo4j.

    Returns number of nodes written.
    """
    if not nodes:
        return 0

    # Upsert Decision nodes
    upsert_query = """
        UNWIND $nodes AS n
        MERGE (d:Decision {id: n.id})
        SET d.display_label  = n.display_label,
            d.promotion_state = n.promotion_state,
            d.meeting_id      = n.properties.meeting_id,
            d.source_id       = n.properties.source_id,
            d.mover           = n.properties.mover,
            d.seconder        = n.properties.seconder,
            d.tally           = n.properties.tally,
            d.motion_text     = n.properties.motion_text,
            d.ayes            = n.properties.ayes,
            d.noes            = n.properties.noes,
            d.recused         = n.properties.recused,
            d.outcome         = n.properties.outcome,
            d.decision_type   = n.properties.decision_type,
            d.status          = n.properties.status
        WITH d
        MATCH (m:Meeting {id: d.meeting_id})
        MERGE (d)-[:DECIDED_AT]->(m)
    """
    with driver.session() as session:
        session.run(upsert_query, {"nodes": nodes})

    # Create CAST_VOTE edges to Person nodes
    vote_edges: list[dict] = []
    for node in nodes:
        for name in node["properties"].get("ayes", []):
            pid = person_map.get(name)
            if pid:
                vote_edges.append({"decision_id": node["id"], "person_id": pid, "vote": "aye"})
        for name in node["properties"].get("noes", []):
            pid = person_map.get(name)
            if pid:
                vote_edges.append({"decision_id": node["id"], "person_id": pid, "vote": "no"})
        for name in node["properties"].get("recused", []):
            pid = person_map.get(name)
            if pid:
                vote_edges.append({"decision_id": node["id"], "person_id": pid, "vote": "recused"})

    if vote_edges:
        edge_query = """
            UNWIND $edges AS e
            MATCH (d:Decision {id: e.decision_id})
            MATCH (p:Person {id: e.person_id})
            MERGE (p)-[:CAST_VOTE {vote: e.vote}]->(d)
        """
        with driver.session() as session:
            session.run(edge_query, {"edges": vote_edges})

    return len(nodes)


# ---------------------------------------------------------------------------
# Processing loop
# ---------------------------------------------------------------------------

def process_meeting(
    meeting: dict,
    dry_run: bool,
    driver,
    data_root: Path,
    person_map: Optional[dict[str, str]] = None,
) -> dict:
    """Download, parse, and optionally write one meeting's decisions."""
    meeting_id = meeting["meeting_id"]
    source_id = meeting["source_id"]
    raw_url = meeting.get("minutes_url")
    url = normalize_minutes_url(raw_url)

    if not url:
        return {"meeting_id": meeting_id, "status": "skip_no_url", "decisions": 0}

    minutes_dir = data_root / "data" / "raw" / source_id / "minutes"
    cached_pdf = minutes_dir / f"{meeting_id}.pdf"

    if cached_pdf.exists():
        log.info("Using cached PDF: %s", cached_pdf)
        pdf_path = cached_pdf
    else:
        log.info("Downloading minutes: %s", url)
        pdf_path = download_minutes(url, minutes_dir, meeting_id)
        if pdf_path is None:
            return {"meeting_id": meeting_id, "status": "download_failed", "decisions": 0}

    text = extract_text(pdf_path)
    if not text or not text.strip():
        return {"meeting_id": meeting_id, "status": "empty_text", "decisions": 0}

    if re.search(r"MOTION:\s+It was M/S/C", text, re.I):
        votes = parse_cortemadera_votes(text)
    else:
        votes = parse_novato_votes(text)
    resolution_nums = extract_resolution_numbers(text)
    ordinance_nums = extract_ordinance_numbers(text)

    if not votes:
        log.info("%s: no votes found", meeting_id)
        return {"meeting_id": meeting_id, "status": "no_votes_found", "decisions": 0}

    nodes = [
        build_decision_node(vote, meeting_id, source_id, i)
        for i, vote in enumerate(votes)
    ]

    log.info(
        "%s: %d votes parsed (resolutions=%s, ordinances=%s)",
        meeting_id, len(votes), resolution_nums, ordinance_nums,
    )

    if dry_run:
        for node in nodes:
            p = node["properties"]
            tally = p.get("tally") or "no-tally"
            ayes_str = ", ".join(p.get("ayes", [])) or "—"
            noes_str = ", ".join(p.get("noes", [])) or "—"
            recused_str = ", ".join(p.get("recused", [])) or "—"
            print(
                f"  [{node['id']}]\n"
                f"    motion : {p['motion_text'][:100]}\n"
                f"    tally  : {tally}  outcome={p['outcome']}\n"
                f"    mover  : {p.get('mover')}  seconder={p.get('seconder')}\n"
                f"    ayes   : {ayes_str}\n"
                f"    noes   : {noes_str}\n"
                f"    recused: {recused_str}\n"
            )
        if resolution_nums:
            print(f"  Resolutions: {', '.join(resolution_nums)}")
        if ordinance_nums:
            print(f"  Ordinances:  {', '.join(ordinance_nums)}")
    else:
        pm = person_map or {}
        write_decisions(driver, nodes, meeting_id, pm)

    return {
        "meeting_id": meeting_id,
        "status": "ok",
        "decisions": len(nodes),
        "resolutions": resolution_nums,
        "ordinances": ordinance_nums,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract vote decisions from meeting minutes PDFs into Neo4j"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="Process meetings for a specific source_id")
    group.add_argument("--all", action="store_true", help="Process all sources")
    parser.add_argument("--limit", type=int, default=10, help="Max meetings to process")
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write to Neo4j")
    parser.add_argument("--load", action="store_true", help="Write parsed decisions to Neo4j")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    neo4j_uri = os.environ.get("NEO4J_URI", "")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "")

    if not neo4j_uri or not neo4j_password:
        log.error("NEO4J_URI and NEO4J_PASSWORD must be set")
        sys.exit(1)

    driver = get_driver(neo4j_uri, neo4j_user, neo4j_password)
    source_id = args.source if not args.all else None

    dry_run = args.dry_run or not args.load

    log.info(
        "Fetching meetings needing decision extraction (source=%s, limit=%d, dry_run=%s)",
        source_id or "ALL", args.limit, dry_run,
    )

    meetings = fetch_meetings_needing_decisions(driver, source_id, args.limit)
    log.info("Found %d meetings to process", len(meetings))

    # Pre-fetch person map for CAST_VOTE edge resolution
    person_map: dict[str, str] = {}
    if not dry_run and source_id:
        person_map = fetch_persons_for_source(driver, source_id)
        log.info("Loaded %d person name mappings for %s", len(person_map), source_id)

    # Cache person maps per source so --all builds them lazily per meeting (Bug 2)
    person_map_cache: dict[str, dict[str, str]] = {}
    if not dry_run and source_id:
        person_map_cache[source_id] = person_map

    results = []
    for meeting in meetings:
        meeting_person_map = person_map
        if not dry_run:
            meeting_source_id = meeting.get("source_id")
            if meeting_source_id:
                if meeting_source_id not in person_map_cache:
                    person_map_cache[meeting_source_id] = fetch_persons_for_source(
                        driver, meeting_source_id
                    )
                    log.info(
                        "Loaded %d person name mappings for %s",
                        len(person_map_cache[meeting_source_id]),
                        meeting_source_id,
                    )
                meeting_person_map = person_map_cache[meeting_source_id]

        result = process_meeting(
            meeting=meeting,
            dry_run=dry_run,
            driver=driver,
            data_root=ROOT,
            person_map=meeting_person_map,
        )
        results.append(result)
        if not dry_run:
            time.sleep(0.5)

    driver.close()

    ok = sum(1 for r in results if r["status"] == "ok")
    total_decisions = sum(r.get("decisions", 0) for r in results)
    errors = [r for r in results if r["status"] not in ("ok", "no_votes_found")]
    log.info(
        "Done: %d/%d meetings processed, %d decisions extracted",
        ok, len(results), total_decisions,
    )
    if errors:
        log.warning("Meetings with errors: %s", [r["meeting_id"] for r in errors])


if __name__ == "__main__":
    main()
