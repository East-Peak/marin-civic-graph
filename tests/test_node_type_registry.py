"""M1a — node-type registry mechanical surfaces.

`registry/node-types.json` is the single source of truth for the type contract.
These tests pin ONLY the mechanical surfaces derived from it:
  - canonical_type.ALL_TYPES / TYPE_BY_ID_PREFIX / ORGANIZATION_SUBTYPES derive
    from the registry (ALL_TYPES still == the 21).
  - every graph type's REAL id prefix resolves via canonical_type (incl. the
    fixed `agenda-item-` prefix; the latent AgendaItem bug).
  - the registry rejects a graph type missing a required boolean flag.
  - registry/neo4j-schema.cypher has a uniqueness constraint for every graph
    type + the ValidationCheck support label.
  - outbound_policy.TYPE_ELIGIBILITY keys == ALL_TYPES.

Do NOT add exhaustive app-UX-surface parity here (M1b). Do NOT parity-check
graph_projection_lib.NODE_TYPE_BY_PREFIX — it is a different, pre-migration
projection-internal contract (see the M1a decision doc).
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import canonical_type as ct
from canonical_type import (
    ALL_TYPES,
    ORGANIZATION_SUBTYPES,
    TYPE_BY_ID_PREFIX,
    canonical_type,
    load_registry,
)

REGISTRY_PATH = ROOT / "registry" / "node-types.json"
SCHEMA_PATH = ROOT / "registry" / "neo4j-schema.cypher"
MALFORMED_FIXTURE = (
    ROOT / "tests" / "fixtures" / "registry" / "malformed-missing-flag.json"
)

# The settled 21-type ontology (spec §4.1). M1a centralizes; it does NOT add.
EXPECTED_TYPES = {
    "Person", "Organization", "Committee", "Seat", "SeatService",
    "Election", "Candidacy", "Meeting", "AgendaItem", "Decision",
    "Filing", "MoneyFlow", "Case", "Proceeding", "Project",
    "Program", "Agreement", "Amendment", "Record", "Place", "Issue",
}


class TestRegistryFile:
    def test_registry_file_exists(self):
        assert REGISTRY_PATH.is_file(), f"{REGISTRY_PATH} missing"

    def test_graph_node_types_are_exactly_the_21(self):
        reg = load_registry()
        assert set(reg["graph_node_types"]) == EXPECTED_TYPES
        assert len(reg["graph_node_types"]) == 21

    def test_every_graph_type_has_both_boolean_flags(self):
        reg = load_registry()
        for t, spec in reg["graph_node_types"].items():
            assert isinstance(spec["searchable"], bool), f"{t}.searchable"
            assert isinstance(spec["outbound_eligible"], bool), f"{t}.outbound_eligible"

    def test_no_sidecar_or_retired_name_in_graph_node_types(self):
        reg = load_registry()
        graph = set(reg["graph_node_types"])
        assert graph.isdisjoint(reg["sidecar_artifacts"])
        assert graph.isdisjoint(reg["retired_labels"])
        assert graph.isdisjoint(reg["support_labels"])


class TestPythonDerivation:
    def test_all_types_derive_from_registry(self):
        reg = load_registry()
        assert list(ALL_TYPES) == list(reg["graph_node_types"].keys())
        assert len(ALL_TYPES) == 21

    def test_prefix_map_derives_from_registry(self):
        reg = load_registry()
        assert TYPE_BY_ID_PREFIX == reg["id_prefixes"]

    def test_org_subtypes_derive_from_registry(self):
        reg = load_registry()
        assert ORGANIZATION_SUBTYPES == set(reg["organization_subtypes"])


class TestPrefixResolution:
    """Every graph type's REAL id prefix must resolve via canonical_type."""

    def test_agenda_item_real_prefix_resolves(self):
        # The latent bug: real ids are `agenda-item-*`, not `agendaitem-*`.
        assert canonical_type([], "agenda-item-2024-08-19-5a") == "AgendaItem"

    def test_every_registry_prefix_resolves_to_its_type(self):
        reg = load_registry()
        for prefix, node_type in reg["id_prefixes"].items():
            real_id = f"{prefix}sample-001"
            assert canonical_type([], real_id) == node_type, (
                f"{real_id!r} should resolve to {node_type}"
            )

    def test_every_graph_type_has_a_resolving_prefix(self):
        reg = load_registry()
        types_with_prefix = set(reg["id_prefixes"].values())
        for t in reg["graph_node_types"]:
            assert t in types_with_prefix, f"{t} has no id prefix"

    def test_legacy_aliases_still_resolve(self):
        assert canonical_type([], "actor-kate-colin") == "Person"
        assert canonical_type([], "inst-san-rafael") == "Organization"
        assert canonical_type([], "eid-12345") == "Filing"


class TestMalformedRegistryRejected:
    def test_missing_boolean_flag_is_rejected(self):
        assert MALFORMED_FIXTURE.is_file(), "malformed fixture missing"
        with pytest.raises((ValueError, KeyError)):
            load_registry(path=MALFORMED_FIXTURE)


class TestSchemaCoverage:
    def _constraint_labels(self) -> set[str]:
        text = SCHEMA_PATH.read_text(encoding="utf-8")
        return set(
            re.findall(
                r"CREATE CONSTRAINT \w+ IF NOT EXISTS FOR \(n:(\w+)\) REQUIRE n\.id IS UNIQUE",
                text,
            )
        )

    def test_schema_has_constraint_for_every_graph_type(self):
        labels = self._constraint_labels()
        for t in EXPECTED_TYPES:
            assert t in labels, f"schema missing uniqueness constraint for {t}"

    def test_schema_covers_validationcheck_support_label(self):
        reg = load_registry()
        labels = self._constraint_labels()
        for support in reg["support_labels"]:
            assert support in labels, f"schema missing constraint for {support}"
