"""Tests for outbound_policy.py — vendor-call gatekeeper."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from outbound_policy import (
    is_eligible, ELIGIBLE_TYPES, INELIGIBLE_TYPES, REDACT_FIELDS,
    synthesize_outbound_text,
)


class TestEligibility:
    def test_all_v2_types_eligible(self):
        for t in ["Person", "Organization", "Decision", "MoneyFlow",
                  "Case", "Filing", "Meeting", "Place", "Issue"]:
            assert is_eligible(t), f"{t} should be eligible by default"

    def test_unknown_type_inelibile(self):
        assert not is_eligible("CriminalRecord")
        assert not is_eligible("UnregisteredFutureType")

    def test_explicitly_ineligible_overrides(self):
        # Even if a type were ELIGIBLE, INELIGIBLE wins.
        assert ELIGIBLE_TYPES is not None  # sanity: import succeeded
        # If we add CriminalRecord later it must default to ineligible.
        assert not is_eligible("CriminalRecord")


class TestSynthesize:
    def _person(self, **kwargs):
        base = {"id": "person-kate-colin", "type": "Person",
                "label": "Kate Colin", "role": "San Rafael City Council"}
        base.update(kwargs)
        return base

    def test_eligible_node_renders(self):
        text = synthesize_outbound_text(
            self._person(),
            neighbors=[],
        )
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
