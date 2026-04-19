#!/usr/bin/env python3
"""
Compute Record.preferred_public_url, Record.preferred_display_artifact, Record.has_public_source.
Per spec §7.1 evidence drawer contract.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from neo4j import GraphDatabase


# Adapter source registries keyed by adapter name; their entries use the `id` field.
# sources.yaml is the broader per-jurisdiction registry and uses `source_id` + `entry_url`.
ADAPTER_REGISTRIES = (
    "granicus-sources.yaml",
    "civicplus-sources.yaml",
    "proudcity-sources.yaml",
    "drupal-sources.yaml",
    "netfile-sources.yaml",
)
BROAD_REGISTRY = "sources.yaml"


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


def _registry_entry_url(entry: dict[str, Any]) -> str | None:
    """Extract a public http(s) URL from a registry entry.

    Adapter YAMLs use the `url` key for the canonical entry point. The broader
    sources.yaml uses `entry_url`. Prefer `url` if present, then fall back.
    Non-http(s) values are rejected (ftp://, file://, etc.).
    """
    for key in ("url", "entry_url"):
        candidate = entry.get(key)
        if not candidate:
            continue
        normalized = normalize_public_url(candidate)
        if normalized is not None:
            return normalized
    return None


def normalize_public_url_with_registry(
    props: dict[str, Any], registry: dict[str, dict[str, Any]]
) -> str | None:
    """Resolve a Record's preferred_public_url per spec §7.1.

    Order of resolution:
      1. `source_url` if it starts with http(s) or is protocol-relative (//).
      2. Registry fallback: look up `source_id` in the merged registry and
         return the entry's canonical upstream URL (`url` or `entry_url`).
      3. Otherwise None.
    """
    direct = normalize_public_url(props.get("source_url"))
    if direct is not None:
        return direct

    source_id = props.get("source_id")
    if not source_id:
        return None

    entry = registry.get(source_id)
    if not entry:
        return None

    return _registry_entry_url(entry)


def load_registry(registry_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load and merge all jurisdiction-source registries into a single lookup map.

    Returns a dict keyed by the source's identifier (adapter YAMLs use `id`,
    sources.yaml uses `source_id`) to the full entry dict. Later adapter entries
    take precedence over earlier ones on collision; sources.yaml fills in anything
    not covered by an adapter YAML.
    """
    if registry_root is None:
        registry_root = Path(__file__).resolve().parent.parent / "registry"

    merged: dict[str, dict[str, Any]] = {}

    # Broad registry first (lowest precedence — adapter YAMLs are authoritative for their sources)
    broad_path = registry_root / BROAD_REGISTRY
    if broad_path.exists():
        with broad_path.open() as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("sources", []) or []:
            key = entry.get("source_id") or entry.get("id")
            if key:
                merged[key] = entry

    # Adapter registries overlay
    for filename in ADAPTER_REGISTRIES:
        path = registry_root / filename
        if not path.exists():
            continue
        with path.open() as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("sources", []) or []:
            key = entry.get("id") or entry.get("source_id")
            if key:
                merged[key] = entry

    return merged


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

    registry = load_registry()

    total = 0
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            cursor = session.run(
                """
                MATCH (r:Record)
                RETURN r.id AS id,
                       r.source_url AS source_url,
                       r.source_id AS source_id,
                       r.record_type AS record_type
                """
            )
            batch: list[dict] = []
            for record in cursor:
                props = {
                    "id": record["id"],
                    "source_url": record["source_url"],
                    "source_id": record["source_id"],
                    "record_type": record["record_type"],
                }
                preferred = normalize_public_url_with_registry(props, registry)
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
