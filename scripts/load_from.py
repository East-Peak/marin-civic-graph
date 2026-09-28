"""`--load-from <dir>`: load previously staged output without refetching.

The weekly runner (docs/specs/2026-09-28-persistent-ingestion-design.md, I5b)
stages each refetching ingester's nodes.jsonl/edges.jsonl for human review.
Loading a fresh refetch after approval would load bytes nobody reviewed, so each
ingester can instead load exactly the staged files, through its usual loader.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STAGED_FILES = ("nodes.jsonl", "edges.jsonl")


def add_load_from_argument(parser: argparse.ArgumentParser | argparse._MutuallyExclusiveGroup) -> None:
    parser.add_argument(
        "--load-from",
        metavar="DIR",
        type=Path,
        help="Load DIR/nodes.jsonl and DIR/edges.jsonl into Neo4j without fetching.",
    )


def reject_fetch_flags(parser: argparse.ArgumentParser, args: argparse.Namespace, flags: tuple[str, ...]) -> None:
    """Exit 2 if ``--load-from`` is combined with any flag that only means something when fetching."""
    if args.load_from is None:
        return
    used = [flag for flag in flags if getattr(args, flag.lstrip("-").replace("-", "_")) not in (None, False)]
    if used:
        parser.error(f"--load-from never fetches; it cannot be combined with {', '.join(used)}")


def load_staged(args: argparse.Namespace, load_into_neo4j) -> int:
    """Load ``args.load_from`` with the ingester's own ``_load_into_neo4j``. Returns an exit code."""
    if not args.password:
        print("ERROR: NEO4J_PASSWORD is required (--password or NEO4J_PASSWORD env var).", file=sys.stderr)
        return 1
    try:
        nodes, edges = read_staged(args.load_from)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Loading staged output from {args.load_from} (no fetch): {len(nodes):,} nodes, {len(edges):,} edges")
    load_into_neo4j(nodes=nodes, edges=edges, uri=args.uri, user=args.user, password=args.password,
                    database=args.database, batch_size=args.batch_size)
    return 0


def read_staged(directory: Path) -> tuple[list[dict], list[dict]]:
    """Read staged (nodes, edges); raise FileNotFoundError if either file is missing."""
    missing = [name for name in STAGED_FILES if not (Path(directory) / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{directory}: missing staged {', '.join(missing)}")
    nodes, edges = ([json.loads(line) for line in (Path(directory) / name).read_text(encoding="utf-8").splitlines()
                     if line.strip()] for name in STAGED_FILES)
    return nodes, edges
