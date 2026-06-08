"""C4 — build_graph_projection's projector CLI is retired; helpers stay reusable.

build_graph_v2 is the projector. build_graph_projection is now a reused-internal
helper library only: its projection helpers are still imported by build_graph_v2,
but its legacy Actor/Institution-emitting main()/CLI must refuse to run and point
callers at build_graph_v2.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_graph_projection


def test_legacy_projector_main_is_retired_and_points_to_build_graph_v2():
    with pytest.raises(SystemExit) as excinfo:
        build_graph_projection.main()
    assert "build_graph_v2" in str(excinfo.value)


def test_reused_projection_helpers_remain_importable():
    # build_graph_v2 depends on these; C4 must NOT touch them.
    for name in (
        "build_actor_alias_map",
        "build_node_envelope",
        "extract_edges_from_object",
        "finalize_edge_for_output",
        "finalize_node_for_output",
        "merge_edge",
        "merge_node",
        "passthrough_relationships",
        "remap_actor_aliases",
        "should_include_object",
        "relpath_for_report",
    ):
        assert hasattr(build_graph_projection, name), f"missing reused helper {name}"
