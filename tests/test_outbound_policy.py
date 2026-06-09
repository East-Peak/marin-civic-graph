"""Tests for outbound_policy.py — vendor-call gatekeeper.

Eligibility is now an EXPLICIT per-type map (TYPE_ELIGIBILITY) derived from
registry/node-types.json (keys == the graph node types; values == each type's
`outbound_eligible` flag). There is NO default-allow: a type absent from the
map — unknown type, sidecar artifact, retired label — is denied.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from canonical_type import ALL_TYPES
from outbound_policy import (
    TYPE_ELIGIBILITY,
    REDACT_FIELDS,
    is_eligible,
    load_eligibility,
    synthesize_outbound_text,
)

MALFORMED_FIXTURE = (
    ROOT / "tests" / "fixtures" / "registry" / "malformed-missing-flag.json"
)


class TestEligibilityMap:
    def test_keys_are_exactly_all_types(self):
        assert set(TYPE_ELIGIBILITY) == set(ALL_TYPES)

    def test_all_v2_graph_types_eligible(self):
        # v2 ships the entire 22-type ontology as outbound-eligible (all-public
        # civic data); every graph type is explicitly true in the registry.
        for t in ALL_TYPES:
            assert is_eligible(t), f"{t} should be eligible per registry"

    def test_no_default_allow_unknown_type_denied(self):
        assert not is_eligible("CriminalRecord")
        assert not is_eligible("UnregisteredFutureType")

    def test_sidecar_name_denied(self):
        # Sidecar artifacts are NOT graph node types; they must never egress.
        for sidecar in ("MediaOccurrence", "AttributionClaim",
                        "ResolutionCandidate", "PatternCandidate"):
            assert not is_eligible(sidecar), f"{sidecar} must be denied"

    def test_retired_label_denied(self):
        for retired in ("Actor", "Institution", "EconomicInterestDisclosure"):
            assert not is_eligible(retired), f"{retired} must be denied"


class TestMalformedRegistryRejected:
    def test_load_eligibility_rejects_missing_flag(self):
        with pytest.raises((ValueError, KeyError)):
            load_eligibility(path=MALFORMED_FIXTURE)


class TestSynthesize:
    def _person(self, **kwargs):
        base = {"id": "person-kate-colin", "type": "Person",
                "label": "Kate Colin", "role": "San Rafael City Council"}
        base.update(kwargs)
        return base

    def test_eligible_node_renders(self):
        text = synthesize_outbound_text(self._person(), neighbors=[])
        assert "Kate Colin" in text
        assert "Person" in text

    def test_ineligible_anchor_returns_empty(self):
        text = synthesize_outbound_text(
            {"id": "x-1", "type": "CriminalRecord", "label": "redacted"},
            neighbors=[],
        )
        assert text == ""

    def test_ineligible_neighbor_dropped(self):
        text = synthesize_outbound_text(
            self._person(),
            neighbors=[
                {"id": "decision-1", "type": "Decision", "label": "Approve permit"},
                {"id": "x-2", "type": "CriminalRecord", "label": "should not appear"},
            ],
        )
        assert "Approve permit" in text
        assert "should not appear" not in text

    def test_redact_fields_for_person(self):
        text = synthesize_outbound_text(
            self._person(home_address="123 Elm St", phone="415-555-0100",
                         email="kate@example.com"),
            neighbors=[],
        )
        assert "123 Elm St" not in text
        assert "415-555-0100" not in text
        assert "kate@example.com" not in text
        assert "Kate Colin" in text


class TestRedactFieldsRegistry:
    def test_person_has_pii_redactions(self):
        assert "home_address" in REDACT_FIELDS["Person"]
        assert "phone" in REDACT_FIELDS["Person"]
        assert "email" in REDACT_FIELDS["Person"]
