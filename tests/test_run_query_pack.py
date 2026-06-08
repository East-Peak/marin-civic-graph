"""C3 — run_graph_query_pack ported to the settled v2 schema.

The breadth-sprint pack now runs over build_graph_v2's Person/Organization
projection (NOT the retired graph-v1 Actor/Institution output). `run_query_pack`
is the importable entrypoint: it REQUIRES an explicit projection_dir (no graph-v1
default), reads projection identity from migration-report.json (not the retired
v1 report.json, with a graceful fallback), and ports IDs/edges via
edge_vocabulary. Q4's noisy-actor guard is recast off the now-gone
node_type=="Actor" onto settled Person/Organization ids that originate in the
noisy form460-schedules bundle.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_graph_query_pack import (
    noisy_campaign_actor_ids,
    read_projection_metadata,
    run_query_pack,
)

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / "data" / "projected" / "phase0-bcore" / "candidate-v2"

FORM460_BUNDLE = "san-rafael-city-campaign-form460-schedules-01__bundle-01"


# --- contract: v2-only, explicit projection_dir required --------------------

def test_run_query_pack_rejects_missing_projection_dir():
    with pytest.raises(ValueError):
        run_query_pack(None, schema="v2")


def test_run_query_pack_rejects_non_v2_schema(tmp_path):
    with pytest.raises(ValueError):
        run_query_pack(tmp_path, schema="v1")


# --- migration-report.json metadata, with graceful fallback -----------------

def test_read_projection_metadata_reads_migration_report(tmp_path):
    (tmp_path / "migration-report.json").write_text(json.dumps({
        "projection_id": "graph-v2-native",
        "generated_at": "2026-06-08T00:00:00Z",
        "nodes_by_type": {"Person": 3},
    }))
    meta = read_projection_metadata(tmp_path)
    assert meta["projection_id"] == "graph-v2-native"
    assert meta["generated_at"] == "2026-06-08T00:00:00Z"


def test_read_projection_metadata_falls_back_when_keys_absent(tmp_path):
    # A migration-report predating the projection_id/generated_at fields must not
    # crash the pack — it falls back instead.
    (tmp_path / "migration-report.json").write_text(json.dumps({"remap_count": 86}))
    meta = read_projection_metadata(tmp_path)
    assert meta["projection_id"]   # non-empty fallback
    assert meta["generated_at"]    # non-empty fallback


# --- Q4 noisy-actor recast (hermetic) ---------------------------------------

def test_noisy_campaign_actor_ids_recasts_off_actor_node_type():
    nodes = [
        {"id": "person-noise", "node_type": "Person", "source_bundle_ids": [FORM460_BUNDLE]},
        {"id": "org-noise", "node_type": "Organization", "source_bundle_ids": [FORM460_BUNDLE]},
        {"id": "person-clean", "node_type": "Person", "source_bundle_ids": ["other-bundle"]},
        {"id": "filing-x", "node_type": "Filing", "source_bundle_ids": [FORM460_BUNDLE]},
    ]
    noisy = noisy_campaign_actor_ids(nodes)
    # Recast keys on settled Person/Organization + bundle origin, NOT node_type.
    assert noisy == ["org-noise", "person-noise"]
    assert "person-clean" not in noisy   # different bundle
    assert "filing-x" not in noisy       # not a settled actor type


# --- build_graph_views import smoke (refactor must not break view exports) ---

def test_build_graph_views_import_smoke():
    import build_graph_views
    for name in ("build_indexes", "edge_sources", "edge_targets",
                 "meeting_for_decision", "node_title", "node_year"):
        assert hasattr(build_graph_views, name), f"build_graph_views lost {name}"


# --- full pack over the v2 candidate (skipped without the projection) -------

@pytest.mark.skipif(not (CANDIDATE / "nodes.jsonl").exists(),
                    reason="needs build_graph_v2 output at candidate-v2/")
def test_run_query_pack_over_candidate_v2():
    result = run_query_pack(CANDIDATE, schema="v2")
    assert isinstance(result["ok"], bool)
    assert isinstance(result["failures"], list)
    metrics = result["metrics"]
    for qid in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        assert qid in metrics
    # Sensible, settled-schema metrics over the v2 candidate:
    assert metrics["Q3"]["decision_count"] > 100             # council timeline materialized
    assert metrics["Q1"]["filing_count"] >= 1                # Kate Colin dossier resolves
    assert metrics["Q4"]["imported_noisy_actor_count"] == 0  # recast: no noisy settled actors
    assert metrics["Q5"]["validation_check_count"] >= 1
    # Identity comes from migration-report.json, not the retired v1 report.json:
    assert result["projection_id"] == "graph-v2-native"
