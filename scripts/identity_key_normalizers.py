"""Identity-key normalizers — the single, stdlib-only home for the per-key
canonicalizers the IdentityKey registry references.

Byte-copied verbatim from their original homes so behavior is identical:
  ``_normalize_ein`` / ``_normalize_uei``   ← ``org_resolution``
  ``_normalize_sos_id``                      ← ``enrich_casos_keys``
  ``_normalize_committee_id``                ← ``enrich_fppc_keys``

This module imports stdlib ONLY (``re``, ``typing``). It must never import
``org_resolution``, the enrich lanes, or ``identity_key_registry`` — that is what
keeps the registry import DAG acyclic: ``identity_key_registry`` imports only this
module, while ``org_resolution`` and the lanes import both this module (for the
normalizer objects) and the registry (for the generated ``KEY_NORMALIZERS`` view).
"""
from __future__ import annotations

import re
from typing import Any


def _normalize_ein(value: Any) -> str | None:
    """Digits only; None when absent or no digits survive."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def _normalize_uei(value: Any) -> str | None:
    """Uppercase with non-alphanumerics stripped; None when absent or empty.

    A UEI is 12-char alphanumeric WITH letters (e.g. JZ9FLAVMPEB9) — it must
    never pass through the digits-only EIN normalizer.
    """
    if not value:
        return None
    cleaned = re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()
    return cleaned or None


def _normalize_sos_id(value: Any) -> str | None:
    """Format-agnostic CA SOS entity-number normalizer.

    Uppercase; strip a single leading `C`/`c` (OpenCorporates' display form —
    the raw SOS file has no prefix); remove all non-alphanumerics; PRESERVE
    leading zeros (7-digit corp numbers are zero-padded). Accepts any resulting
    non-empty alphanumeric token, so `0257045`, `202118310837`, and
    `B20260076487` all key. Empty / no-surviving-alphanumeric → None (never a
    fabricated key)."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if text.startswith("C"):
        text = text[1:]
    text = re.sub(r"[^0-9A-Z]", "", text)
    return text or None


def _normalize_committee_id(value: Any) -> str | None:
    """Strict numeric FPPC committee id. Accepts a clean 1–9 digit numeric value
    (CAL Format allows ≤9); whitespace stripped; ints coerced. Anything else —
    `Pending`/`Unknown`, empty, overlength (>9 digits), or any non-digit
    character (letters, dots, an SOS-style `C` prefix) — is None (never a
    fabricated or wrong-shape key)."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text.isdigit() and 1 <= len(text) <= 9 else None
