"""Unit tests for the single reconciliation case-ref accessor module."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from reconciliation_refs import (  # noqa: E402
    anchor_id_of,
    anchor_ref_of,
    literal_key_of,
    vendor_id_of,
    vendor_ref_of,
)


def _case(source: str, anchor_id: str, vendor_id: str, public_fields: dict[str, object]) -> dict:
    return {
        "case_id": f"attach|{anchor_id}|{vendor_id}",
        "case_type": "identity_key_attach",
        "candidate_joins": [
            {
                "left_ref": {
                    "source_id": source,
                    "local_id": vendor_id,
                    "display_label": "County Vendor",
                    "public_fields": {"display_label": "County Vendor"},
                },
                "right_ref": {
                    "source_id": source,
                    "local_id": anchor_id,
                    "display_label": "Registry Anchor",
                    "public_fields": public_fields,
                },
            }
        ],
    }


def test_vendor_and_anchor_refs_are_the_left_right_convention():
    case = _case("ein", "org-bmf-ein-111111111", "org-vendor-alpha", {"registry_ein": "111111111"})

    assert vendor_ref_of(case)["local_id"] == "org-vendor-alpha"
    assert anchor_ref_of(case)["local_id"] == "org-bmf-ein-111111111"
    assert vendor_id_of(case) == "org-vendor-alpha"
    assert anchor_id_of(case) == "org-bmf-ein-111111111"


@pytest.mark.parametrize(
    ("source", "anchor_id", "public_fields", "expected"),
    [
        ("ein", "org-bmf-ein-111111111", {"registry_ein": "111111111"}, "111111111"),
        ("sos_id", "org-casos-0222222", {"sos_id": "0222222"}, "0222222"),
        ("committee_id", "org-fppc-3333333", {"committee_id": "3333333"}, "3333333"),
    ],
)
def test_literal_key_of_reads_the_anchor_public_key_field(
    source: str,
    anchor_id: str,
    public_fields: dict[str, object],
    expected: str,
):
    assert literal_key_of(_case(source, anchor_id, "org-vendor", public_fields)) == expected


def test_literal_key_of_falls_back_to_stripped_anchor_id():
    assert literal_key_of(_case("ein", "org-bmf-ein-111111111", "org-vendor", {})) == "111111111"
    assert literal_key_of(_case("sos_id", "org-casos-0222222", "org-vendor", {})) == "0222222"


def test_accessors_fail_loud_on_non_single_join_case():
    with pytest.raises(ValueError, match="exactly one candidate_join"):
        vendor_ref_of({"case_id": "empty", "candidate_joins": []})

    multi = _case("ein", "org-bmf-ein-111111111", "org-vendor", {"registry_ein": "111111111"})
    multi["candidate_joins"].append(multi["candidate_joins"][0])
    with pytest.raises(ValueError, match="exactly one candidate_join"):
        anchor_ref_of(multi)
