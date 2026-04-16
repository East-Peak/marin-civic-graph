#!/usr/bin/env python3
"""ingest_courtlistener_cases.py — CourtListener federal case ingestion.

Searches the CourtListener RECAP/federal dockets API for cases where Marin
County jurisdictions appear as parties, and produces Case + Organization nodes
with PARTY_TO, IN_JURISDICTION, and HEARD_IN edges.

Usage:
  # Fetch and save locally (limited to 10 per query for testing)
  python scripts/ingest_courtlistener_cases.py --limit 10

  # Fetch and load into Neo4j
  python scripts/ingest_courtlistener_cases.py --limit 50 --load

  # Full run (no limit)
  python scripts/ingest_courtlistener_cases.py --load
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterator

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CL_SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
CL_BASE_URL = "https://www.courtlistener.com"
PAGE_SIZE = 20  # CourtListener default
RATE_LIMIT_SECS = 2.0  # respectful usage
SOURCE_ID = "courtlistener"

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data" / "normalized" / "courtlistener-cases"

# Marin jurisdiction queries — one per entity to maximise recall
QUERIES = [
    '"City of San Rafael"',
    '"City of Novato"',
    '"City of Sausalito"',
    '"City of Mill Valley"',
    '"Town of Fairfax"',
    '"Town of Corte Madera"',
    '"Town of Tiburon"',
    '"Town of Ross"',
    '"City of Belvedere"',
    '"City of Larkspur"',
    '"Town of San Anselmo"',
    '"County of Marin"',
    '"Marin County"',
]

# Canonical jurisdiction registry — maps search token → (org_id, place_id)
# Ordered longest-first so that "Town of Corte Madera" matches before "Marin"
_JURISDICTION_REGISTRY: list[tuple[str, str, str]] = [
    ("City of San Rafael",    "org-city-of-san-rafael",    "place-san-rafael"),
    ("City of Novato",        "org-city-of-novato",        "place-novato"),
    ("City of Sausalito",     "org-city-of-sausalito",     "place-sausalito"),
    ("City of Mill Valley",   "org-city-of-mill-valley",   "place-mill-valley"),
    ("Town of Fairfax",       "org-town-of-fairfax",       "place-fairfax"),
    ("Town of Corte Madera",  "org-town-of-corte-madera",  "place-corte-madera"),
    ("Town of Tiburon",       "org-town-of-tiburon",       "place-tiburon"),
    ("Town of Ross",          "org-town-of-ross",          "place-ross"),
    ("City of Belvedere",     "org-city-of-belvedere",     "place-belvedere"),
    ("City of Larkspur",      "org-city-of-larkspur",      "place-larkspur"),
    ("Town of San Anselmo",   "org-town-of-san-anselmo",   "place-san-anselmo"),
    ("County of Marin",       "org-county-of-marin",       "place-marin-county"),
    ("Marin County",          "org-county-of-marin",       "place-marin-county"),
]

# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def slugify_jurisdiction(name: str) -> str:
    """Convert a jurisdiction name to a URL-safe slug.

    Examples:
        "City of San Rafael" → "city-of-san-rafael"
        "Marin County"       → "marin-county"
    """
    return "-".join(name.strip().lower().split())


def identify_defendant_jurisdiction(case_name: str | None) -> str | None:
    """Scan a case name for a known Marin jurisdiction and return its org_id.

    Matching is case-insensitive.  Returns the first match or None.

    Examples:
        "Rivera v. City of San Rafael"          → "org-city-of-san-rafael"
        "Alves v. Marin County Board of Supers" → "org-county-of-marin"
        "Smith v. Jones"                        → None
    """
    if not case_name:
        return None
    lower = case_name.lower()
    for token, org_id, _ in _JURISDICTION_REGISTRY:
        if token.lower() in lower:
            return org_id
    return None


def _place_id_for_org(org_id: str | None) -> str | None:
    """Return the canonical place_id for a given org_id, or None."""
    if not org_id:
        return None
    for _, oid, place_id in _JURISDICTION_REGISTRY:
        if oid == org_id:
            return place_id
    return None


def transform_case(raw: dict) -> dict:
    """Transform a raw CourtListener search result into a Case node dict.

    Args:
        raw: Single result from the CourtListener search API.

    Returns:
        A Case node dict in the settled graph ontology format.
    """
    docket_id = raw.get("docket_id")
    docket_number = raw.get("docketNumber") or ""
    case_name = raw.get("caseName") or raw.get("case_name_full") or "Unknown"

    # Prefer docket_id for stable identity; fall back to slugified docket number
    if docket_id:
        node_id = f"case-cl-{docket_id}"
    else:
        slug = "-".join(docket_number.replace(":", "-").replace("/", "-").lower().split())
        node_id = f"case-cl-{slug}"

    # Build CourtListener URL if we have the absolute path
    docket_abs = raw.get("docket_absolute_url") or ""
    cl_url = f"{CL_BASE_URL}{docket_abs}" if docket_abs else None

    # Identify which Marin jurisdiction is involved
    defendant_org_id = identify_defendant_jurisdiction(case_name)

    return {
        "id": node_id,
        "node_type": "Case",
        "labels": ["Case"],
        "display_label": case_name,
        "properties": {
            "case_name": case_name,
            "docket_number": docket_number or None,
            "court": raw.get("court") or None,
            "court_id": raw.get("court_id") or None,
            "date_filed": raw.get("dateFiled") or None,
            "date_terminated": raw.get("dateTerminated") or None,
            "cause": raw.get("cause") or None,
            "assigned_to": raw.get("assignedTo") or None,
            "courtlistener_url": cl_url,
            "defendant_org_id": defendant_org_id,
            "source": SOURCE_ID,
        },
    }


def build_case_edges(node: dict, place_id: str | None) -> list[dict]:
    """Build edges for a Case node.

    Produces up to three edge types:
      - PARTY_TO: Case → Organization  (defendant jurisdiction, if identified)
      - IN_JURISDICTION: Case → Place  (if place_id is provided)
      - HEARD_IN: Case → Organization  (federal court org stub)

    Args:
        node:     A transformed Case node dict.
        place_id: The place node ID for the jurisdiction, or None.

    Returns:
        List of edge dicts.
    """
    edges: list[dict] = []
    case_id = node["id"]
    props = node["properties"]

    # PARTY_TO → defendant jurisdiction org
    defendant_org_id = props.get("defendant_org_id")
    if defendant_org_id:
        edges.append({
            "source_id": case_id,
            "target_id": defendant_org_id,
            "relationship_type": "PARTY_TO",
            "properties": {"role": "defendant"},
        })

    # IN_JURISDICTION → place
    if place_id:
        edges.append({
            "source_id": case_id,
            "target_id": place_id,
            "relationship_type": "IN_JURISDICTION",
            "properties": {},
        })

    # HEARD_IN → court org stub
    court_id = props.get("court_id")
    if court_id:
        edges.append({
            "source_id": case_id,
            "target_id": f"org-court-{court_id}",
            "relationship_type": "HEARD_IN",
            "properties": {},
        })

    return edges


def build_court_org_node(court_id: str, court_name: str | None) -> dict:
    """Build an Organization stub node for a federal court.

    Args:
        court_id:   CourtListener short court identifier (e.g. "cand").
        court_name: Human-readable court name, or None.

    Returns:
        An Organization node dict.
    """
    display = court_name if court_name else court_id
    return {
        "id": f"org-court-{court_id}",
        "node_type": "Organization",
        "labels": ["Organization"],
        "display_label": display,
        "properties": {
            "name": display,
            "court_id": court_id,
            "org_type": "court",
            "source": SOURCE_ID,
        },
    }


def build_jurisdiction_org_node(org_id: str, name: str) -> dict:
    """Build an Organization stub node for a Marin jurisdiction.

    Args:
        org_id: The canonical org node ID (e.g. "org-city-of-san-rafael").
        name:   The human-readable jurisdiction name.

    Returns:
        An Organization node dict.
    """
    return {
        "id": org_id,
        "node_type": "Organization",
        "labels": ["Organization", "Government"],
        "display_label": name,
        "properties": {
            "name": name,
            "org_type": "government",
            "county": "Marin",
            "state": "CA",
            "source": SOURCE_ID,
        },
    }


def build_place_node(place_id: str, name: str) -> dict:
    """Build a Place node for a Marin jurisdiction's geography."""
    return {
        "id": place_id,
        "node_type": "Place",
        "labels": ["Place"],
        "display_label": name,
        "properties": {
            "name": name,
            "place_type": "city",
            "county": "Marin",
            "state": "CA",
            "source": SOURCE_ID,
        },
    }


# ---------------------------------------------------------------------------
# Fetch functions (require network)
# ---------------------------------------------------------------------------


def fetch_page(query: str, cursor: str | None = None) -> dict:
    """Fetch a single page of CourtListener search results.

    Args:
        query:  The search query string.
        cursor: Pagination cursor from a prior response's `next` URL, or None
                to start from page 1.

    Returns:
        Raw API response dict with `results`, `count`, and optionally `next`.
    """
    params: dict = {
        "q": query,
        "type": "r",
        "order_by": "score desc",
    }
    if cursor:
        params["cursor"] = cursor

    resp = requests.get(CL_SEARCH_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _extract_cursor(next_url: str | None) -> str | None:
    """Extract the cursor parameter value from a CourtListener `next` URL."""
    if not next_url:
        return None
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(next_url)
    qs = parse_qs(parsed.query)
    cursors = qs.get("cursor", [])
    return cursors[0] if cursors else None


def fetch_cases_for_query(
    query: str,
    limit: int | None = None,
) -> Iterator[dict]:
    """Yield raw case result dicts from CourtListener for a given query.

    Paginates through all results, respecting the RATE_LIMIT_SECS delay
    between requests.

    Args:
        query:  The search query string.
        limit:  Optional cap on total records to fetch per query.
    """
    cursor = None
    total_fetched = 0
    first_page = True

    while True:
        if limit is not None and total_fetched >= limit:
            break

        if not first_page:
            time.sleep(RATE_LIMIT_SECS)

        data = fetch_page(query, cursor=cursor)
        first_page = False

        results = data.get("results", [])
        if not results:
            break

        for record in results:
            yield record
            total_fetched += 1
            if limit is not None and total_fetched >= limit:
                return

        next_url = data.get("next")
        if not next_url:
            break
        cursor = _extract_cursor(next_url)
        if not cursor:
            break


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    limit: int | None = None,
) -> tuple[list[dict], list[dict]]:
    """Search all Marin jurisdiction queries and produce nodes + edges lists.

    Deduplicates cases across queries using docketNumber as the unique key.

    Returns:
        (nodes, edges) containing Case, Organization, and Place nodes.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    seen_dockets: set[str] = set()   # dedup by docketNumber
    seen_courts: set[str] = set()    # court org stubs emitted
    seen_orgs: set[str] = set()      # jurisdiction org stubs emitted
    seen_places: set[str] = set()    # place stubs emitted

    total_cases = 0
    total_dupes = 0

    for query in QUERIES:
        print(f"  Searching: {query}")
        query_count = 0

        for raw in fetch_cases_for_query(query, limit=limit):
            docket_number = raw.get("docketNumber") or ""
            dedup_key = docket_number or raw.get("docket_id") or raw.get("caseName", "")

            if dedup_key in seen_dockets:
                total_dupes += 1
                continue
            seen_dockets.add(dedup_key)

            node = transform_case(raw)
            nodes.append(node)
            query_count += 1
            total_cases += 1

            # Determine the Marin jurisdiction involved
            defendant_org_id = node["properties"].get("defendant_org_id")
            place_id = _place_id_for_org(defendant_org_id)

            # Emit jurisdiction org stub (once per org)
            if defendant_org_id and defendant_org_id not in seen_orgs:
                seen_orgs.add(defendant_org_id)
                # Find the human-readable name for this org_id
                org_name = next(
                    (token for token, oid, _ in _JURISDICTION_REGISTRY if oid == defendant_org_id),
                    defendant_org_id,
                )
                nodes.append(build_jurisdiction_org_node(defendant_org_id, org_name))

            # Emit place stub (once per place)
            if place_id and place_id not in seen_places:
                seen_places.add(place_id)
                place_name = place_id.replace("place-", "").replace("-", " ").title()
                nodes.append(build_place_node(place_id, place_name))

            # Emit court org stub (once per court)
            court_id = node["properties"].get("court_id")
            court_name = node["properties"].get("court")
            if court_id and court_id not in seen_courts:
                seen_courts.add(court_id)
                nodes.append(build_court_org_node(court_id, court_name))

            # Build edges
            case_edges = build_case_edges(node, place_id)
            edges.extend(case_edges)

            time.sleep(0.05)  # tiny intra-page yield for cooperative multitasking

        print(f"    → {query_count} new cases")

    print(
        f"\nTotal: {total_cases} unique cases, {total_dupes} duplicates filtered, "
        f"{len(nodes)} nodes, {len(edges)} edges."
    )
    return nodes, edges


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts to a JSONL file, one record per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Neo4j loader
# ---------------------------------------------------------------------------


def _load_into_neo4j(
    nodes: list[dict],
    edges: list[dict],
    uri: str,
    user: str,
    password: str,
    database: str = "neo4j",
    batch_size: int = 500,
) -> None:
    """Load nodes and edges into Neo4j using batched UNWIND writes."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from load_neo4j_v2 import load_edges, load_nodes

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print(
            "ERROR: neo4j Python driver not installed. Run: pip install neo4j",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Connecting to Neo4j: {uri} (database={database})")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        print("  Connection verified.")

        print(f"Loading {len(nodes):,} nodes into Neo4j (batch_size={batch_size}) ...")
        node_counts = load_nodes(driver, nodes, batch_size=batch_size)
        total_nodes = sum(node_counts.values())
        print(f"  {total_nodes:,} nodes written.")
        for ntype, count in sorted(node_counts.items()):
            print(f"    {ntype:30s} {count:6,d}")

        print(f"Loading {len(edges):,} edges into Neo4j (batch_size={batch_size}) ...")
        edge_counts = load_edges(driver, edges, batch_size=batch_size)
        total_edges = sum(edge_counts.values())
        print(f"  {total_edges:,} edges written.")
        for rel, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
            print(f"    {rel:40s} {count:6,d}")

    finally:
        driver.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search CourtListener for Marin County federal cases and load into Neo4j."
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load nodes and edges into Neo4j after fetching.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit total cases fetched per query (for testing).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Directory to write nodes.jsonl and edges.jsonl (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--uri",
        default=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j connection URI",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("NEO4J_USER", "neo4j"),
        help="Neo4j username",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("NEO4J_PASSWORD"),
        help="Neo4j password (or NEO4J_PASSWORD env var)",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("NEO4J_DATABASE", "neo4j"),
        help="Neo4j database name",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for Neo4j UNWIND writes (default: 500)",
    )
    args = parser.parse_args()

    print(f"CourtListener case ingestion — {len(QUERIES)} queries")
    if args.limit:
        print(f"  (limited to {args.limit} cases per query)")

    nodes, edges = run_pipeline(limit=args.limit)

    output_dir = Path(args.output_dir)
    nodes_path = output_dir / "nodes.jsonl"
    edges_path = output_dir / "edges.jsonl"

    print(f"\nWriting nodes to: {nodes_path}")
    _write_jsonl(nodes_path, nodes)

    print(f"Writing edges to: {edges_path}")
    _write_jsonl(edges_path, edges)

    if args.load:
        if not args.password:
            print(
                "ERROR: NEO4J_PASSWORD is required (--password or NEO4J_PASSWORD env var).",
                file=sys.stderr,
            )
            sys.exit(1)
        _load_into_neo4j(
            nodes=nodes,
            edges=edges,
            uri=args.uri,
            user=args.user,
            password=args.password,
            database=args.database,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
