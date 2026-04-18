#!/usr/bin/env python3
"""ingest_form700.py — NetFile /pub/ Form 700 ingestion for Marin Civic Graph.

Fetches the Form 700 filing index from any NetFile /pub/ portal (identified by
AID parameter) and produces Filing nodes with FILED_BY edges to Person nodes
and IN_JURISDICTION edges to Place nodes.

All nine Marin-area portals use the same ASP.NET form-post pattern with only
the AID differing.

Usage:
  # Fetch from Marin County portal (broadest — 80+ agencies)
  python scripts/ingest_form700.py --agency cmar --load

  # Fetch from San Rafael
  python scripts/ingest_form700.py --agency raf --load

  # All known portals
  python scripts/ingest_form700.py --all --load

  # Limit for testing
  python scripts/ingest_form700.py --agency cmar --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data" / "normalized" / "form700"
USER_AGENT = "Mozilla/5.0"
DEFAULT_FLOOR_DATE = date(2019, 1, 1)

# All known Marin-area NetFile /pub/ portals; key = AID (case-insensitive)
KNOWN_AGENCIES: dict[str, dict[str, str]] = {
    "cmar": {
        "label": "Marin County",
        "place_id": "place-marin-county",
        "url": "https://public.netfile.com/pub/?aid=cmar",
    },
    "raf": {
        "label": "City of San Rafael",
        "place_id": "place-san-rafael",
        "url": "https://public.netfile.com/pub/?AID=raf",
    },
    "nvo": {
        "label": "City of Novato",
        "place_id": "place-novato",
        "url": "https://public.netfile.com/pub/?AID=NVO",
    },
    "sau": {
        "label": "City of Sausalito",
        "place_id": "place-sausalito",
        "url": "https://public.netfile.com/pub/?AID=SAU",
    },
    "tib": {
        "label": "Town of Tiburon",
        "place_id": "place-tiburon",
        "url": "https://public.netfile.com/pub/?AID=tib",
    },
    "ctm": {
        "label": "Town of Corte Madera",
        "place_id": "place-corte-madera",
        "url": "https://public.netfile.com/pub/?aid=ctm",
    },
    "lark": {
        "label": "City of Larkspur",
        "place_id": "place-larkspur",
        "url": "https://public.netfile.com/pub/?aid=LARK",
    },
    "smo": {
        "label": "Town of San Anselmo",
        "place_id": "place-san-anselmo",
        "url": "https://public.netfile.com/pub/?aid=SMO",
    },
    "ross": {
        "label": "Town of Ross",
        "place_id": "place-ross",
        "url": "https://public.netfile.com/pub/?AID=ROSS",
    },
}

# ---------------------------------------------------------------------------
# Regex patterns (compiled once)
# ---------------------------------------------------------------------------

INPUT_PATTERN = re.compile(
    r'<input[^>]*name="(?P<name>[^"]+)"[^>]*?(?:value="(?P<value>[^"]*)")?[^>]*>',
    re.I,
)

# Match <tr> rows where all five leading cells are <td> (not <th>), followed
# by optional extra cells.  The date cell must be MM/DD/YYYY.
ROW_PATTERN = re.compile(
    r"<tr>\s*"
    r"<td>(?P<filer_name>[^<]+)</td>\s*"
    r"<td>(?P<filed_at>\d{1,2}/\d{1,2}/\d{4})</td>\s*"
    r"<td>(?P<statement_type>[^<]*)</td>\s*"
    r"<td>(?P<job_title>[^<]*)</td>\s*"
    r"<td>(?P<department>[^<]*)</td>"
    r"(?P<tail>.*?)"
    r"</tr>",
    re.I | re.S,
)

# ---------------------------------------------------------------------------
# Pure helper functions (tested directly)
# ---------------------------------------------------------------------------


def slugify(value: str) -> str:
    """Convert a string to a lowercase URL-safe slug."""
    value = unescape(value).lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def normalize_name(raw: str) -> str:
    """Convert 'Last, First [Middle]' to 'First [Middle] Last'.

    If the value contains no comma the input is returned stripped.
    """
    raw = raw.strip()
    if "," in raw:
        last, _, rest = raw.partition(",")
        return f"{rest.strip()} {last.strip()}"
    return raw


def person_id_from_name(raw_name: str) -> str:
    """Produce a stable person node ID from a (possibly inverted) filer name.

    'Colin, Kate' and 'Kate Colin' both produce 'person-kate-colin'.
    """
    normalized = normalize_name(raw_name)
    return f"person-f700-{slugify(normalized)}"


def parse_filing_rows(html: str) -> list[dict[str, Any]]:
    """Parse HTML table rows from a NetFile /pub/ Form 700 export.

    Each matching <tr> with five leading <td> cells (name, date, type, title,
    dept) becomes one row dict.  Header rows using <th> are skipped by the
    regex.  HTML entities in cell text are decoded.

    Returns a list of row dicts with keys:
        filer_name, filed_at (ISO YYYY-MM-DD), statement_type,
        job_title, department
    """
    rows: list[dict[str, Any]] = []
    for m in ROW_PATTERN.finditer(html):
        filer_name = unescape(m.group("filer_name").strip())
        raw_date = m.group("filed_at").strip()
        filed_dt = datetime.strptime(raw_date, "%m/%d/%Y").date()
        statement_type = unescape(m.group("statement_type").strip())
        job_title = unescape(m.group("job_title").strip())
        department = unescape(m.group("department").strip())
        rows.append(
            {
                "filer_name": filer_name,
                "filed_at": filed_dt.isoformat(),
                "statement_type": statement_type,
                "job_title": job_title,
                "department": department,
            }
        )
    return rows


def build_filing_node(
    row: dict[str, Any],
    *,
    agency_id: str,
    agency_label: str | None = None,
) -> dict[str, Any]:
    """Build a Filing node dict from a parsed row.

    Args:
        row:          Parsed row dict from parse_filing_rows().
        agency_id:    Lower-cased NetFile AID (e.g. 'raf', 'cmar').
        agency_label: Human-readable agency name (e.g. 'City of San Rafael').

    Returns:
        A Filing node dict in the graph ontology format.
    """
    filer_name = row["filer_name"]
    filed_at = row["filed_at"]
    statement_type = row["statement_type"]
    job_title = row["job_title"]
    department = row["department"]

    slug_parts = [
        agency_id,
        filed_at,
        slugify(filer_name),
        slugify(statement_type),
        slugify(job_title),
        slugify(department),
    ]
    node_id = "filing-form700-" + "-".join(p for p in slug_parts if p)

    display_label = (
        f"Form 700 — {normalize_name(filer_name)} ({statement_type}) — {filed_at}"
    )

    props: dict[str, Any] = {
        "filing_type": "form_700",
        "filer_name": filer_name,
        "filed_at": filed_at,
        "statement_type": statement_type,
        "job_title": job_title,
        "department": department,
        "agency_id": agency_id,
    }
    if agency_label:
        props["agency"] = agency_label

    return {
        "id": node_id,
        "node_type": "Filing",
        "labels": ["Filing"],
        "display_label": display_label,
        "properties": props,
    }


def build_filed_by_edge(filing_id: str, person_id: str) -> dict[str, Any]:
    """Build a FILED_BY edge from a Filing node to a Person/Actor node."""
    return {
        "source_id": filing_id,
        "target_id": person_id,
        "relationship_type": "FILED_BY",
        "properties": {},
    }


def build_in_jurisdiction_edge(filing_id: str, place_id: str) -> dict[str, Any]:
    """Build an IN_JURISDICTION edge from a Filing node to a Place node."""
    return {
        "source_id": filing_id,
        "target_id": place_id,
        "relationship_type": "IN_JURISDICTION",
        "properties": {},
    }


# ---------------------------------------------------------------------------
# HTTP helpers (network-dependent; monkey-patchable for tests)
# ---------------------------------------------------------------------------


def _fetch_html(url: str, data: dict[str, str] | None = None) -> str:
    """GET or POST a URL and return the response body as a string."""
    headers: dict[str, str] = {"User-Agent": USER_AGENT}
    encoded = urllib.parse.urlencode(data).encode() if data is not None else None
    if encoded is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=encoded, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", "ignore")


def _extract_inputs(html: str) -> dict[str, str]:
    """Extract all <input> field name/value pairs from an HTML page."""
    inputs: dict[str, str] = {}
    for m in INPUT_PATTERN.finditer(html):
        inputs[m.group("name")] = unescape(m.group("value") or "")
    return inputs


def _build_export_form(
    initial_html: str,
    floor_date: date,
    ceiling_date: date,
) -> dict[str, str]:
    """Build the ASP.NET form-post payload for the Form 700 export.

    Starts from all hidden/state inputs on the portal page, then overrides
    with the Form 700 search parameters.
    """
    inputs = _extract_inputs(initial_html)
    # Keep ASP.NET state fields and any known search/grid fields
    form: dict[str, str] = {
        key: value
        for key, value in inputs.items()
        if key.startswith("__")
        or "ClientState" in key
        or "calendar_" in key
        or "DropDown" in key
        or "searchSD" in key
        or "searchED" in key
        or "tbFilerName" in key
        or "searchJob" in key
        or "SEIDocumentListGrid" in key
        or "listExcelFormat" in key
    }
    form.update(
        {
            "ctl00$phBody$filingSearch$tbFilerName": "",
            "ctl00$phBody$filingSearch$searchJob": "",
            "ctl00$phBody$filingSearch$StatementTypeDropDown": "All",
            "ctl00$phBody$filingSearch$StatementTypeDropDown_Input": "All",
            "ctl00$phBody$filingSearch$FilerTypeDropDown": "700",
            "ctl00$phBody$filingSearch$FilerTypeDropDown_Input": "700 Filers Only",
            "ctl00$phBody$filingSearch$searchSD": floor_date.isoformat(),
            "ctl00$phBody$filingSearch$searchSD$dateInput": (
                f"{floor_date.month}/{floor_date.day}/{floor_date.year}"
            ),
            "ctl00$phBody$filingSearch$searchED": ceiling_date.isoformat(),
            "ctl00$phBody$filingSearch$searchED$dateInput": (
                f"{ceiling_date.month}/{ceiling_date.day}/{ceiling_date.year}"
            ),
            "ctl00$phBody$filingSearch$listExcelFormat": "2007",
            "ctl00$phBody$filingSearch$btnExportExcel2": "Export",
        }
    )
    return form


# ---------------------------------------------------------------------------
# Per-agency fetch pipeline
# ---------------------------------------------------------------------------


def fetch_filings_for_agency(
    agency_id: str,
    floor_date: date | None = None,
    *,
    fetch_html: Any = None,  # injectable for tests
) -> list[dict[str, Any]]:
    """Fetch all Form 700 filing rows for a single agency portal.

    Args:
        agency_id:  Lower-cased AID key in KNOWN_AGENCIES.
        floor_date: Earliest date to include (defaults to DEFAULT_FLOOR_DATE).
        fetch_html: Override HTTP fetcher (for tests).

    Returns:
        List of parsed row dicts.
    """
    aid = agency_id.lower()
    if aid not in KNOWN_AGENCIES:
        raise ValueError(
            f"Unknown agency '{agency_id}'. Known: {sorted(KNOWN_AGENCIES)}"
        )
    info = KNOWN_AGENCIES[aid]
    url = info["url"]
    _floor = floor_date or DEFAULT_FLOOR_DATE
    _ceiling = datetime.now().date()
    _do_fetch = fetch_html or _fetch_html

    print(f"  GET {url}")
    portal_html = _do_fetch(url)

    form = _build_export_form(portal_html, _floor, _ceiling)
    print(f"  POST {url} (Form 700 export, floor={_floor})")
    export_html = _do_fetch(url, form)

    rows = parse_filing_rows(export_html)
    # Filter by floor_date in case the portal ignores date params
    rows = [r for r in rows if r["filed_at"] >= _floor.isoformat()]
    print(f"  {len(rows)} filings found for {aid}")
    return rows


# ---------------------------------------------------------------------------
# Node + edge builders for a full agency batch
# ---------------------------------------------------------------------------


def build_nodes_and_edges(
    rows: list[dict[str, Any]],
    agency_id: str,
    *,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert parsed rows into Filing + Person nodes and edges.

    Deduplicates Filing IDs within this batch (appends -rowN on collision).
    Produces one Person node per unique normalized name.

    Returns (nodes, edges).
    """
    aid = agency_id.lower()
    info = KNOWN_AGENCIES.get(aid, {})
    agency_label = info.get("label", "")
    place_id = info.get("place_id", "")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_filing_ids: dict[str, int] = {}
    seen_person_ids: set[str] = set()

    batch = rows[:limit] if limit is not None else rows

    for row in batch:
        filing_node = build_filing_node(
            row, agency_id=aid, agency_label=agency_label or None
        )
        fid = filing_node["id"]

        # Deduplicate filing IDs
        if fid in seen_filing_ids:
            seen_filing_ids[fid] += 1
            fid = f"{fid}-row-{seen_filing_ids[fid]}"
            filing_node["id"] = fid
        else:
            seen_filing_ids[fid] = 1

        nodes.append(filing_node)

        # Person node (one per unique name)
        pid = person_id_from_name(row["filer_name"])
        if pid not in seen_person_ids:
            seen_person_ids.add(pid)
            person_node = {
                "id": pid,
                "node_type": "Person",
                "labels": ["Person"],
                "display_label": normalize_name(row["filer_name"]),
                "properties": {
                    "name": normalize_name(row["filer_name"]),
                    "source_filer_name": row["filer_name"],
                    "source": f"form700-{aid}",
                },
            }
            nodes.append(person_node)

        edges.append(build_filed_by_edge(fid, pid))

        if place_id:
            edges.append(build_in_jurisdiction_edge(fid, place_id))

    return nodes, edges


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
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

        print(f"Loading {len(nodes):,} nodes (batch_size={batch_size}) ...")
        node_counts = load_nodes(driver, nodes, batch_size=batch_size)
        total_nodes = sum(node_counts.values())
        print(f"  {total_nodes:,} nodes written.")
        for ntype, count in sorted(node_counts.items()):
            print(f"    {ntype:30s} {count:6,d}")

        print(f"Loading {len(edges):,} edges (batch_size={batch_size}) ...")
        edge_counts = load_edges(driver, edges, batch_size=batch_size)
        total_edges = sum(edge_counts.values())
        print(f"  {total_edges:,} edges written.")
        for rel, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
            print(f"    {rel:40s} {count:6,d}")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Form 700 filing index from NetFile /pub/ portals "
            "and ingest into the Marin Civic Graph."
        )
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--agency",
        metavar="AID",
        help=(
            "NetFile agency ID (e.g. cmar, raf, nvo). "
            f"Known: {', '.join(sorted(KNOWN_AGENCIES))}"
        ),
    )
    source.add_argument(
        "--all",
        action="store_true",
        help="Fetch from all known Marin-area portals.",
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
        help="Cap rows per agency (for testing).",
    )
    parser.add_argument(
        "--floor-date",
        default=DEFAULT_FLOOR_DATE.isoformat(),
        help=f"Earliest filing date to include (default: {DEFAULT_FLOOR_DATE})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Directory to write nodes.jsonl / edges.jsonl (default: {OUTPUT_DIR})",
    )
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    floor_date = date.fromisoformat(args.floor_date)

    agency_ids = (
        list(KNOWN_AGENCIES.keys()) if args.all else [args.agency.lower()]
    )

    all_nodes: list[dict] = []
    all_edges: list[dict] = []

    for aid in agency_ids:
        print(f"\nFetching {aid} ...")
        try:
            rows = fetch_filings_for_agency(aid, floor_date=floor_date)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue

        nodes, edges = build_nodes_and_edges(rows, aid, limit=args.limit)
        filing_count = sum(1 for n in nodes if n["node_type"] == "Filing")
        person_count = sum(1 for n in nodes if n["node_type"] == "Person")
        print(
            f"  {filing_count} Filing nodes, {person_count} Person nodes, "
            f"{len(edges)} edges"
        )
        all_nodes.extend(nodes)
        all_edges.extend(edges)

    output_dir = Path(args.output_dir)
    nodes_path = output_dir / "nodes.jsonl"
    edges_path = output_dir / "edges.jsonl"
    print(f"\nWriting nodes to: {nodes_path}")
    _write_jsonl(nodes_path, all_nodes)
    print(f"Writing edges to: {edges_path}")
    _write_jsonl(edges_path, all_edges)

    if args.load:
        if not args.password:
            print(
                "ERROR: NEO4J_PASSWORD is required (--password or NEO4J_PASSWORD env var).",
                file=sys.stderr,
            )
            sys.exit(1)
        _load_into_neo4j(
            nodes=all_nodes,
            edges=all_edges,
            uri=args.uri,
            user=args.user,
            password=args.password,
            database=args.database,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
