"""Tests for scripts/build_county_vendor_orgs.py — County Attribution Phase A.

Unit 1: build a canonical vendor `Organization` node per unapproved recipient
group (id = `org-` + recipient_group_id so it routes via the `org-` prefix;
name + provenance only — explicit person/address property denylist). Exclusion is
the approved group_ids ONLY (an existing-org name match still gets a node — it is
a resolver candidate, not an attributed state).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_county_vendor_orgs import build_vendor_org_nodes  # noqa: E402

_DENIED_KEY_SUBSTRINGS = ("person", "address", "street", "zip", "phone")


def _group(slug, label, *, kinds=("org_token_present",), depts=("Public Works",),
           moneyflows=("mf-1",)):
    gid = f"marincontract-recipient-{slug}"
    return gid, {
        "group_id": gid,
        "resolved_names": [label],
        "raw_variants": [label],
        "moneyflow_ids": list(moneyflows),
        "data_portal_ids": [m.replace("mf-", "") for m in moneyflows],
        "record_ids": [],
        "departments": list(depts),
        "recipient_kind_hints": list(kinds),
        "moneyflow_ids_by_variant": {label: list(moneyflows)},
        "display_label": label,
    }


def _groups(*pairs):
    return dict(pairs)


def test_builds_one_vendor_org_node_per_unapproved_group():
    groups = _groups(
        _group("vivalon", "Vivalon"),
        _group("spahr-center", "Spahr Center"),
    )
    nodes = build_vendor_org_nodes(groups, approved_group_ids=set())
    assert len(nodes) == 2
    n = {x["id"]: x for x in nodes}["org-marincontract-recipient-vivalon"]
    assert n["node_type"] == "Organization"
    assert n["labels"] == ["Organization"]
    assert n["display_label"] == "Vivalon"
    assert n["properties"]["source"] == "marin_county_open_data"
    assert n["properties"]["county_recipient_group_id"] == "marincontract-recipient-vivalon"
    assert n["properties"]["not_full_checkbook"] is True


def test_id_uses_org_prefix_for_routing():
    groups = _groups(_group("west-marin-senior-services", "West Marin Senior Services"))
    [node] = build_vendor_org_nodes(groups, approved_group_ids=set())
    assert node["id"] == "org-marincontract-recipient-west-marin-senior-services"


def test_excludes_only_approved_group_ids():
    approved_gid, approved_g = _group("approved-vendor", "Approved Vendor")
    exact_gid, exact_g = _group("dance-palace", "Dance Palace")  # name-matches an existing org
    plain_gid, plain_g = _group("huckleberry", "Huckleberry Youth Programs")
    groups = _groups((approved_gid, approved_g), (exact_gid, exact_g), (plain_gid, plain_g))
    nodes = build_vendor_org_nodes(groups, approved_group_ids={approved_gid})
    ids = {n["id"] for n in nodes}
    # ONLY the approved group is excluded; the existing-org name match still gets a node
    assert "org-" + approved_gid not in ids
    assert "org-" + exact_gid in ids
    assert "org-" + plain_gid in ids


def test_property_keys_have_no_person_or_address_field():
    # person-vendors are modeled as businesses, but NO home/address/phone field
    # may ever land on a vendor org (the slash classifier exposes person_side).
    groups = _groups(_group("smith-john", "Smith, John", kinds=("person_name_pattern",)))
    [node] = build_vendor_org_nodes(groups, approved_group_ids=set())
    for key in node["properties"]:
        low = key.lower()
        assert all(bad not in low for bad in _DENIED_KEY_SUBSTRINGS), key
        assert "contract_contact_person" not in low and "person_side" not in low


# --------------------------------------------------------------------------
# Unit 2 — TO_TARGET edges (one per unapproved MoneyFlow) + DUAL tie-out
# --------------------------------------------------------------------------
from decimal import Decimal  # noqa: E402

from build_county_vendor_orgs import (  # noqa: E402
    build_vendor_to_target_edges,
    summarize_attribution,
)
from ingest_marin_county_contracts import moneyflow_id  # noqa: E402


def _row(dpid, amount, vendor):
    return {"month_year": "2024-01", "contract_number": "C1", "department": "Public Works",
            "vendor_name_raw": vendor, "amount": amount, "data_portal_id": dpid}


def test_to_target_edge_per_unapproved_moneyflow():
    approved_gid, approved_g = _group("approved-co", "Approved Co", moneyflows=("mf-9",))
    g1id, g1 = _group("vivalon", "Vivalon", moneyflows=("mf-1", "mf-2"))
    g2id, g2 = _group("spahr", "Spahr Center", moneyflows=("mf-3",))
    groups = _groups((approved_gid, approved_g), (g1id, g1), (g2id, g2))
    edges = build_vendor_to_target_edges(groups, approved_group_ids={approved_gid})
    assert len(edges) == 3  # 2 + 1; the approved group's MoneyFlow gets no Phase-A edge
    e = edges[0]
    assert e["relationship_type"] == "TO_TARGET"
    assert e["source_id"].startswith("mf-")  # MoneyFlow is the source
    assert {x["target_id"] for x in edges} == {
        "org-marincontract-recipient-vivalon", "org-marincontract-recipient-spahr"}
    assert all(x["properties"]["county_recipient_group_id"] for x in edges)


def test_dual_tie_out_edge_count_and_dollars_with_missing_amount():
    # vivalon: mf-1 $100, mf-2 missing; spahr: mf-3 $50; approved-co: mf-9 $7 (excluded $)
    g1id, g1 = _group("vivalon", "Vivalon", moneyflows=("mf-1", "mf-2"))
    g2id, g2 = _group("spahr", "Spahr Center", moneyflows=("mf-3",))
    aid, ag = _group("approved-co", "Approved Co", moneyflows=("mf-9",))
    groups = _groups((g1id, g1), (g2id, g2), (aid, ag))
    rows = [_row("1", Decimal("100"), "Vivalon"), _row("2", None, "Vivalon"),
            _row("3", Decimal("50"), "Spahr Center"), _row("9", Decimal("7"), "Approved Co")]
    # the fixture mids must equal moneyflow_id(dpid); align them
    for g, dpids in ((g1, ["1", "2"]), (g2, ["3"]), (ag, ["9"])):
        g["moneyflow_ids"] = [moneyflow_id(d) for d in dpids]
    s = summarize_attribution(rows, groups, approved_group_ids={aid})
    assert s["new_vendor_orgs"] == 2
    assert s["new_edges"] == 3                  # mf-1, mf-2, mf-3
    assert s["new_missing_amount_edges"] == 1   # mf-2
    assert s["new_dollars"] == 150              # 100 + 50 (missing excluded)
    assert s["approved_dollars"] == 7
    assert s["total_dollars"] == 157


# --------------------------------------------------------------------------
# Unit 3 — dedup-SAFETY: vendor orgs are real dedup-able nodes; an existing-org
# name match gets a node AND surfaces as a candidate (never excluded/auto-linked);
# honest about the first-token-block limit (hard keys in Phase B catch the rest).
# --------------------------------------------------------------------------
from build_county_vendor_orgs import vendor_org_id  # noqa: E402
from dedup_org_candidates import is_anchor, name_tier_candidates  # noqa: E402


def test_vendor_org_is_a_real_dedupable_org_not_an_anchor():
    assert is_anchor(vendor_org_id("marincontract-recipient-vivalon")) is False


def test_vendor_matching_existing_org_surfaces_as_dedup_name_candidate():
    gid, g = _group("vivalon", "Vivalon")
    [vendor] = build_vendor_org_nodes(_groups((gid, g)), approved_group_ids=set())
    existing = {"id": "org-vivalon", "display_label": "Vivalon"}
    cands = name_tier_candidates([vendor, existing])
    linked = {(c["subject_ref"], c["candidate_ref"]) for c in cands}
    assert ("org-marincontract-recipient-vivalon", "org-vivalon") in linked \
        or ("org-vivalon", "org-marincontract-recipient-vivalon") in linked
    assert vendor["id"] == "org-marincontract-recipient-vivalon"  # node exists, not excluded


def test_first_token_block_misses_marinlink_variant_documented_limit():
    # "Marinlink" (first token marinlink) vs existing "Marin Link" (first token
    # marin) — the name tier blocks by first token, so this real near-match is
    # MISSED here (Phase B hard keys catch it). Honest limit, never a silent dup.
    gid, g = _group("marinlink", "Marinlink")
    [vendor] = build_vendor_org_nodes(_groups((gid, g)), approved_group_ids=set())
    existing = {"id": "org-marin-link", "display_label": "Marin Link"}
    assert name_tier_candidates([vendor, existing]) == []


# --------------------------------------------------------------------------
# Unit 4 — envelope writer + operator-gated load (db-scoped, no top-level neo4j)
# --------------------------------------------------------------------------
import json  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from build_county_vendor_orgs import write_envelope, load_envelope  # noqa: E402


class _FakeSession:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, *a, **k): return None


def _recording_driver():
    driver = MagicMock()
    calls = {"database": "__UNSCOPED__"}
    def session(**kw):
        calls["database"] = kw.get("database", "__UNSCOPED__")
        return _FakeSession()
    driver.session.side_effect = session
    return driver, calls


def test_write_envelope_roundtrips(tmp_path):
    nodes = [{"id": "org-marincontract-recipient-x", "node_type": "Organization",
              "labels": ["Organization"], "display_label": "X", "properties": {}}]
    edges = [{"source_id": "mf-1", "target_id": "org-marincontract-recipient-x",
              "relationship_type": "TO_TARGET", "properties": {}}]
    write_envelope(nodes, edges, tmp_path)
    rn = [json.loads(l) for l in (tmp_path / "nodes.jsonl").read_text().splitlines() if l.strip()]
    re_ = [json.loads(l) for l in (tmp_path / "edges.jsonl").read_text().splitlines() if l.strip()]
    assert rn == nodes and re_ == edges


def test_load_envelope_is_database_scoped(tmp_path):
    nodes = [{"id": "org-marincontract-recipient-x", "node_type": "Organization",
              "labels": ["Organization"], "display_label": "X", "properties": {}}]
    edges = [{"source_id": "mf-1", "target_id": "org-marincontract-recipient-x",
              "relationship_type": "TO_TARGET", "properties": {}}]
    write_envelope(nodes, edges, tmp_path)
    driver, calls = _recording_driver()
    summary = load_envelope(driver, tmp_path, database="scratchdb")
    assert calls["database"] == "scratchdb"  # never the default/live DB
    assert summary == {"nodes_loaded": 1, "edges_loaded": 1}


def test_module_has_no_top_level_neo4j_import():
    src = (Path(__file__).resolve().parents[2] / "scripts" / "build_county_vendor_orgs.py").read_text()
    for line in src.splitlines():
        # module-level (unindented) only — a lazy import inside a function is fine
        assert not line.startswith(("import neo4j", "from neo4j")), line


# --------------------------------------------------------------------------
# Unit 5 — coverage report + REAL e2e (executed, not skipped) on the staged CSV
# --------------------------------------------------------------------------
from build_county_vendor_orgs import coverage_report, _load_approved_group_ids  # noqa: E402
from ingest_marin_county_contracts import parse_contract_rows, build_recipient_groups  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_CSV = _ROOT / "data" / "raw" / "marin-county-delegated-contracts" / "2026-06-10" / "delegated-contracts.csv"
_APPROVED = _ROOT / "data" / "review" / "county" / "approved-resolutions.jsonl"


def test_e2e_real_county_csv_attribution():
    assert _CSV.is_file() and _APPROVED.is_file(), "BLOCKED: staged County inputs missing"
    rows = parse_contract_rows(_CSV)
    groups = build_recipient_groups(rows)
    approved = _load_approved_group_ids(_APPROVED)
    assert len(approved) == 43

    report = coverage_report(rows, groups, approved_group_ids=approved)
    assert report["groups_total"] == 2130
    assert report["new_vendor_orgs"] == 2087
    assert report["new_edges"] == 6543
    assert report["new_missing_amount_edges"] == 17
    assert report["new_dollars"] == 134_468_767
    assert report["approved_dollars"] == 6_769_405
    assert report["total_dollars"] == 141_238_172          # ties to the County total
    assert report["person_vendor_orgs"] == 149             # person-vendors included as businesses
    assert report["denylist_clean"] is True                # no person/address field on any vendor org

    nodes = build_vendor_org_nodes(groups, approved_group_ids=approved)
    edges = build_vendor_to_target_edges(groups, approved_group_ids=approved)
    assert len(nodes) == 2087 and len(edges) == 6543
    assert all(n["id"].startswith("org-marincontract-recipient-") for n in nodes)
    assert all(e["relationship_type"] == "TO_TARGET" and e["source_id"] for e in edges)
