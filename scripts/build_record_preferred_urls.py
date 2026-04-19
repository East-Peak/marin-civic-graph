#!/usr/bin/env python3
"""
Compute Record.preferred_public_url, Record.preferred_display_artifact, Record.has_public_source.
Per spec §7.1 evidence drawer contract.
"""
from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase


def normalize_public_url(source_url: str | None) -> str | None:
    if not source_url:
        return None
    s = source_url.strip()
    if not s:
        return None
    if s.startswith(("http://", "https://")):
        return s
    if s.startswith("//"):
        return "https:" + s
    # Anything else (file://, relative path, etc.) is not publicly reachable.
    return None


def build_display_label(record_type: str | None, url: str | None) -> str:
    rt = (record_type or "record").replace("_", " ").strip()
    rt = rt[:1].upper() + rt[1:] if rt else "Record"
    if not url:
        return rt
    lower = url.lower()
    if lower.endswith(".pdf"):
        return f"{rt} PDF"
    if lower.endswith((".html", ".htm")) or (lower.startswith("http") and not lower.rsplit("/", 1)[-1].count(".")):
        return f"{rt} page"
    if lower.endswith(".txt"):
        return f"{rt} text"
    return rt


BATCH_SIZE = 500


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    total = 0
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            cursor = session.run(
                "MATCH (r:Record) RETURN r.id AS id, r.source_url AS source_url, r.record_type AS record_type"
            )
            batch: list[dict] = []
            for record in cursor:
                preferred = normalize_public_url(record["source_url"])
                label = build_display_label(record["record_type"], preferred)
                batch.append({
                    "id": record["id"],
                    "preferred_public_url": preferred,
                    "preferred_display_artifact": label,
                    "has_public_source": preferred is not None,
                })
                if len(batch) >= BATCH_SIZE:
                    session.run(
                        """
                        UNWIND $rows AS row
                        MATCH (r:Record {id: row.id})
                        SET r.preferred_public_url = row.preferred_public_url,
                            r.preferred_display_artifact = row.preferred_display_artifact,
                            r.has_public_source = row.has_public_source
                        """,
                        rows=batch,
                    )
                    total += len(batch)
                    batch = []
            if batch:
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (r:Record {id: row.id})
                    SET r.preferred_public_url = row.preferred_public_url,
                        r.preferred_display_artifact = row.preferred_display_artifact,
                        r.has_public_source = row.has_public_source
                    """,
                    rows=batch,
                )
                total += len(batch)
    print(f"Updated {total} Records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
