"""enrich_county_vendor_sos.py — Open Marin · County Attribution Phase C (CA-SOS sos_id).

Phase A created name-only County vendor `Organization` nodes (`org-marincontract-
recipient-*`); Phase B keyed the nonprofit bucket to EINs. Phase C name-resolves
ALL 2,087 vendor orgs against the staged CA Secretary-of-State Filings export
(9.44M rows) to propose `sos_id` keys, QUEUED for operator review (a name match
NEVER auto-attaches a key). CA-SOS carries natural-person home addresses — the
shipped Lane-2 redaction gate (`publishable_casos_fields` + `scan_for_forbidden` +
`individual_agent_flags`) is the load-bearing invariant.

Right-sized blocker (Stuart: "the elegant way"): the recall net is significant-token
overlap OR a SUFFIX-AWARE compact key (closes the `Marinlink`/`Marin Link` +
fused-suffix fuzzy class with no char-trigram index); a PROVABLE lossless prefilter
(`length_band_ok` + `quick_ratio≥0.85` + exact-normalize) then gates the expensive
resolver; the output is the RESOLVER tier only (exact / difflib≥0.85),
confidence-tiered. All shipped modules are CONSUMED, never edited.
"""
from __future__ import annotations

from typing import Any

from org_resolution import _NAME_SUFFIXES, _normalize_name  # consumed, never edited
from enrich_casos_keys import significant_tokens  # consumed, never edited

# Strip the EXACT suffix set `_normalize_name` strips, longest-first (so
# `incorporated` is peeled before `inc`), repeated (so a fused `...llcinc` → '').
_SUFFIXES_LONGEST_FIRST = tuple(sorted(_NAME_SUFFIXES, key=len, reverse=True))


def _strip_fused_suffix(s: str) -> str:
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES_LONGEST_FIRST:
            if len(s) > len(suf) and s.endswith(suf):
                s = s[: -len(suf)]
                changed = True
                break
    return s


def compact_key(name: str) -> str:
    """`_normalize_name` (casefold, punct→space, strip tokenized suffixes) → drop
    spaces → strip FUSED trailing suffixes. Collapses spacing + fused-suffix
    variants (`Foo LLC`/`FooLLC`/`FooLLCInc`→`foo`) so the no-shared-token fuzzy
    class blocks. Uses ONLY `_NAME_SUFFIXES` — `Cisco` (no such suffix) is safe."""
    return _strip_fused_suffix(_normalize_name(name).replace(" ", ""))


def blocks_to(sos_ref: dict[str, Any], vendor_ref: dict[str, Any]) -> bool:
    """The recall net: a SOS row blocks to a vendor iff they share ≥1 significant
    token OR have the same compact key. Over-inclusive by design — the lossless
    prefilter + resolver supply precision; this only bounds what they examine."""
    sos_name, vendor_name = sos_ref["display_label"], vendor_ref["display_label"]
    if significant_tokens(sos_name) & significant_tokens(vendor_name):
        return True
    return compact_key(sos_name) == compact_key(vendor_name)
