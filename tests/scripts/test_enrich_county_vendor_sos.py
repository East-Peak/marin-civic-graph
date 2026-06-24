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
