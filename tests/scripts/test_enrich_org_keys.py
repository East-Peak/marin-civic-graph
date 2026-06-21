"""Tests for scripts/enrich_org_keys.py — Unit 1: the IRS EO-BMF parser.

Identity Enrichment Lane 1, Unit 1 (Predeclared 1 + 2 of the goal doc). The
operator stages a Marin-filtered IRS Business Master File CSV; this module parses
it into keyed registry org refs for the shared resolver. The teeth:

- EIN must be EXACTLY 9 digits after stripping non-digits, or the row is skipped
  with a logged reason — never a fabricated key (the resolver would key any
  surviving digits).
- The two-digit `SUBSECTION` code maps to a SEPARATE `irs_subsection_class`
  subtype field (`"06"` -> trade_association, `"03"` -> charity, unmapped ->
  nonprofit_other) — NOT Identity Control A's `entity_class`, which stays
  `"organization"` so the egress gate's class-equality check never demotes the
  deterministic EIN merge.
- Byte-identical duplicate rows for one EIN dedupe to a single ref; rows that
  share an EIN but disagree on name/subsection are NOT first-wins — they emit a
  `bmf_row_conflict` and that EIN is WITHHELD from resolution.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from enrich_org_keys import (  # noqa: E402
    bmf_org_ref,
    irs_subsection_class,
    parse_bmf_csv,
    parse_bmf_rows,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity_enrichment"
BMF_SLICE = FIXTURES / "eo_bmf_marin_slice.csv"


# --------------------------------------------------------------------------
# irs_subsection_class — the false-friend subtype map (Predeclared 2)
# --------------------------------------------------------------------------


def test_subsection_map_pinned_codes():
    """The full pinned two-digit map — the signal that separates a c6 trade
    association from its c3 scholarship fund."""
    assert irs_subsection_class("03") == "charity"
    assert irs_subsection_class("04") == "social_welfare"
    assert irs_subsection_class("05") == "labor_ag"
    assert irs_subsection_class("06") == "trade_association"
    assert irs_subsection_class("07") == "social_club"
    assert irs_subsection_class("19") == "veterans"


def test_subsection_normalizes_leading_zeros():
    """BMF codes are two-digit strings; a stray un-padded code still maps."""
    assert irs_subsection_class("3") == "charity"
    assert irs_subsection_class("6") == "trade_association"


def test_subsection_unmapped_is_nonprofit_other_never_blank():
    assert irs_subsection_class("71") == "nonprofit_other"
    assert irs_subsection_class("") == "nonprofit_other"
    assert irs_subsection_class(None) == "nonprofit_other"


# --------------------------------------------------------------------------
# bmf_org_ref — one validated row -> one keyed registry ref
# --------------------------------------------------------------------------


def test_bmf_org_ref_shape():
    row = {
        "EIN": "941415040",
        "NAME": "MARIN BUILDERS ASSOCIATION",
        "CITY": "SAN RAFAEL",
        "STATE": "CA",
        "SUBSECTION": "06",
    }
    ref = bmf_org_ref(row)
    assert ref["id"] == "org-bmf-ein-941415040"
    assert ref["ein"] == "941415040"
    assert ref["entity_class"] == "organization"  # NOT the subtype (Codex r1 blocker 1)
    assert ref["irs_subsection_class"] == "trade_association"
    assert ref["state"] == "CA"
    assert ref["evidence_record_ids"] == ["record-bmf-941415040"]
    # display + city are operator-facing; all-caps source is cleaned up.
    assert ref["display_label"] == "Marin Builders Association"
    assert ref["city"] == "San Rafael"


# --------------------------------------------------------------------------
# parse_bmf_rows — dedupe / conflict / skip aggregation
# --------------------------------------------------------------------------


def _rows():
    return [
        {"EIN": "200879422", "NAME": "MARIN LINK INC", "CITY": "SAN RAFAEL", "STATE": "CA", "SUBSECTION": "03"},
        {"EIN": "200879422", "NAME": "MARIN LINK INC", "CITY": "SAN RAFAEL", "STATE": "CA", "SUBSECTION": "03"},
        {"EIN": "941415040", "NAME": "MARIN BUILDERS ASSOCIATION", "CITY": "SAN RAFAEL", "STATE": "CA", "SUBSECTION": "06"},
        {"EIN": "123", "NAME": "BOGUS SHORT EIN ORG", "CITY": "NOVATO", "STATE": "CA", "SUBSECTION": "03"},
        {"EIN": "946000000", "NAME": "CONFLICTED ORG ALPHA", "CITY": "FAIRFAX", "STATE": "CA", "SUBSECTION": "03"},
        {"EIN": "946000000", "NAME": "CONFLICTED ORG BETA", "CITY": "FAIRFAX", "STATE": "CA", "SUBSECTION": "06"},
    ]


def test_byte_identical_rows_dedupe_to_one_ref():
    result = parse_bmf_rows(_rows())
    marin_link = [r for r in result["refs"] if r["ein"] == "200879422"]
    assert len(marin_link) == 1


def test_non_nine_digit_ein_is_skipped_with_reason_never_keyed():
    result = parse_bmf_rows(_rows())
    assert all(r["ein"] != "123" for r in result["refs"])
    skipped = [s for s in result["skipped"] if s.get("ein_raw") == "123"]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "ein_not_9_digits"


def test_same_ein_conflicting_rows_emit_bmf_row_conflict_and_withhold():
    result = parse_bmf_rows(_rows())
    # the conflicted EIN is WITHHELD — no ref at all (never first-wins)
    assert all(r["ein"] != "946000000" for r in result["refs"])
    conflicts = [c for c in result["conflicts"] if c["ein"] == "946000000"]
    assert len(conflicts) == 1
    assert conflicts[0]["reason"] == "bmf_row_conflict"
    # the competing variants are recorded for the coverage report
    variant_names = {v["display_label"] for v in conflicts[0]["variants"]}
    assert variant_names == {"Conflicted Org Alpha", "Conflicted Org Beta"}


# --------------------------------------------------------------------------
# parse_bmf_csv — end to end on the committed fixture slice
# --------------------------------------------------------------------------


def test_parse_bmf_csv_on_fixture_slice():
    result = parse_bmf_csv(BMF_SLICE)
    by_ein = {r["ein"]: r for r in result["refs"]}

    # 5 distinct valid, non-conflicting EINs survive
    assert set(by_ein) == {
        "200879422",  # Marin Link (dedup of 2 identical rows)
        "941415040",  # Marin Builders Association (c6)
        "942540274",  # Scholarship Fund (c3)
        "237172128",  # San Geronimo Valley CC (c3)
        "941000001",  # unmapped subsection -> nonprofit_other
    }
    # the c6 trade association vs its c3 scholarship fund separate cleanly
    assert by_ein["941415040"]["irs_subsection_class"] == "trade_association"
    assert by_ein["942540274"]["irs_subsection_class"] == "charity"
    # unmapped subsection 71 -> nonprofit_other (never blank)
    assert by_ein["941000001"]["irs_subsection_class"] == "nonprofit_other"
    # the short EIN was skipped, the conflict withheld
    assert any(s["reason"] == "ein_not_9_digits" for s in result["skipped"])
    assert any(c["ein"] == "946000000" and c["reason"] == "bmf_row_conflict" for c in result["conflicts"])
