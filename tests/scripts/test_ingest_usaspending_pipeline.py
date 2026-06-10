"""Tests for scripts/ingest_usaspending.py — pipeline + CLI unit (M2c).

`build_nodes_and_edges` assembles the full fixture batch (dedupe → sort by
award id → builders → resolver wiring); `main` is the parse/build/resolve/
write CLI mirroring ingest_990 (NO fetching, NO database unless the operator
passes --load). Everything writes to tmp_path here — the suite must leave
`git status` untouched. The end-to-end test proves byte-identical output
across two runs (stable ordering, no timestamps) and re-proves the ethics
floor at the artifact level: the CLI input dir includes the real
direct-payments page whose 5 aggregate rows must leave NO trace in any
output file.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from canonical_type import canonical_type  # noqa: E402
from ingest_usaspending import (  # noqa: E402
    build_nodes_and_edges,
    main,
    parse_awards_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usaspending"
GRANTS_P1 = FIXTURES / "spending-by-award-grants-p1.json"
GRANTS_P2 = FIXTURES / "spending-by-award-grants-p2.json"

CAM_UEI = "JZ9FLAVMPEB9"
CAM_RID = "cf3072ee-ffc8-260e-4fc3-57dc5b893427-C"


def all_grant_awards() -> list[dict]:
    return parse_awards_file(GRANTS_P1) + parse_awards_file(GRANTS_P2)


# ---------------------------------------------------------------------------
# Assembly — counts, closure, registry conformance, determinism
# ---------------------------------------------------------------------------


def test_assembly_counts():
    nodes, edges, candidates = build_nodes_and_edges(all_grant_awards())
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node["node_type"]] = counts.get(node["node_type"], 0) + 1
    # 9 recipients + 4 agencies; one MoneyFlow + Record per award.
    assert counts == {"Organization": 13, "MoneyFlow": 20, "Record": 20}
    assert len(edges) == 60  # three edges per award, no existing orgs
    assert candidates == []


def test_every_edge_endpoint_is_an_emitted_node():
    # With no existing_orgs there is no SAME_AS — every edge must close over
    # the emitted node set.
    nodes, edges, _ = build_nodes_and_edges(all_grant_awards())
    node_ids = {n["id"] for n in nodes}
    for edge in edges:
        assert edge["source_id"] in node_ids
        assert edge["target_id"] in node_ids


def test_every_emitted_id_resolves_via_canonical_type():
    nodes, _, _ = build_nodes_and_edges(all_grant_awards())
    for node in nodes:
        assert canonical_type(node["labels"], node["id"]) == node["node_type"]


def test_assembly_is_order_independent():
    # The batch sorts by award id internally — feeding the same real rows in
    # reverse order must produce the identical batch (byte-identical runs).
    awards = all_grant_awards()
    assert build_nodes_and_edges(list(reversed(awards))) == build_nodes_and_edges(
        awards
    )


# ---------------------------------------------------------------------------
# Resolver wiring in the batch — SAME_AS is an edge, candidates sidecar-only
# ---------------------------------------------------------------------------


def test_same_as_lands_in_edges_output():
    cam_awards = [a for a in all_grant_awards() if a["recipient_id"] == CAM_RID]
    existing = [
        {
            "id": "org-existing-cam",
            "display_label": "Community Action Marin",
            "uei": CAM_UEI.lower(),
        }
    ]
    _, edges, candidates = build_nodes_and_edges(cam_awards, existing)
    assert {
        "source_id": f"org-usasp-uei-{CAM_UEI}",
        "target_id": "org-existing-cam",
        "relationship_type": "SAME_AS",
        "properties": {"basis": "uei_exact"},
    } in edges
    assert candidates == []


def test_candidates_never_reach_nodes_or_edges():
    # Real-shaped no-key existing list → ZERO SAME_AS; the single CAM
    # exact-name candidate stays in the sidecar return, never in the graph.
    existing = [
        {"id": "org-existing-cam", "display_label": "Community Action Marin"},
        {"id": "org-existing-county", "display_label": "County of Marin"},
    ]
    nodes, edges, candidates = build_nodes_and_edges(all_grant_awards(), existing)
    assert [c["candidate_ref"] for c in candidates] == ["org-existing-cam"]
    assert all(e["relationship_type"] != "SAME_AS" for e in edges)
    for item in [*nodes, *edges]:
        assert "subject_ref" not in item
        assert "candidate_ref" not in item


# ---------------------------------------------------------------------------
# CLI end-to-end — tmp_path only, two runs byte-identical, no PII trace
# ---------------------------------------------------------------------------


def _run_cli(tmp_path: Path, run_name: str, existing_path: Path) -> dict[str, str]:
    out_dir = tmp_path / run_name / "normalized"
    review_dir = tmp_path / run_name / "review"
    main(
        [
            "--input-dir", str(FIXTURES),
            "--output-dir", str(out_dir),
            "--review-dir", str(review_dir),
            "--existing-orgs", str(existing_path),
        ]
    )
    files = {
        "nodes": out_dir / "nodes.jsonl",
        "edges": out_dir / "edges.jsonl",
        "candidates": review_dir / "resolution-candidates-usaspending.jsonl",
    }
    for path in files.values():
        assert path.exists(), f"missing pipeline output: {path}"
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in files.items()
    }


def test_cli_end_to_end_two_runs_byte_identical(tmp_path: Path):
    existing_path = tmp_path / "existing-orgs.json"
    existing_path.write_text(
        json.dumps(
            [
                {"id": "org-existing-cam", "display_label": "Community Action Marin"},
                {"id": "org-existing-county", "display_label": "County of Marin"},
            ]
        ),
        encoding="utf-8",
    )
    first = _run_cli(tmp_path, "run1", existing_path)
    second = _run_cli(tmp_path, "run2", existing_path)
    assert first == second  # byte-identical: stable ordering, no timestamps

    # The review sidecar holds the queued CAM candidate; no graph-envelope keys.
    review = tmp_path / "run1" / "review" / "resolution-candidates-usaspending.jsonl"
    rows = [json.loads(line) for line in review.read_text().splitlines()]
    assert [r["candidate_ref"] for r in rows] == ["org-existing-cam"]
    assert all(r["status"] == "queued" for r in rows)
    assert all("relationship_type" not in r for r in rows)

    # No-key existing list → ZERO SAME_AS anywhere in the edge output.
    edges_text = (tmp_path / "run1" / "normalized" / "edges.jsonl").read_text()
    assert "SAME_AS" not in edges_text

    # Ethics floor at the artifact level: the input dir includes the real
    # direct-payments page (5 aggregate rows) — no trace in ANY output file.
    for name in ("nodes", "edges"):
        text = (tmp_path / "run1" / "normalized" / f"{name}.jsonl").read_text()
        assert "ASST_AGG_" not in text
        assert "MULTIPLE RECIPIENTS" not in text
    assert "ASST_AGG_" not in review.read_text()
    assert "MULTIPLE RECIPIENTS" not in review.read_text()


def test_cli_without_existing_orgs_writes_empty_review(tmp_path: Path):
    out_dir = tmp_path / "normalized"
    review_dir = tmp_path / "review"
    main(
        [
            "--input-dir", str(FIXTURES),
            "--output-dir", str(out_dir),
            "--review-dir", str(review_dir),
        ]
    )
    assert (
        review_dir / "resolution-candidates-usaspending.jsonl"
    ).read_text() == ""
    nodes = [
        json.loads(line)
        for line in (out_dir / "nodes.jsonl").read_text().splitlines()
    ]
    org_ids = sorted(n["id"] for n in nodes if n["node_type"] == "Organization")
    assert len(org_ids) == 13  # 9 recipients + 4 agencies
    assert f"org-usasp-uei-{CAM_UEI}" in org_ids
    assert "org-usasp-agency-department-of-the-treasury" in org_ids
