#!/usr/bin/env python3
"""Write/update the :_SyncState {kind: 'ingest'} singleton with the current timestamp.
Run after each successful ingestion pass. /api/status reads this as the authoritative INGEST time."""
from __future__ import annotations

import datetime as dt
import os
import sys

from neo4j import GraphDatabase


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            session.run(
                "MERGE (s:_SyncState {kind: 'ingest'}) SET s.updated_at = $updated_at",
                updated_at=now,
            )
    print(f"Set :_SyncState{{kind:'ingest'}}.updated_at = {now}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
