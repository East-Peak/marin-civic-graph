"""build_county_vendor_orgs.py — Open Marin · County Attribution Completion, Phase A.

Attributes the ~$134.5M (95.2%) of Marin County delegated-contract money that is
unattributed today: the County ingestor draws `TO_TARGET` only to EXISTING
canonical orgs via approved name-resolution and creates NO recipient nodes, so an
unmatched vendor has nowhere to attribute. Phase A creates one canonical vendor
`Organization` node per UNAPPROVED recipient group (`build_recipient_groups`,
consumed) and draws `TO_TARGET` from each of the group's MoneyFlows to it.

Design (Codex-converged, see the goal doc):
  - id = `org-` + the deterministic `recipient_group_id` (`org-marincontract-recipient-<slug>`)
    so it round-trips the app's `org-` prefix routing; NO new id_prefix, NO registry edit.
  - Exclusion = the approved group_ids ONLY. An unapproved resolver exact-name match
    is a CANDIDATE, not an attributed state — it still gets a node (reconciled later
    by the shipped dedup), never silently dropped.
  - Node carries NAME + PROVENANCE only. Explicit person/address property denylist:
    the County CSV has no address columns, and the slash classifier's `person_side`
    must NEVER land on a vendor org. Person-named vendors are modeled as the
    businesses they are (public-money recipients), name only.
  - Pure build (envelope dir offline); the live load is OPERATOR-gated.

`ingest_marin_county_contracts.py` is CONSUMED, never edited.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ingest_marin_county_contracts import moneyflow_id  # consumed, never edited

# County Socrata dataset id (mirrors the ingestor's provenance stamp).
_DATASET_ID = "rp6f-b7dy"
_VENDOR_ORG_ID_PREFIX = "org-"  # org- + recipient_group_id == org-marincontract-recipient-<slug>


def vendor_org_id(recipient_group_id: str) -> str:
    """The canonical vendor org id for a recipient group — `org-` + the group id,
    so it resolves to an `Organization` through the existing `org-` prefix."""
    return _VENDOR_ORG_ID_PREFIX + recipient_group_id


def build_vendor_org_nodes(
    groups: dict[str, dict[str, Any]], *, approved_group_ids: set[str]
) -> list[dict[str, Any]]:
    """One canonical vendor `Organization` node per group whose group_id is NOT in
    `approved_group_ids` (the 43 already TO_TARGETed). Name + provenance only —
    no person/address field. Sorted by id (deterministic)."""
    nodes: list[dict[str, Any]] = []
    for gid, g in sorted(groups.items()):
        if gid in approved_group_ids:
            continue  # already attributed to an existing org — exclusion is approved-only
        nodes.append({
            "id": vendor_org_id(gid),
            "node_type": "Organization",
            "labels": ["Organization"],
            "display_label": g["display_label"],
            "properties": {
                "source": "marin_county_open_data",
                "dataset_id": _DATASET_ID,
                "county_recipient_group_id": gid,
                "recipient_kind_hints": list(g.get("recipient_kind_hints", [])),
                "department_raw": list(g.get("departments", [])),
                "not_full_checkbook": True,
            },
        })
    return nodes


def build_vendor_to_target_edges(
    groups: dict[str, dict[str, Any]], *, approved_group_ids: set[str]
) -> list[dict[str, Any]]:
    """One `MoneyFlow -[:TO_TARGET]-> <vendor org>` edge per MoneyFlow in each
    UNAPPROVED group (mirrors the ingestor's TO_TARGET shape: MoneyFlow source).
    Approved groups already have edges to existing orgs — none drawn here."""
    edges: list[dict[str, Any]] = []
    for gid, g in sorted(groups.items()):
        if gid in approved_group_ids:
            continue
        target = vendor_org_id(gid)
        for mid in g["moneyflow_ids"]:
            edges.append({
                "source_id": mid,
                "target_id": target,
                "relationship_type": "TO_TARGET",
                "properties": {
                    "basis": "county_vendor_attribution",
                    "county_recipient_group_id": gid,
                },
            })
    return edges


def summarize_attribution(
    rows: list[dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    *,
    approved_group_ids: set[str],
) -> dict[str, int]:
    """DUAL tie-out: EDGE coverage (one per MoneyFlow, incl. missing-amount $0
    edges) and DOLLAR coverage (sum of non-missing amounts), split new vs the
    approved 43. `total_dollars` ties to the County total."""
    mid_amount = {moneyflow_id(r["data_portal_id"]): r["amount"] for r in rows}
    new_vendor_orgs = new_edges = new_missing = approved_edges = 0
    new_dollars = Decimal(0)
    approved_dollars = Decimal(0)
    for gid, g in groups.items():
        is_approved = gid in approved_group_ids
        if not is_approved:
            new_vendor_orgs += 1
        for mid in g["moneyflow_ids"]:
            amt = mid_amount.get(mid)
            if is_approved:
                approved_edges += 1
                if amt is not None:
                    approved_dollars += amt
            else:
                new_edges += 1
                if amt is None:
                    new_missing += 1
                else:
                    new_dollars += amt
    return {
        "new_vendor_orgs": new_vendor_orgs,
        "new_edges": new_edges,
        "new_missing_amount_edges": new_missing,
        "new_dollars": int(new_dollars),
        "approved_edges": approved_edges,
        "approved_dollars": int(approved_dollars),
        "total_dollars": int(new_dollars + approved_dollars),
    }


# ---------------------------------------------------------------------------
# Envelope writer (pure) + OPERATOR-GATED load. The loop NEVER loads; the live
# write is an operator step. No top-level neo4j import — the CLI does the lazy
# GraphDatabase import; load_envelope takes an already-connected driver and is
# database-scoped (mirrors load_neo4j_v2, which had the unscoped-session bug).
# ---------------------------------------------------------------------------

import json
from pathlib import Path


def write_envelope(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], out_dir: Path
) -> dict[str, int]:
    """Write nodes.jsonl + edges.jsonl to `out_dir` (created). Pure, offline —
    this is what the loop produces; the operator loads it later."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nodes.jsonl").write_text(
        "".join(json.dumps(n, ensure_ascii=False) + "\n" for n in nodes), encoding="utf-8"
    )
    (out_dir / "edges.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in edges), encoding="utf-8"
    )
    return {"nodes_written": len(nodes), "edges_written": len(edges)}


def load_envelope(driver, envelope_dir: Path, *, database: str) -> dict[str, int]:
    """OPERATOR-GATED. Read the envelope + load via load_neo4j_v2's
    database-scoped load_nodes/load_edges. `database` is REQUIRED (never the
    implicit default/live DB). Runbook BEFORE calling:
      1. Snapshot/backup the target Neo4j database.
      2. Confirm `database` is the intended target (a scratch DB first).
      3. Reload-order: do NOT blind-reload the County source after the vendor
         orgs are deduped until a merge-map-aware loader exists (else edges to
         tombstoned ids reappear) — see the goal doc Predeclared 6.
    """
    envelope_dir = Path(envelope_dir)
    nodes = [
        json.loads(line)
        for line in (envelope_dir / "nodes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    edges = [
        json.loads(line)
        for line in (envelope_dir / "edges.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    from load_neo4j_v2 import load_nodes, load_edges  # lazy; no top-level neo4j
    load_nodes(driver, nodes, database=database)
    load_edges(driver, edges, database=database)
    return {"nodes_loaded": len(nodes), "edges_loaded": len(edges)}


def coverage_report(
    rows: list[dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    *,
    approved_group_ids: set[str],
) -> dict[str, Any]:
    """Honest coverage: the dual tie-out + group/vendor/person counts +
    denylist-clean. (Enumerating existing-org name matches as dedup candidates is
    the dedup follow-on's job, not Phase A's hot path — see Predeclared 6.)"""
    nodes = build_vendor_org_nodes(groups, approved_group_ids=approved_group_ids)
    person_orgs = sum(
        1 for n in nodes if "person_name_pattern" in n["properties"]["recipient_kind_hints"]
    )
    denied = ("person", "address", "street", "zip", "phone")
    denylist_clean = all(
        not any(d in k.lower() for d in denied)
        and "contract_contact_person" not in k.lower() and "person_side" not in k.lower()
        for n in nodes for k in n["properties"]
    )
    return {
        **summarize_attribution(rows, groups, approved_group_ids=approved_group_ids),
        "groups_total": len(groups),
        "approved_groups": len(approved_group_ids & set(groups)),
        "person_vendor_orgs": person_orgs,
        "denylist_clean": denylist_clean,
    }


def _load_approved_group_ids(path: Path) -> set[str]:
    return {
        json.loads(line)["subject_ref"]
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from ingest_marin_county_contracts import build_recipient_groups, parse_contract_rows

    p = argparse.ArgumentParser(description="County Attribution Phase A — vendor org creation + TO_TARGET")
    p.add_argument("--input", type=Path, required=True, help="delegated-contracts.csv")
    p.add_argument("--approved", type=Path, required=True, help="approved-resolutions.jsonl (the 43)")
    p.add_argument("--out-dir", type=Path, required=True, help="envelope output dir")
    p.add_argument("--load", action="store_true", help="OPERATOR-GATED: load the envelope live")
    p.add_argument("--uri"); p.add_argument("--user"); p.add_argument("--password")
    p.add_argument("--database", help="REQUIRED with --load (never the implicit default)")
    args = p.parse_args(argv)

    rows = parse_contract_rows(args.input)
    groups = build_recipient_groups(rows)
    approved = _load_approved_group_ids(args.approved)
    nodes = build_vendor_org_nodes(groups, approved_group_ids=approved)
    edges = build_vendor_to_target_edges(groups, approved_group_ids=approved)
    write_envelope(nodes, edges, args.out_dir)
    report = coverage_report(rows, groups, approved_group_ids=approved)
    print(json.dumps(report, indent=2))

    if args.load:
        if not args.database:
            p.error("--load requires --database (never the implicit default/live DB)")
        print("OPERATOR LOAD: snapshot the DB first; confirm --database is the intended target.")
        from neo4j import GraphDatabase  # lazy — no top-level neo4j import
        driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
        try:
            print(json.dumps(load_envelope(driver, args.out_dir, database=args.database), indent=2))
        finally:
            driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
