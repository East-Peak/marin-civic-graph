"""Tests for canonical_type.py — Python port of app/src/lib/canonical-type.ts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from canonical_type import canonical_type, ALL_TYPES, ORGANIZATION_SUBTYPES


class TestCanonicalType:
    def test_id_prefix_person(self):
        assert canonical_type([], "person-kate-colin") == "Person"

    def test_id_prefix_legacy_actor(self):
        assert canonical_type([], "actor-kate-colin") == "Person"

    def test_id_prefix_legacy_inst(self):
        assert canonical_type([], "inst-san-rafael") == "Organization"

    def test_id_prefix_eid_to_filing(self):
        assert canonical_type([], "eid-12345") == "Filing"

    def test_known_base_label_wins_when_no_prefix(self):
        assert canonical_type(["Decision"], "x-1") == "Decision"

    def test_known_base_preferred_over_subtype(self):
        # Has both "Organization" base and "Government" subtype — base wins.
        assert canonical_type(["Government", "Organization"], "x-1") == "Organization"

    def test_org_subtype_label_resolves_to_organization(self):
        assert canonical_type(["Government"], "x-1") == "Organization"
        assert canonical_type(["Court"], "x-1") == "Organization"

    def test_unknown_returns_none(self):
        assert canonical_type([], "no-prefix-id") is None
        assert canonical_type(["RandomLabel"], "no-prefix-id") is None

    def test_all_types_count_matches_ts(self):
        assert len(ALL_TYPES) == 21

    def test_org_subtypes_match_ts(self):
        assert ORGANIZATION_SUBTYPES == {
            "Government", "Nonprofit", "Business",
            "Political", "Court", "Department", "Commission",
        }
