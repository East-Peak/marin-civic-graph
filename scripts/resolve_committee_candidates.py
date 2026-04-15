#!/usr/bin/env python3
"""Resolve campaign committee names to candidate Person nodes.

Parses candidate names from FPPC committee name conventions and
creates CONTROLLED_BY edges in Neo4j.

California FPPC convention: candidate-controlled committee names follow
"{Candidate Name} for {Office} {Year}" and related patterns.

Usage:
  python scripts/resolve_committee_candidates.py --dry-run
  python scripts/resolve_committee_candidates.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Name extraction patterns — ordered from most to least specific
# ---------------------------------------------------------------------------

# "Friends of Jane Smith for Office 2024"
_FRIENDS_OF_RE = re.compile(r"^Friends of (.+?) for ", re.I)

# "Committee to (Re-)Elect Name for Office" or "Committee to (Re-)Elect Name District …"
_COMMITTEE_TO_ELECT_RE = re.compile(
    r"Committee to (?:Re-)?Elect (.+?)(?:\s+for\s+|\s+District\b|\s+\d{4})", re.I
)

# "Re-Elect Name for Office 2024"
_REELECT_RE = re.compile(r"^Re-[Ee]lect (.+?) for ", re.I)

# "Elect Name for Office 2024" (less common prefix)
_ELECT_RE = re.compile(r"^Elect (.+?) for ", re.I)

# Generic "Name for Office Year" — must end with a 4-digit year
_NAME_FOR_OFFICE_RE = re.compile(r"^(.+?) for .+\b\d{4}\b", re.I)

_EXTRACTION_PATTERNS = [
    _FRIENDS_OF_RE,
    _COMMITTEE_TO_ELECT_RE,
    _REELECT_RE,
    _ELECT_RE,
    _NAME_FOR_OFFICE_RE,
]

# Patterns that indicate non-candidate (PAC / ballot measure / slate) committees
_SKIP_PATTERNS = [
    re.compile(r"Political Action Committee", re.I),
    re.compile(r"\bPAC\b", re.I),
    re.compile(r"\b(?:Yes|No) on\b", re.I),
    re.compile(r"^Committee for\b", re.I),       # "Committee for Safe Schools"
    re.compile(r"&", re.I),                       # Slate: "Doe & Smith for …"
    re.compile(r",.*,", re.I),                    # Slate: "Doe, Smith, Jones for …"
    re.compile(r"\b(?:Alliance|Coalition|Initiative|Foundation)\b", re.I),
    re.compile(r"^Stay\b", re.I),                 # "Stay Green, Keep SMART"
]

# Committee node types that carry a single candidate
CANDIDATE_TYPES: frozenset[str] = frozenset({"CTL", "CAO", "candidate_linked_committee"})


# ---------------------------------------------------------------------------
# Pure functions (tested independently of Neo4j)
# ---------------------------------------------------------------------------

def extract_candidate_name(committee_name: str) -> str | None:
    """Extract the candidate name embedded in an FPPC committee name.

    Returns the candidate name string, or None if the committee does not
    appear to be candidate-controlled (PAC, ballot measure, slate, etc.).
    """
    for pattern in _SKIP_PATTERNS:
        if pattern.search(committee_name):
            return None

    for regex in _EXTRACTION_PATTERNS:
        match = regex.search(committee_name)
        if match:
            name = match.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            # Reject if name contains digits or is only whitespace
            if len(name) >= 1 and not any(c.isdigit() for c in name):
                return name

    return None


def slugify_name(name: str) -> str:
    """Convert a display name to a hyphen-slug (lowercase, no special chars).

    "Kate Colin"              → "kate-colin"
    "Heather McPhail Sridharan" → "heather-mcphail-sridharan"
    "Rodoni"                  → "rodoni"
    """
    # Strip possessives/punctuation that shouldn't become hyphens
    cleaned = re.sub(r"[''`]", "", name)
    cleaned = cleaned.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def _candidate_slugs(candidate_name: str) -> list[str]:
    """Return the set of person-ID slug candidates to try for a name.

    Person IDs in the graph are inconsistent:
      - Migration seeds:  person-{first}-{last}   e.g. person-kate-colin
      - Campaign finance: person-{last}-{first}    e.g. person-kertz-rachel

    For multi-part names we try both orderings.
    """
    parts = candidate_name.lower().split()
    # Strip possessives from each part
    parts = [re.sub(r"[''`]", "", p) for p in parts]
    parts = [re.sub(r"[^a-z0-9]+", "-", p).strip("-") for p in parts]
    parts = [p for p in parts if p]

    slugs: list[str] = []
    if len(parts) == 1:
        slugs.append(f"person-{parts[0]}")
    elif len(parts) == 2:
        first, last = parts
        slugs.append(f"person-{first}-{last}")   # first-last (migration)
        slugs.append(f"person-{last}-{first}")    # last-first (campaign finance)
    elif len(parts) == 3:
        a, b, c = parts
        # "First Middle Last" → try last-first-middle, first-middle-last, last-middle-first
        slugs.append(f"person-{a}-{b}-{c}")       # as-is
        slugs.append(f"person-{c}-{a}-{b}")       # last-first-middle
        slugs.append(f"person-{c}-{b}-{a}")       # last-middle-first
    else:
        # Fallback: as-is and reversed
        all_slug = "person-" + "-".join(parts)
        rev_slug = "person-" + "-".join(reversed(parts))
        slugs.extend([all_slug, rev_slug])

    return slugs


def find_person_match(candidate_name: str, person_lookup: dict[str, str]) -> str | None:
    """Find the Person node ID that best matches the candidate name.

    person_lookup: {person_id: display_name}

    Resolution order:
      1. Case-insensitive exact name match on display_name
      2. Slug match (both first-last and last-first orderings)
      3. Last-name-only match (only if exactly one person has that last name)

    Returns the person_id, or None if no unambiguous match is found.
    """
    # 1. Exact display-name match (case-insensitive)
    name_lower = candidate_name.lower().strip()
    for pid, pname in person_lookup.items():
        if pname.lower() == name_lower:
            return pid

    # 2. Slug match
    for slug in _candidate_slugs(candidate_name):
        if slug in person_lookup:
            return slug

    # 3. Last-name-only fallback (single word, or last token of a multi-word name)
    parts = candidate_name.strip().split()
    if parts:
        last_name = parts[-1].lower()
        matches = [
            pid for pid, pname in person_lookup.items()
            if pname.lower().split()[-1] == last_name
        ]
        if len(matches) == 1:
            return matches[0]

    return None


# ---------------------------------------------------------------------------
# Neo4j I/O
# ---------------------------------------------------------------------------

def _neo4j_driver(uri: str, user: str, password: str):
    """Return an authenticated Neo4j driver."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("neo4j Python driver not installed — run: pip install neo4j")
    return GraphDatabase.driver(uri, auth=(user, password))


def _fetch_persons(session) -> dict[str, str]:
    """Return {person_id: name} for all Person nodes in the graph."""
    result = session.run("MATCH (p:Person) RETURN p.id AS id, p.name AS name")
    return {row["id"]: row["name"] for row in result if row["id"] and row["name"]}


def _fetch_committees(session) -> list[dict]:
    """Return committee dicts with id, name, committee_type."""
    result = session.run(
        "MATCH (c:Committee) RETURN c.id AS id, c.name AS name, "
        "c.committee_type AS committee_type"
    )
    return [
        {"id": row["id"], "name": row["name"], "committee_type": row["committee_type"]}
        for row in result
        if row["id"] and row["name"]
    ]


def _create_controlled_by_edges(session, edges: list[dict]) -> int:
    """MERGE CONTROLLED_BY edges. Returns count of edges written."""
    if not edges:
        return 0
    query = (
        "UNWIND $batch AS row "
        "MATCH (c:Committee {id: row.committee_id}) "
        "MATCH (p:Person {id: row.person_id}) "
        "MERGE (c)-[r:CONTROLLED_BY]->(p) "
        "SET r.resolved_by = 'resolve_committee_candidates', "
        "    r.candidate_name = row.candidate_name"
    )
    session.run(query, batch=edges)
    return len(edges)


# ---------------------------------------------------------------------------
# Main resolution logic
# ---------------------------------------------------------------------------

def resolve(session, dry_run: bool = False) -> dict:
    """Run committee-to-candidate resolution against a live Neo4j session.

    Returns a summary dict with keys:
      processed, matched, unresolved, skipped_type, skipped_no_name, edges_written
    """
    persons = _fetch_persons(session)
    committees = _fetch_committees(session)

    matched_edges: list[dict] = []
    unresolved: list[dict] = []
    skipped_type: list[str] = []
    skipped_no_name: list[str] = []

    for committee in committees:
        ctype = committee.get("committee_type") or ""
        cname = committee["name"]
        cid = committee["id"]

        if ctype not in CANDIDATE_TYPES:
            skipped_type.append(cid)
            continue

        candidate_name = extract_candidate_name(cname)
        if not candidate_name:
            skipped_no_name.append(cid)
            continue

        person_id = find_person_match(candidate_name, persons)
        if person_id:
            matched_edges.append({
                "committee_id": cid,
                "person_id": person_id,
                "candidate_name": candidate_name,
            })
        else:
            unresolved.append({
                "committee_id": cid,
                "committee_name": cname,
                "candidate_name": candidate_name,
            })

    edges_written = 0
    if not dry_run:
        edges_written = _create_controlled_by_edges(session, matched_edges)

    return {
        "processed": len(committees),
        "matched": len(matched_edges),
        "unresolved": len(unresolved),
        "skipped_type": len(skipped_type),
        "skipped_no_name": len(skipped_no_name),
        "edges_written": edges_written,
        "matched_edges": matched_edges,
        "unresolved_list": unresolved,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve campaign committee names to Person nodes and create CONTROLLED_BY edges."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show matches without writing edges to Neo4j."
    )
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "neo4j+s://<INSTANCE-ID>.databases.neo4j.io"))
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", ""))
    args = parser.parse_args()

    if not args.password:
        sys.exit("NEO4J_PASSWORD not set. Pass --password or set the env var.")

    driver = _neo4j_driver(args.uri, args.user, args.password)

    try:
        with driver.session() as session:
            summary = resolve(session, dry_run=args.dry_run)
    finally:
        driver.close()

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{mode}Committee-to-candidate resolution complete")
    print(f"  Committees processed : {summary['processed']}")
    print(f"  Skipped (wrong type) : {summary['skipped_type']}")
    print(f"  Skipped (no name)    : {summary['skipped_no_name']}")
    print(f"  Matched              : {summary['matched']}")
    print(f"  Unresolved           : {summary['unresolved']}")
    if not args.dry_run:
        print(f"  Edges written        : {summary['edges_written']}")

    if summary["matched_edges"]:
        print("\nMatched edges:")
        for edge in summary["matched_edges"]:
            print(f"  {edge['committee_id']} → {edge['person_id']}  [{edge['candidate_name']}]")

    if summary["unresolved_list"]:
        print("\nUnresolved committees (no Person match found):")
        for item in summary["unresolved_list"]:
            print(f"  {item['committee_id']}  \"{item['committee_name']}\"  → extracted: \"{item['candidate_name']}\"")


if __name__ == "__main__":
    main()
