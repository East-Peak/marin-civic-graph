"""M0 — the projection helpers live in scripts/projection_helpers.py.

build_graph_v2 is the projector; its projection phases reuse a shared helper
library. M0 extracts that library out of the retired build_graph_projection.py
and DELETES the legacy file. This test pins the result: the legacy file is gone,
and projection_helpers exposes the full moved surface so no helper (or constant)
can be silently dropped during the extraction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# The full constants + helper surface moved out of build_graph_projection.py.
# build_graph_v2 imports from this set; dropping any name would break the
# projector or its parity, so each must remain importable.
EXPECTED_SURFACE = (
    # constants
    "EXPLICIT_RELATION_TYPES",
    "COMMON_REFERENCE_FIELDS",
    # helpers
    "utc_now_iso",
    "relpath_for_report",
    "should_include_object",
    "infer_relationship_type",
    "build_node_envelope",
    "build_edge_envelope",
    "extract_edges_from_evidence",
    "extract_vote_edges",
    "extract_edges_from_object",
    "passthrough_relationships",
    "merge_node",
    "merge_edge",
    "finalize_node_for_output",
    "finalize_edge_for_output",
    "build_actor_alias_map",
    "remap_actor_aliases",
)


def test_legacy_build_graph_projection_file_is_deleted():
    legacy = Path(__file__).resolve().parent.parent / "scripts" / "build_graph_projection.py"
    assert not legacy.exists(), (
        f"{legacy} must be deleted — its helpers moved to projection_helpers.py"
    )


def test_projection_helpers_exposes_full_surface():
    import projection_helpers

    for name in EXPECTED_SURFACE:
        assert hasattr(projection_helpers, name), f"projection_helpers missing {name}"
