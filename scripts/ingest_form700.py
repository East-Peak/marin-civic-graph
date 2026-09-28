#!/usr/bin/env python3
"""ingest_form700.py — NetFile Form 700 index ingestion for Marin Civic Graph.

Pages the Form 700 (Statement of Economic Interests) filing index for a NetFile
agency out of NetFile's public JSON API and produces Filing nodes with FILED_BY
edges to Person nodes and IN_JURISDICTION edges to Place nodes.

NetFile replatformed its public portal into a Vue SPA (~2026): the old
``public.netfile.com/pub/?aid=…`` ASP.NET pages now 301 to
``netfile.com/public/<AID>/sei`` and a scrape of them parses zero rows. The SPA
reads ``POST https://netfile.com/api/public/sites/api/searchfilings`` (JSON, no
captcha), which is what this module calls. The WAF answers 403 to urllib's
default User-Agent, so requests carry a curl-style one.

A run never makes data worse: if any agency's pull fails, comes back empty, or
returns fewer items than the API's own ``totalCount``, nothing is written or
loaded and the process exits non-zero, leaving the previous output in place.

Usage:
  # Fetch from Marin County (broadest — 80+ agencies)
  python scripts/ingest_form700.py --agency cmar --load

  # Fetch from San Rafael
  python scripts/ingest_form700.py --agency raf --load

  # All known agencies
  python scripts/ingest_form700.py --all --load

  # Limit for testing
  python scripts/ingest_form700.py --agency cmar --limit 50

  # Load previously staged output without fetching (weekly runner, I5b)
  python scripts/ingest_form700.py --load-from data/ingest-runs/<run>/staged/form700
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_from import add_load_from_argument, load_staged, reject_fetch_flags  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data" / "normalized" / "form700"
API_URL = "https://netfile.com/api/public/sites/api/searchfilings"
USER_AGENT = "curl/8.7.1"  # the WAF 403s urllib's default UA
PAGE_SIZE = 100
MAX_PAGES = 1_000  # runaway guard: cmar, the largest agency, is ~70 pages
DEFAULT_FLOOR_DATE = date(2019, 1, 1)

# All known Marin-area NetFile agencies; key = AID (case-insensitive)
KNOWN_AGENCIES: dict[str, dict[str, str]] = {
    "cmar": {
        "label": "Marin County",
        "place_id": "place-marin-county",
        "url": "https://netfile.com/public/CMAR/sei",
    },
    "raf": {
        "label": "City of San Rafael",
        "place_id": "place-san-rafael",
        "url": "https://netfile.com/public/RAF/sei",
    },
    "nvo": {
        "label": "City of Novato",
        "place_id": "place-novato",
        "url": "https://netfile.com/public/NVO/sei",
    },
    "sau": {
        "label": "City of Sausalito",
        "place_id": "place-sausalito",
        "url": "https://netfile.com/public/SAU/sei",
    },
    "tib": {
        "label": "Town of Tiburon",
        "place_id": "place-tiburon",
        "url": "https://netfile.com/public/TIB/sei",
    },
    "ctm": {
        "label": "Town of Corte Madera",
        "place_id": "place-corte-madera",
        "url": "https://netfile.com/public/CTM/sei",
    },
    "lark": {
        "label": "City of Larkspur",
        "place_id": "place-larkspur",
        "url": "https://netfile.com/public/LARK/sei",
    },
    "smo": {
        "label": "Town of San Anselmo",
        "place_id": "place-san-anselmo",
        "url": "https://netfile.com/public/SMO/sei",
    },
    "ross": {
        "label": "Town of Ross",
        "place_id": "place-ross",
        "url": "https://netfile.com/public/ROSS/sei",
    },
}

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

    'Colin, Kate' and 'Kate Colin' both produce 'person-f700-kate-colin'.
    Namespaced with 'f700' to prevent collision with other pipelines.
    """
    normalized = normalize_name(raw_name)
    return f"person-f700-{slugify(normalized)}"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_filings_page(payload: Any) -> list[dict[str, Any]]:
    """Map one ``searchfilings`` response page to row dicts.

    Rows have the shape build_filing_node() consumes — filer_name, filed_at
    (ISO YYYY-MM-DD), statement_type, job_title, department — the same shape
    the retired HTML export parser produced, so Filing ids are unchanged.
    ``filingDate`` is agency-local with no zone, so its date part is taken
    as printed. A payload without an ``items`` list raises ValueError.
    """
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("searchfilings response has no 'items' list")
    return [
        {
            "filer_name": _text(item.get("filerName")),
            "filed_at": _text(item.get("filingDate"))[:10],
            "statement_type": _text(item.get("statementType")),
            "job_title": _text(item.get("positionName")),
            "department": _text(item.get("departmentName")),
        }
        for item in items
    ]


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
# NetFile JSON API (network-dependent; injectable for tests)
# ---------------------------------------------------------------------------

PostJson = Callable[[str, dict[str, Any]], Any]


def _post_json(url: str, body: dict[str, Any]) -> Any:
    """POST a JSON body and return the decoded JSON response."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_search_body(
    agency_id: str, floor_date: date, ceiling_date: date, *, page: int, page_size: int
) -> dict[str, Any]:
    """The searchfilings request body: every statement type, one date window, one page."""
    return {
        "aid": agency_id.upper(),
        "searchFilerName": "",
        "searchStatementType": None,
        "afterFilingDate": floor_date.isoformat(),
        "beforeFilingDate": ceiling_date.isoformat(),
        "currentPage": page,
        "pageSize": page_size,
    }


def fetch_filings_for_agency(
    agency_id: str,
    floor_date: date | None = None,
    *,
    post_json: PostJson | None = None,
    page_size: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Fetch every Form 700 index row for one agency, following all pages.

    Pages are 1-based and followed until ``hasNextPage`` is false. The pull is
    rejected (RuntimeError) if a page is empty while more are promised, the
    page count runs away, or the items collected fall short of ``totalCount`` —
    a partial index must never pass for a complete one.
    """
    aid = agency_id.lower()
    if aid not in KNOWN_AGENCIES:
        raise ValueError(
            f"Unknown agency '{agency_id}'. Known: {sorted(KNOWN_AGENCIES)}"
        )
    _floor = floor_date or DEFAULT_FLOOR_DATE
    _ceiling = datetime.now().date()
    _post = post_json or _post_json

    print(f"  POST {API_URL} (aid={aid.upper()}, floor={_floor})")
    rows: list[dict[str, Any]] = []
    total_count: Any = None
    for page in range(1, MAX_PAGES + 1):
        body = build_search_body(aid, _floor, _ceiling, page=page, page_size=page_size)
        payload = _post(API_URL, body)
        page_rows = parse_filings_page(payload)
        rows.extend(page_rows)
        if total_count is None:
            total_count = payload.get("totalCount")
        if not payload.get("hasNextPage"):
            break
        if not page_rows:
            raise RuntimeError(f"{aid}: page {page} is empty but hasNextPage is set")
    else:
        raise RuntimeError(f"{aid}: still paging after {MAX_PAGES} pages")

    if isinstance(total_count, int) and len(rows) != total_count:
        raise RuntimeError(
            f"{aid}: collected {len(rows)} filings but the API reports totalCount={total_count}"
        )

    # Filter by floor_date in case the API ignores the date window
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
    """Write JSONL atomically: a crash mid-write never truncates the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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
        from neo4j_target import open_driver
    except ImportError:
        print(
            "ERROR: neo4j Python driver not installed. Run: pip install neo4j",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Connecting to Neo4j: {uri} (database={database})")
    driver = open_driver(uri, auth=(user, password))
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the Form 700 filing index from the NetFile public API "
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
        help="Fetch from all known Marin-area agencies.",
    )
    add_load_from_argument(source)

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
        default=None,
        help=f"Earliest filing date to include (default: {DEFAULT_FLOOR_DATE})",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Directory to write nodes.jsonl / edges.jsonl (default: {OUTPUT_DIR})",
    )
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)
    reject_fetch_flags(parser, args, ("--load", "--limit", "--floor-date", "--output-dir"))
    return args


def main(argv: list[str] | None = None) -> int:
    """Fetch → build → write → (optionally) load. Returns the process exit code.

    Every agency must come back complete and non-empty before anything is
    written; otherwise the previous output stays byte-identical, nothing is
    loaded, and the exit code is 1.
    """
    args = _parse_args(argv)
    if args.load_from is not None:
        return load_staged(args, _load_into_neo4j)
    floor_date = date.fromisoformat(args.floor_date) if args.floor_date else DEFAULT_FLOOR_DATE
    if args.load and not args.password:
        print(
            "ERROR: NEO4J_PASSWORD is required (--password or NEO4J_PASSWORD env var).",
            file=sys.stderr,
        )
        return 1

    agency_ids = (
        list(KNOWN_AGENCIES.keys()) if args.all else [args.agency.lower()]
    )

    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    failed: list[str] = []

    for aid in agency_ids:
        print(f"\nFetching {aid} ...")
        try:
            rows = fetch_filings_for_agency(aid, floor_date=floor_date)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}", file=sys.stderr)
            failed.append(aid)
            continue
        if not rows:
            print(f"  ERROR: {aid} returned zero filings", file=sys.stderr)
            failed.append(aid)
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

    if failed:
        print(
            f"\nABORTED: failed or empty pull for {', '.join(failed)}. "
            "Nothing written or loaded; previous output left untouched.",
            file=sys.stderr,
        )
        return 1

    output_dir = Path(args.output_dir or OUTPUT_DIR)
    nodes_path = output_dir / "nodes.jsonl"
    edges_path = output_dir / "edges.jsonl"
    print(f"\nWriting nodes to: {nodes_path}")
    _write_jsonl(nodes_path, all_nodes)
    print(f"Writing edges to: {edges_path}")
    _write_jsonl(edges_path, all_edges)

    if args.load:
        _load_into_neo4j(
            nodes=all_nodes,
            edges=all_edges,
            uri=args.uri,
            user=args.user,
            password=args.password,
            database=args.database,
            batch_size=args.batch_size,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
