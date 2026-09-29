#!/usr/bin/env python3
"""Normalize NetFile campaign finance ZIP exports into an operator-private staging bundle.

Writes, per source, under an explicit --output-root (never data/normalized, the private data repo,
data/exports, data/ingest-runs, or anywhere inside a git checkout):
  - manifest.json   every input's path, size and sha256; pinned HTML pages as unavailable coverage
  - ledger.jsonl, filings.jsonl, reconciliation.json   the private ledger (see campaign_ledger.py)
  - nodes.jsonl / edges.jsonl   (Committee, MoneyFlow, Person, Organization, Place)
  - normalization-report.json
and a run-manifest.json (the only file carrying timestamps) at the root. Nothing is loaded into Neo4j:
a load goes through a reviewed migration plan, because an additive MERGE cannot retire flows.

Usage:
  python scripts/normalize_campaign_finance.py --all --output-root ~/open-marin-staging/cf-ledger/run-1
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campaign_ledger import (  # noqa: E402
    InputError, LedgerError, UnsafeOutputError, build_ledger, build_transactions, inventory_inputs,
    resolve_output_root, write_ledger,
)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify_name(last: str | None, first: str | None = None) -> str:
    """Produce a stable hyphen-slug from a name pair."""
    parts = []
    if last:
        parts.append(last.strip())
    if first:
        parts.append(first.strip())
    raw = " ".join(parts)
    # Strip possessive / punctuation-only characters before lowercasing,
    # so "O'Brien" → "OBrien" (no extra hyphen) rather than "O-Brien".
    slug = re.sub(r"[''`]", "", raw)
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug


def _node(
    id: str,
    node_type: str,
    labels: list[str],
    display_label: str,
    properties: dict,
    capture_id: str,
    section: str = "campaign_finance",
    status: str | None = None,
) -> dict:
    return {
        "id": id,
        "node_type": node_type,
        "labels": labels,
        "display_label": display_label,
        "promotion_state": "promoted",
        "source_bundle_ids": [capture_id],
        "source_sections": [section],
        "source_status": status,
        "properties": properties,
        "qa_lane": False,
    }


def _edge(
    source_id: str,
    source_type: str,
    target_id: str,
    target_type: str,
    rel_type: str,
    capture_id: str,
    properties: dict | None = None,
) -> dict:
    return {
        "source_id": source_id,
        "source_node_type": source_type,
        "target_id": target_id,
        "target_node_type": target_type,
        "relationship_type": rel_type,
        "source_bundle_ids": [capture_id],
        "source_fields": ["normalize_campaign_finance"],
        "properties": properties or {},
    }


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------

def build_committee_node(
    filer_id: int | str,
    filer_name: str,
    committee_type: str,
    jurisdiction_id: str,
    capture_id: str,
) -> dict:
    # filer_id is usually a numeric string but can be "Pending" for newly-registered committees
    try:
        filer_id_stored: int | str = int(filer_id)
    except (TypeError, ValueError):
        filer_id_stored = str(filer_id) if filer_id is not None else ""
    node_id = f"committee-netfile-{filer_id_stored}"
    return _node(
        id=node_id,
        node_type="Committee",
        labels=["Committee"],
        display_label=filer_name or node_id,
        properties={
            "name": filer_name,
            "netfile_filer_id": filer_id_stored,
            "committee_type": committee_type,
            "jurisdiction_id": jurisdiction_id,
        },
        capture_id=capture_id,
        section="committee_stubs",
        status="stub_from_netfile_export",
    )


def build_moneyflow_node(moneyflow_id: str, amount: float, flow_date: str | None, flow_type: str,
                         source_schedule: str, capture_id: str) -> dict:
    """A MoneyFlow with exactly the live graph's properties; its provenance lives in the private ledger."""
    props: dict = {"amount": amount, "flow_type": flow_type, "source_schedule": source_schedule}
    if flow_date:
        props["flow_date"] = flow_date
    return _node(
        id=moneyflow_id,
        node_type="MoneyFlow",
        labels=["MoneyFlow"],
        display_label=f"{flow_type} ${amount:.2f}",
        properties=props,
        capture_id=capture_id,
        section="money_flows",
        status="from_netfile_export",
    )


def build_contributor_node(
    name_last: str | None,
    name_first: str | None,
    entity_cd: str,
    capture_id: str,
) -> dict:
    slug = slugify_name(name_last, name_first)
    org_entity_codes = {"COM", "OTH", "SCC", "PTY"}
    if entity_cd in org_entity_codes:
        node_id = f"org-{slug}"
        display = name_last or slug
        return _node(
            id=node_id,
            node_type="Organization",
            labels=["Organization"],
            display_label=display,
            properties={"name": display, "entity_cd": entity_cd},
            capture_id=capture_id,
            section="contributor_stubs",
            status="stub_from_netfile_export",
        )
    else:
        # IND (individual) and anything else → Person, under the live graph's id. Name-slug ids merge
        # namesakes (and can meet other pipelines' person-{slug}); that known defect belongs to identity work.
        node_id = f"person-{slug}"
        parts = [p for p in [name_first, name_last] if p and p.strip()]
        display = " ".join(parts) if parts else slug
        return _node(
            id=node_id,
            node_type="Person",
            labels=["Person"],
            display_label=display,
            properties={"name": display, "entity_cd": entity_cd},
            capture_id=capture_id,
            section="contributor_stubs",
            status="stub_from_netfile_export",
        )


# ---------------------------------------------------------------------------
# Graph emission from the ledger
# ---------------------------------------------------------------------------

FLOW_TYPES = {"A": "contribution", "E": "expenditure"}
DEFAULT_ENTITY = {"A": "IND", "E": "OTH"}  # legacy defaults when Entity_Cd is blank


def normalize_campaign_source(capture: dict, ledger, output_dir: Path) -> tuple[list[dict], list[dict], dict]:
    """Emit the graph bundle for one source from its ledger (after build_transactions).

    Actors (committees, contributors, payees) are exactly the legacy set: built first-seen from every nonzero
    retained A/E row, in export order. MoneyFlows exist only for counted transactions. Filing provenance and
    reported contributor details stay in the private ledger: the bundle publishes nothing the live graph lacks.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_id, jurisdiction_id, source_id = capture["capture_id"], capture["jurisdiction_id"], capture["source_id"]
    place_name = jurisdiction_id.replace("place-", "").replace("-", " ").title()
    nodes: dict[str, dict] = {jurisdiction_id: _node(
        id=jurisdiction_id, node_type="Place", labels=["Place"], display_label=place_name,
        properties={"name": place_name}, capture_id=capture_id, section="place_stubs",
        status="stub_from_source_config")}

    committees: dict[str, dict] = {}
    counterparties: dict[str, dict] = {}
    for row in ledger.rows:  # sorted by file, then A-Contributions before E-Expenditure, then row: export order
        if not row["schedule"] or row["disposition"] != "retained" or Decimal(row["amount"]) == 0:
            continue
        filer_id = ledger.filings[row["filing_id"]]["filer_id"]
        if filer_id not in committees:
            committees[filer_id] = build_committee_node(
                filer_id=filer_id, filer_name=row["filer_name"], committee_type=row["committee_type"] or "",
                jurisdiction_id=jurisdiction_id, capture_id=capture_id)
        slug = slugify_name(row["name"]["last"], row["name"]["first"])
        if slug and slug not in counterparties:
            counterparties[slug] = build_contributor_node(
                row["name"]["last"], row["name"]["first"], row["entity_cd"] or DEFAULT_ENTITY[row["schedule"]],
                capture_id)

    edges: list[dict] = []
    for committee in committees.values():
        nodes[committee["id"]] = committee
        edges.append(_edge(committee["id"], "Committee", jurisdiction_id, "Place", "IN_JURISDICTION", capture_id))
    for actor in counterparties.values():
        nodes[actor["id"]] = actor

    withheld: dict[str, int] = {}
    emitted = {"A": Decimal("0.00"), "E": Decimal("0.00")}
    for tx in ledger.transactions:
        if not tx["counts"]:
            withheld[tx["reason"]] = withheld.get(tx["reason"], 0) + 1
            continue
        amount = Decimal(tx["amount"])
        emitted[tx["schedule"]] += amount
        mf_id = tx["moneyflow_id"]
        nodes[mf_id] = build_moneyflow_node(mf_id, float(amount), tx["tran_date"], FLOW_TYPES[tx["schedule"]],
                                            tx["schedule"], capture_id)
        committee = committees[tx["filer_id"]]
        actor = counterparties.get(slugify_name(tx["name"]["last"], tx["name"]["first"]))
        if tx["schedule"] == "A":
            if actor:
                edges.append(_edge(actor["id"], actor["node_type"], mf_id, "MoneyFlow", "FROM_SOURCE", capture_id))
            edges.append(_edge(mf_id, "MoneyFlow", committee["id"], "Committee", "TO_TARGET", capture_id))
        else:
            edges.append(_edge(committee["id"], "Committee", mf_id, "MoneyFlow", "FROM_SOURCE", capture_id))
            if actor:
                edges.append(_edge(mf_id, "MoneyFlow", actor["id"], actor["node_type"], "TO_TARGET", capture_id))

    node_list = [nodes[i] for i in sorted(nodes)]
    edges.sort(key=lambda e: (e["relationship_type"], e["source_id"], e["target_id"]))
    triples = [(e["source_id"], e["relationship_type"], e["target_id"]) for e in edges]
    broken = [e for e in edges if e["source_id"] not in nodes or e["target_id"] not in nodes]
    report = {
        "source_id": source_id,
        "capture_id": capture_id,
        "node_count": len(node_list),
        "edge_count": len(edges),
        "committee_count": len(committees),
        "contributor_count": len(counterparties),
        "moneyflow_count": sum(1 for n in node_list if n["node_type"] == "MoneyFlow"),
        "emitted_amount": {k: str(v) for k, v in emitted.items()},
        "withheld": dict(sorted(withheld.items())),
        "broken_edge_count": len(broken),
        "duplicate_id_count": 0,
        "duplicate_edge_count": len(triples) - len(set(triples)),
    }
    with open(output_dir / "nodes.jsonl", "w") as f:
        for node in node_list:
            f.write(json.dumps(node, sort_keys=True) + "\n")
    with open(output_dir / "edges.jsonl", "w") as f:
        for edge in edges:
            f.write(json.dumps(edge, sort_keys=True) + "\n")
    (output_dir / "normalization-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return node_list, edges, report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SAFE_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")


def _git_checkouts() -> list[Path]:
    """This checkout plus the main checkout it may be a worktree of: both are protected destinations."""
    roots = [ROOT]
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, check=True).stdout.strip()
        roots.append(Path(common).parent)
    except (OSError, subprocess.CalledProcessError):
        pass
    return roots


def _capture_date(input_root: Path, source_id: str) -> str:
    return sorted(p.name for p in (input_root / source_id).iterdir() if p.is_dir())[-1]


def _years(backfill_from: str, capture_date: str) -> list[str]:
    return [str(y) for y in range(int(backfill_from[:4]), int(capture_date[:4]) + 1)]


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize NetFile campaign finance exports into an operator-private staging bundle"
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--source", help="Source ID to normalize")
    target.add_argument("--all", dest="all_sources", action="store_true", help="Normalize all NetFile sources")
    parser.add_argument("--input-root", type=Path, default=ROOT / "data" / "raw",
                        help="Root holding <source>/<capture date>/<year>.zip (default: data/raw)")
    parser.add_argument("--output-root", type=Path, required=True,
                        help="Empty staging dir outside every git checkout and protected data dir")
    parser.add_argument("--registry", type=Path, default=ROOT / "registry" / "netfile-sources.yaml")
    parser.add_argument("--exceptions", type=Path,
                        help="JSON list of reconciliation exceptions {source_id, filing_id, schedule, locator, evidence}")
    parser.add_argument("--version-evidence", type=Path,
                        help="JSON list of amendment evidence {source_id, original, amended, locator, evidence}")
    args = parser.parse_args(argv)

    import yaml

    try:
        out_root = resolve_output_root(args.output_root, *_git_checkouts())
    except UnsafeOutputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    sources = yaml.safe_load(args.registry.read_text()).get("sources", [])
    unsafe = [repr(s.get("id")) for s in sources if not SAFE_SOURCE_ID.fullmatch(str(s.get("id") or ""))]
    if unsafe:
        print(f"ERROR: source id must be one safe path component: {', '.join(unsafe)}", file=sys.stderr)
        return 1
    targets = sources if args.all_sources else [s for s in sources if s["id"] == args.source]
    if not targets:
        print(f"Unknown source: {args.source}", file=sys.stderr)
        return 1

    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    inventories = []
    try:
        for source_config in targets:
            source_id = source_config["id"]
            capture_date = _capture_date(args.input_root, source_id)
            pins = [p for p in source_config.get("unavailable_inputs", []) if p["capture"] == capture_date]
            inputs = inventory_inputs(args.input_root, source_id, capture_date,
                                      years=_years(source_config["backfill_from"], capture_date),
                                      unavailable=pins)
            inventories.append((source_config, capture_date, inputs))
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    exceptions = json.loads(args.exceptions.read_text()) if args.exceptions else []
    versions = json.loads(args.version_evidence.read_text()) if args.version_evidence else []
    run_ids = {s["id"] for s, _, _ in inventories}
    strays = sorted({str(e.get("source_id")) for e in exceptions + versions} - run_ids)
    if strays:
        print(f"ERROR: exception/evidence entries for source(s) not in this run: {', '.join(strays)}",
              file=sys.stderr)
        return 1
    flow_ids: set[str] = set()
    for source_config, capture_date, inputs in inventories:
        source_id = source_config["id"]
        capture = {
            "source_id": source_id,
            "capture_id": f"{source_id}__{capture_date}",
            "jurisdiction_id": source_config["jurisdiction_id"],
            "institution_id": source_config["institution_id"],
            "captured_at": f"{capture_date}T00:00:00Z",
        }
        output_dir = out_root / source_id
        _write_json(output_dir / "manifest.json", {"capture_id": capture["capture_id"], "inputs": inputs})
        workbooks = [(i["path"], args.input_root / i["path"]) for i in inputs if i["coverage"] == "workbook"]
        print(f"\nNormalizing: {source_id}")
        try:
            ledger = build_ledger(source_id, workbooks,
                                  version_evidence=[v for v in versions if v.get("source_id") == source_id],
                                  exceptions=[e for e in exceptions if e.get("source_id") == source_id])
            if not ledger.errors:
                build_transactions(ledger)
        except LedgerError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        write_ledger(ledger, output_dir)
        print(f"  Reconciliation: {json.dumps(ledger.counts(), sort_keys=True)}")
        if ledger.errors:
            for error in ledger.errors:
                print(f"  ERROR: {error}", file=sys.stderr)
            return 1
        nodes, _, report = normalize_campaign_source(capture, ledger, output_dir)
        print(f"  MoneyFlows:   {report['moneyflow_count']}  withheld: {report['withheld']}")
        print(f"  Output:       {output_dir}")
        if report["broken_edge_count"] or report["duplicate_edge_count"]:
            print(f"  ERROR: {report['broken_edge_count']} broken edges, "
                  f"{report['duplicate_edge_count']} duplicate edges", file=sys.stderr)
            return 1
        clashes = sorted(flow_ids & {n["id"] for n in nodes if n["node_type"] == "MoneyFlow"})
        if clashes:
            print(f"  ERROR: MoneyFlow ids also emitted by another source: {clashes[:5]}", file=sys.stderr)
            return 1
        flow_ids |= {n["id"] for n in nodes if n["node_type"] == "MoneyFlow"}

    _write_json(out_root / "run-manifest.json", {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "argv": sys.argv[1:] if argv is None else argv,
        "input_root": str(Path(args.input_root).resolve()),
        "sources": [s["id"] for s, _, _ in inventories],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
