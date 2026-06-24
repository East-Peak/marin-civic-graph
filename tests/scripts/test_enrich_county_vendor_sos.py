"""Tests for scripts/enrich_county_vendor_sos.py — County Attribution Phase C (CA-SOS).

Unit 1: the recall blocker. `compact_key` = `_normalize_name` → strip spaces →
strip FUSED trailing suffixes using EXACTLY `org_resolution._NAME_SUFFIXES`
(repeated, longest-first), so `FooLLCInc`/`Foo LLC Inc` collide and `Marinlink`/
`Marin Link` collide — closing the no-shared-token spacing/fused-suffix fuzzy
class. `Cisco` must NOT be mauled (no `co` suffix). `blocks_to` = significant-token
overlap OR compact-key equality (the recall net; the resolver filters precision).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from enrich_county_vendor_sos import compact_key, blocks_to  # noqa: E402


def _r(label):
    return {"id": "x", "display_label": label}


def test_compact_key_collapses_spacing_and_fused_suffix_variants():
    assert compact_key("Marin Link") == compact_key("Marinlink")
    assert compact_key("Foo LLC") == compact_key("FooLLC")
    assert compact_key("Foo LLC Inc") == compact_key("FooLLCInc") == "foo"  # repeated strip


def test_compact_key_does_not_maul_cisco():
    # _NAME_SUFFIXES has no "co"/"company" → a real name ending in those letters is safe
    assert compact_key("Cisco") == "cisco"


def test_blocks_to_via_compact_key():
    assert blocks_to(_r("Marin Link"), _r("Marinlink")) is True       # no shared token; compact match
    assert blocks_to(_r("Foo LLC"), _r("FooLLC")) is True


def test_blocks_to_via_significant_token():
    assert blocks_to(_r("Marin Construction Co"), _r("Marin Builders")) is True  # shared "marin"


def test_blocks_to_false_when_no_token_and_no_compact():
    assert blocks_to(_r("Apple Orchard"), _r("Banana Grove")) is False


# --------------------------------------------------------------------------
# Unit 2 — resolve_vendor_sos: stream → block → LOSSLESS prefilter → resolver-tier
# hits only (raw direction, queued); pass-2 blocks_to conflict (casos_row_conflict).
# --------------------------------------------------------------------------
from enrich_county_vendor_sos import resolve_vendor_sos  # noqa: E402

_H = "ENTITY_NAME*|*ENTITY_NUM*|*ENTITY_STATUS*|*ENTITY_TYPE*|*INITIAL_FILING_DATE*|*PRINCIPAL_CITY*|*PRINCIPAL_STATE"


def _row(name, num, status="ACTIVE", etype="Stock Corporation", date="1990-01-01", city="San Rafael", state="CA"):
    return f"{name}*|*{num}*|*{status}*|*{etype}*|*{date}*|*{city}*|*{state}"


def _vendor(vid, label):
    return {"id": vid, "display_label": label}


def test_resolve_vendor_sos_resolver_tier_hits_raw_direction():
    vendors = [_vendor("org-marincontract-recipient-ghilotti-construction", "Ghilotti Construction"),
               _vendor("org-marincontract-recipient-marinlink", "Marin Link")]
    lines = [_H,
             _row("Ghilotti Construction Inc", "1111111"),       # Inc stripped → exact-normalize match
             _row("Marinlink", "2222222"),                       # compact-key match
             _row("Apple Inc", "3333333"),                       # no block, no match
             _row("Marin Yacht Club", "4444444")]                # shares "marin" token, low difflib → prefilter/resolver cut
    out = resolve_vendor_sos(vendors, lambda: iter(lines))
    by_vendor = {c["vendor_ref"]: c for c in out["candidates"]}
    assert set(by_vendor) == {"org-marincontract-recipient-ghilotti-construction",
                              "org-marincontract-recipient-marinlink"}
    g = by_vendor["org-marincontract-recipient-ghilotti-construction"]
    assert g["subject_ref"] == "org-casos-1111111"          # RAW: sos anchor is subject
    assert g["candidate_ref"] == "org-marincontract-recipient-ghilotti-construction"
    assert g["sos_anchor_ref"] == "org-casos-1111111" and g["status"] == "queued"
    assert g["sos_ref"]["sos_id"] == "1111111"
    # Marin Link surfaced only via the compact key (no shared significant token)
    assert by_vendor["org-marincontract-recipient-marinlink"]["sos_ref"]["sos_id"] == "2222222"
    # the prefilter cut the Marin Yacht Club pair (low difflib) — resolver_pairs < block_pairs
    assert out["stats"]["resolver_pairs_evaluated"] < out["stats"]["block_pairs_evaluated"]


def test_resolve_vendor_sos_never_auto_attaches():
    vendors = [_vendor("org-v", "Ghilotti Construction")]
    lines = [_H, _row("Ghilotti Construction Inc", "1111111")]
    out = resolve_vendor_sos(vendors, lambda: iter(lines))
    assert all(c["status"] == "queued" for c in out["candidates"])
    assert out.get("same_as_edges", []) == [] and out.get("assertions", []) == []


def test_resolve_vendor_sos_same_sos_id_conflict_withheld():
    # same ENTITY_NUM, two different names, both block the vendor → casos_row_conflict
    vendors = [_vendor("org-v", "Ghilotti Construction")]
    lines = [_H,
             _row("Ghilotti Construction Inc", "1111111"),
             _row("Ghilotti Construction LLC", "1111111")]
    out = resolve_vendor_sos(vendors, lambda: iter(lines))
    assert out["candidates"] == []
    assert any(c["sos_id"] == "1111111" and c["reason"] == "casos_row_conflict" for c in out["conflicts"])


def test_resolve_vendor_sos_nonblocking_same_sos_id_no_false_conflict():
    # a 2nd row with the same sos_id but a name that does NOT block the vendor must
    # NOT trigger a false conflict (dedupe_casos_refs only sees blocked rows).
    vendors = [_vendor("org-v", "Ghilotti Construction")]
    lines = [_H,
             _row("Ghilotti Construction Inc", "1111111"),
             _row("Zzz Unrelated Entity", "1111111")]   # same num, shares nothing with the vendor
    out = resolve_vendor_sos(vendors, lambda: iter(lines))
    assert [c["vendor_ref"] for c in out["candidates"]] == ["org-v"]   # candidate stands
    assert out["conflicts"] == []
