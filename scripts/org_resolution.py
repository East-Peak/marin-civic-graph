"""Shared cross-source org resolver — deterministic SAME_AS + ResolutionCandidate sidecar.

Extracted verbatim-in-spirit from `ingest_990.py` (M2b, Decision 6 of the M2c
goal doc) and generalized to `identity_keys` so each ingestor names the
deterministic identity keys its source actually carries (990 → EIN,
USASpending → EIN + UEI). `ingest_990` re-exports `propose_org_resolutions`
so existing imports keep working unchanged.

Spec §4.3/§4.4 posture: deterministic identity-key equality is the definition
of identity, not a judgment — the ONE permitted exception to "enrichment-only
until reviewed." Everything judged (name signals) lands in the JSONL review
sidecar, never in the graph; name similarity alone NEVER merges.

Keys are NOT interchangeable through one normalizer: an EIN is digits, a UEI
is 12-char alphanumeric WITH letters — the digits-only EIN normalizer would
strip every letter from a UEI and manufacture false merges. Each key
registers its own normalizer; an unregistered key fails loud.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Callable

# Trailing corporate suffixes stripped during name normalization. Bounded by
# design — this is a tie-breaker for exact-equality after cleanup, not a
# general company-name canonicalizer.
_NAME_SUFFIXES = {"inc", "incorporated", "llc", "corp"}

# Minimum difflib ratio for a name-similarity ResolutionCandidate. Below this
# the pair produces nothing — no edge, no candidate.
_SIMILARITY_THRESHOLD = 0.85


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


# Per-key normalizer registry — `identity_keys` entries resolve here; a key
# with no registered normalizer fails loud (never a silent identity match).
KEY_NORMALIZERS: dict[str, Callable[[Any], str | None]] = {
    "ein": _normalize_ein,
    "uei": _normalize_uei,
}


def _normalize_name(value: str) -> str:
    """Casefold, collapse non-alphanumeric runs to single spaces, and strip
    trailing corporate suffixes (inc/incorporated/llc/corp) repeatedly.
    """
    tokens = re.sub(r"[^0-9a-z]+", " ", value.casefold()).split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def propose_org_resolutions(
    new_orgs: list[dict[str, Any]],
    existing_orgs: list[dict[str, Any]],
    identity_keys: tuple[str, ...] = ("ein",),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure resolver: (SAME_AS edges, ResolutionCandidate dicts).

    Deterministic auto-merge on exact identity-key equality ONLY (both sides
    must carry the key; per (new, existing) pair the FIRST key in tuple order
    that matches under its normalizer wins, basis ``<key>_exact``). Conflict
    rule: per new org all key-exact matches are collected FIRST — matches
    targeting >= 2 distinct existing ids emit ZERO SAME_AS and queue each
    matched pair (``identity_conflict``, confidence 0.95): contradictory
    deterministic identity is a human call, never a silent double-merge.

    Everything else is bounded stdlib-only name evidence that lands in the
    JSONL review sidecar, never in the graph: exact normalized-name equality
    (conf 0.9), else difflib ratio >= 0.85 (conf = the 2dp ratio). A key
    disagreement does NOT suppress name candidacy. Name similarity alone
    NEVER merges.

    `existing_orgs` is injected (`[{id, display_label, ein?, uei?}]`) — no
    graph access here; the operator feeds a real export at run time.
    """
    for key in identity_keys:
        if key not in KEY_NORMALIZERS:
            raise ValueError(
                f"no normalizer registered for identity key {key!r} "
                f"(registered: {sorted(KEY_NORMALIZERS)})"
            )

    same_as_edges: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for new in new_orgs:
        new_keys = {key: KEY_NORMALIZERS[key](new.get(key)) for key in identity_keys}
        new_name = new["display_label"]

        # Pass 1 — collect ALL key-exact matches across the existing list
        # before emitting anything (the conflict rule needs the full set).
        key_matches: list[tuple[dict[str, Any], str]] = []
        for existing in existing_orgs:
            for key in identity_keys:
                new_value = new_keys[key]
                if new_value is None:
                    continue
                existing_value = KEY_NORMALIZERS[key](existing.get(key))
                if existing_value is not None and new_value == existing_value:
                    key_matches.append((existing, key))
                    break  # first matching key in tuple order wins this pair

        matched_ids = {existing["id"] for existing, _ in key_matches}
        if len(matched_ids) == 1:
            existing, key = key_matches[0]
            same_as_edges.append(
                {
                    "source_id": new["id"],
                    "target_id": existing["id"],
                    "relationship_type": "SAME_AS",
                    "properties": {"basis": f"{key}_exact"},
                }
            )
        elif len(matched_ids) >= 2:
            for existing, key in key_matches:
                candidates.append(
                    {
                        "subject_ref": new["id"],
                        "candidate_ref": existing["id"],
                        "signals": [f"{key}_exact", "identity_conflict"],
                        "confidence": 0.95,
                        "status": "queued",
                        "evidence_record_ids": list(
                            new.get("evidence_record_ids", [])
                        ),
                    }
                )

        # Pass 2 — name signals for every pair NOT settled (or queued as a
        # conflict) by a key match. Key disagreement falls through to here.
        for existing in existing_orgs:
            if existing["id"] in matched_ids:
                continue  # settled deterministically or conflict-queued

            existing_name = existing["display_label"]
            if _normalize_name(new_name) == _normalize_name(existing_name):
                signals = ["normalized_name_exact"]
                confidence = 0.9
            else:
                ratio = difflib.SequenceMatcher(
                    None, new_name.casefold(), existing_name.casefold()
                ).ratio()
                if ratio < _SIMILARITY_THRESHOLD:
                    continue
                confidence = round(ratio, 2)
                signals = [f"name_similarity:{confidence}"]

            candidates.append(
                {
                    "subject_ref": new["id"],
                    "candidate_ref": existing["id"],
                    "signals": signals,
                    "confidence": confidence,
                    "status": "queued",
                    "evidence_record_ids": list(
                        new.get("evidence_record_ids", [])
                    ),
                }
            )

    return same_as_edges, candidates
