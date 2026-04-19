#!/usr/bin/env python3
"""
Apply the Open Marin search index definitions against AuraDB.
Idempotent: uses `CREATE ... IF NOT EXISTS`. Safe to re-run.

Reads Neo4j credentials from environment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = REPO_ROOT / "registry" / "neo4j-schema.cypher"

# Statements we want to run. We apply the whole file — CREATE IF NOT EXISTS is idempotent.
def read_statements() -> list[str]:
    raw = SCHEMA_FILE.read_text()
    # Strip comment-only lines, then split on semicolons.
    cleaned = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("//"))
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    statements = read_statements()
    print(f"Applying {len(statements)} schema statements to {uri}")

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            for stmt in statements:
                first_line = stmt.splitlines()[0][:80]
                try:
                    session.run(stmt)
                    print(f"  ok  {first_line}")
                except Exception as exc:  # noqa: BLE001 — we want to surface anything
                    print(f"  ERR {first_line}: {exc}", file=sys.stderr)
                    return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
