"""Phase 0 equivalence gate — skeleton (Open Marin Phase 0, A4).

The acceptance gate for the v2-native rebuild. It loads the frozen live-graph
baseline and a rebuilt-graph export, asserts NO legacy labels survive, applies
the count floors, and diffs the two exports with the pure comparator. The ported
query-pack check is intentionally STUBBED until Milestone B3 — this milestone
only wires the gate; it does not change graph-building behavior.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter
from pathlib import Path

from graph_compare import compare_graphs
from export_graph_baseline import assert_live_graph_floors

# The legacy two-headed schema. None of these may survive into the settled graph.
LEGACY_LABELS = frozenset({
    "Actor", "Institution", "EconomicInterestDisclosure", "CaseParticipation"})


def assert_no_legacy_labels(nodes) -> None:
    """Raise AssertionError if any node carries a retired legacy label."""
    for node in nodes:
        for label in node.get("labels", []):
            if label in LEGACY_LABELS:
                raise AssertionError(
                    f"legacy label {label!r} present on node {node.get('id')!r} "
                    f"— the settled schema forbids {sorted(LEGACY_LABELS)}")


def load_baseline_export(path) -> tuple[list, list]:
    """Load a baseline/rebuilt JSONL export into (nodes, rels).

    Each line is a canonical row tagged with ``kind`` ("node" or "rel"), as
    written by export_graph_baseline.export_baseline.
    """
    nodes, rels = [], []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        row = json.loads(raw)
        kind = row.pop("kind", None)
        if kind == "node":
            nodes.append(row)
        elif kind == "rel":
            rels.append(row)
        else:
            raise ValueError(f"unrecognised row kind {kind!r} in {path}")
    return nodes, rels


def _per_label_counts(nodes) -> dict:
    counts: Counter = Counter()
    for node in nodes:
        for label in node.get("labels", []):
            counts[label] += 1
    return dict(counts)


def run_query_pack_stub(nodes, rels) -> dict:
    """Placeholder for the ported v2 query pack — wired in Milestone B3.

    Returns a stub result so the gate's call site exists now; it performs no
    metric checks yet and never fails the gate.
    """
    return {"status": "stubbed", "note": "ported query pack arrives in Milestone B3"}


def verify(baseline_path, rebuilt_path) -> tuple[bool, list]:
    """Run the full gate over a baseline and a rebuilt export. Returns
    (ok, failures) without exiting, so it is unit-testable later."""
    failures: list = []
    base_nodes, base_rels = load_baseline_export(baseline_path)
    new_nodes, new_rels = load_baseline_export(rebuilt_path)

    try:
        assert_no_legacy_labels(new_nodes)
    except AssertionError as exc:
        failures.append(f"legacy labels: {exc}")

    try:
        assert_live_graph_floors(len(new_nodes), len(new_rels),
                                 _per_label_counts(new_nodes))
    except ValueError as exc:
        failures.append(f"count floors: {exc}")

    result = compare_graphs(base_nodes, base_rels, new_nodes, new_rels)
    if not result.equivalent:
        failures.append(f"baseline diff: {len(result.diffs)} difference(s); "
                        f"{result.denied_keys} volatile key(s) ignored")

    run_query_pack_stub(new_nodes, new_rels)  # stubbed until B3
    return (not failures), failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Phase 0 equivalence gate (skeleton)")
    parser.add_argument("--baseline", required=True, help="frozen baseline JSONL")
    parser.add_argument("--rebuilt", required=True, help="rebuilt-graph export JSONL")
    args = parser.parse_args(argv)

    ok, failures = verify(args.baseline, args.rebuilt)
    if ok:
        print("PASS: no legacy labels, floors cleared, baseline equivalent "
              "(query pack stubbed until B3)")
        return 0
    print("FAIL:", file=sys.stderr)
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
