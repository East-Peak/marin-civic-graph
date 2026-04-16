#!/usr/bin/env python3
"""ingest_socrata_permits.py — Marin County Socrata building permit ingestion.

Fetches all building permits from the Marin County open data portal (SODA API)
and produces Project + Place nodes with IN_JURISDICTION edges in the settled
graph ontology.

Usage:
  # Fetch and save locally
  python scripts/ingest_socrata_permits.py

  # Fetch and load into Neo4j
  python scripts/ingest_socrata_permits.py --load

  # Limit records (for testing)
  python scripts/ingest_socrata_permits.py --limit 100 --load
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterator

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SODA_URL = "https://data.marincounty.gov/resource/mkbn-caye.json"
PAGE_SIZE = 1000
SOURCE_ID = "marin-county-socrata-permits"

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data" / "normalized" / "marin-county-permits"

# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def slugify_city(city: str) -> str:
    """Convert a city name to a URL-safe slug for Place node IDs.

    Examples:
        "SAUSALITO"    → "sausalito"
        "SAN RAFAEL"   → "san-rafael"
        "CORTE MADERA" → "corte-madera"
    """
    return "-".join(city.strip().lower().split())


def _title_case_city(city: str) -> str:
    """Convert an all-caps city name to title case for display.

    Examples:
        "SAN RAFAEL"   → "San Rafael"
        "CORTE MADERA" → "Corte Madera"
    """
    return " ".join(word.capitalize() for word in city.strip().split())


def build_place_node(city_town: str) -> dict:
    """Build a Place node dict for a given city_town string."""
    slug = slugify_city(city_town)
    return {
        "id": f"place-{slug}",
        "node_type": "Place",
        "labels": ["Place"],
        "display_label": _title_case_city(city_town),
        "properties": {
            "city_town": city_town,
            "place_type": "city",
            "county": "Marin",
            "state": "CA",
            "source": SOURCE_ID,
        },
    }


def _parse_date(raw: str | None) -> str | None:
    """Parse ISO datetime string to YYYY-MM-DD date string.

    Handles the Socrata format "2025-06-20T00:00:00.000".
    Returns None if the input is missing or unparseable.
    """
    if not raw:
        return None
    try:
        return raw[:10]
    except (TypeError, IndexError):
        return None


def _parse_float(raw: str | None) -> float | None:
    """Convert a string to float, returning None on empty or invalid input."""
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def transform_permit(raw: dict) -> dict:
    """Transform a raw Socrata permit record into a Project node dict.

    Args:
        raw: Single record from the SODA API response.

    Returns:
        A Project node dict in the settled graph ontology format.
    """
    unique_id = raw.get("unique_id", "")
    description = raw.get("description") or ""
    address = raw.get("address") or ""

    if description and address:
        display_label = f"{description} at {address}"
    elif description:
        display_label = description
    elif address:
        display_label = f"Permit at {address}"
    else:
        display_label = f"Permit {unique_id}"

    return {
        "id": f"permit-marin-{unique_id}",
        "node_type": "Project",
        "labels": ["Project"],
        "display_label": display_label,
        "properties": {
            "project_type": "building_permit",
            "permit_number": raw.get("permit_number") or None,
            "address": address or None,
            "parcel_number": raw.get("parcel_number") or None,
            "city_town": raw.get("city_town") or None,
            "construction_value": _parse_float(raw.get("construction_value")),
            "description": description or None,
            "type_permit": raw.get("type_permit") or None,
            "permit_category": raw.get("permit_category") or None,
            "issued_date": _parse_date(raw.get("issued_date")),
            "latitude": _parse_float(raw.get("latitude")),
            "longitude": _parse_float(raw.get("longitude")),
            "source": SOURCE_ID,
        },
    }


def build_permit_edges(node: dict) -> list[dict]:
    """Build edges for a permit Project node.

    Currently produces:
        IN_JURISDICTION: Project → Place (one per non-empty city_town)

    Args:
        node: A transformed Project node dict.

    Returns:
        List of edge dicts.
    """
    edges: list[dict] = []
    city_town = node["properties"].get("city_town") or ""
    if city_town:
        slug = slugify_city(city_town)
        edges.append({
            "source_id": node["id"],
            "target_id": f"place-{slug}",
            "relationship_type": "IN_JURISDICTION",
            "properties": {},
        })
    return edges


# ---------------------------------------------------------------------------
# Fetch functions (require network)
# ---------------------------------------------------------------------------


def fetch_page(offset: int, limit: int = PAGE_SIZE) -> list[dict]:
    """Fetch a single page of permits from the SODA API.

    Args:
        offset: Record offset for pagination.
        limit:  Max records to return (capped by SODA at 50 000).

    Returns:
        List of raw record dicts. Empty list signals end of data.
    """
    params = {
        "$limit": limit,
        "$offset": offset,
        "$order": ":id",
    }
    resp = requests.get(SODA_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_permits(limit: int | None = None) -> Iterator[dict]:
    """Yield all permit records, paginating through the SODA API.

    Args:
        limit: Optional cap on total records to fetch (for testing).
    """
    offset = 0
    total_fetched = 0

    while True:
        page_size = PAGE_SIZE
        if limit is not None:
            remaining = limit - total_fetched
            if remaining <= 0:
                break
            page_size = min(PAGE_SIZE, remaining)

        page = fetch_page(offset, page_size)
        if not page:
            break

        for record in page:
            yield record
            total_fetched += 1
            if limit is not None and total_fetched >= limit:
                return

        if len(page) < page_size:
            break  # last page

        offset += len(page)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts to a JSONL file, one record per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts, skipping blank lines."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(limit: int | None = None) -> tuple[list[dict], list[dict]]:
    """Fetch permits and produce nodes + edges lists.

    Returns:
        (nodes, edges) where nodes contains Project and Place nodes,
        and edges contains IN_JURISDICTION relationships.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_places: set[str] = set()

    print(f"Fetching permits from {SODA_URL} ...")
    if limit:
        print(f"  (limited to {limit:,} records)")

    for i, raw in enumerate(fetch_all_permits(limit=limit)):
        node = transform_permit(raw)
        nodes.append(node)

        permit_edges = build_permit_edges(node)
        edges.extend(permit_edges)

        # Collect unique Place nodes from city_town values
        city_town = node["properties"].get("city_town") or ""
        if city_town:
            slug = slugify_city(city_town)
            if slug not in seen_places:
                seen_places.add(slug)
                place_node = build_place_node(city_town)
                nodes.append(place_node)

        if (i + 1) % 5000 == 0:
            print(f"  Fetched {i + 1:,} permits ...")

    total_permits = sum(1 for n in nodes if n["node_type"] == "Project")
    total_places = sum(1 for n in nodes if n["node_type"] == "Place")
    print(f"  Done. {total_permits:,} permit nodes, {total_places} place nodes, {len(edges):,} edges.")
    return nodes, edges


# ---------------------------------------------------------------------------
# Neo4j loader (inline, mirrors load_neo4j_v2 pattern)
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
        print("ERROR: neo4j Python driver not installed. Run: pip install neo4j", file=sys.stderr)
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
        description="Fetch Marin County building permits from Socrata and load into Neo4j."
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
        help="Limit total permits fetched (for testing).",
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

    nodes, edges = run_pipeline(limit=args.limit)

    output_dir = Path(args.output_dir)
    nodes_path = output_dir / "nodes.jsonl"
    edges_path = output_dir / "edges.jsonl"

    print(f"Writing nodes to: {nodes_path}")
    _write_jsonl(nodes_path, nodes)

    print(f"Writing edges to: {edges_path}")
    _write_jsonl(edges_path, edges)

    if args.load:
        if not args.password:
            print("ERROR: NEO4J_PASSWORD is required (--password or NEO4J_PASSWORD env var).", file=sys.stderr)
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
