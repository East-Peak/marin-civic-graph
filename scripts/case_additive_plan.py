#!/usr/bin/env python3
"""Plan (never execute) an ADDITIVE load of a worked-case bundle into the live graph.

cf_migration_plan.py owns the campaign flows: it retires any flow its bundle lacks and loads edges without their
properties, so it cannot carry a hand-built case. This planner can only add — new nodes, new edges with all of
their properties, and properties an existing node does not have yet — and refuses anything else: a changed
value or label, an edge that already exists with other properties, a dangling endpoint, a value Neo4j cannot
store. The candidate is the baseline with exactly those ops applied; verification checks every intended node
and edge property AND that removing the additions gives back the untouched baseline, byte for byte.

Bundle and baseline use export_live_graph.py's format: nodes {id, labels, properties}, edges
{start_id, end_id, type, properties}. Nothing here connects to Neo4j.

Usage:
  python scripts/case_additive_plan.py --baseline <export dir> --case <bundle dir> --out <staging dir>
  python scripts/case_additive_plan.py --check-baseline <fresh export dir> --plan <staging dir>
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

STAGING_ROOT = Path.home() / "open-marin-staging" / "cf6-case"
EXPORT_FILES = ("nodes.jsonl", "edges.jsonl")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AdditivePlanError(Exception):
    """The case bundle would do something other than add."""


class StatementCountError(Exception):
    """A statement touched a different number of rows than planned (or a precheck found existing data)."""


def _edge_key(e: dict) -> tuple[str, str, str]:
    return e["start_id"], e["type"], e["end_id"]


INT64 = (-2 ** 63, 2 ** 63 - 1)


def _neo4j_scalar(value) -> bool:
    if isinstance(value, bool) or isinstance(value, (float, str)):
        return True
    return isinstance(value, int) and INT64[0] <= value <= INT64[1]


def _neo4j_value(value) -> bool:
    """What a SET round-trips: scalars and homogeneous lists of them. Never null (SET drops it), maps or
    mixed lists."""
    if isinstance(value, list):
        return len({type(v) for v in value}) <= 1 and all(_neo4j_scalar(v) for v in value)
    return _neo4j_scalar(value)


def _index(rows, key, what: str) -> dict:
    out = {}
    for row in rows:
        k = key(row)
        if k in out:
            raise AdditivePlanError(f"duplicate {what} {k}")
        out[k] = row
    return out


def _check_values(props: dict, where: str) -> None:
    bad = sorted(k for k, v in props.items() if not _neo4j_value(v) or not IDENTIFIER.fullmatch(k))
    if bad:
        raise AdditivePlanError(f"{where}: property {bad} is not a Neo4j-storable key/value")


def plan_additive(baseline_nodes, baseline_edges, case_nodes, case_edges) -> dict:
    base = _index(baseline_nodes, lambda n: n["id"], "baseline node")
    base_edges = _index(baseline_edges, _edge_key, "baseline edge")
    case = _index(case_nodes, lambda n: n["id"], "case node")
    case_e = _index(case_edges, _edge_key, "case edge")

    add_nodes, add_props, noop_nodes = [], {}, 0
    for nid, node in sorted(case.items()):
        props = node["properties"]
        if props.get("id", nid) != nid:
            raise AdditivePlanError(f"{nid}: properties.id {props['id']!r} differs from the node id")
        _check_values(props, nid)
        if not node["labels"]:
            raise AdditivePlanError(f"{nid}: a node needs at least one label")
        for label in node["labels"]:
            if not IDENTIFIER.fullmatch(label):
                raise AdditivePlanError(f"{nid}: label {label!r} is not a safe identifier")
        if nid not in base:
            add_nodes.append({"id": nid, "labels": sorted(node["labels"]), "properties": {**props, "id": nid}})
            continue
        have = base[nid]
        if sorted(node["labels"]) != sorted(have["labels"]):
            raise AdditivePlanError(f"{nid}: labels {sorted(node['labels'])} differ from the baseline's "
                                    f"{sorted(have['labels'])}")
        changed = sorted(k for k, v in props.items() if k in have["properties"] and have["properties"][k] != v)
        if changed:
            raise AdditivePlanError(f"{nid}: the case would change baseline properties {changed}")
        new = {k: v for k, v in props.items() if k not in have["properties"]}
        if new:
            add_props[nid] = new
        else:
            noop_nodes += 1

    known = set(base) | set(case)
    add_edges, noop_edges = [], 0
    for key, edge in sorted(case_e.items()):
        _check_values(edge["properties"], f"edge {key}")
        if not IDENTIFIER.fullmatch(key[1]):
            raise AdditivePlanError(f"edge {key}: type is not a safe identifier")
        missing = [end for end in (key[0], key[2]) if end not in known]
        if missing:
            raise AdditivePlanError(f"edge {key}: endpoint {missing} is in neither the baseline nor the case")
        if key in base_edges:
            if base_edges[key]["properties"] != edge["properties"]:
                raise AdditivePlanError(f"edge {key} exists with other properties; the case may not change them")
            noop_edges += 1
            continue
        add_edges.append({"start_id": key[0], "end_id": key[2], "type": key[1],
                          "properties": dict(edge["properties"])})

    return {
        "add_nodes": add_nodes,
        "add_props": add_props,
        "add_edges": add_edges,
        "summary": {
            "added_nodes": dict(Counter("|".join(n["labels"]) for n in add_nodes)),
            "nodes_gaining_props": len(add_props),
            "added_edges": dict(Counter(e["type"] for e in add_edges)),
            "noop_nodes": noop_nodes,
            "noop_edges": noop_edges,
        },
    }


def apply_additive(baseline_nodes, baseline_edges, ops) -> tuple[list[dict], list[dict]]:
    """The candidate graph: the baseline plus exactly the planned additions."""
    nodes = {n["id"]: copy.deepcopy(n) for n in baseline_nodes}
    for node in ops["add_nodes"]:
        nodes[node["id"]] = copy.deepcopy(node)
    for nid, props in ops["add_props"].items():
        nodes[nid]["properties"].update(copy.deepcopy(props))
    edges = [copy.deepcopy(e) for e in baseline_edges] + [copy.deepcopy(e) for e in ops["add_edges"]]
    return [nodes[i] for i in sorted(nodes)], sorted(edges, key=_edge_key)


def verify_additive(nodes, edges, baseline_nodes, baseline_edges, case_nodes, case_edges) -> list[str]:
    """Every intended node/edge property is in the candidate, and the rest of it is the baseline unchanged."""
    problems = []
    cand = {}
    for n in nodes:
        if n["id"] in cand:
            problems.append(f"duplicate candidate node {n['id']}")
        cand[n["id"]] = n
    cand_edges = {}
    for e in edges:
        if _edge_key(e) in cand_edges:
            problems.append(f"duplicate candidate edge {_edge_key(e)}")
        cand_edges[_edge_key(e)] = e
    for node in case_nodes:
        have = cand.get(node["id"])
        if have is None:
            problems.append(f"missing node {node['id']}")
            continue
        if not set(node["labels"]) <= set(have["labels"]):
            problems.append(f"{node['id']} lacks labels {sorted(set(node['labels']) - set(have['labels']))}")
        diff = sorted(k for k, v in node["properties"].items() if have["properties"].get(k, object()) != v)
        if diff:
            problems.append(f"{node['id']} differs on {diff}")
    for edge in case_edges:
        have = cand_edges.get(_edge_key(edge))
        if have is None:
            problems.append(f"missing edge {_edge_key(edge)}")
        elif have["properties"] != edge["properties"]:
            problems.append(f"edge {_edge_key(edge)} properties {have['properties']} != {edge['properties']}")

    case_ids = {n["id"] for n in case_nodes}
    case_keys = {_edge_key(e) for e in case_edges}
    base = {n["id"]: n for n in baseline_nodes}
    intended = {n["id"]: n["properties"] for n in case_nodes}
    for nid, node in base.items():
        have = cand.get(nid)
        if have is None:
            problems.append(f"baseline node {nid} is gone")
            continue
        rest = {k: v for k, v in have["properties"].items()
                if k in node["properties"] or k not in intended.get(nid, {})}
        if rest != node["properties"] or sorted(have["labels"]) != sorted(node["labels"]):
            problems.append(f"baseline node {nid} changed")
    for nid in set(cand) - set(base) - case_ids:
        problems.append(f"unplanned node {nid}")
    base_keys = {_edge_key(e): e for e in baseline_edges}
    for key, edge in base_keys.items():
        if key not in cand_edges:
            problems.append(f"baseline edge {key} is gone")
        elif cand_edges[key]["properties"] != edge["properties"]:
            problems.append(f"baseline edge {key} changed")
    for key in set(cand_edges) - set(base_keys) - case_keys:
        problems.append(f"unplanned edge {key}")
    return problems


def strip_additions(nodes, edges, ops) -> tuple[list[dict], list[dict]]:
    """The candidate with exactly the planned additions removed — must re-export as the baseline."""
    added = {n["id"] for n in ops["add_nodes"]}
    added_edges = {_edge_key(e) for e in ops["add_edges"]}
    rest = []
    for n in nodes:
        if n["id"] in added:
            continue
        drop = ops["add_props"].get(n["id"], {})
        rest.append({**n, "properties": {k: v for k, v in n["properties"].items() if k not in drop}})
    return rest, [e for e in edges if _edge_key(e) not in added_edges]


# ---------------------------------------------------------------------------
# Cypher for ONE explicit transaction (rendered into the plan; nothing here runs it)
# ---------------------------------------------------------------------------

def statements(ops: dict) -> list[dict]:
    """Prechecks (must count 0) then additions (must count exactly their rows), in dependency order."""
    stmts = []

    def add(step, query, rows, expect=None):
        if rows:
            stmts.append({"step": step, "query": query + " RETURN count(*) AS n", "params": {"rows": rows},
                          "expect": len(rows) if expect is None else expect})

    add("precheck:nodes_absent", "UNWIND $rows AS id OPTIONAL MATCH (n {id: id}) WITH n WHERE n IS NOT NULL",
        [n["id"] for n in ops["add_nodes"]], expect=0)
    add("precheck:edges_absent", "UNWIND $rows AS e OPTIONAL MATCH (s {id: e.start_id})-[r]->(t {id: e.end_id}) "
        "WITH r, e WHERE r IS NOT NULL AND type(r) = e.type",
        [{"start_id": e["start_id"], "type": e["type"], "end_id": e["end_id"]} for e in ops["add_edges"]], expect=0)
    by_labels: dict[tuple[str, ...], list[dict]] = {}
    for node in ops["add_nodes"]:
        by_labels.setdefault(tuple(node["labels"]), []).append({"props": node["properties"]})
    for labels, rows in sorted(by_labels.items()):
        add(f"add_nodes:{':'.join(labels)}", f"UNWIND $rows AS row CREATE (n:{':'.join(labels)}) SET n = row.props",
            rows)
    by_key: dict[str, list[dict]] = {}
    for nid, props in sorted(ops["add_props"].items()):
        for key, value in sorted(props.items()):
            by_key.setdefault(key, []).append({"id": nid, "value": value})
    for key, rows in sorted(by_key.items()):
        add(f"add_prop:{key}", f"UNWIND $rows AS row MATCH (n {{id: row.id}}) WHERE n.{key} IS NULL "
            f"SET n.{key} = row.value", rows)
    by_type: dict[str, list[dict]] = {}
    for e in ops["add_edges"]:
        by_type.setdefault(e["type"], []).append({"start_id": e["start_id"], "end_id": e["end_id"],
                                                  "props": e["properties"]})
    for rel, rows in sorted(by_type.items()):
        add(f"add_edges:{rel}", f"UNWIND $rows AS e MATCH (s {{id: e.start_id}}) MATCH (t {{id: e.end_id}}) "
            f"CREATE (s)-[r:{rel}]->(t) SET r = e.props", rows)
    return stmts


def apply_in_transaction(tx, ops: dict) -> dict:
    """Run every statement on the caller's single transaction; any count off plan raises before the next.

    The caller owns the transaction (`with session.begin_transaction() as tx: apply_in_transaction(tx, ops);
    tx.commit()`); an exception leaves it uncommitted, so Neo4j rolls back everything already run.
    """
    counts = {}
    for stmt in statements(ops):
        touched = tx.run(stmt["query"], **stmt["params"]).single()["n"]
        if touched != stmt["expect"]:
            kind = "precheck" if stmt["step"].startswith("precheck") else "statement"
            raise StatementCountError(f"{kind} {stmt['step']}: touched {touched}, planned {stmt['expect']}")
        counts[stmt["step"]] = touched
    return counts


# ---------------------------------------------------------------------------
# Files and CLI
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))  # export_live_graph's format


def write_export(out_dir: Path, nodes: list[dict], edges: list[dict]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nodes.jsonl").write_text("".join(_line(n) + "\n" for n in sorted(nodes, key=lambda n: n["id"])),
                                         encoding="utf-8")
    (out_dir / "edges.jsonl").write_text("".join(_line(e) + "\n" for e in sorted(edges, key=_edge_key)),
                                         encoding="utf-8")
    return fingerprint(out_dir)


def fingerprint(export_dir: Path) -> dict:
    return {name: hashlib.sha256((export_dir / name).read_bytes()).hexdigest() for name in EXPORT_FILES}


def staging_dir(path: Path) -> Path:
    """Resolve an output dir; refuse anything outside the goal's staging root (symlinks resolved) or non-empty."""
    out = Path(path).expanduser().resolve()
    root = Path(STAGING_ROOT).expanduser().resolve()
    if out != root and root not in out.parents:
        raise AdditivePlanError(f"refusing to write outside {root}")
    if out.exists() and any(out.iterdir()):
        raise AdditivePlanError(f"output dir {out} is not empty")
    return out


def _render(report: dict, ops: dict) -> str:
    lines = [
        "# Additive case load plan (NOT EXECUTED — awaits Stuart's \"apply\")", "",
        f"Baseline: `{report['baseline']['dir']}` — nodes `{report['baseline']['sha256']['nodes.jsonl']}`, "
        f"edges `{report['baseline']['sha256']['edges.jsonl']}`  ",
        f"Case bundle: `{report['case']['dir']}` — nodes `{report['case']['sha256']['nodes.jsonl']}`, "
        f"edges `{report['case']['sha256']['edges.jsonl']}`  ",
        f"Candidate: nodes `{report['candidate_sha256']['nodes.jsonl']}`, "
        f"edges `{report['candidate_sha256']['edges.jsonl']}`", "",
        f"- Added nodes: {ops['summary']['added_nodes']}",
        f"- Existing nodes gaining properties: {ops['summary']['nodes_gaining_props']}",
        f"- Added edges: {ops['summary']['added_edges']}",
        f"- No-op restatements: {ops['summary']['noop_nodes']} nodes, {ops['summary']['noop_edges']} edges",
        f"- Verification problems: {len(report['verification'])}; untouched baseline re-exports identically: "
        f"{report['baseline_reexport_identical']}", "",
        "## Procedure", "",
        "1. Fresh read-only export (`export_live_graph.py --backup`), then `case_additive_plan.py --check-baseline "
        "<it> --plan <this dir>`: its sha256 must equal the baseline above. Drift → re-plan.",
        "2. Keep that export as the backup.",
        "3. In ONE write transaction on bolt://localhost:7688: `with session.begin_transaction() as tx: "
        "case_additive_plan.apply_in_transaction(tx, ops); tx.commit()`; prechecks must count 0 and every "
        "statement exactly its rows, else the transaction is abandoned uncommitted. Statements:",
        *[f"   - `{s['step']}` ({len(s['params']['rows'])} rows, expect {s['expect']}): `{s['query']}`"
          for s in statements(ops)],
        "4. Re-export; its sha256 must equal the candidate above.",
        "5. Rollback: `restore_neo4j_local.py` from the step-1 export.", "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", type=Path, help="read-only export_live_graph.py --backup directory")
    mode.add_argument("--check-baseline", type=Path, help="a fresh export to compare with --plan's baseline")
    parser.add_argument("--case", type=Path, help="case bundle dir (nodes.jsonl, edges.jsonl)")
    parser.add_argument("--out", type=Path, help="empty dir under the staging root")
    parser.add_argument("--plan", type=Path, help="a plan dir written by --baseline")
    args = parser.parse_args(argv)

    if args.check_baseline:
        if args.plan is None:
            parser.error("--plan is required with --check-baseline")
        want = json.loads((args.plan / "plan-report.json").read_text())["baseline"]["sha256"]
        have = fingerprint(args.check_baseline)
        print("baseline matches the plan" if have == want else f"DRIFT: {have} != {want} — re-plan")
        return 0 if have == want else 1

    if args.case is None or args.out is None:
        parser.error("--case and --out are required with --baseline")
    try:
        out = staging_dir(args.out)
        baseline_nodes = _read_jsonl(args.baseline / "nodes.jsonl")
        baseline_edges = _read_jsonl(args.baseline / "edges.jsonl")
        case_nodes = _read_jsonl(args.case / "nodes.jsonl")
        case_edges = _read_jsonl(args.case / "edges.jsonl")
        ops = plan_additive(baseline_nodes, baseline_edges, case_nodes, case_edges)
    except AdditivePlanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    nodes, edges = apply_additive(baseline_nodes, baseline_edges, ops)
    problems = verify_additive(nodes, edges, baseline_nodes, baseline_edges, case_nodes, case_edges)
    candidate_sha = write_export(out / "candidate", nodes, edges)
    rest_sha = write_export(out / "baseline-reexport", *strip_additions(nodes, edges, ops))
    identical = rest_sha == fingerprint(args.baseline)
    if not identical:
        problems.append("the candidate minus the additions does not re-export as the baseline")
    report = {
        "baseline": {"dir": str(args.baseline.resolve()), "sha256": fingerprint(args.baseline)},
        "case": {"dir": str(args.case.resolve()), "sha256": fingerprint(args.case)},
        "candidate_sha256": candidate_sha,
        "baseline_reexport_sha256": rest_sha,
        "baseline_reexport_identical": identical,
        "summary": ops["summary"],
        "verification": problems,
    }
    (out / "ops.json").write_text(json.dumps(ops, indent=1, sort_keys=True) + "\n")
    (out / "plan-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "plan.md").write_text(_render(report, ops))
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    print(f"plan: {out}  ({len(problems)} verification problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
