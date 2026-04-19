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


def build_search_key_fact(type_name: str, props: dict) -> str | None:
    """Short type-specific headline for search results. Returns None if props lack key fields."""
    if type_name == "Person":
        seat = props.get("current_seat_display")
        start = props.get("current_seat_start")
        if seat and start:
            return f"{seat} · {start}–"
        if seat:
            return str(seat)
        return None
    if type_name == "Decision":
        title = props.get("title") or props.get("name")
        date = props.get("decided_at")
        if title and date:
            return f"{title} · {date}"
        return str(title) if title else None
    if type_name == "Project" or type_name == "Program":
        name = props.get("name")
        status = props.get("status")
        parts = [p for p in (name, status) if p]
        return " · ".join(parts) if parts else None
    if type_name == "Case":
        caption = props.get("caption") or props.get("name")
        filed = props.get("filed_at")
        parts = [p for p in (caption, filed) if p]
        return " · ".join(parts) if parts else None
    if type_name == "Meeting":
        title = props.get("title")
        date = props.get("meeting_date")
        inst = props.get("institution_name")
        parts = [p for p in (title, date, inst) if p]
        return " · ".join(parts) if parts else None
    if type_name == "Filing":
        ft = (props.get("filing_type") or "").replace("_", " ").title()
        filer = props.get("filed_by_name")
        date = props.get("signed_at")
        parts = [p for p in (ft, filer, date) if p]
        return " · ".join(parts) if parts else None
    if type_name == "Committee":
        name = props.get("name")
        fppc = props.get("fppc_id")
        parts = [p for p in (name, f"FPPC {fppc}" if fppc else None) if p]
        return " · ".join(parts) if parts else None
    if type_name == "Organization":
        name = props.get("name")
        subtype = props.get("subtype")
        parts = [p for p in (name, subtype) if p]
        return " · ".join(parts) if parts else None
    if type_name == "Election":
        kind = props.get("election_type", "Election")
        date = props.get("election_date")
        return f"{kind} · {date}" if date else str(kind)
    if type_name == "Record":
        rt = (props.get("record_type") or "Record").replace("_", " ").title()
        parent_title = props.get("parent_title")
        parent_date = props.get("parent_date")
        parts = [p for p in (rt, parent_title, parent_date) if p]
        return " · ".join(parts) if parts else None
    return props.get("name") or None


def build_search_last_activity(type_name: str, props: dict) -> str | None:
    """Latest ISO date from linked events. props['_linked_event_dates'] is a list of ISO strings."""
    dates = props.get("_linked_event_dates") or []
    dates = [d for d in dates if d]
    if not dates:
        # Fall back to own date fields
        for k in (
            "decided_at", "meeting_date", "flow_date", "signed_at", "election_date",
            "date", "effective_date", "filed_at", "captured_at", "published_at",
        ):
            v = props.get(k)
            if v:
                return str(v)
        return None
    return max(dates)


def compute_search_rank(type_name: str, props: dict) -> int:
    # Entities: 50 base + up to 20 from degree (log-scaled) + up to 25 recency + type_weight.
    # Records: capped at 30.
    import datetime as dt
    import math

    degree = int(props.get("degree", 0) or 0)
    degree_component = min(25, int(20 * math.log1p(degree) / math.log(1000))) if degree > 0 else 0

    last_activity = props.get("_last_activity") or props.get("search_last_activity")
    recency_component = 0
    if last_activity:
        try:
            la_str = str(last_activity).replace("Z", "+00:00")
            # Handle bare YYYY-MM-DD by appending midnight UTC.
            if "T" not in la_str and len(la_str) <= 10:
                la = dt.datetime.fromisoformat(la_str + "T00:00:00+00:00")
            else:
                la = dt.datetime.fromisoformat(la_str)
            if la.tzinfo is None:
                la = la.replace(tzinfo=dt.timezone.utc)
            days_ago = (dt.datetime.now(dt.timezone.utc) - la).days
            if days_ago < 0:
                recency_component = 25
            else:
                recency_component = max(0, 25 - int(25 * days_ago / 1095))
        except (ValueError, TypeError):
            pass

    base = 50 + degree_component + recency_component + TYPE_WEIGHT.get(type_name, 0)
    if type_name == "Record":
        return max(0, min(30, degree_component + 10))
    return max(0, min(100, base))


# --------- Cypher runner ----------

def update_type(session: Session, type_name: str) -> int:
    query = f"""
    MATCH (n:{type_name})
    OPTIONAL MATCH (n)-[r]-()
    WITH n, count(r) AS degree
    OPTIONAL MATCH (n)-[]-(e)
    WHERE e:Meeting OR e:Decision OR e:MoneyFlow OR e:Filing OR e:Election
       OR e:Proceeding OR e:Agreement OR e:Amendment OR e:Case
    WITH n, degree, collect(DISTINCT coalesce(
      e.meeting_date, e.decided_at, e.flow_date, e.signed_at,
      e.election_date, e.date, e.effective_date, e.filed_at
    )) AS raw_dates
    RETURN n, degree, [d IN raw_dates WHERE d IS NOT NULL] AS linked_dates
    """
    records = session.run(query)
    updated = 0
    batch: list[dict] = []
    for record in records:
        node = record["n"]
        props = dict(node.items())
        props["degree"] = record["degree"]
        linked = list(record["linked_dates"] or [])
        props["_linked_event_dates"] = linked
        last_activity = build_search_last_activity(type_name, props)
        props["_last_activity"] = last_activity
        batch.append({
            "id": props["id"],
            "search_label": build_search_label(type_name, props),
            "search_terms": build_search_terms(type_name, props),
            "search_rank": compute_search_rank(type_name, props),
            "search_key_fact": build_search_key_fact(type_name, props),
            "search_last_activity": last_activity,
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
            n.search_rank = row.search_rank,
            n.search_key_fact = row.search_key_fact,
            n.search_last_activity = row.search_last_activity
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
