"""enrich_fppc_keys.py — Open Marin Identity Enrichment, Lane 3 (`committee_id`).

Attaches the FPPC committee id (the CA SOS Cal-Access FILER_ID) as a hard
identity key to campaign-committee `Organization` (`org-*`) contributor nodes,
so the shipped graph-org-dedup deterministic tier merges name-variant committee
dups and keeps different-election-cycle committees DISTINCT (Bonta-AG-2022 vs
-2026 carry different FPPC ids). Third lane on the shipped machinery (Lane 1 EIN
`enrich_org_keys`, Lane 2 CA-SOS `enrich_casos_keys`); `org_resolution.py` is
NEVER edited — the `committee_id` normalizer is registered at runtime.

Sources (both read from disk; no network/DB in the loop):
  - tier 1: the `committee-netfile-*` filer nodes in the normalized campaign
    bundle already carry `netfile_filer_id` = the FPPC committee id.
  - tier 2: an operator-staged Cal-Access `FILERNAME_CD` extract (committee
    registry) for state committees + name aliases.

The lane proposes name(+election-year)-gated `committee_id` candidates; the
operator approves; approval attaches `committee_id` via the Identity Control A
ledger. A NAME match NEVER attaches a key without audited approval, and the lane
NEVER collapses two distinct FILER_IDs.
"""
from __future__ import annotations

from typing import Any

from org_resolution import KEY_NORMALIZERS


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


def register_committee_id_normalizer() -> None:
    """Idempotently register `_normalize_committee_id` under `"committee_id"` in
    the shared `KEY_NORMALIZERS`. Refuses to clobber a foreign registration (a
    stray mutation fails loud rather than silently winning). Called by every
    module that uses the key — `org_resolution.py` itself is never edited."""
    existing = KEY_NORMALIZERS.get("committee_id")
    if existing is None:
        KEY_NORMALIZERS["committee_id"] = _normalize_committee_id
    elif existing is not _normalize_committee_id:
        raise RuntimeError(
            "KEY_NORMALIZERS['committee_id'] is already registered to a different "
            f"callable ({existing!r}); refusing to clobber it"
        )
