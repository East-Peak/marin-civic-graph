"""Tests for scripts/ingest_990.py — pipeline + idempotence unit (M2b).

`build_nodes_and_edges` assembles the full fixture batch with in-batch dedupe
(EIN-identity org collapse across years); `main` is the parse/build/resolve/
write CLI. Everything writes to tmp_path here — the suite must leave
`git status` untouched. The end-to-end test proves byte-identical output
across two runs (stable ordering, no timestamps).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from canonical_type import canonical_type  # noqa: E402
from ingest_990 import (  # noqa: E402
    build_nodes_and_edges,
    main,
    parse_return_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "990"


def parse_all() -> list[dict]:
    """Every committed fixture through the parser — skips drop out as None."""
    parsed = [parse_return_file(p) for p in sorted(FIXTURES.glob("*.xml"))]
    return [p for p in parsed if p is not None]


# ---------------------------------------------------------------------------
# Assembly — in-batch dedupe + integrity
# ---------------------------------------------------------------------------


def test_org_collapses_across_years():
    nodes, _, _ = build_nodes_and_edges(parse_all())
    org_ids = sorted(n["id"] for n in nodes if n["node_type"] == "Organization")
    # MCF appears in two tax years → ONE org node (EIN is the identity).
    assert org_ids == ["org-990-ein-942689383", "org-990-ein-943007979"]


def test_one_filing_and_record_per_return():
    nodes, _, _ = build_nodes_and_edges(parse_all())
    filing_ids = sorted(n["id"] for n in nodes if n["node_type"] == "Filing")
    record_ids = sorted(n["id"] for n in nodes if n["node_type"] == "Record")
    assert filing_ids == [
        "filing-990-942689383-2022",
        "filing-990-943007979-2022",
        "filing-990-943007979-2023",
    ]
    assert record_ids == [
        "record-990-942689383-2022",
        "record-990-943007979-2022",
        "record-990-943007979-2023",
    ]


def test_filing_edges_wired():
    _, edges, _ = build_nodes_and_edges(parse_all())
    assert {
        "source_id": "filing-990-943007979-2022",
        "target_id": "org-990-ein-943007979",
        "relationship_type": "FILED_BY_ORG",
        "properties": {},
    } in edges
    assert {
        "source_id": "filing-990-943007979-2022",
        "target_id": "record-990-943007979-2022",
        "relationship_type": "EVIDENCED_BY",
        "properties": {},
    } in edges


def test_every_edge_endpoint_is_an_emitted_node():
    # With no existing_orgs there is no SAME_AS — every edge must close over
    # the emitted node set (memberships, persons, filings, records, orgs).
    nodes, edges, _ = build_nodes_and_edges(parse_all())
    node_ids = {n["id"] for n in nodes}
    for edge in edges:
        assert edge["source_id"] in node_ids
        assert edge["target_id"] in node_ids


def test_every_emitted_id_resolves_via_canonical_type():
    nodes, _, _ = build_nodes_and_edges(parse_all())
    for node in nodes:
        assert canonical_type(node["labels"], node["id"]) == node["node_type"]


def test_skipped_returns_leave_no_trace():
    # The 990-EZ fixture (EIN 946077085) is skipped by the parser — nothing
    # in the assembled batch may reference it.
    nodes, edges, candidates = build_nodes_and_edges(parse_all())
    for item in [*nodes, *edges, *candidates]:
        assert "946077085" not in json.dumps(item)


# ---------------------------------------------------------------------------
# Resolver wiring — SAME_AS is an edge, candidates are sidecar-only
# ---------------------------------------------------------------------------


def test_same_as_lands_in_edges_output():
    existing = [
        {
            "id": "org-marin-community-foundation",
            "display_label": "Marin Community Foundation",
            "ein": "94-3007979",
        }
    ]
    _, edges, candidates = build_nodes_and_edges(parse_all(), existing)
    assert {
        "source_id": "org-990-ein-943007979",
        "target_id": "org-marin-community-foundation",
        "relationship_type": "SAME_AS",
        "properties": {"basis": "ein_exact"},
    } in edges
    assert candidates == []


def test_candidates_never_reach_nodes_or_edges():
    existing = [
        {"id": "org-marin-community-foundation", "display_label": "Marin Community Foundation"},
        {"id": "org-county-of-marin", "display_label": "County of Marin"},
    ]
    nodes, edges, candidates = build_nodes_and_edges(parse_all(), existing)
    assert len(candidates) == 1  # MCF exact-name match, queued
    assert all(e["relationship_type"] != "SAME_AS" for e in edges)
    for item in [*nodes, *edges]:
        assert "subject_ref" not in item
        assert "candidate_ref" not in item


def test_resolver_evidence_is_the_union_of_record_ids():
    existing = [
        {"id": "org-marin-community-foundation", "display_label": "Marin Community Foundation"}
    ]
    _, _, candidates = build_nodes_and_edges(parse_all(), existing)
    # The MCF org ref carries BOTH years' records as resolver evidence.
    assert candidates[0]["evidence_record_ids"] == [
        "record-990-943007979-2022",
        "record-990-943007979-2023",
    ]


# ---------------------------------------------------------------------------
# CLI end-to-end — tmp_path only, two runs byte-identical
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
        "candidates": review_dir / "resolution-candidates-990.jsonl",
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
                {"id": "org-county-of-marin", "display_label": "County of Marin"},
                {
                    "id": "org-marin-community-foundation",
                    "display_label": "Marin Community Foundation",
                },
            ]
        ),
        encoding="utf-8",
    )
    first = _run_cli(tmp_path, "run1", existing_path)
    second = _run_cli(tmp_path, "run2", existing_path)
    assert first == second  # byte-identical: stable ordering, no timestamps

    # The review sidecar holds the queued MCF candidate; no graph-envelope keys.
    review = tmp_path / "run1" / "review" / "resolution-candidates-990.jsonl"
    rows = [json.loads(line) for line in review.read_text().splitlines()]
    assert [r["candidate_ref"] for r in rows] == ["org-marin-community-foundation"]
    assert all(r["status"] == "queued" for r in rows)
    assert all("relationship_type" not in r for r in rows)

    # No-ein existing list → ZERO SAME_AS anywhere in the edge output.
    edges_text = (tmp_path / "run1" / "normalized" / "edges.jsonl").read_text()
    assert "SAME_AS" not in edges_text


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
    assert (review_dir / "resolution-candidates-990.jsonl").read_text() == ""
    nodes = [
        json.loads(line)
        for line in (out_dir / "nodes.jsonl").read_text().splitlines()
    ]
    assert sorted(n["id"] for n in nodes if n["node_type"] == "Organization") == [
        "org-990-ein-942689383",
        "org-990-ein-943007979",
    ]
