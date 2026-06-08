"""C1 — build_graph_v2.py parity is pinned by a COMMITTED canonical golden.

build_graph_v2 is the canonical v2-native projector: it reads
import-manifest.yaml and emits settled-schema Person/Organization nodes/edges in
a single pass. Its regression gate is now a COMMITTED canonical-sha256 reference
captured from the current pipeline (while migrate_graph_v2 still existed), NOT a
live legacy regeneration. The reference hashes each row as sorted-key JSON (see
projection_compare.projection_digest) — robust to byte-layout differences that a
raw-file hash would false-fail on.

Two pins:
 1. Mini (hermetic, always runs): on the committed mini-manifest, build_graph_v2's
    canonical digest + counts == tests/fixtures/phase0/golden-mini.sha256.
 2. Full-scale (skipped without the private normalized data): on
    registry/import-manifest.yaml, build_graph_v2's canonical digest + counts ==
    tests/fixtures/phase0/golden-current.sha256, no legacy labels survive, and the
    migration report's parity counts hold.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_graph_v2
from projection_compare import load_jsonl, projection_digest
from verify_phase0_consolidation import assert_no_legacy_labels

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "phase0"
WORK = ROOT / "data" / "projected" / "_pytest_bgv2"
DATA = ROOT / "data" / "normalized"
MANIFEST = ROOT / "registry" / "import-manifest.yaml"
CANDIDATE = ROOT / "data" / "projected" / "phase0-bcore" / "candidate-v2"
REF_FULL = FIXTURES / "golden-current.sha256"
REF_MINI = FIXTURES / "golden-mini.sha256"


@pytest.fixture
def work_dir():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    yield WORK
    shutil.rmtree(WORK, ignore_errors=True)


def _assert_digest_matches_reference(candidate_dir: Path, reference_path: Path) -> None:
    """build_graph_v2's canonical digest over candidate_dir == committed reference."""
    reference = json.loads(reference_path.read_text())
    digest = projection_digest(
        load_jsonl(candidate_dir / "nodes.jsonl"),
        load_jsonl(candidate_dir / "edges.jsonl"),
    )
    for key in ("node_count", "edge_count", "nodes_sha256", "edges_sha256"):
        assert digest[key] == reference[key], (
            f"{reference_path.name}: {key} mismatch "
            f"(candidate={digest[key]!r} reference={reference[key]!r})"
        )


def test_build_graph_v2_mini_matches_committed_golden(work_dir):
    candidate = work_dir / "v2-candidate"
    build_graph_v2.run(FIXTURES / "mini-manifest.json", candidate)
    _assert_digest_matches_reference(candidate, REF_MINI)


def test_build_graph_v2_mini_emits_no_legacy_labels(work_dir):
    candidate = work_dir / "v2-candidate"
    build_graph_v2.run(FIXTURES / "mini-manifest.json", candidate)
    assert_no_legacy_labels(load_jsonl(candidate / "nodes.jsonl"))


def test_build_graph_v2_report_emits_projection_metadata(work_dir):
    # The query pack reads projection identity from migration-report.json, so the
    # v2 report must carry projection_id + generated_at (C3 dependency).
    candidate = work_dir / "v2-candidate"
    report = build_graph_v2.run(FIXTURES / "mini-manifest.json", candidate)
    assert report.get("projection_id"), "report must carry a projection_id"
    assert report.get("generated_at"), "report must carry generated_at"
    persisted = json.loads((candidate / "migration-report.json").read_text())
    assert persisted["projection_id"] == report["projection_id"]
    assert persisted["generated_at"] == report["generated_at"]


def test_build_graph_v2_mini_report_shape(work_dir):
    candidate = work_dir / "v2-candidate"
    report = build_graph_v2.run(FIXTURES / "mini-manifest.json", candidate)
    # The migration-style report exposes the parity-diagnostic counts.
    for key in ("remap_count", "dropped_node_count", "dropped_edge_count",
                "conversion_count", "migrated_node_count", "migrated_edge_count"):
        assert key in report, f"report missing {key}"
    # Mini bundle: 2 CaseParticipations dropped + 2 PARTY_TO conversions.
    assert report["dropped_node_count"] == 2
    assert report["conversion_count"] == 2


@pytest.mark.skipif(
    not DATA.exists(),
    reason="needs the private normalized data to regenerate the candidate projection",
)
def test_build_graph_v2_full_parity_vs_committed_golden():
    report = build_graph_v2.run(MANIFEST, CANDIDATE)
    _assert_digest_matches_reference(CANDIDATE, REF_FULL)
    assert_no_legacy_labels(load_jsonl(CANDIDATE / "nodes.jsonl"))
    # Migration parity counts (defence-in-depth alongside the canonical digest).
    assert report["remap_count"] == 86
    assert report["dropped_node_count"] == 9
    assert report["dropped_edge_count"] == 31
    assert report["conversion_count"] == 9
