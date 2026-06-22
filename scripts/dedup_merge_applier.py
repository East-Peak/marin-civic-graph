"""dedup_merge_applier.py — the reversible graph-org-dedup merge applier.

Two modes:
  - PURE bundle/edge-rewrite mode (this file's core; the loop tests it against
    in-memory fixtures). A graph is `{"nodes": {id: {id,labels,properties}},
    "edges": {(source,type,target): props}}` (edges keyed by triple, mirroring
    load_neo4j_v2's MERGE-by-(source,type,target) dedup). Merging a component
    repoints every duplicate edge onto the canonical, TOMBSTONES each dup via a
    `dedup_superseded_by` property (the :Organization label is KEPT so node
    identity/uniqueness survives reload — Codex r5), and writes a FULL PREIMAGE
    journal so the merge is reversible.
  - LIVE-Cypher mode (operator-gated, separate unit): generates database-scoped
    Cypher, tested against a fake session, NEVER run by the loop.

Why a full preimage (Codex r2 #5): the loader's `MERGE (s)-[r]->(t) SET r += row.props`
collapses a repointed edge onto a pre-existing canonical edge and overwrites its
props — edge-ids alone cannot undo that, so every op records its before-state
(and, for a collision, the destination's prior props).
"""
from __future__ import annotations

import copy
from typing import Any

# A graph: {"nodes": {id: node}, "edges": {(source, type, target): props}}.
Graph = dict[str, Any]
EdgeKey = tuple[str, str, str]


def _node_preimage(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "labels": list(node.get("labels", [])),
        "properties": copy.deepcopy(node.get("properties", {})),
    }


def apply_component_merge(graph: Graph, component: dict[str, Any]) -> dict[str, Any]:
    """Merge `component` (canonical + dups) into `graph` IN PLACE; return the
    preimage merge-record. Edges repoint onto the canonical (collapsing onto a
    pre-existing canonical edge with `props` last-writer-wins, dropping self-loops);
    each dup is tombstoned with `dedup_superseded_by` (label kept)."""
    canonical = component["canonical"]
    dups = sorted(m for m in component["members"] if m != canonical)

    node_preimages: dict[str, dict[str, Any]] = {
        canonical: _node_preimage(graph["nodes"][canonical])
    }
    for dup in dups:
        node_preimages[dup] = _node_preimage(graph["nodes"][dup])

    edge_ops: list[dict[str, Any]] = []
    for dup in dups:
        for key in [k for k in graph["edges"] if dup in (k[0], k[2])]:
            source, rel, target = key
            old_props = graph["edges"].pop(key)
            new_source = canonical if source == dup else source
            new_target = canonical if target == dup else target

            if new_source == new_target:  # self-loop — drop (record for restore)
                edge_ops.append({
                    "op": "selfloop_drop",
                    "before": [source, rel, target],
                    "before_props": old_props,
                })
                continue

            new_key: EdgeKey = (new_source, rel, new_target)
            if new_key in graph["edges"]:  # collision — loader SET r += repointed props
                dest_prior = copy.deepcopy(graph["edges"][new_key])
                graph["edges"][new_key] = {**graph["edges"][new_key], **old_props}
                edge_ops.append({
                    "op": "collapse",
                    "before": [source, rel, target],
                    "before_props": old_props,
                    "dest": [new_source, rel, new_target],
                    "dest_prior_props": dest_prior,
                })
            else:
                graph["edges"][new_key] = old_props
                edge_ops.append({
                    "op": "repoint",
                    "before": [source, rel, target],
                    "before_props": old_props,
                    "after": [new_source, rel, new_target],
                })

        graph["nodes"][dup]["properties"]["dedup_superseded_by"] = canonical

    return {
        "canonical_id": canonical,
        "superseded_ids": dups,
        "node_preimages": node_preimages,
        "edge_ops": edge_ops,
    }


def rollback_component_merge(graph: Graph, record: dict[str, Any]) -> None:
    """Restore `graph` to its pre-merge state IN PLACE from a merge-record.
    Reverses edge ops in REVERSE order, then restores node labels+properties
    (removing the tombstone) — byte-identical to before, incl. edge collisions."""
    for op in reversed(record["edge_ops"]):
        if op["op"] == "repoint":
            del graph["edges"][tuple(op["after"])]
            graph["edges"][tuple(op["before"])] = op["before_props"]
        elif op["op"] == "collapse":
            graph["edges"][tuple(op["dest"])] = op["dest_prior_props"]
            graph["edges"][tuple(op["before"])] = op["before_props"]
        elif op["op"] == "selfloop_drop":
            graph["edges"][tuple(op["before"])] = op["before_props"]
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown edge op {op['op']!r}")

    for node_id, preimage in record["node_preimages"].items():
        graph["nodes"][node_id]["labels"] = list(preimage["labels"])
        graph["nodes"][node_id]["properties"] = copy.deepcopy(preimage["properties"])


def plan_merges(graph: Graph, assembly_result: dict[str, Any]) -> list[dict[str, Any]]:
    """A zero-mutation plan for each accepted component — computed on a scratch
    copy so the real graph is never touched (the --dry-run report)."""
    plan: list[dict[str, Any]] = []
    for component in assembly_result.get("accepted", []):
        scratch = copy.deepcopy(graph)
        record = apply_component_merge(scratch, component)
        plan.append({
            "canonical_id": record["canonical_id"],
            "superseded_ids": record["superseded_ids"],
            "edge_ops": len(record["edge_ops"]),
        })
    return plan


def apply_accepted(
    graph: Graph, assembly_result: dict[str, Any], *, dry_run: bool = True
) -> dict[str, Any]:
    """Apply ONLY accepted (deterministic/approved) components — refused ones
    (anchor/rejected-pair/key-conflict) and queued/rejected assertions never
    reach the graph (Predeclared 8). `dry_run` defaults True: report the plan
    with ZERO mutation; `dry_run=False` mutates the graph and returns the
    reversible merge-records."""
    if dry_run:
        return {"dry_run": True, "plan": plan_merges(graph, assembly_result)}
    records = [
        apply_component_merge(graph, component)
        for component in assembly_result.get("accepted", [])
    ]
    return {"dry_run": False, "merge_records": records}


# ---------------------------------------------------------------------------
# Live-Cypher mode (Predeclared 6) — OPERATOR-GATED, never run by the loop.
#
# Operator runbook:
#   1. Take a fresh full graph backup FIRST (the live merge mutates the graph;
#      dedup is reversible via the pure-mode preimage journal, but a backup is
#      the belt-and-suspenders restore path).
#   2. Run the candidate pass + assemble accepted components; review.
#   3. DRY-RUN: apply_accepted(graph, assembly) (dry_run defaults True) — inspect
#      the plan; ZERO writes.
#   4. Only then, with explicit intent, call apply_component_merge_live(driver,
#      component, database=<scoped db>, confirm=True) per accepted component.
#      Requires APOC (apoc.merge.relationship) for dynamic relationship types.
#   5. Do NOT blind-reload sources post-merge until a merge-map-aware loader
#      exists (Predeclared 9) — a reload would re-split edges onto the dup id.
#
# No top-level `neo4j` import: the driver is injected; the loop tests Cypher
# GENERATION + database scoping against a fake session, never a real DB.
# ---------------------------------------------------------------------------


def build_merge_cypher(component: dict[str, Any]) -> list[dict[str, Any]]:
    """The database-mutating statements for a component merge (pure — no DB).
    Per dup: repoint outgoing + incoming relationships onto the canonical (APOC
    for dynamic rel types; self-loops to the canonical are skipped), then
    TOMBSTONE the dup with a `dedup_superseded_by` property (the :Organization
    label is KEPT — never removed)."""
    canonical = component["canonical"]
    dups = sorted(m for m in component["members"] if m != canonical)
    statements: list[dict[str, Any]] = []
    for dup in dups:
        params = {"dup": dup, "canonical": canonical}
        statements.append({
            "cypher": (
                "MATCH (canon:Organization {id:$canonical}) "
                "MATCH (d:Organization {id:$dup})-[r]->(o) WHERE o.id <> $canonical "
                "CALL apoc.merge.relationship(canon, type(r), {}, properties(r), o, {}) "
                "YIELD rel DELETE r"
            ),
            "params": params,
        })
        statements.append({
            "cypher": (
                "MATCH (canon:Organization {id:$canonical}) "
                "MATCH (s)-[r]->(d:Organization {id:$dup}) WHERE s.id <> $canonical "
                "CALL apoc.merge.relationship(s, type(r), {}, properties(r), canon, {}) "
                "YIELD rel DELETE r"
            ),
            "params": params,
        })
        statements.append({
            "cypher": (
                "MATCH (d:Organization {id:$dup}) SET d.dedup_superseded_by = $canonical"
            ),
            "params": params,
        })
    return statements


def apply_component_merge_live(
    driver: Any, component: dict[str, Any], *, database: str, confirm: bool = False
) -> None:
    """Execute a component merge against a live graph — OPERATOR-GATED, never
    run by the loop. Requires an explicit `database` (a bare/unscoped session is
    forbidden — it could hit the default/live DB) and `confirm=True` (the
    operator gate). Runs the generated Cypher through a database-scoped session."""
    if not database:
        raise ValueError(
            "live merge requires an explicit database= (a bare session could hit "
            "the default/live DB)"
        )
    if not confirm:
        raise ValueError(
            "live merge is operator-gated: pass confirm=True after a backup + dry-run"
        )
    with driver.session(database=database) as session:
        for statement in build_merge_cypher(component):
            session.run(statement["cypher"], **statement["params"])


def canonical_graph(graph: Graph) -> dict[str, Any]:
    """A comparable, order-normalized view of a graph (for byte-identity asserts)."""
    return {
        "nodes": {
            nid: {
                "labels": list(node.get("labels", [])),
                "properties": copy.deepcopy(node.get("properties", {})),
            }
            for nid, node in sorted(graph["nodes"].items())
        },
        "edges": sorted(
            ([k[0], k[1], k[2], v] for k, v in graph["edges"].items()),
            key=lambda e: (e[0], e[1], e[2]),
        ),
    }
