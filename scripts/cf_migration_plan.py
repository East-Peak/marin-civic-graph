#!/usr/bin/env python3
"""Plan (never execute) the migration of the live graph's campaign-finance flows to a staged ledger bundle.

The plan is an explicit op list computed from a read-only live-graph export (the baseline) and a staging run of
normalize_campaign_finance.py: retire nodes, retire edges, add nodes, set/remove normalizer-owned properties,
add edges. The candidate graph is produced by applying exactly those ops to the baseline in memory, then
verified against the bundle, so what is reviewed is what would be loaded. An additive MERGE alone could not
retire a flow; nothing here connects to Neo4j.

Usage:
  python scripts/cf_migration_plan.py --baseline <export dir> --bundle <staging run> --out <empty staging dir>
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campaign_ledger import UnsafeOutputError, resolve_output_root  # noqa: E402
from contributor_detail import (  # noqa: E402
    ENTITY_PROP, PROPS, REVIEWED_PATH, flow_props, load_reviewed, transaction_details,
)

CAMPAIGN_FLOW_TYPES = ("contribution", "expenditure")
NETFILE_FLOW_ID = re.compile(r"moneyflow-(\d+|Pending)-")
CF_EDGE_TYPES = ("FROM_SOURCE", "TO_TARGET", "EVIDENCED_BY")
CONTRIBUTOR_PROPS = (*PROPS.values(), ENTITY_PROP)
# What the normalizer writes on a MoneyFlow; anything else on a live flow (embeddings, clusters) is kept.
OWNED_FLOW_PROPS = ("amount", "flow_type", "source_schedule", "flow_date", "display_label", "promotion_state",
                    *CONTRIBUTOR_PROPS)


def _is_campaign_flow(node: dict) -> bool:
    return ("MoneyFlow" in node["labels"] and node["properties"].get("flow_type") in CAMPAIGN_FLOW_TYPES
            and bool(NETFILE_FLOW_ID.match(node["id"])))


def _bundle_props(node: dict) -> dict:
    """The properties a bundle node would hold after the loader's MERGE + SET."""
    return {**{k: v for k, v in node["properties"].items() if k != "payload_json"},
            "id": node["id"], "display_label": node.get("display_label", ""),
            "promotion_state": node.get("promotion_state", "")}


def _edge_key(e: dict) -> tuple[str, str, str]:
    if "start_id" in e:
        return e["start_id"], e["type"], e["end_id"]
    return e["source_id"], e["relationship_type"], e["target_id"]


def _edge_dict(key: tuple[str, str, str]) -> dict:
    return {"start_id": key[0], "end_id": key[2], "type": key[1]}


def _resolver(nodes) -> dict[str, str]:
    """Live identity decisions: an alias node keeps `dedup_superseded_by` and its edges move to the canonical."""
    superseded = {n["id"]: n["properties"]["dedup_superseded_by"] for n in nodes
                  if n["properties"].get("dedup_superseded_by")}
    resolved = {}
    for alias in superseded:
        target, seen = alias, set()
        while target in superseded and target not in seen:
            seen.add(target)
            target = superseded[target]
        resolved[alias] = target
    return resolved


def _resolve_edges(edges, resolved: dict[str, str]) -> list[tuple[str, str, str]]:
    return [(resolved.get(k[0], k[0]), k[1], resolved.get(k[2], k[2])) for k in map(_edge_key, edges)]


def plan_ops(baseline_nodes, baseline_edges, bundle_nodes, bundle_edges) -> dict:
    base = {n["id"]: n for n in baseline_nodes}
    bundle = {n["id"]: n for n in bundle_nodes}
    bundle_flows = {i for i, n in bundle.items() if n["node_type"] == "MoneyFlow"}
    owned = {i for i, n in base.items() if _is_campaign_flow(n)} | (bundle_flows & set(base))
    retire = sorted(owned - bundle_flows)
    added = sorted(set(bundle) - set(base))

    set_props = {}
    for fid in sorted(bundle_flows & set(base)):
        want = _bundle_props(bundle[fid])
        have = base[fid]["properties"]
        changes = {"set": {k: want[k] for k in OWNED_FLOW_PROPS if k in want and have.get(k) != want[k]},
                   "remove": [k for k in OWNED_FLOW_PROPS if k in have and k not in want]}
        if changes["set"] or changes["remove"]:
            set_props[fid] = changes

    resolved = _resolver(baseline_nodes)
    bundle_keys = set(_resolve_edges(bundle_edges, resolved))
    endpoints_resolved = sum(1 for e in bundle_edges if {_edge_key(e)[0], _edge_key(e)[2]} & set(resolved))
    retired = set(retire)
    retire_edges, external = [], []
    for e in baseline_edges:
        key = _edge_key(e)
        ends = {key[0], key[2]}
        if ends & retired:
            retire_edges.append(key)
            if key[1] not in CF_EDGE_TYPES:
                external.append(key)
        elif ends & owned and key[1] in CF_EDGE_TYPES and key not in bundle_keys:
            retire_edges.append(key)
    base_keys = {_edge_key(e) for e in baseline_edges}
    add_edges = sorted(bundle_keys - base_keys)

    retained = [i for i in sorted(set(bundle) & set(base)) if i not in set_props]
    return {
        "retire_nodes": retire,
        "retire_edges": [_edge_dict(k) for k in sorted(set(retire_edges))],
        "add_nodes": [bundle[i] for i in added],
        "set_props": set_props,
        "add_edges": [_edge_dict(k) for k in add_edges],
        "summary": {
            "retained_nodes": len(retained),
            "changed_nodes": len(set_props),
            "retired_nodes": len(retire),
            "added_nodes": Counter(bundle[i]["node_type"] for i in added),
            "retired_edges": len(set(retire_edges)),
            "added_edges": len(add_edges),
            "shared_actors_touched": sorted(i for i in set(bundle) & set(base) if i not in bundle_flows),
            "external_edges_on_retired": [_edge_dict(k) for k in sorted(set(external))],
            "endpoints_resolved": endpoints_resolved,
        },
    }


def apply_ops(baseline_nodes, baseline_edges, ops) -> tuple[list[dict], list[dict]]:
    """The candidate graph: exactly what loading the ops into the baseline would leave (DETACH DELETE semantics)."""
    retired = set(ops["retire_nodes"])
    nodes = {n["id"]: copy.deepcopy(n) for n in baseline_nodes if n["id"] not in retired}
    for node in ops["add_nodes"]:
        nodes[node["id"]] = {"id": node["id"], "labels": list(node["labels"]), "properties": _bundle_props(node)}
    for nid, change in ops["set_props"].items():
        props = nodes[nid]["properties"]
        props.update(change["set"])
        for key in change["remove"]:
            props.pop(key, None)
    gone = {(e["start_id"], e["type"], e["end_id"]) for e in ops["retire_edges"]}
    edges = [copy.deepcopy(e) for e in baseline_edges
             if _edge_key(e) not in gone and e["start_id"] not in retired and e["end_id"] not in retired]
    have = {_edge_key(e) for e in edges}
    for e in ops["add_edges"]:
        key = (e["start_id"], e["type"], e["end_id"])
        if key not in have:
            edges.append({**e, "properties": {}})
            have.add(key)
    return [nodes[i] for i in sorted(nodes)], sorted(edges, key=_edge_key)


def verify_candidate(nodes, edges, bundle_nodes, bundle_edges) -> list[str]:
    """Everything the bundle says is in the candidate, and no campaign flow or edge the bundle lacks."""
    problems = []
    cand = {n["id"]: n for n in nodes}
    bundle = {n["id"]: n for n in bundle_nodes}
    flows = {i for i, n in bundle.items() if n["node_type"] == "MoneyFlow"}
    for nid, node in bundle.items():
        if nid not in cand:
            problems.append(f"missing node {nid}")
        elif nid in flows:
            want = _bundle_props(node)
            have = cand[nid]["properties"]
            diff = [k for k in OWNED_FLOW_PROPS if have.get(k) != want.get(k)]
            if diff:
                problems.append(f"{nid} differs on {diff}")
    for nid, node in cand.items():
        if _is_campaign_flow(node) and nid not in flows:
            problems.append(f"campaign flow {nid} is not in the bundle")
    cand_keys = {_edge_key(e) for e in edges}
    bundle_keys = set(_resolve_edges(bundle_edges, _resolver(nodes)))
    problems += [f"missing edge {k}" for k in sorted(bundle_keys - cand_keys)]
    problems += [f"extra campaign edge {k}" for k in sorted(cand_keys - bundle_keys)
                 if k[1] in CF_EDGE_TYPES and ({k[0], k[2]} & flows)]
    return problems


# ---------------------------------------------------------------------------
# The ops as Cypher for ONE explicit transaction (rendered into the plan; nothing here runs it)
# ---------------------------------------------------------------------------

class MigrationError(Exception):
    """An op cannot be expressed safely, or a statement touched a different number of rows than planned."""


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _ident(name: str) -> str:
    if not IDENTIFIER.fullmatch(name):
        raise MigrationError(f"not a safe Cypher identifier: {name!r}")
    return name


def migration_statements(ops: dict) -> list[dict]:
    """Every op as a parameterized statement returning the rows it touched, in dependency order."""
    stmts = []

    def add(step, query, rows):
        if rows:
            stmts.append({"step": step, "query": query + " RETURN count(*) AS n", "params": {"rows": rows}})

    add("retire_edges", "UNWIND $rows AS e MATCH (s {id: e.start_id})-[r]->(t {id: e.end_id}) "
        "WHERE type(r) = e.type DELETE r", ops["retire_edges"])
    add("retire_nodes", "UNWIND $rows AS id MATCH (n:MoneyFlow {id: id}) DETACH DELETE n", ops["retire_nodes"])
    by_labels: dict[tuple, list[dict]] = {}
    for node in ops["add_nodes"]:
        by_labels.setdefault(tuple(_ident(label) for label in node["labels"]), []).append({
            "id": node["id"], "props": {k: v for k, v in node["properties"].items() if k != "payload_json"},
            "display_label": node.get("display_label", ""), "promotion_state": node.get("promotion_state", "")})
    for labels, rows in sorted(by_labels.items()):
        add(f"add_nodes:{':'.join(labels)}",
            f"UNWIND $rows AS row MERGE (n:{labels[0]} {{id: row.id}}) SET n:{':'.join(labels)} "
            "SET n += row.props, n.display_label = row.display_label, n.promotion_state = row.promotion_state", rows)
    add("set_props", "UNWIND $rows AS row MATCH (n:MoneyFlow {id: row.id}) SET n += row.set",
        [{"id": i, "set": c["set"]} for i, c in sorted(ops["set_props"].items()) if c["set"]])
    removals: dict[str, list[str]] = {}
    for nid, change in sorted(ops["set_props"].items()):
        for key in change["remove"]:
            removals.setdefault(_ident(key), []).append(nid)
    for key, ids in sorted(removals.items()):
        add(f"remove_prop:{key}", f"UNWIND $rows AS id MATCH (n:MoneyFlow {{id: id}}) REMOVE n.{key}", ids)
    by_type: dict[str, list[dict]] = {}
    for e in ops["add_edges"]:
        by_type.setdefault(_ident(e["type"]), []).append({"start_id": e["start_id"], "end_id": e["end_id"]})
    for rel, rows in sorted(by_type.items()):
        add(f"add_edges:{rel}", f"UNWIND $rows AS e MATCH (s {{id: e.start_id}}) MATCH (t {{id: e.end_id}}) "
            f"MERGE (s)-[r:{rel}]->(t)", rows)
    return stmts


def apply_in_transaction(tx, ops: dict) -> dict:
    """Run every statement on the caller's single transaction; any count short of plan raises before the next.

    The caller owns the transaction: `with session.begin_transaction() as tx: apply_in_transaction(tx, ops);
    tx.commit()` — an exception leaves it uncommitted, so Neo4j rolls every statement back.
    """
    counts = {}
    for stmt in migration_statements(ops):
        touched = tx.run(stmt["query"], **stmt["params"]).single()["n"]
        if touched != len(stmt["params"]["rows"]):
            raise MigrationError(f"{stmt['step']}: touched {touched} of {len(stmt['params']['rows'])} planned rows")
        counts[stmt["step"]] = touched
    return counts


# ---------------------------------------------------------------------------
# Files, report and CLI
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent


def _read_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))  # export_live_graph's format


def write_export(out_dir: Path, nodes: list[dict], edges: list[dict]) -> dict:
    """Write nodes/edges in export_live_graph's exact format and order; return their sha256."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nodes.jsonl").write_text("".join(_line(n) + "\n" for n in sorted(nodes, key=lambda n: n["id"])))
    (out_dir / "edges.jsonl").write_text("".join(_line(e) + "\n" for e in sorted(edges, key=_edge_key)))
    return _fingerprint(out_dir)


def _fingerprint(export_dir: Path) -> dict:
    return {name: hashlib.sha256((export_dir / name).read_bytes()).hexdigest()
            for name in ("nodes.jsonl", "edges.jsonl")}


def _read_bundle(bundle_dir: Path) -> tuple[list[dict], list[dict], list[Path]]:
    sources = sorted(p for p in bundle_dir.iterdir() if (p / "nodes.jsonl").is_file())
    nodes, edges = [], []
    for source in sources:
        nodes += _read_jsonl(source / "nodes.jsonl")
        edges += _read_jsonl(source / "edges.jsonl")
    return nodes, edges, sources


def _cents(value) -> str:
    from decimal import Decimal
    return str(Decimal(value).quantize(Decimal("0.01")))


def _amounts(nodes: list[dict]) -> dict:
    from decimal import Decimal
    totals: dict[str, Decimal] = {}
    for n in nodes:
        if _is_campaign_flow(n):
            ft = n["properties"]["flow_type"]
            totals[ft] = totals.get(ft, Decimal("0")) + Decimal(str(n["properties"]["amount"]))
    return totals


def _ledger_problems(nodes: list[dict], sources: list[Path]) -> list[str]:
    """Each counted transaction's flow carries its ledger amount; each filing's emitted total is in the graph."""
    from decimal import Decimal
    amount = {n["id"]: Decimal(str(n["properties"]["amount"])) for n in nodes
              if "MoneyFlow" in n["labels"] and n["properties"].get("amount") is not None}
    problems = []
    for source in sources:
        ledger = source / "ledger.jsonl"
        if not ledger.is_file():
            continue
        emitted: dict[tuple[str, str], Decimal] = {}
        for row in _read_jsonl(ledger):
            if row.get("counted") and row.get("primary"):
                key = (row["filing_id"], row["schedule"])
                if amount.get(row["moneyflow_id"]) != Decimal(row["amount"]):
                    problems.append(f"{row['moneyflow_id']}: graph amount {amount.get(row['moneyflow_id'])} "
                                    f"vs ledger {row['amount']}")
                emitted[key] = emitted.get(key, Decimal("0")) + amount.get(row["moneyflow_id"], Decimal("0"))
        recon = json.loads((source / "reconciliation.json").read_text())
        for group in recon["groups"]:
            key = (group["filing_id"], group["schedule"])
            if Decimal(group["bridge"]["emitted"]) != emitted.get(key, Decimal("0")):
                problems.append(f"{key}: graph holds {emitted.get(key, 0)} of an emitted {group['bridge']['emitted']}")
    return problems


LEDGER_FORMATS = (1, 2)  # 1: CF1 bundles (no ledger_format key; no contributor details); 2: raw reported cells


def _ledger_format(source: Path) -> int | None:
    """The source's declared ledger format, or None when there is no manifest or the format is not a known one."""
    manifest = source / "manifest.json"
    if not manifest.is_file():
        return None
    fmt = json.loads(manifest.read_text()).get("ledger_format", 1)
    return fmt if type(fmt) is int and fmt in LEDGER_FORMATS else None


def ledger_checks(nodes: list[dict], sources: list[Path]) -> list[str]:
    """Contributor details in the graph must be exactly what the bundle's ledgers yield; fail closed on format."""
    formats = {source.name: _ledger_format(source) for source in sources}
    unknown = sorted(name for name, fmt in formats.items() if fmt is None)
    if unknown:
        return [f"{name}: no manifest or an unknown ledger format" for name in unknown]
    if set(formats.values()) == {2}:
        return contributor_problems(nodes, sources)
    if set(formats.values()) == {1}:
        return [f"{n['id']}: {k} present, but a format-1 ledger yields no contributor details"
                for n in nodes if "MoneyFlow" in n["labels"] for k in CONTRIBUTOR_PROPS if k in n["properties"]]
    return [f"bundle mixes ledger formats {sorted(set(formats.values()))}"]


def contributor_problems(nodes: list[dict], sources: list[Path], reviewed_path: Path = REVIEWED_PATH) -> list[str]:
    """Every campaign flow's contributor props equal what the ledger's raw cells yield today; fail closed.

    Expected values are recomputed from each source's ledger.jsonl through contributor_detail.py, never read from
    the bundle's nodes, so a bundle that drifted from its own ledger fails too. Missing, wrong and stale fail.
    """
    problems, expected = [], {}
    reviewed_sha = hashlib.sha256(Path(reviewed_path).read_bytes()).hexdigest()
    reviewed = load_reviewed(reviewed_path)
    for source in sources:
        manifest = json.loads((source / "manifest.json").read_text())
        if manifest.get("contributor_review") != reviewed_sha:
            problems.append(f"{source.name}: the bundle was built under other review decisions than {reviewed_path}")
        if not (source / "ledger.jsonl").is_file():
            problems.append(f"{source.name}: no ledger.jsonl to derive contributor details from")
            continue
        members: dict[str, list[dict]] = {}
        for row in _read_jsonl(source / "ledger.jsonl"):
            if row.get("counted") and row.get("schedule") == "A":
                members.setdefault(row["moneyflow_id"], []).append(row)
        for flow_id, rows in members.items():
            expected[flow_id] = flow_props(transaction_details("A", rows, reviewed)[1])
    for node in nodes:
        if "MoneyFlow" not in node["labels"]:
            continue
        want = expected.get(node["id"], {}) if _is_campaign_flow(node) else {}
        have = {k: node["properties"][k] for k in CONTRIBUTOR_PROPS if k in node["properties"]}
        for key in sorted(set(want) | set(have)):
            if key not in have:
                problems.append(f"{node['id']}: {key} missing (ledger: {want[key]!r})")
            elif key not in want:
                problems.append(f"{node['id']}: {key} is stale (the ledger yields none)")
            elif have[key] != want[key]:
                problems.append(f"{node['id']}: {key} is {have[key]!r}, the ledger yields {want[key]!r}")
    return problems


def _contributor_scope_problems(ops: dict) -> list[str]:
    """A contributor-detail migration only sets or removes contributor props on flows that already exist."""
    problems = [f"structural change refused: {len(ops[k])} {k}" for k in
                ("retire_nodes", "add_nodes", "retire_edges", "add_edges") if ops[k]]
    for nid, change in ops["set_props"].items():
        other = sorted((set(change["set"]) | set(change["remove"])) - set(CONTRIBUTOR_PROPS))
        if other:
            problems.append(f"structural change refused: {nid} would change {other}")
    return problems


def check_live(export_dir: Path, bundle_dir: Path) -> list[str]:
    """Post-load check. A format-1 (CF1) bundle is checked as it always was; format 2 adds the ledger-derived
    contributor details."""
    nodes, edges = _read_jsonl(export_dir / "nodes.jsonl"), _read_jsonl(export_dir / "edges.jsonl")
    bundle_nodes, bundle_edges, sources = _read_bundle(bundle_dir)
    return (verify_candidate(nodes, edges, bundle_nodes, bundle_edges) + _ledger_problems(nodes, sources)
            + ledger_checks(nodes, sources))


def _render_plan(report: dict, ops: dict) -> str:
    s = ops["summary"]
    lines = [
        "# Campaign-finance ledger migration plan (NOT EXECUTED — awaits Stuart's approval)", "",
        f"Baseline: `{report['baseline']['dir']}`  ",
        f"Baseline sha256: nodes `{report['baseline']['sha256']['nodes.jsonl']}`, "
        f"edges `{report['baseline']['sha256']['edges.jsonl']}`  ",
        f"Bundle: `{report['bundle']}`  ",
        f"Candidate sha256: nodes `{report['candidate_sha256']['nodes.jsonl']}`, "
        f"edges `{report['candidate_sha256']['edges.jsonl']}`", "",
        "## Changes", "",
        f"- Nodes: {s['retained_nodes']} retained unchanged, {s['changed_nodes']} changed, "
        f"{s['retired_nodes']} retired, added {dict(s['added_nodes'])}",
        f"- Edges: {s['retired_edges']} retired, {s['added_edges']} added",
        f"- Shared actors the bundle references (never rewritten): {len(s['shared_actors_touched'])}",
        f"- Other pipelines' edges on retired flows: {len(s['external_edges_on_retired'])}", "",
        "| flow type | baseline | candidate | delta |", "|---|---|---|---|",
        *[f"| {ft} | {a['baseline']} | {a['candidate']} | {a['delta']} |" for ft, a in report["amounts"].items()],
        "", "### Retired MoneyFlows", "", *([f"- `{i}`" for i in ops["retire_nodes"]] or ["- none"]),
        "", "### Added MoneyFlows", "",
        *([f"- `{n['id']}` {n['properties'].get('amount')}" for n in ops["add_nodes"] if n["node_type"] == "MoneyFlow"]
          or ["- none"]),
        "", "### Changed MoneyFlows", "", *([f"- `{i}`: {c}" for i, c in ops["set_props"].items()] or ["- none"]),
        "", "## Procedure (every step waits for approval of this concrete plan)", "",
        "1. **Preconditions.** No weekly refresh running (`data/ingest-runs/.lock` holder not alive; do it outside "
        "Monday 05:00). Take a fresh read-only export (`scripts/export_live_graph.py --backup --out-dir <new dir>`); "
        "its nodes/edges sha256 must equal the baseline sha256 above. Any drift → stop and re-plan.",
        "2. **Backup.** Keep that fresh export as the JSONL backup. Also stop the openmarin instance "
        "(`launchctl bootout` of cc.eastpeak.neo4j-openmarin) and take `neo4j-admin database dump neo4j` "
        "with the openmarin NEO4J_HOME/NEO4J_CONF, then restart it.",
        "3. **Apply `ops.json` in ONE explicit write transaction** (bolt://localhost:7688 only): "
        "`with session.begin_transaction() as tx: cf_migration_plan.apply_in_transaction(tx, ops); tx.commit()`. "
        "Each statement must touch exactly its planned row count or the transaction is abandoned uncommitted "
        "(rolled back). The statements, in order:",
        *[f"   - `{st['step']}` ({len(st['params']['rows'])} rows): `{st['query']}`"
          for st in migration_statements(ops)],
        "4. **Post-load reconciliation.** Re-export the live graph; its sha256 must equal the candidate sha256 above, "
        "and `scripts/cf_migration_plan.py --check-live <export> --bundle <bundle>` must report nothing: every "
        "counted transaction's flow carries its ledger amount and every filing's emitted total is in the graph.",
        "5. **Rollback** (if step 3 or 4 fails): `scripts/restore_neo4j_local.py` from the step-1 export (wipes and "
        "reloads; confirm node/edge counts and sha256 of a re-export against the baseline), or `neo4j-admin "
        "database load` of the step-2 dump with the instance stopped.",
        "6. Bake and publish through the normal path only after step 4 passes.", "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bundle", type=Path, required=True, help="normalize_campaign_finance.py output root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", type=Path, help="read-only export_live_graph.py --backup directory")
    mode.add_argument("--check-live", type=Path, help="post-load: verify an export against the bundle and ledger")
    parser.add_argument("--out", type=Path, help="empty staging dir for the plan (with --baseline)")
    parser.add_argument("--contributor-detail", action="store_true",
                        help="a props-only plan: refuse any structural change; verify details against the ledger")
    args = parser.parse_args(argv)

    if args.check_live:
        problems = check_live(args.check_live, args.bundle)
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        print(f"check-live: {len(problems)} problem(s)")
        return 1 if problems else 0

    if args.out is None:
        parser.error("--out is required with --baseline")
    try:
        from normalize_campaign_finance import _git_checkouts
        out = resolve_output_root(args.out, *_git_checkouts())
    except UnsafeOutputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    baseline_nodes = _read_jsonl(args.baseline / "nodes.jsonl")
    baseline_edges = _read_jsonl(args.baseline / "edges.jsonl")
    bundle_nodes, bundle_edges, sources = _read_bundle(args.bundle)
    if args.contributor_detail and {_ledger_format(source) for source in sources} != {2}:
        print("ERROR: a contributor-detail plan needs ledger format 2 in every source", file=sys.stderr)
        return 1
    ops = plan_ops(baseline_nodes, baseline_edges, bundle_nodes, bundle_edges)
    cand_nodes, cand_edges = apply_ops(baseline_nodes, baseline_edges, ops)
    problems = verify_candidate(cand_nodes, cand_edges, bundle_nodes, bundle_edges)
    problems += _ledger_problems(cand_nodes, sources) + ledger_checks(cand_nodes, sources)
    if args.contributor_detail:
        problems += _contributor_scope_problems(ops)
    candidate_sha = write_export(out / "candidate", cand_nodes, cand_edges)
    before, after = _amounts(baseline_nodes), _amounts(cand_nodes)
    report = {
        "baseline": {"dir": str(args.baseline.resolve()), "sha256": _fingerprint(args.baseline)},
        "bundle": str(args.bundle.resolve()),
        "candidate_sha256": candidate_sha,
        "summary": ops["summary"],
        "amounts": {ft: {"baseline": _cents(before.get(ft, 0)), "candidate": _cents(after.get(ft, 0)),
                         "delta": _cents(after.get(ft, 0) - before.get(ft, 0))} for ft in CAMPAIGN_FLOW_TYPES},
        "verification": problems,
    }
    if args.contributor_detail:
        report["contributor_detail"] = {
            "flows_changed": len(ops["set_props"]),
            "props_set": dict(sorted(Counter(k for c in ops["set_props"].values() for k in c["set"]).items())),
            "props_removed": dict(sorted(Counter(k for c in ops["set_props"].values() for k in c["remove"]).items())),
        }
    (out / "ops.json").write_text(json.dumps(ops, indent=1, sort_keys=True) + "\n")
    (out / "migration-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "migration-plan.md").write_text(_render_plan(report, ops))
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    print(f"plan: {out}  ({len(problems)} verification problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
