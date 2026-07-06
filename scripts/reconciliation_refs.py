"""Accessors for identity-attach reconciliation case endpoints.

This is the single owner of the read-model pair convention:
``left_ref`` is the County/vendor endpoint and ``right_ref`` is the registry anchor.
Ledger assertions invert those names at write time: subject = anchor, target = vendor.
"""
from __future__ import annotations

from typing import Any

from identity_key_registry import ANCHOR_PREFIXES

_PUBLIC_KEY_FIELDS = ("registry_ein", "sos_id", "committee_id")


def _join_of(case: dict[str, Any]) -> dict[str, Any]:
    joins = case.get("candidate_joins")
    if not isinstance(joins, list) or len(joins) != 1:
        raise ValueError(
            f"case {case.get('case_id', '<unknown>')!r} must contain exactly one candidate_join"
        )
    return joins[0]


def vendor_ref_of(case: dict[str, Any]) -> dict[str, Any]:
    return _join_of(case)["left_ref"]


def anchor_ref_of(case: dict[str, Any]) -> dict[str, Any]:
    return _join_of(case)["right_ref"]


def vendor_id_of(case: dict[str, Any]) -> str:
    return str(vendor_ref_of(case)["local_id"])


def anchor_id_of(case: dict[str, Any]) -> str:
    return str(anchor_ref_of(case)["local_id"])


def literal_key_of(case: dict[str, Any]) -> str:
    anchor = anchor_ref_of(case)
    fields = anchor.get("public_fields", {})
    for field in _PUBLIC_KEY_FIELDS:
        value = fields.get(field)
        if value is not None and value != "":
            return str(value)
    anchor_id = str(anchor.get("local_id", ""))
    for prefix in ANCHOR_PREFIXES:
        if anchor_id.startswith(prefix):
            return anchor_id[len(prefix):]
    return anchor_id
