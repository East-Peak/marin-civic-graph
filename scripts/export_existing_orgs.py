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
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from identity_ledger import PUBLISHING_STATUSES  # noqa: E402
from org_resolution import KEY_NORMALIZERS  # noqa: E402

ORGS_QUERY = (
    "MATCH (n:Organization) "
    "RETURN n.id AS id, "
    "coalesce(n.display_label, n.name) AS display_label, "
    "n.ein AS ein, n.uei AS uei "
    "ORDER BY n.id"
)

# ---------------------------------------------------------------------------
# Lane-1 enrichment (Identity Enrichment, Unit 3) — read-only, ledger-validated
# ---------------------------------------------------------------------------

# Bases on a SAME_AS that legitimately carry a hard key (self-identity merges
# and operator key-approvals). A relationship basis (sponsor/parent/PAC/dba/
# project, or the resolver's `relationship_candidate`) carries NO key.
_KEY_BEARING_BASES = frozenset(
    {"ein_exact", "uei_exact", "operator_approved_ein", "operator_approved_uei"}
)

# An OWN `n.ein`/`n.uei` is trusted as a deterministic key only when the node's
# provenance is recognized via fields that already exist (Codex r2 — there is no
# invented `key_source`): a known `n.source`, or a registry key-prefixed id.
_TRUSTED_SOURCES = frozenset({"irs-990", "marin_county_open_data", "usaspending"})
_TRUSTED_ID_PREFIXES = ("org-990-ein-", "org-bmf-ein-", "org-usasp-uei-")

# The live enrichment query (operator-gated; tested against a fake session, never
# run by the loop). Per Organization: its own keys/source/subtype, edge-degree,
# and every assertion-stamped SAME_AS to a key-bearing node (with the edge's real
# endpoints, so the orientation rule can reject a stale/copied id).
ENRICHED_ORGS_QUERY = (
    "MATCH (n:Organization) "
    "OPTIONAL MATCH (n)-[r:SAME_AS]-(m) "
    "  WHERE r.assertion_id IS NOT NULL AND (m.ein IS NOT NULL OR m.uei IS NOT NULL) "
    "WITH n, collect(CASE WHEN m IS NULL THEN NULL ELSE { "
    "  linked_node_id: m.id, "
    "  edge_source_id: startNode(r).id, "
    "  edge_target_id: endNode(r).id, "
    "  assertion_id: r.assertion_id, "
    "  ein: m.ein, uei: m.uei, "
    "  irs_subsection_class: m.irs_subsection_class "
    "} END) AS raw_links "
    "RETURN n.id AS id, "
    "  coalesce(n.display_label, n.name) AS display_label, "
    "  n.ein AS own_ein, n.uei AS own_uei, n.source AS own_source, "
    "  n.irs_subsection_class AS own_irs_subsection_class, "
    "  COUNT { (n)--() } AS degree, "
    "  [l IN raw_links WHERE l IS NOT NULL] AS key_links "
    "ORDER BY n.id"
)


def _own_key_trusted(record: dict[str, Any]) -> bool:
    """True iff the node's OWN key may be a deterministic merge key — recognized
    `n.source` OR a registry key-prefixed id. No invented `key_source` field."""
    if record.get("own_source") in _TRUSTED_SOURCES:
        return True
    rid = str(record.get("id") or "")
    return any(rid.startswith(p) for p in _TRUSTED_ID_PREFIXES)


def _link_orientation(
    link: dict[str, Any], assertions_by_id: dict[str, dict[str, Any]]
) -> str | None:
    """`"direct"` / `"inverse"` if the link's backing assertion is valid in the
    CURRENT ledger, else None.

    Valid IFF the assertion resolves and is `deterministic|approved`,
    `superseded_by is None`, carries a key-bearing basis, AND its unordered
    `{subject_ref, target_ref}` equals the edge's `{source, target}` endpoints
    (A's ids are directional from subject|target|basis|snapshot — a copied id on
    a different pair must fail)."""
    assertion = assertions_by_id.get(link.get("assertion_id"))
    if assertion is None:
        return None
    if assertion.get("status") not in PUBLISHING_STATUSES:
        return None
    if assertion.get("superseded_by") is not None:
        return None
    if assertion.get("basis") not in _KEY_BEARING_BASES:
        return None
    subj, targ = assertion.get("subject_ref"), assertion.get("target_ref")
    src, tgt = link.get("edge_source_id"), link.get("edge_target_id")
    if {subj, targ} != {src, tgt}:
        return None
    return "direct" if (subj == src and targ == tgt) else "inverse"


def org_ref_from_enriched_record(
    record: dict[str, Any], assertions_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Pure transform: one enriched query record → an enriched org ref.

    Surfaces `ein`/`uei` ONLY when exactly one ledger-validated value exists
    (own trusted key + every key reached over a VALID approved/deterministic
    SAME_AS). A disagreement withholds the key and records `identity_key_conflict`.
    An own key on a node with unrecognized provenance is `review_keys`-only, never
    deterministic. `irs_subsection_class` + `degree` ride along."""
    ref: dict[str, Any] = {"id": record["id"]}
    if record.get("display_label"):
        ref["display_label"] = record["display_label"]
    if record.get("degree") is not None:
        ref["degree"] = record["degree"]

    own_trusted = _own_key_trusted(record)
    trusted: dict[str, dict[str, set[str]]] = {"ein": {}, "uei": {}}
    review_only: dict[str, str] = {}
    subtypes: dict[str, set[str]] = {}

    # Own keys — trusted only with recognized provenance, else review-only.
    for key in ("ein", "uei"):
        value = KEY_NORMALIZERS[key](record.get(f"own_{key}"))
        if value is None:
            continue
        if own_trusted:
            trusted[key].setdefault(value, set()).add("own")
        else:
            review_only[key] = value
    own_subtype = record.get("own_irs_subsection_class")
    if own_trusted and own_subtype:
        subtypes.setdefault(own_subtype, set()).add("own")

    # Linked keys — only over a ledger-VALID approved/deterministic SAME_AS.
    for link in record.get("key_links") or []:
        if _link_orientation(link, assertions_by_id) is None:
            continue
        aid = link.get("assertion_id")
        for key in ("ein", "uei"):
            value = KEY_NORMALIZERS[key](link.get(key))
            if value is not None:
                trusted[key].setdefault(value, set()).add(aid)
        subtype = link.get("irs_subsection_class")
        if subtype:
            subtypes.setdefault(subtype, set()).add(aid)

    conflicts: list[dict[str, Any]] = []
    for key in ("ein", "uei"):
        values = trusted[key]
        if len(values) == 1:
            ref[key] = next(iter(values))
        elif len(values) >= 2:
            conflicts.append({
                "key": key,
                "reason": "identity_key_conflict",
                "values": sorted(values),
                "assertion_ids": sorted(
                    {a for tags in values.values() for a in tags if a != "own"}
                ),
            })

    if len(subtypes) == 1:
        ref["irs_subsection_class"] = next(iter(subtypes))
    if review_only:
        ref["review_keys"] = review_only
    if conflicts:
        ref["identity_key_conflict"] = conflicts
    return ref


def enrich_existing_orgs(
    session: Any, assertions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Run the read-only enrichment query against an injected session and map each
    record through the ledger-validated transform. `session` is any object with a
    `.run(query)` returning record-like mappings — a real driver session in the
    operator path, a fake in tests. NEVER writes."""
    by_id = {a["id"]: a for a in assertions}
    refs = [org_ref_from_enriched_record(dict(r), by_id) for r in session.run(ENRICHED_ORGS_QUERY)]
    refs.sort(key=lambda r: r["id"])
    return refs


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
