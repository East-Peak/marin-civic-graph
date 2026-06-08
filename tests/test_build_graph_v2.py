"""B3 — build_graph_v2.py: single-pass v2-native projector, golden-pinned.

build_graph_v2 collapses build_graph_projection (Actor/Institution) and
migrate_graph_v2 (→ Person/Organization) into one pass that reads
import-manifest.yaml and emits settled-schema nodes/edges directly. It must be
behavior-preserving: byte-for-byte (field-level) identical to running the two
stages, proven by the projection comparator.

Two pins:
 1. Hermetic — on a committed mini-manifest, build_graph_v2 output equals
    (build_graph_projection -> migrate_graph_v2) output. Always runs.
 2. Full-scale — on registry/import-manifest.yaml, zero diffs vs the captured
    golden, no legacy labels, and report counts (remap 86, dropped nodes 9,
    dropped edges 31, conversions 9). Skipped when the private data / golden
    are absent.

TDD: written before scripts/build_graph_v2.py exists.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_graph_v2
from migrate_graph_v2 import run_migration
from projection_compare import compare_projection, load_jsonl
from verify_phase0_consolidation import assert_no_legacy_labels

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "phase0"
WORK = ROOT / "data" / "projected" / "_pytest_bgv2"
GOLDEN = ROOT / "data" / "projected" / "phase0-bcore" / "golden-current"
DATA = ROOT / "data" / "normalized"


@pytest.fixture
def work_dir():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    yield WORK
    shutil.rmtree(WORK, ignore_errors=True)


def _run_legacy_pipeline(manifest: Path, work: Path) -> Path:
    """Run the CURRENT two-stage pipeline; return the migrated-output dir."""
    v1 = work / "v1"
    subprocess.run(
        [sys.executable, "scripts/build_graph_projection.py",
         "--manifest", str(manifest), "--output-dir", str(v1)],
        check=True, cwd=ROOT,
    )
    golden = work / "v2-golden"
    golden.mkdir(parents=True, exist_ok=True)
    run_migration(v1 / "nodes.jsonl", v1 / "edges.jsonl", golden)
    return golden


def test_build_graph_v2_matches_pipeline_on_mini(work_dir):
    manifest = FIXTURES / "mini-manifest.json"
    golden = _run_legacy_pipeline(manifest, work_dir)

    candidate = work_dir / "v2-candidate"
    build_graph_v2.run(manifest, candidate)

    diff = compare_projection(
        load_jsonl(golden / "nodes.jsonl"), load_jsonl(golden / "edges.jsonl"),
        load_jsonl(candidate / "nodes.jsonl"), load_jsonl(candidate / "edges.jsonl"),
    )
    assert diff.equivalent, diff.summary + "\n" + diff.sample()


def test_build_graph_v2_mini_emits_no_legacy_labels(work_dir):
    manifest = FIXTURES / "mini-manifest.json"
    candidate = work_dir / "v2-candidate"
    build_graph_v2.run(manifest, candidate)
    assert_no_legacy_labels(load_jsonl(candidate / "nodes.jsonl"))


def test_build_graph_v2_mini_report_shape(work_dir):
    manifest = FIXTURES / "mini-manifest.json"
    candidate = work_dir / "v2-candidate"
    report = build_graph_v2.run(manifest, candidate)
    # The migration-style report exposes the parity-diagnostic counts.
    for key in ("remap_count", "dropped_node_count", "dropped_edge_count",
                "conversion_count", "migrated_node_count", "migrated_edge_count"):
        assert key in report, f"report missing {key}"
    # Mini bundle: 2 CaseParticipations dropped + 2 PARTY_TO conversions.
    assert report["dropped_node_count"] == 2
    assert report["conversion_count"] == 2


@pytest.mark.skipif(
    not (GOLDEN / "nodes.jsonl").exists() or not DATA.exists(),
    reason="needs the private normalized data + captured golden-current/",
)
def test_build_graph_v2_full_parity_vs_golden():
    manifest = ROOT / "registry" / "import-manifest.yaml"
    candidate = ROOT / "data" / "projected" / "phase0-bcore" / "candidate-v2"
    report = build_graph_v2.run(manifest, candidate)

    diff = compare_projection(
        load_jsonl(GOLDEN / "nodes.jsonl"), load_jsonl(GOLDEN / "edges.jsonl"),
        load_jsonl(candidate / "nodes.jsonl"), load_jsonl(candidate / "edges.jsonl"),
    )
    assert diff.equivalent, diff.summary + "\n" + diff.sample()

    assert report["remap_count"] == 86
    assert report["dropped_node_count"] == 9
    assert report["dropped_edge_count"] == 31
    assert report["conversion_count"] == 9
    assert_no_legacy_labels(load_jsonl(candidate / "nodes.jsonl"))
