#!/usr/bin/env python3
"""
Compute and write search_label, search_terms, search_rank on every searchable node.
Runs post-ingestion against AuraDB. Idempotent — MERGE-style updates.

Per spec §3.3.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase, Session

INDEXED_TYPES = [
    "Person", "Organization", "Committee", "Decision", "Project", "Program",
    "Case", "Meeting", "Filing", "Agreement", "Amendment", "Election",
    "Place", "Issue",
]
ALL_SEARCHABLE_TYPES = INDEXED_TYPES + ["Record"]

# Type-weight table — additive prominence per type. Entities only; Record excluded.
TYPE_WEIGHT: dict[str, int] = {
    "Person": 20,
    "Organization": 18,
    "Decision": 16,
    "Project": 14,
    "Program": 14,
    "Case": 14,
    "Meeting": 10,
    "Filing": 10,
    "Committee": 10,
    "Agreement": 8,
    "Amendment": 6,
    "Election": 6,
    "Place": 4,
    "Issue": 4,
    "Record": 0,  # capped below 30 regardless
}


def build_search_label(type_name: str, props: dict) -> str:
    if type_name == "Person":
        return str(props.get("name") or props["id"])
    if type_name == "Organization":
        return str(props.get("name") or props["id"])
    if type_name == "Committee":
        return str(props.get("name") or props["id"])
    if type_name == "Decision":
        date = props.get("decided_at") or ""
        title = props.get("title") or props["id"]
        return f"{title} · {date}" if date else str(title)
    if type_name == "Project" or type_name == "Program":
        return str(props.get("name") or props["id"])
    if type_name == "Case":
        caption = props.get("caption") or props.get("name") or props["id"]
        return str(caption)
    if type_name == "Meeting":
        title = props.get("title") or "Meeting"
        date = props.get("meeting_date") or ""
        return f"{title} — {date}" if date else str(title)
    if type_name == "Filing":
        filing_type = props.get("filing_type", "Filing")
        filer = props.get("filed_by_name") or ""
        date = props.get("signed_at") or ""
        pretty_type = filing_type.replace("_", " ").title().replace("Form ", "Form ")
        parts = [pretty_type]
        if filer:
            parts.append(filer)
        if date:
            parts.append(date)
        return " · ".join(parts)
    if type_name == "Agreement":
        return str(props.get("name") or props["id"])
    if type_name == "Amendment":
        return str(props.get("name") or props["id"])
    if type_name == "Election":
        date = props.get("election_date") or ""
        kind = props.get("election_type") or "Election"
        return f"{kind} — {date}" if date else str(kind)
    if type_name == "Place":
        return str(props.get("name") or props["id"])
    if type_name == "Issue":
        return str(props.get("name") or props["id"])
    if type_name == "Record":
        record_type = props.get("record_type", "Record")
        parent_date = props.get("parent_date") or ""
        parent_title = props.get("parent_title") or ""
        parts = [record_type.replace("_", " ").title()]
        if parent_title:
            parts.append(parent_title)
        if parent_date:
            parts.append(parent_date)
        return " · ".join(parts)
    return str(props["id"])


def build_search_terms(type_name: str, props: dict) -> str:
    tokens: list[str] = [str(props["id"])]
    name = props.get("name")
    if name:
        tokens.append(str(name))
    for alias in props.get("aliases", []) or []:
        tokens.append(str(alias))
    # Type-specific extra tokens.
    if type_name == "Meeting":
        if props.get("title"):
            tokens.append(str(props["title"]))
        if props.get("meeting_date"):
            tokens.append(str(props["meeting_date"]))
        if props.get("institution_name"):
            tokens.append(str(props["institution_name"]))
    if type_name == "Decision":
        if props.get("title"):
            tokens.append(str(props["title"]))
        if props.get("decided_at"):
            tokens.append(str(props["decided_at"]))
    if type_name == "Filing":
        if props.get("filing_type"):
            tokens.append(str(props["filing_type"]))
        if props.get("filed_by_name"):
            tokens.append(str(props["filed_by_name"]))
    if type_name == "Record":
        if props.get("record_type"):
            tokens.append(str(props["record_type"]))
        if props.get("parent_title"):
            tokens.append(str(props["parent_title"]))
        if props.get("source_url"):
            # Add host only — tokenization would split paths.
            from urllib.parse import urlparse
            parsed = urlparse(str(props["source_url"]))
            if parsed.hostname:
                tokens.append(parsed.hostname)
    return " ".join(tok.lower() for tok in tokens if tok)


def compute_search_rank(type_name: str, props: dict) -> int:
    # Entities: 50 base + up to 30 from degree (log-scaled) + type_weight.
    # Records: capped at 30.
    degree = int(props.get("degree", 0) or 0)
    import math
    degree_component = min(30, int(25 * math.log1p(degree) / math.log(1000))) if degree > 0 else 0
    base = 50 + degree_component + TYPE_WEIGHT.get(type_name, 0)
    if type_name == "Record":
        return max(0, min(30, degree_component + 10))
    return max(0, min(100, base))


# --------- Cypher runner ----------

def update_type(session: Session, type_name: str) -> int:
    query = f"""
    MATCH (n:{type_name})
    OPTIONAL MATCH (n)-[r]-()
    WITH n, count(r) AS degree
    RETURN n, degree
    """
    records = session.run(query)
    updated = 0
    batch: list[dict] = []
    for record in records:
        node = record["n"]
        props = dict(node.items())
        props["degree"] = record["degree"]
        batch.append({
            "id": props["id"],
            "search_label": build_search_label(type_name, props),
            "search_terms": build_search_terms(type_name, props),
            "search_rank": compute_search_rank(type_name, props),
        })
        if len(batch) >= 500:
            _write_batch(session, type_name, batch)
            updated += len(batch)
            batch = []
    if batch:
        _write_batch(session, type_name, batch)
        updated += len(batch)
    return updated


def _write_batch(session: Session, type_name: str, rows: list[dict]) -> None:
    session.run(
        f"""
        UNWIND $rows AS row
        MATCH (n:{type_name} {{id: row.id}})
        SET n.search_label = row.search_label,
            n.search_terms = row.search_terms,
            n.search_rank = row.search_rank
        """,
        rows=rows,
    )


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    total = 0
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            for type_name in ALL_SEARCHABLE_TYPES:
                count = update_type(session, type_name)
                print(f"  {type_name}: {count} nodes updated")
                total += count
    print(f"Total updated: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
