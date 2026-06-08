"""Pure graph comparator with a FIXED volatile denylist (Open Marin Phase 0, A3).

Diffs two canonical-fact graph exports (nodes + rels). Nodes are keyed by ``id``
and compared on labels + props; relationships are compared as an ORDER-INSENSITIVE
MULTISET of canonical records — Neo4j's export order isn't stable, so an
order-sensitive index would raise false diffs, and a plain set would miss a
duplicated/dropped edge. A small fixed denylist of volatile props is stripped
before comparison so timestamps/run-ids never cause a spurious mismatch.
"""
from __future__ import annotations
import json
from collections import Counter
from dataclasses import dataclass, field

# Small, FIXED denylist — no per-run expansion. These are write-time bookkeeping
# props that legitimately differ between two equivalent rebuilds.
VOLATILE_PROPS = frozenset({"ingested_at", "captured_at", "run_id", "_loaded_at"})


@dataclass
class CompareResult:
    equivalent: bool
    diffs: list = field(default_factory=list)
    denied_keys: int = 0


def _strip_volatile(props: dict) -> dict:
    return {k: v for k, v in props.items() if k not in VOLATILE_PROPS}


def _canon_node(n: dict) -> dict:
    return {"id": n["id"], "labels": sorted(n.get("labels", [])),
            "props": dict(sorted(_strip_volatile(n.get("props", {})).items()))}


def _canon_rel(r: dict) -> dict:
    return {"source": r["source"], "target": r["target"], "type": r["type"],
            "props": dict(sorted(_strip_volatile(r.get("props", {})).items()))}


def _rel_key(r: dict) -> str:
    # Stable, hashable multiset key (handles nested list/dict prop values).
    return json.dumps(_canon_rel(r), sort_keys=True, ensure_ascii=False)


def _count_denied(items) -> int:
    return sum(1 for it in items for k in it.get("props", {}) if k in VOLATILE_PROPS)


def compare_graphs(base_nodes, base_rels, new_nodes, new_rels) -> CompareResult:
    """Compare two graph exports. Returns a CompareResult with ``equivalent``,
    a list of ``diffs`` (added/removed/changed nodes; added/removed rels), and a
    ``denied_keys`` count of volatile props ignored (so the gate can log them).
    """
    diffs: list = []

    base_by_id = {n["id"]: _canon_node(n) for n in base_nodes}
    new_by_id = {n["id"]: _canon_node(n) for n in new_nodes}
    for nid in base_by_id.keys() - new_by_id.keys():
        diffs.append({"kind": "node_removed", "id": nid})
    for nid in new_by_id.keys() - base_by_id.keys():
        diffs.append({"kind": "node_added", "id": nid})
    for nid in base_by_id.keys() & new_by_id.keys():
        if base_by_id[nid] != new_by_id[nid]:
            diffs.append({"kind": "node_changed", "id": nid,
                          "base": base_by_id[nid], "new": new_by_id[nid]})

    base_rel_counts = Counter(_rel_key(r) for r in base_rels)
    new_rel_counts = Counter(_rel_key(r) for r in new_rels)
    for key, n in (base_rel_counts - new_rel_counts).items():
        diffs.append({"kind": "rel_removed", "rel": json.loads(key), "count": n})
    for key, n in (new_rel_counts - base_rel_counts).items():
        diffs.append({"kind": "rel_added", "rel": json.loads(key), "count": n})

    denied = (_count_denied(base_nodes) + _count_denied(new_nodes)
              + _count_denied(base_rels) + _count_denied(new_rels))
    return CompareResult(equivalent=not diffs, diffs=diffs, denied_keys=denied)
