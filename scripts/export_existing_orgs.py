"""export_existing_orgs.py — read-only export of live Organization nodes.

Produces the `--existing-orgs` JSON every ingestor's resolver consumes: a sorted
array of ``{id, display_label, ein?, uei?}`` for each Organization in the live
graph. The resolver matches new-source recipients against this export and queues
cross-namespace merge candidates for review — it NEVER auto-merges on name.

READ-ONLY. This module only ever runs ``MATCH ... RETURN`` — it never writes,
MERGEs, or deletes. Credentials come from the environment (NEO4J_URI / NEO4J_USER
/ NEO4J_PASSWORD / NEO4J_DATABASE), falling back to app/.env.local so it works
out of the box locally.

Usage:
    python scripts/export_existing_orgs.py --out data/exports/existing-orgs.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

ORGS_QUERY = (
    "MATCH (n:Organization) "
    "RETURN n.id AS id, "
    "coalesce(n.display_label, n.name) AS display_label, "
    "n.ein AS ein, n.uei AS uei "
    "ORDER BY n.id"
)


def _load_env_local(path: Path) -> None:
    """Populate NEO4J_* from app/.env.local for any key not already in os.environ."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        m = re.match(r'\s*([A-Z0-9_]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)


def org_ref_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """One resolver ref. Identity keys are OMITTED when null (never None-filled)."""
    ref: dict[str, Any] = {"id": record["id"]}
    if record.get("display_label"):
        ref["display_label"] = record["display_label"]
    for key in ("ein", "uei"):
        if record.get(key):
            ref[key] = record[key]
    return ref


def export_orgs(out_path: Path) -> int:
    from neo4j import GraphDatabase  # lazy: no DB dependency at import time

    _load_env_local(Path(__file__).resolve().parent.parent / "app" / ".env.local")
    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session(database=database) as session:
            refs = [org_ref_from_record(dict(r)) for r in session.run(ORGS_QUERY)]
    finally:
        driver.close()

    refs.sort(key=lambda r: r["id"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(refs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(refs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only export of live Organization nodes.")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    n = export_orgs(args.out)
    print(f"exported {n} Organization refs → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
