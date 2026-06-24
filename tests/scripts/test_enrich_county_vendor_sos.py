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


# --------------------------------------------------------------------------
# Unit 3 — EXACT-schema whitelist (primary redaction guard) + scan_for_forbidden
# (secondary). CA-SOS carries home addresses — they must NEVER reach an artifact.
# --------------------------------------------------------------------------
from enrich_casos_keys import scan_for_forbidden, PUBLISHABLE_FIELDS  # noqa: E402

_CANDIDATE_KEYS = {
    "subject_ref", "candidate_ref", "signals", "confidence", "status",
    "evidence_record_ids", "vendor_ref", "sos_anchor_ref", "sos_ref",
    "individual_agent", "needs_careful_review",
}


def test_candidate_has_exact_whitelist_schema():
    vendors = [_vendor("org-v", "Ghilotti Construction")]
    out = resolve_vendor_sos(vendors, lambda: iter([_H, _row("Ghilotti Construction Inc", "1111111")]))
    [c] = out["candidates"]
    assert set(c) == _CANDIDATE_KEYS                       # PRIMARY guard: no stray key
    assert set(c["sos_ref"]) <= set(PUBLISHABLE_FIELDS)    # nested sos_ref is whitelist-only


def test_output_redaction_clean_even_when_file_has_address_columns():
    # the file row carries a PRINCIPAL_ADDRESS with a sentinel; parse_casos_filings
    # never reads it → it must not appear anywhere in the output (SECONDARY guard).
    header = _H + "*|*PRINCIPAL_ADDRESS"
    sentinel = "REDACT" + "_ME"  # built at runtime so no forbidden literal lands in committed source
    row = _row("Ghilotti Construction Inc", "1111111") + "*|*" + sentinel  # in the IGNORED address column
    out = resolve_vendor_sos([_vendor("org-v", "Ghilotti Construction")], lambda: iter([header, row]))
    assert out["candidates"], "expected the match (address column present but ignored)"
    assert scan_for_forbidden(out) == []   # parse never read PRINCIPAL_ADDRESS → sentinel absent → clean


# --------------------------------------------------------------------------
# Unit 4 — individual-agent 2-pass: candidate-FILTERED Agents.csv stream → per
# candidate natural-person-agent flag; not_staged waiver when Agents absent.
# --------------------------------------------------------------------------
from enrich_county_vendor_sos import attach_individual_agent_flags  # noqa: E402

_AGENTS_H = "ENTITY_NUM*|*AGENT_TYPE"


def test_individual_agent_applied_filtered_to_hit_sos():
    cands = [{"sos_ref": {"sos_id": "1111111"}, "individual_agent": None},
             {"sos_ref": {"sos_id": "2222222"}, "individual_agent": None}]
    agents = [_AGENTS_H,
              "1111111*|*Individual Agent",        # natural person → flag
              "2222222*|*Registered Corporate Agent 1505",
              "9999999*|*Individual Agent"]         # non-hit sos_id → ignored
    n = attach_individual_agent_flags(cands, iter(agents))
    assert n == 1
    assert cands[0]["individual_agent"] is True and cands[1]["individual_agent"] is False


def test_resolve_vendor_sos_agents_not_staged_waiver():
    out = resolve_vendor_sos([_vendor("org-v", "Ghilotti Construction")],
                             lambda: iter([_H, _row("Ghilotti Construction Inc", "1111111")]))
    assert out["stats"]["individual_agent_status"] == "not_staged"
    assert out["candidates"][0]["individual_agent"] is None   # waived, not fabricated


def test_resolve_vendor_sos_agents_applied():
    out = resolve_vendor_sos(
        [_vendor("org-v", "Ghilotti Construction")],
        lambda: iter([_H, _row("Ghilotti Construction Inc", "1111111")]),
        agents_factory=lambda: iter([_AGENTS_H, "1111111*|*Individual Agent"]),
    )
    assert out["stats"]["individual_agent_status"] == "applied"
    assert out["stats"]["individual_agent_count"] == 1
    assert out["candidates"][0]["individual_agent"] is True


# --------------------------------------------------------------------------
# Unit 5 — build_sos_attach (assertion + SAME_AS) → surfaces sos_id via enriched
# export → feeds the deterministic dedup tier (the payoff).
# --------------------------------------------------------------------------
from enrich_county_vendor_sos import build_sos_attach  # noqa: E402
from export_existing_orgs import org_ref_from_enriched_record  # noqa: E402
from dedup_org_candidates import deterministic_dedup_assertions  # noqa: E402

_CAND_SOS = {"subject_ref": "org-casos-1234567",
             "candidate_ref": "org-marincontract-recipient-ghilotti",
             "evidence_record_ids": ["record-casos-1234567"],
             "sos_ref": {"sos_id": "1234567", "display_label": "Ghilotti Construction Inc"}}
_VENDOR_SOS = {"id": "org-marincontract-recipient-ghilotti", "display_label": "Ghilotti Construction"}


def test_build_sos_attach_yields_assertion_and_same_as():
    a, same_as = build_sos_attach(_CAND_SOS, _VENDOR_SOS, reviewer="stuart@eastpeak.cc",
                                  decided_at="2026-06-24", policy_version="v1")
    assert a["status"] == "approved" and a["basis"] == "operator_approved_sos_id"
    assert a["subject_ref"] == "org-casos-1234567"                       # anchor is subject
    assert a["target_ref"] == "org-marincontract-recipient-ghilotti"
    assert same_as["source_id"] == "org-casos-1234567"
    assert same_as["target_id"] == "org-marincontract-recipient-ghilotti"
    assert same_as["relationship_type"] == "SAME_AS"
    assert same_as["properties"]["assertion_id"] == a["id"]


def test_attach_surfaces_sos_id_via_enriched_export():
    a, same_as = build_sos_attach(_CAND_SOS, _VENDOR_SOS, reviewer="stuart@eastpeak.cc",
                                  decided_at="2026-06-24", policy_version="v1")
    link = {"linked_node_id": same_as["source_id"], "edge_source_id": same_as["source_id"],
            "edge_target_id": same_as["target_id"], "assertion_id": a["id"],
            "ein": None, "uei": None, "sos_id": "1234567", "committee_id": None,
            "irs_subsection_class": None, "entity_status": None, "entity_type": None,
            "formation_date": None}
    record = {"id": _VENDOR_SOS["id"], "display_label": _VENDOR_SOS["display_label"],
              "own_ein": None, "own_uei": None, "own_sos_id": None, "own_committee_id": None,
              "own_source": None, "own_irs_subsection_class": None, "degree": 1, "key_links": [link]}
    ref = org_ref_from_enriched_record(record, {a["id"]: a})
    assert ref["sos_id"] == "1234567"


def test_approved_sos_id_feeds_deterministic_dedup():
    refs = [
        {"id": "org-marincontract-recipient-ghilotti", "display_label": "Ghilotti Construction", "sos_id": "1234567"},
        {"id": "org-ghilotti-construction-company", "display_label": "Ghilotti Construction Company", "sos_id": "1234567"},
    ]
    asserts = deterministic_dedup_assertions(refs, reviewer="dedup", policy_version="v1")
    assert any(x["basis"] == "org_dedup_key_exact" for x in asserts)


# --------------------------------------------------------------------------
# Unit 6 — coverage report (Pre 10) + CLI (queued candidates + coverage)
# --------------------------------------------------------------------------
import json as _json  # noqa: E402
from enrich_county_vendor_sos import coverage_report, main  # noqa: E402


def test_coverage_report_tiers_and_token_vs_compact():
    vendors = [_vendor("org-v-ghilotti", "Ghilotti Construction"),
               _vendor("org-v-marinlink", "Marin Link")]
    lines = [_H, _row("Ghilotti Construction Inc", "1111111"), _row("Marinlink", "2222222")]
    out = resolve_vendor_sos(vendors, lambda: iter(lines))
    rep = coverage_report(out, vendors)
    assert rep["vendor_orgs_total"] == 2
    assert rep["with_sos_candidate"] == 2
    assert rep["exact_tier"] == 1 and rep["difflib_tier"] == 1        # Ghilotti exact, Marinlink difflib
    assert rep["token_matched"] == 1 and rep["compact_only"] == 1     # Marin Link blocked only via compact
    assert rep["conflicts"] == 0 and rep["individual_agent_status"] == "not_staged"
    assert "max_per_vendor_hits" in rep and "resolver_pairs_evaluated" in rep


def test_cli_writes_candidates_and_coverage(tmp_path):
    filings = tmp_path / "Filings.csv"
    filings.write_text("\n".join([_H, _row("Ghilotti Construction Inc", "1111111")]), encoding="utf-8")
    out_dir = tmp_path / "out"
    rc = main(["--vendors-inline", _json.dumps([{"id": "org-v", "display_label": "Ghilotti Construction"}]),
               "--filings", str(filings), "--out-dir", str(out_dir)])
    assert rc == 0
    cands = [_json.loads(l) for l in (out_dir / "vendor-sos-candidates.jsonl").read_text().splitlines() if l.strip()]
    assert cands and cands[0]["status"] == "queued" and cands[0]["sos_ref"]["sos_id"] == "1111111"
    rep = _json.loads((out_dir / "coverage.json").read_text())
    assert rep["with_sos_candidate"] == 1
    # the written artifacts carry NO person/address data
    from enrich_casos_keys import scan_for_forbidden
    assert scan_for_forbidden(cands) == [] and scan_for_forbidden(rep) == []


# --------------------------------------------------------------------------
# Unit 7 — env-gated real e2e over the full 9.44M-row Filings.csv
# --------------------------------------------------------------------------
import os  # noqa: E402
import pytest  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_FILINGS = _ROOT / "data" / "raw" / "ca-sos" / "Filings.csv"
_AGENTS = _ROOT / "data" / "raw" / "ca-sos" / "Agents.csv"
_CSV = _ROOT / "data" / "raw" / "marin-county-delegated-contracts" / "2026-06-10" / "delegated-contracts.csv"
_APPROVED = _ROOT / "data" / "review" / "county" / "approved-resolutions.jsonl"


@pytest.mark.skipif(not os.environ.get("RUN_PHASE_C_E2E"), reason="slow real e2e — set RUN_PHASE_C_E2E=1")
def test_e2e_real_casos_sos_coverage_redaction_and_budgets():
    import time
    from ingest_marin_county_contracts import parse_contract_rows, build_recipient_groups
    from build_county_vendor_orgs import build_vendor_org_nodes
    rows = parse_contract_rows(_CSV)
    groups = build_recipient_groups(rows)
    approved = {_json.loads(l)["subject_ref"] for l in _APPROVED.read_text().splitlines() if l.strip()}
    vorgs = [{"id": n["id"], "display_label": n["display_label"]}
             for n in build_vendor_org_nodes(groups, approved_group_ids=approved)]
    assert len(vorgs) == 2087

    def filings_factory():
        return open(_FILINGS, encoding="utf-8", errors="replace")
    agents_factory = (lambda: open(_AGENTS, encoding="utf-8", errors="replace")) if _AGENTS.is_file() else None

    t = time.time()
    out = resolve_vendor_sos(vorgs, filings_factory, agents_factory=agents_factory)
    elapsed = time.time() - t
    rep = coverage_report(out, vorgs)

    # CONCRETE budgets (Codex r3) — the lossless prefilter cut 137.6M → 224k (99.84%)
    assert out["stats"]["block_pairs_evaluated"] == 137_612_921
    assert out["stats"]["resolver_pairs_evaluated"] == 224_393      # ≪ the 10M ceiling
    assert elapsed < 5400                                            # 90-min wall-clock budget (actual ~7.6min)
    # redaction: NO person/address/agent data in ANY artifact
    assert scan_for_forbidden(out["candidates"]) == []
    assert scan_for_forbidden(out["conflicts"]) == []
    assert scan_for_forbidden(rep) == []
    # coverage (pinned exact over the 2026-06-01 staged Filings.csv)
    assert rep["with_sos_candidate"] == 1047
    assert rep["exact_tier"] == 964
    assert rep["compact_only"] == 10                                # the compact key's no-shared-token catches
    assert rep["conflicts"] == 0
    assert rep["individual_agent_status"] == "applied"
    print("PHASE-C E2E:", _json.dumps(rep))
