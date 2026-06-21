"""enrich_casos_keys.py — CA Secretary-of-State entity-number enrichment (Lane 2).

Open Marin Identity Enrichment, Lane 2 (`sos_id`). Attaches the California SOS
business entity number to existing FOR-PROFIT vendor `Organization` nodes — the
for-profit analog of Lane 1's EIN (there is no public for-profit EIN source). The
operator stages the CA SOS "BE Master Unload" (`data/raw/ca-sos/Filings.csv`,
9.44M entities, `*|*`-delimited); this module STREAMS it (never materializes the
3.6 GB file) into keyed registry org refs for the shared resolver.

Reuses Lane 1's resolver/ledger/gate/export. THREE things are new:
  1. `sos_id` — a new identity key, registered into the shared resolver's
     `KEY_NORMALIZERS` at RUNTIME via the idempotent, non-clobbering
     `register_sos_id_normalizer()` (so `org_resolution.py` stays byte-identical
     and there is no import-order hazard).
  2. Scale + recall — a streaming significant-token pre-block (see
     `block_casos_against_existing`, a later unit) reduces 9.44M rows to a tiny
     candidate pool before any resolution.
  3. A redaction gate — for-profit registry records carry natural-person data
     (registered-agent / officer names + home addresses) that is NEVER published.
     This parser already reads ONLY the entity-level whitelist into refs.

Operator runbook (the download is the OPERATOR step — this module never fetches):
  1. Sign in at https://bizfileonline.sos.ca.gov/ → Data Requests → New Data
     Request → "BE Bulk Order - Master Unload of Data" ($100, full snapshot).
  2. Accept the in-workflow Terms; download `Data.zip`; unzip.
  3. Stage `Filings.csv` (+ optional `Agents.csv` for the redaction signal) under
     `data/raw/ca-sos/` (gitignored). The file is `*|*`-delimited (NOT comma).
  4. Run this lane's CLI (a later unit) to parse → block → resolve → coverage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from org_resolution import KEY_NORMALIZERS, _normalize_name, propose_org_resolutions  # noqa: E402
from identity_resolution_adapter import (  # noqa: E402
    normalize_resolution_candidate_for_artifact,
)

# This lane's source-system stamp + the registry id key-prefix it mints.
SOURCE_SYSTEM = "ca_sos"

# The ONLY columns the parser reads into a ref — the entity-level whitelist. The
# street/ZIP/mailing columns the staged file carries are NEVER read (redaction at
# source); the natural-person Agents/Principals files are never read here at all.
_WHITELIST_COLUMNS = {
    "ENTITY_NAME": "display_label",
    "ENTITY_NUM": "_entity_num",
    "INITIAL_FILING_DATE": "formation_date",
    "ENTITY_STATUS": "entity_status",
    "ENTITY_TYPE": "entity_type",
    "PRINCIPAL_CITY": "principal_city",
    "PRINCIPAL_STATE": "principal_state",
}

DELIMITER = "*|*"


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


def register_sos_id_normalizer() -> None:
    """Idempotently register `_normalize_sos_id` under `"sos_id"` in the shared
    `KEY_NORMALIZERS`. Refuses to clobber a foreign registration (so a stray test
    mutation fails loud rather than silently winning). Called at import by every
    module that uses the key — `org_resolution.py` itself is never edited."""
    existing = KEY_NORMALIZERS.get("sos_id")
    if existing is None:
        KEY_NORMALIZERS["sos_id"] = _normalize_sos_id
    elif existing is not _normalize_sos_id:
        raise RuntimeError(
            "KEY_NORMALIZERS['sos_id'] is already registered to a different "
            f"callable ({existing!r}); refusing to clobber it"
        )


def entity_num_prefix_shape(normalized: str) -> str:
    """Coverage-honesty classifier for a normalized entity number."""
    if normalized.isdigit():
        return "digits"
    if normalized[:1] == "B" and normalized[1:].isdigit():
        return "b_prefixed"
    return "alpha_other"


def _clean_name(raw: str) -> str:
    """Strip the leading `' ` quote artifact + surrounding quotes/space the SOS
    Master Unload puts on ENTITY_NAME; title-case the all-caps source for display."""
    name = raw.strip().lstrip("'").strip().strip("'").strip()
    return name.title() if name.isupper() else name


def parse_casos_filings(
    lines: Iterable[str],
) -> Iterator[tuple[dict[str, Any] | None, str | None]]:
    """STREAM the `*|*`-delimited Filings export → `(ref, skip_reason)` per row.

    Lazy by contract — consumes an iterable of lines and never materializes the
    file (no `.read()`/`list(reader)`). Reads ONLY the entity-level whitelist
    columns into each ref (the street/ZIP columns are never touched). A row with a
    missing/non-normalizable ENTITY_NUM yields `(None, "entity_num_missing")`."""
    header: dict[str, int] | None = None
    for line in lines:
        fields = line.rstrip("\n").split(DELIMITER)
        if header is None:
            header = {name: i for i, name in enumerate(fields)}
            continue

        def cell(col: str) -> str:
            idx = header.get(col)
            return fields[idx].strip() if idx is not None and idx < len(fields) else ""

        sos_id = _normalize_sos_id(cell("ENTITY_NUM"))
        if sos_id is None:
            yield None, "entity_num_missing"
            continue
        ref = {
            "id": f"org-casos-{sos_id}",
            "display_label": _clean_name(cell("ENTITY_NAME")),
            "sos_id": sos_id,
            "entity_class": "organization",
            "entity_status": cell("ENTITY_STATUS"),
            "entity_type": cell("ENTITY_TYPE"),
            "formation_date": cell("INITIAL_FILING_DATE"),
            "principal_city": _clean_name(cell("PRINCIPAL_CITY")),
            "principal_state": cell("PRINCIPAL_STATE").upper(),
            "evidence_record_ids": [f"record-casos-{sos_id}"],
        }
        yield ref, None


# Fields whose disagreement across rows of the same ENTITY_NUM is a conflict.
_CONFLICT_FIELDS = ("display_label", "entity_type")


def dedupe_casos_refs(
    refs: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse byte-identical duplicate-ENTITY_NUM refs to one; withhold numbers
    whose rows disagree on name/type (→ `casos_row_conflict`).

    Operates on the BOUNDED matched set (the blocking pool), never the full file —
    so it is memory-safe despite holding by-number groups."""
    by_num: dict[str, list[dict[str, Any]]] = {}
    for ref in refs:
        by_num.setdefault(ref["sos_id"], []).append(ref)

    deduped: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for sos_id in sorted(by_num):
        group = by_num[sos_id]
        variants = {tuple(r.get(f) for f in _CONFLICT_FIELDS): r for r in group}
        if len(variants) == 1:
            deduped.append(next(iter(variants.values())))
        else:
            conflicts.append({
                "sos_id": sos_id,
                "reason": "casos_row_conflict",
                "variants": [
                    {"display_label": dl, "entity_type": et}
                    for (dl, et) in sorted(variants)
                ],
            })
    return deduped, conflicts


# ---------------------------------------------------------------------------
# Unit 2 — significant-token pre-block + union candidate generation (Predeclared 3)
# ---------------------------------------------------------------------------

# Corporate stopwords dropped before significant-token blocking — generic tokens
# that carry no disambiguating signal (so the block keys on "ghilotti"/"miller",
# not "company"/"group").
_CORPORATE_STOPWORDS = frozenset({
    "inc", "incorporated", "llc", "corp", "corporation", "company", "co",
    "group", "lp", "llp", "the", "and", "of", "jv", "fund",
})

# token-overlap candidate strength (review-only; ranks below the resolver's
# normalized-name-exact 0.9 / difflib>=0.85 candidates). Never an auto-approver.
_TOKEN_OVERLAP_STRENGTH = 0.5

# entity-status rank for the deterministic cap sort (Active first).
_STATUS_RANK = {"active": 0}


def significant_tokens(name: str) -> set[str]:
    """`_normalize_name` tokens minus the corporate stopwords — the blocking key."""
    return {t for t in _normalize_name(name).split() if t not in _CORPORATE_STOPWORDS}


def _status_rank(status: str) -> int:
    s = (status or "").strip().lower()
    if s in _STATUS_RANK:
        return _STATUS_RANK[s]
    if s.startswith("suspended"):
        return 1
    if s.startswith("terminated") or s.startswith("converted"):
        return 2
    return 3


def _resolver_candidates(refs, existing):
    """Resolver path: normalized-name-exact / difflib>=0.85 → signal_strength
    candidates (the resolver emits `confidence`; the adapter renames it)."""
    _edges, raw = propose_org_resolutions(refs, [existing], identity_keys=("sos_id",))
    out = []
    for cand in raw:
        c = normalize_resolution_candidate_for_artifact(cand)  # confidence → signal_strength
        out.append(c)
    return out


def _token_overlap(a: set[str], b: set[str]) -> bool:
    """A review-worthy overlap: >=2 shared significant tokens, or one set ⊆ other."""
    shared = a & b
    return len(shared) >= 2 or (a and a <= b) or (b and b <= a)


def block_casos_against_existing(
    filings_lines: Iterable[str],
    existing_orgs: list[dict[str, Any]],
    *,
    cap: int = 25,
) -> dict[str, Any]:
    """Stream the Filings export, pre-block on significant tokens, and generate the
    UNION of resolver + token-overlap queued candidates per existing org (capped).

    Memory-safe: only SOS refs that share a significant token with some existing
    org are held (the matched buckets), never the full file."""
    register_sos_id_normalizer()
    existing_tokens = {e["id"]: significant_tokens(e["display_label"]) for e in existing_orgs}
    existing_by_id = {e["id"]: e for e in existing_orgs}
    token_index: dict[str, list[str]] = {}
    for eid, toks in existing_tokens.items():
        for t in toks:
            token_index.setdefault(t, []).append(eid)

    # Stream → per-existing buckets of matched SOS rows (a LIST per existing: each
    # matched row is added once, so a same-number CONFLICT pair lands as two refs
    # and `dedupe_casos_refs` can see/flag it — keying by sos_id here would drop
    # the second conflict row before detection).
    buckets: dict[str, list[dict[str, Any]]] = {e["id"]: [] for e in existing_orgs}
    for ref, _skip in parse_casos_filings(filings_lines):
        if ref is None:
            continue
        sos_toks = significant_tokens(ref["display_label"])
        matched: set[str] = set()
        for t in sos_toks:
            matched.update(token_index.get(t, ()))
        for eid in matched:
            buckets[eid].append(ref)

    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    capped: list[dict[str, Any]] = []
    pool_pairs = 0

    for eid, bucket in buckets.items():
        if not bucket:
            continue
        existing = existing_by_id[eid]
        refs, bucket_conflicts = dedupe_casos_refs(bucket)
        conflicts.extend(bucket_conflicts)
        pool_pairs += len(refs)

        # (a) resolver path
        resolver_cands = _resolver_candidates(refs, existing)
        resolved_sos = set()
        merged: list[dict[str, Any]] = []
        ref_by_id = {r["id"]: r for r in refs}
        for c in resolver_cands:
            ref = ref_by_id.get(c["subject_ref"])
            if ref is None:
                continue
            resolved_sos.add(ref["sos_id"])
            merged.append({
                **c,
                "sos_id": ref["sos_id"],
                "status": "queued",
                "entity_status": ref["entity_status"],
            })
        # (b) token-overlap path — only for refs the resolver did not already pick
        e_toks = existing_tokens[eid]
        for ref in refs:
            if ref["sos_id"] in resolved_sos:
                continue
            if _token_overlap(significant_tokens(ref["display_label"]), e_toks):
                merged.append({
                    "subject_ref": ref["id"],
                    "candidate_ref": eid,
                    "sos_id": ref["sos_id"],
                    "signals": ["significant_token_overlap"],
                    "signal_strength": _TOKEN_OVERLAP_STRENGTH,
                    "status": "queued",
                    "entity_status": ref["entity_status"],
                    "evidence_record_ids": list(ref["evidence_record_ids"]),
                })

        # deterministic cap sort: (-signal_strength, status_rank, sos_id)
        merged.sort(key=lambda c: (-c["signal_strength"], _status_rank(c["entity_status"]), c["sos_id"]))
        if len(merged) > cap:
            capped.append({"candidate_ref": eid, "dropped": len(merged) - cap})
            merged = merged[:cap]
        candidates.extend(merged)

    return {
        "candidates": candidates,
        "pool_size": pool_pairs,
        "conflicts": conflicts,
        "capped": capped,
    }


# Register at import so any importer of this module can use the `sos_id` key.
register_sos_id_normalizer()
