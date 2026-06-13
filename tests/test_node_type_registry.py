"""M1a — node-type registry mechanical surfaces.

`registry/node-types.json` is the single source of truth for the type contract.
These tests pin ONLY the mechanical surfaces derived from it:
  - canonical_type.ALL_TYPES / TYPE_BY_ID_PREFIX / ORGANIZATION_SUBTYPES derive
    from the registry (ALL_TYPES == the 23: the original 21 + Membership +
    EconomicInterest).
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

# The settled ontology: the original 21 (spec §4.1, centralized by M1a) plus
# Membership (COI spec §4.1, added by M2a) and EconomicInterest (Form 700
# interiors, added by M4) — 23 graph types.
EXPECTED_TYPES = {
    "Person", "Organization", "Committee", "Seat", "SeatService",
    "Election", "Candidacy", "Meeting", "AgendaItem", "Decision",
    "Filing", "MoneyFlow", "Case", "Proceeding", "Project",
    "Program", "Agreement", "Amendment", "Record", "Place", "Issue",
    "Membership", "EconomicInterest",
}


class TestRegistryFile:
    def test_registry_file_exists(self):
        assert REGISTRY_PATH.is_file(), f"{REGISTRY_PATH} missing"

    def test_graph_node_types_are_exactly_the_23(self):
        reg = load_registry()
        assert set(reg["graph_node_types"]) == EXPECTED_TYPES
        assert len(reg["graph_node_types"]) == 23

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
        assert len(ALL_TYPES) == 23

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


class TestOutboundEligibilityDerivation:
    def test_outbound_keys_equal_all_types(self):
        from outbound_policy import TYPE_ELIGIBILITY
        assert set(TYPE_ELIGIBILITY) == set(ALL_TYPES)

    def test_outbound_values_come_from_registry(self):
        from outbound_policy import TYPE_ELIGIBILITY
        reg = load_registry()
        for t, spec in reg["graph_node_types"].items():
            assert TYPE_ELIGIBILITY[t] == spec["outbound_eligible"]


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


class TestEconomicInterestRegistration:
    """M4 — EconomicInterest (the 23rd graph type) flag choices are deliberate,
    not defaults; pin them so a later edit must consciously change the decision.
    """

    def test_economic_interest_is_a_graph_type_with_its_prefix(self):
        reg = load_registry()
        assert "EconomicInterest" in reg["graph_node_types"]
        assert reg["id_prefixes"]["economicinterest-"] == "EconomicInterest"

    def test_economic_interest_not_searchable_reached_through_endpoints(self):
        # A reified Form 700 disclosure line is reached through its Filing /
        # Person / Organization endpoints, not free-text search — same call as
        # Membership. searchable=false keeps it out of INDEXED_TYPES.
        reg = load_registry()
        assert reg["graph_node_types"]["EconomicInterest"]["searchable"] is False

    def test_economic_interest_outbound_eligible_scrutiny_up_the_gradient(self):
        # Form 700s are officials' own statutorily public disclosures — scrutiny
        # up the power gradient; deliberately outbound-eligible (contrast the
        # planned Mention/Claim ineligibility).
        from outbound_policy import is_eligible

        reg = load_registry()
        assert reg["graph_node_types"]["EconomicInterest"]["outbound_eligible"] is True
        assert is_eligible("EconomicInterest") is True
