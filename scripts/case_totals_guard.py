#!/usr/bin/env python3
"""Guard the public money totals against a case load: compare a staging bake of the baseline with one of the
candidate, and fail on any unintended change or any double counting.

Every public money figure — money_rollups ("VERIFIED MONEY"), committee totals and rankings, by-name totals,
local-pressure sums, hero props — is computed from MoneyFlow amounts summed over the edges that touch them,
resolved through stamped identity links. So the guard compares exactly those inputs (the money surface): the
money_rollups table, every MoneyFlow row, every edge incident to a MoneyFlow, every identity link, and any
money-like property on another node. If the surface is unchanged no total can move, whichever consumer reads it.

A change must be listed in the intended-changes file — and even then the double-count detector runs on the
candidate export, because the bake cannot tell an authorization from the payment of it: a $100 approval plus its
$100 disbursement bakes to $200.

Usage:
  python scripts/case_totals_guard.py --baseline-db B.sqlite --candidate-db C.sqlite \
      --candidate-export <export dir> --intended intended-changes.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path

MONEY_PROP = re.compile(r"amount|money|total")
COUNTED_RELS = ("FROM_SOURCE", "TO_TARGET")
UNPAID_STAGES = ("authorization", "commitment")
DUPLICATE_WINDOW_DAYS = 7


def money_surface(db_path: Path) -> dict[str, dict[str, str]]:
    """Everything a public money total is derived from, keyed for diffing.

    Beyond the flows and their edges, every node adjacent to a flow is part of the surface in full (type, label,
    props): consumers choose which flows to sum by their neighbours' types and join keys (local-pressure ranking
    selects Programs by place ids, contribution queries by endpoint type)."""
    with sqlite3.connect(db_path) as conn:
        types = dict(conn.execute("SELECT id, type FROM nodes"))
        flows = {i for i, t in types.items() if t == "MoneyFlow"}
        surface: dict[str, dict[str, str]] = {
            "money_rollups": {row[0]: json.dumps(row[1:]) for row in conn.execute("SELECT * FROM money_rollups")},
            "flows": {},
            "flow_edges": {},
            "identity_links": {"|".join(row[:3]): json.dumps(row[3:]) for row in
                               conn.execute("SELECT source, target, assertion_id, basis, decided_at, reviewer "
                                            "FROM identity_links")},
            "money_props": {},
            "flow_neighbours": {},
        }
        rows = {node_id: (types[node_id], label, props) for node_id, label, props in
                conn.execute("SELECT id, search_label, props FROM nodes")}
        for node_id, props in conn.execute("SELECT id, props FROM nodes"):
            props = json.loads(props)
            if node_id in flows:
                surface["flows"][node_id] = json.dumps(props, sort_keys=True)
                continue
            money = {k: v for k, v in props.items() if MONEY_PROP.search(k)}
            if money:
                surface["money_props"][node_id] = json.dumps(money, sort_keys=True)
        for source, rel, target in conn.execute("SELECT source, rel, target FROM edges"):
            if source in flows or target in flows:
                surface["flow_edges"][f"{source}|{rel}|{target}"] = "1"
                for end in (source, target):
                    if end not in flows and end in rows:
                        surface["flow_neighbours"][end] = json.dumps(rows[end], sort_keys=True)
    return surface


def surface_changes(before: dict, after: dict) -> list[tuple[str, str, str | None, str | None]]:
    changes = []
    for surface in before:
        for key in sorted(set(before[surface]) | set(after[surface])):
            if before[surface].get(key) != after[surface].get(key):
                changes.append((surface, key, before[surface].get(key), after[surface].get(key)))
    return changes


def _edge(row: dict) -> dict:
    """Export rows say start_id/type/end_id; the attach overlay says source_id/relationship_type/target_id."""
    if "start_id" in row:
        return row
    return {"start_id": row["source_id"], "type": row["relationship_type"], "end_id": row["target_id"],
            "properties": row.get("properties") or {}}


def _closure(edges) -> dict[str, str]:
    """Identity sets from stamped SAME_AS edges (an assertion_id), unioned. The bake takes them from the attach
    overlay; the guard passes the candidate bake's own identity_links with the export's edges, a superset."""
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in map(_edge, edges):
        if e["type"] == "SAME_AS" and (e["properties"] or {}).get("assertion_id"):
            parent[find(e["start_id"])] = find(e["end_id"])
    return {x: find(x) for x in parent}


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _same_filing(a: dict, b: dict) -> bool:
    """Only recorded filing provenance establishes one filing; a shared id prefix is the filer, not the filing."""
    fa, fb = a["properties"].get("filing_id"), b["properties"].get("filing_id")
    return bool(fa) and fa == fb


def double_count_problems(nodes, edges, only: set[str] | None = None, identity_edges=()) -> list[str]:
    """Flows the bake would count twice or count as paid. With `only`, report just pairs touching those flows."""
    flows = {n["id"]: n for n in nodes if "MoneyFlow" in n["labels"]}
    resolve = _closure([*edges, *identity_edges])
    ends: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"FROM_SOURCE": set(), "TO_TARGET": set()})
    related: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        flow, other = (e["start_id"], e["end_id"]) if e["start_id"] in flows else (e["end_id"], e["start_id"])
        if flow not in flows or other in flows:
            continue
        if e["type"] in COUNTED_RELS:
            ends[flow][e["type"]].add(resolve.get(other, other))
        elif e["type"].startswith("RELATES_TO_"):
            related[flow].add(other)

    def wanted(*ids):
        return only is None or bool(set(ids) & only)

    problems = []
    for fid, flow in sorted(flows.items()):
        stage = flow["properties"].get("money_stage")
        counted = any(ends[fid].values())
        if stage in UNPAID_STAGES and counted and wanted(fid):
            problems.append(f"{fid}: a {stage} would be summed as VERIFIED MONEY; hold it back from the publish")

    by_thing: dict[str, set[str]] = defaultdict(set)
    for fid, flow in flows.items():
        for thing in related[fid] | ({flow["properties"]["agreement_id"]} if flow["properties"].get("agreement_id")
                                     else set()):
            by_thing[thing].add(fid)
    for thing, members in sorted(by_thing.items()):
        stages = {flows[f]["properties"].get("money_stage") for f in members}
        if stages & set(UNPAID_STAGES) and "disbursement" in stages and wanted(*members):
            problems.append(f"{thing}: {', '.join(sorted(members))} are the authorization and the disbursement of "
                            f"one thing; both would be counted")

    groups: dict[tuple, list[str]] = defaultdict(list)
    for fid, flow in flows.items():
        if any(ends[fid].values()) and flow["properties"].get("amount") is not None:
            key = (frozenset(ends[fid]["FROM_SOURCE"]), frozenset(ends[fid]["TO_TARGET"]),
                   str(float(flow["properties"]["amount"])))
            groups[key].append(fid)
    for members in groups.values():
        for a, b in combinations(sorted(members), 2):
            da, db = _day(flows[a]["properties"].get("flow_date")), _day(flows[b]["properties"].get("flow_date"))
            if (da and db and abs((da - db).days) <= DUPLICATE_WINDOW_DAYS and not _same_filing(flows[a], flows[b])
                    and wanted(a, b)):
                problems.append(f"{a} and {b}: same amount, same counterparties, {abs((da - db).days)} day(s) "
                                f"apart in different filings — possibly one transfer reported twice")
    return problems


def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _identity_edges(db_path: Path) -> list[dict]:
    """The identity links the candidate bake actually used (it takes them from the attach overlay)."""
    with sqlite3.connect(db_path) as conn:
        return [{"start_id": s, "type": "SAME_AS", "end_id": t, "properties": {"assertion_id": a}}
                for s, t, a in conn.execute("SELECT source, target, assertion_id FROM identity_links")]


def guard(baseline_db: Path, candidate_db: Path, candidate_export: Path, intended: list[dict]) -> list[str]:
    """Every change to the money surface must be intended with its exact before/after values; any change also
    runs the double-count detector (over the whole candidate when an identity link changed)."""
    allowed = {(c["surface"], c["key"]): (c.get("before"), c.get("after")) for c in intended}
    changes = surface_changes(money_surface(baseline_db), money_surface(candidate_db))
    problems = [f"{surface} changed at {key}: {before} -> {after} (not intended with these values)"
                for surface, key, before, after in changes if allowed.get((surface, key)) != (before, after)]
    touched = {key for surface, key, _, _ in changes if surface == "flows"}
    touched |= {part for surface, key, _, _ in changes if surface == "flow_edges" for part in key.split("|")}
    if changes:
        nodes = _read_jsonl(candidate_export / "nodes.jsonl")
        edges = _read_jsonl(candidate_export / "edges.jsonl")
        identity = _identity_edges(candidate_db)
        whole = any(surface == "identity_links" for surface, *_ in changes)
        problems += double_count_problems(nodes, edges, only=None if whole else touched, identity_edges=identity)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline-db", type=Path, required=True)
    parser.add_argument("--candidate-db", type=Path, required=True)
    parser.add_argument("--candidate-export", type=Path, required=True)
    parser.add_argument("--intended", type=Path, required=True, help="JSON list of {surface, key, before, after}: each change exactly as intended")
    args = parser.parse_args(argv)
    intended = json.loads(args.intended.read_text())
    changes = surface_changes(money_surface(args.baseline_db), money_surface(args.candidate_db))
    problems = guard(args.baseline_db, args.candidate_db, args.candidate_export, intended)
    print(f"money surface: {len(changes)} change(s), {len(intended)} intended")
    for surface, key, before, after in changes:
        print(f"  {surface} {key}: {before} -> {after}")
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    print(f"totals guard: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
