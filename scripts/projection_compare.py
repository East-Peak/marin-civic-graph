"""projection_compare.py — a full-field-set, multiset comparator for graph
PROJECTIONS (JSONL node/edge dicts), used to prove build_graph_v2 reproduces the
current pipeline's migrated output exactly.

This is deliberately NOT graph_compare.compare_graphs: that comparator targets
Neo4j DB exports (keys `source`/`target`/`type`) and KeyErrors on projection
edges (`source_id`/`relationship_type`), and it strips projection metadata.
Here every field is compared and nothing is silently ignored:

  nodes: the full dict, with `labels` compared order-insensitively
  edges: the full dict exactly — including `id`, `source_bundle_ids`,
         `source_fields`, and `properties` (the 9 generated PARTY_TO edges carry
         ids + provenance that must match)

Records are canonicalised (nested dict keys sorted; node labels sorted) and
compared as MULTISETS, so order and duplicate counts are accounted for.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts."""
    rows: list[dict] = []
    with Path(path).open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _canon_node(node: dict[str, Any]) -> str:
    d = dict(node)
    labels = d.get("labels")
    if isinstance(labels, list):
        d["labels"] = sorted(labels)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def _canon_edge(edge: dict[str, Any]) -> str:
    return json.dumps(edge, sort_keys=True, ensure_ascii=False)


def _multiset_diff(golden: list[str], candidate: list[str]) -> tuple[list[str], list[str]]:
    """Return (surplus_in_golden, surplus_in_candidate) as flat lists,
    accounting for duplicate counts."""
    gc, cc = Counter(golden), Counter(candidate)
    only_g = list((gc - cc).elements())
    only_c = list((cc - gc).elements())
    return only_g, only_c


@dataclass
class ProjectionDiff:
    node_only_in_golden: list[str] = field(default_factory=list)
    node_only_in_candidate: list[str] = field(default_factory=list)
    edge_only_in_golden: list[str] = field(default_factory=list)
    edge_only_in_candidate: list[str] = field(default_factory=list)

    @property
    def equivalent(self) -> bool:
        return not (
            self.node_only_in_golden
            or self.node_only_in_candidate
            or self.edge_only_in_golden
            or self.edge_only_in_candidate
        )

    @property
    def summary(self) -> str:
        if self.equivalent:
            return "EQUIVALENT — zero node diffs, zero edge diffs"
        return (
            "DIFFERENT — "
            f"nodes: {len(self.node_only_in_golden)} only-in-golden, "
            f"{len(self.node_only_in_candidate)} only-in-candidate; "
            f"edges: {len(self.edge_only_in_golden)} only-in-golden, "
            f"{len(self.edge_only_in_candidate)} only-in-candidate"
        )

    def sample(self, n: int = 5) -> str:
        """A few example diffs, for diagnostics."""
        lines: list[str] = []
        for label, items in (
            ("node only-in-golden", self.node_only_in_golden),
            ("node only-in-candidate", self.node_only_in_candidate),
            ("edge only-in-golden", self.edge_only_in_golden),
            ("edge only-in-candidate", self.edge_only_in_candidate),
        ):
            for item in items[:n]:
                lines.append(f"  [{label}] {item}")
        return "\n".join(lines)


def projection_digest(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """A canonical, order-insensitive sha256 digest of a projection.

    Each row is hashed as sorted-key JSON (node `labels` sorted too), and the
    rows themselves are sorted before hashing. So two projections that
    compare_projection deems equivalent (same field-for-field multiset,
    regardless of row order, key order, or label order) yield the SAME digest.

    This is deliberately NOT a raw-file-bytes hash: the legacy golden and a v2
    candidate can carry identical canonical content while differing in byte
    layout (key ordering, label ordering), and a raw-bytes hash would false-fail
    on that. Returns counts plus separate node/edge hashes for diagnostics.
    """
    node_rows = sorted(_canon_node(node) for node in nodes)
    edge_rows = sorted(_canon_edge(edge) for edge in edges)
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes_sha256": hashlib.sha256("\n".join(node_rows).encode("utf-8")).hexdigest(),
        "edges_sha256": hashlib.sha256("\n".join(edge_rows).encode("utf-8")).hexdigest(),
    }


def compare_projection(
    golden_nodes: list[dict],
    golden_edges: list[dict],
    candidate_nodes: list[dict],
    candidate_edges: list[dict],
) -> ProjectionDiff:
    """Compare two projections (node + edge dict lists) as field-for-field
    multisets. Returns a ProjectionDiff; `.equivalent` is True iff identical."""
    n_g, n_c = _multiset_diff(
        [_canon_node(n) for n in golden_nodes],
        [_canon_node(n) for n in candidate_nodes],
    )
    e_g, e_c = _multiset_diff(
        [_canon_edge(e) for e in golden_edges],
        [_canon_edge(e) for e in candidate_edges],
    )
    return ProjectionDiff(
        node_only_in_golden=n_g,
        node_only_in_candidate=n_c,
        edge_only_in_golden=e_g,
        edge_only_in_candidate=e_c,
    )
