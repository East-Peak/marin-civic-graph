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
