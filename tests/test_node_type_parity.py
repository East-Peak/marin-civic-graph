"""M1b — exhaustive node-type SURFACE parity (Python surfaces).

The gate that proves every *active* Python surface covers every graph node type,
so adding a type (EconomicInterest / Membership next) is a proven-complete change
instead of a guessing game. Driven from `registry/node-types.json` (source of truth).

Surface-class-aware (per the M1b decision doc). Each surface is tested by the
contract that matches its actual shape — we do NOT reshape product code to fit a
uniform test:

  EXHAUSTIVE_GROUPING  build_catalog.ALL_TYPES           == registry ALL_TYPES
  PREFIX_RESOLUTION    build_signature_subgraphs / canonical_type resolve a REAL
                       id for EVERY type's prefix (incl. agenda-item-). The M1a
                       lesson: assert RESOLUTION, not list-membership — a stale
                       prefix KEY passes a membership check but fails resolution.
  SEARCHABLE_SUBSET    build_search_properties.INDEXED_TYPES == registry
                       searchable=true (14); ALL_SEARCHABLE_TYPES == INDEXED +
                       ["Record"] — Record is a deliberate secondary-bucket type
                       (searchable=false in the registry BY DESIGN).
  sidecar negative     no sidecar_artifact name leaks into any exhaustive surface.

CURATED_SUBSET / GENERIC_EXCLUDED surfaces are intentionally NOT forced exhaustive
(forcing them creates dead per-type entries) — justified one-liners:
  * build_search_properties.build_search_label / _key_fact / _terms — per-type
    search formatting with a generic id/name fallback for every other type.
  * build_search_properties.TYPE_WEIGHT — scoped to the searchable subset + Record;
    compute_search_rank uses .get(type, 0), so no type silently breaks.
  * graph_projection_lib.NODE_TYPE_BY_PREFIX / projection_helpers / migration_mapping
    / graph_v2_transforms — pre-migration projection-internal contract
    (actor-→Actor, inst-→Institution); EXPLICITLY left alone (M1a decision).
  * domain normalizers/ingestors (campaign-finance, meetings, form700, courtlistener,
    legal, socrata, agenda/decision extractors) — emit only their domain's types.

NO-DB-WRITES: this module imports CONSTANTS + PURE FUNCTIONS only. It never calls
any main()/update_type/_write_batch nor instantiates a real neo4j session.
Module-level imports below open NO connection (DB access lives in main()).

Registry-mechanical surfaces (canonical_type / outbound_policy / schema) are pinned
by tests/test_node_type_registry.py (M1a) — not re-tested here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

REGISTRY_PATH = ROOT / "registry" / "node-types.json"
_REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

REGISTRY_TYPES = list(_REGISTRY["graph_node_types"].keys())
REGISTRY_TYPE_SET = set(REGISTRY_TYPES)
SEARCHABLE_TYPES = {
    t for t, spec in _REGISTRY["graph_node_types"].items() if spec["searchable"]
}
ID_PREFIXES = dict(_REGISTRY["id_prefixes"])  # prefix -> type (incl. legacy aliases)
SIDECAR_ARTIFACTS = list(_REGISTRY["sidecar_artifacts"])


# ---------------------------------------------------------------------------
# EXHAUSTIVE_GROUPING — build_catalog bakes a count per type; it must enumerate
# exactly the registry's 23, each once. (Teeth-demo target.)
# ---------------------------------------------------------------------------
class TestCatalogExhaustive:
    def test_build_catalog_all_types_equals_registry(self):
        import build_catalog

        assert build_catalog.ALL_TYPES == REGISTRY_TYPES, (
            "build_catalog.ALL_TYPES drifted from registry order/membership"
        )

    def test_build_catalog_covers_every_type_exactly_once(self):
        import build_catalog

        assert sorted(build_catalog.ALL_TYPES) == sorted(REGISTRY_TYPES)
        assert len(build_catalog.ALL_TYPES) == len(set(build_catalog.ALL_TYPES)) == 23


# ---------------------------------------------------------------------------
# PREFIX_RESOLUTION — feed a REAL id for every registry prefix and assert it
# RESOLVES (not just "the type is in the value-set"). Covers both the
# build_signature_subgraphs resolver (the M1b residual) and canonical_type.py.
# ---------------------------------------------------------------------------
def _real_id_for(prefix: str) -> str:
    # A representative real id; agenda-item uses the real dated shape.
    if prefix == "agenda-item-":
        return "agenda-item-2024-08-19-5a"
    return f"{prefix}2024-sample-001"


PREFIX_CASES = sorted(ID_PREFIXES.items())


class TestSignatureSubgraphPrefixResolution:
    """RESIDUAL 3: build_signature_subgraphs.py carried a stale agendaitem-."""

    @pytest.mark.parametrize("prefix,node_type", PREFIX_CASES)
    def test_every_registry_prefix_resolves(self, prefix, node_type):
        import build_signature_subgraphs as bss

        real_id = _real_id_for(prefix)
        assert bss.canonical_type([], real_id) == node_type, (
            f"{real_id!r} should resolve to {node_type} via the registry prefix"
        )

    def test_real_agenda_item_id_resolves(self):
        import build_signature_subgraphs as bss

        # Empty labels isolates the PREFIX path — the M1a lesson. With labels
        # ["AgendaItem"] the label-fallback would mask a stale prefix KEY.
        assert bss.canonical_type([], "agenda-item-2024-08-19-5a") == "AgendaItem"

    def test_prefix_map_is_registry_derived(self):
        import build_signature_subgraphs as bss

        # Centralized: no hand-rolled second copy that can drift.
        assert dict(bss.TYPE_BY_ID_PREFIX) == ID_PREFIXES


class TestCanonicalTypePrefixResolution:
    """canonical_type.py is registry-derived; assert resolution holds here too."""

    @pytest.mark.parametrize("prefix,node_type", PREFIX_CASES)
    def test_every_registry_prefix_resolves(self, prefix, node_type):
        from canonical_type import canonical_type

        assert canonical_type([], _real_id_for(prefix)) == node_type


# ---------------------------------------------------------------------------
# SEARCHABLE_SUBSET — INDEXED_TYPES must equal the registry searchable=true set
# (14), with Record as the documented secondary-bucket exception.
# ---------------------------------------------------------------------------
class TestSearchableSubset:
    def test_indexed_types_equals_registry_searchable_set(self):
        import build_search_properties as bsp

        assert set(bsp.INDEXED_TYPES) == SEARCHABLE_TYPES
        assert len(bsp.INDEXED_TYPES) == len(SEARCHABLE_TYPES) == 14

    def test_record_is_searchable_false_by_design(self):
        # The documented exception — do NOT flip the flag to make equality pass.
        assert _REGISTRY["graph_node_types"]["Record"]["searchable"] is False

    def test_all_searchable_types_is_indexed_plus_record(self):
        import build_search_properties as bsp

        assert bsp.ALL_SEARCHABLE_TYPES == [*bsp.INDEXED_TYPES, "Record"]

    def test_type_weight_keys_cover_all_searchable_types(self):
        import build_search_properties as bsp

        assert set(bsp.TYPE_WEIGHT) == set(bsp.ALL_SEARCHABLE_TYPES)


# ---------------------------------------------------------------------------
# Sidecar negative — no sidecar artifact name may appear in any exhaustive
# surface's type list/keys (M1b-specific, reads registry.sidecar_artifacts).
# ---------------------------------------------------------------------------
class TestSidecarNamesAbsent:
    @pytest.mark.parametrize("sidecar", SIDECAR_ARTIFACTS)
    def test_sidecar_absent_from_exhaustive_surfaces(self, sidecar):
        import build_catalog
        import build_search_properties as bsp
        import build_signature_subgraphs as bss

        assert sidecar not in REGISTRY_TYPE_SET
        assert sidecar not in build_catalog.ALL_TYPES
        assert sidecar not in bsp.INDEXED_TYPES
        assert sidecar not in bsp.ALL_SEARCHABLE_TYPES
        assert sidecar not in bsp.TYPE_WEIGHT
        assert sidecar not in set(bss.TYPE_BY_ID_PREFIX.values())
        assert sidecar not in bss.KNOWN_TYPES


# ---------------------------------------------------------------------------
# NO-DB-WRITES guard — importing the surface modules must not require live env
# vars or open a session. (If a module grew a top-level DB call, this fails.)
# ---------------------------------------------------------------------------
class TestNoDbWriteOnImport:
    def test_surface_modules_import_without_db(self):
        import build_catalog  # noqa: F401
        import build_search_properties  # noqa: F401
        import build_signature_subgraphs  # noqa: F401
        # Reaching here means no module-level connection / env requirement.
        assert True
