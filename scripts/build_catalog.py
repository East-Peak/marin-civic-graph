#!/usr/bin/env python3
"""Bake per-type counts into data/projected/graph-v1/catalog.json.
Per spec §3.7 — catalog is a baked bundle, not a live query per request."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

ALL_TYPES = [
    "Person", "Organization", "Committee", "Seat", "SeatService", "Election",
    "Candidacy", "Meeting", "AgendaItem", "Decision", "Filing", "MoneyFlow",
    "Case", "Proceeding", "Project", "Program", "Agreement", "Amendment",
    "Record", "Place", "Issue",
]

OUT = Path(__file__).resolve().parent.parent / "data" / "projected" / "graph-v1" / "catalog.json"


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    counts: dict[str, int] = {}
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            for label in ALL_TYPES:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) AS c")
                counts[label] = result.single()["c"]
                print(f"  {label}: {counts[label]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "counts": counts}
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
