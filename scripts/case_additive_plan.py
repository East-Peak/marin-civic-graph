#!/usr/bin/env python3
"""Plan (never execute) an ADDITIVE load of a worked-case bundle into the live graph.

cf_migration_plan.py owns the campaign flows: it retires any flow its bundle lacks and loads edges without their
properties, so it cannot carry a hand-built case. This planner can only add — new nodes, new edges with all of
their properties, and properties an existing node does not have yet — and refuses anything else: a changed
value or label, an edge that already exists with other properties, a dangling endpoint, a value Neo4j cannot
store. The candidate is the baseline with exactly those ops applied; verification checks every intended node
and edge property AND that removing the additions gives back the untouched baseline, byte for byte.

A profile narrows what a goal's bundle may do (`--profile votes-b`: only new Decision and Person nodes, only
CAST_VOTE and DECIDED_AT edges, no property additions, no restatements of baseline rows). The plan also carries
the inverse (delete exactly the additions) for recovery.

Bundle and baseline use export_live_graph.py's format: nodes {id, labels, properties}, edges
{start_id, end_id, type, properties}. Nothing here connects to Neo4j.

Usage:
  python scripts/case_additive_plan.py --baseline <export dir> --case <bundle dir> --out <staging dir> [--profile votes-b]
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

STAGING_ROOTS = (Path.home() / "open-marin-staging" / "cf6-case", Path.home() / "open-marin-staging" / "votes-b")
PROFILES = {
    "votes-b": {"labels": frozenset({"Decision", "Person"}), "rel_types": frozenset({"CAST_VOTE", "DECIDED_AT"}),
                "add_props": False, "noop": False},
}
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


def plan_additive(baseline_nodes, baseline_edges, case_nodes, case_edges, constraints: dict | None = None) -> dict:
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

    if constraints is not None:
        _enforce(constraints, add_nodes, add_props, add_edges, noop_nodes, noop_edges)
    labels = {}
    for nid in sorted({e[end] for e in add_edges for end in ("start_id", "end_id")} | set(add_props)):
        have = sorted((case.get(nid) or base[nid])["labels"])
        if not have or not all(isinstance(x, str) and IDENTIFIER.fullmatch(x) for x in have):
            raise AdditivePlanError(f"{nid}: labels {have!r} are not safe identifiers; statements match by label")
        labels[nid] = have
    return {
        "add_nodes": add_nodes,
        "add_props": add_props,
        "add_edges": add_edges,
        "labels": labels,
        "summary": {
            "added_nodes": dict(Counter("|".join(n["labels"]) for n in add_nodes)),
            "nodes_gaining_props": len(add_props),
            "added_edges": dict(Counter(e["type"] for e in add_edges)),
            "noop_nodes": noop_nodes,
            "noop_edges": noop_edges,
        },
    }


def _enforce(c: dict, add_nodes, add_props, add_edges, noop_nodes: int, noop_edges: int) -> None:
    for node in add_nodes:
        if not set(node["labels"]) <= c["labels"]:
            raise AdditivePlanError(f"{node['id']}: label {sorted(set(node['labels']) - c['labels'])} is outside "
                                    f"the profile's {sorted(c['labels'])}")
    for edge in add_edges:
        if edge["type"] not in c["rel_types"]:
            raise AdditivePlanError(f"edge {_edge_key(edge)}: type {edge['type']} is outside the profile's "
                                    f"{sorted(c['rel_types'])}")
    if add_props and not c["add_props"]:
        raise AdditivePlanError(f"the profile may not add properties to existing nodes ({sorted(add_props)[:3]})")
    if (noop_nodes or noop_edges) and not c.get("noop", False):
        raise AdditivePlanError(f"the profile may not restate baseline rows ({noop_nodes} nodes, {noop_edges} edges)")


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

def _label_of(ops: dict):
    """node id → its `:A:B` label expression, from the plan's validated labels (no label-free fallback)."""
    if "labels" not in ops:
        raise AdditivePlanError("the plan has no node labels; re-plan (statements match nodes by label and id)")

    def label(nid: str) -> str:
        have = ops["labels"].get(nid)
        if not have or not all(isinstance(x, str) and IDENTIFIER.fullmatch(x) for x in have):
            raise AdditivePlanError(f"{nid}: the plan has no safe labels for it")
        return ":" + ":".join(have)
    return label


def _by_endpoint_labels(ops: dict, edges, row) -> dict[tuple[str, str, str], list]:
    label = _label_of(ops)
    groups: dict[tuple[str, str, str], list] = {}
    for e in edges:
        groups.setdefault((e["type"], label(e["start_id"]), label(e["end_id"])), []).append(row(e))
    return groups


def _step_name(rel: str, start: str, end: str) -> str:
    return f"{rel}:{start[1:]}->{end[1:]}"


def statements(ops: dict) -> list[dict]:
    """Prechecks (must count 0) then additions (must count exactly their rows), in dependency order. Nodes are
    matched by (label, id) so every lookup is an index seek; only the node-absence precheck is global (an id
    must be free under every label)."""
    stmts = []
    label = _label_of(ops)

    def add(step, query, rows, expect=None):
        if rows:
            stmts.append({"step": step, "query": query + " RETURN count(*) AS n", "params": {"rows": rows},
                          "expect": len(rows) if expect is None else expect})

    add("precheck:nodes_absent", "UNWIND $rows AS id OPTIONAL MATCH (n {id: id}) WITH n WHERE n IS NOT NULL",
        [n["id"] for n in ops["add_nodes"]], expect=0)
    pre = _by_endpoint_labels(ops, ops["add_edges"],
                              lambda e: {"start_id": e["start_id"], "type": e["type"], "end_id": e["end_id"]})
    for (rel, sl, tl), rows in sorted(pre.items()):
        add(f"precheck:edges_absent:{_step_name(rel, sl, tl)}",
            f"UNWIND $rows AS e OPTIONAL MATCH (s{sl} {{id: e.start_id}})-[r]->(t{tl} {{id: e.end_id}}) "
            "WITH r, e WHERE r IS NOT NULL AND type(r) = e.type", rows, expect=0)
    by_labels: dict[tuple[str, ...], list[dict]] = {}
    for node in ops["add_nodes"]:
        by_labels.setdefault(tuple(node["labels"]), []).append({"props": node["properties"]})
    for labels, rows in sorted(by_labels.items()):
        add(f"add_nodes:{':'.join(labels)}", f"UNWIND $rows AS row CREATE (n:{':'.join(labels)}) SET n = row.props",
            rows)
    by_key: dict[tuple[str, str], list[dict]] = {}
    for nid, props in sorted(ops["add_props"].items()):
        for key, value in sorted(props.items()):
            by_key.setdefault((key, label(nid)), []).append({"id": nid, "value": value})
    for (key, nl), rows in sorted(by_key.items()):
        add(f"add_prop:{key}:{nl[1:]}", f"UNWIND $rows AS row MATCH (n{nl} {{id: row.id}}) WHERE n.{key} IS NULL "
            f"SET n.{key} = row.value", rows)
    create = _by_endpoint_labels(ops, ops["add_edges"],
                                 lambda e: {"start_id": e["start_id"], "end_id": e["end_id"], "props": e["properties"]})
    for (rel, sl, tl), rows in sorted(create.items()):
        add(f"add_edges:{_step_name(rel, sl, tl)}", f"UNWIND $rows AS e MATCH (s{sl} {{id: e.start_id}}) "
            f"MATCH (t{tl} {{id: e.end_id}}) CREATE (s)-[r:{rel}]->(t) SET r = e.props", rows)
    return stmts


def inverse_statements(ops: dict) -> list[dict]:
    """Recovery only: delete exactly the planned additions — edges first, then the nodes (which by then must have
    no relationship left), then the added properties. Never DETACH; each statement must count its rows."""
    stmts = []
    label = _label_of(ops)
    groups = _by_endpoint_labels(ops, ops["add_edges"], lambda e: {"start_id": e["start_id"], "end_id": e["end_id"]})
    for (rel, sl, tl), rows in sorted(groups.items()):
        stmts.append({"step": f"inverse:edges:{_step_name(rel, sl, tl)}",
                      "query": f"UNWIND $rows AS e MATCH (s{sl} {{id: e.start_id}})-[r:{rel}]->(t{tl} {{id: e.end_id}}) "
                      "DELETE r RETURN count(*) AS n", "params": {"rows": rows}, "expect": len(rows)})
    by_labels: dict[tuple[str, ...], list[str]] = {}
    for node in ops["add_nodes"]:
        by_labels.setdefault(tuple(node["labels"]), []).append(node["id"])
    for labels, rows in sorted(by_labels.items()):
        stmts.append({"step": f"inverse:nodes:{':'.join(labels)}", "query": f"UNWIND $rows AS id MATCH "
                      f"(n:{':'.join(labels)} {{id: id}}) WHERE NOT (n)--() DELETE n RETURN count(*) AS n",
                      "params": {"rows": rows}, "expect": len(rows)})
    by_key: dict[tuple[str, str], list[str]] = {}
    for nid, props in sorted(ops["add_props"].items()):
        for key in sorted(props):
            by_key.setdefault((key, label(nid)), []).append(nid)
    for (key, nl), rows in sorted(by_key.items()):
        stmts.append({"step": f"inverse:prop:{key}:{nl[1:]}", "query": f"UNWIND $rows AS id MATCH (n{nl} {{id: id}}) "
                      f"REMOVE n.{key} RETURN count(*) AS n", "params": {"rows": rows}, "expect": len(rows)})
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
    """Resolve an output dir; refuse anything outside the goals' staging roots (symlinks resolved) or non-empty."""
    out = Path(path).expanduser().resolve()
    roots = [Path(r).expanduser().resolve() for r in STAGING_ROOTS]
    if not any(out == root or root in out.parents for root in roots):
        raise AdditivePlanError(f"refusing to write outside {', '.join(map(str, roots))}")
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
        "5. Rollback: `restore_neo4j_local.py` from the step-1 export; or, additions only, `inverse.json` "
        "(deletes exactly the planned rows, each statement counted).", "",
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
    parser.add_argument("--profile", choices=sorted(PROFILES), help="constrain the bundle (e.g. votes-b)")
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
        ops = plan_additive(baseline_nodes, baseline_edges, case_nodes, case_edges,
                            constraints=PROFILES[args.profile] if args.profile else None)
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
        "profile": args.profile,
    }
    (out / "ops.json").write_text(json.dumps(ops, indent=1, sort_keys=True) + "\n")
    (out / "plan-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "plan.md").write_text(_render(report, ops))
    (out / "inverse.json").write_text(json.dumps({"statements": inverse_statements(ops)}, indent=1, sort_keys=True)
                                      + "\n")
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    print(f"plan: {out}  ({len(problems)} verification problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
