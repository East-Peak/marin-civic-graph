"""Tests for scripts/build_dual_role_org_stubs.py.

The M2d dual-role read model extracts funding-in legs PER INPUT CLASS from the
funding envelope's OWN nodes (build_dual_role_candidates._merge_nodes_across_classes
fails loud on a same-id/divergent-payload node, by design). The County funding
ingestor, given --approved-resolutions, points TO_TARGET at canonical org-* ids
but does NOT re-emit those Organization nodes (they live in the live graph). So
the join needs an "org-stubs" funding dir that supplies those recipient
Organization nodes WITHOUT colliding with the influence side. This helper builds
it: influence Organization nodes are copied VERBATIM (guaranteeing byte-identity
across classes), and funding-only recipients absent from influence are
synthesized from the canonical org export. The suite leaves git status untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_dual_role_org_stubs import (  # noqa: E402
    build_org_stub_nodes,
    main,
)


def _org(node_id, label, **props):
    return {
        "id": node_id,
        "node_type": "Organization",
        "labels": ["Organization"],
        "display_label": label,
        "properties": props,
    }


def test_copies_influence_organization_nodes_verbatim_excluding_non_orgs():
    org = {
        "id": "org-aspen-company",
        "node_type": "Organization",
        "labels": ["Organization"],
        "display_label": "Aspen Company",
        "properties": {},
        "source_bundle_ids": ["marin-county-campaign-finance__2026-04-14"],
        "source_sections": ["contributors"],
    }
    influence = [
        org,
        {"id": "moneyflow-1", "node_type": "MoneyFlow", "labels": ["MoneyFlow"],
         "display_label": "contribution $1", "properties": {"amount": 1.0}},
        {"id": "person-1", "node_type": "Person", "labels": ["Person"],
         "display_label": "Jane Doe", "properties": {}},
    ]

    nodes = build_org_stub_nodes(influence, recipient_org_ids=set(), org_export_by_id={})

    assert nodes == [org]  # only the Organization, copied byte-for-byte (superset keys intact)


def test_synthesizes_funding_only_recipient_absent_from_influence():
    influence = [_org("org-aspen-company", "Aspen Company")]
    export = {
        "org-homeward-bound-of-marin": {
            "id": "org-homeward-bound-of-marin",
            "display_label": "Homeward Bound of Marin",
            "ein": "941234567",
            "degree": 9,
            "irs_subsection_class": "charity",
            "unrelated_field": "must-not-leak",
        }
    }

    nodes = build_org_stub_nodes(
        influence,
        recipient_org_ids={"org-homeward-bound-of-marin"},
        org_export_by_id=export,
    )

    by_id = {n["id"]: n for n in nodes}
    assert by_id["org-aspen-company"] == influence[0]  # verbatim, unchanged
    synth = by_id["org-homeward-bound-of-marin"]
    assert synth == {
        "id": "org-homeward-bound-of-marin",
        "node_type": "Organization",
        "labels": ["Organization"],
        "display_label": "Homeward Bound of Marin",
        "properties": {"ein": "941234567", "degree": 9, "irs_subsection_class": "charity"},
    }


def test_recipient_in_influence_is_not_synthesized():
    # A recipient that already appears in influence must use the influence node
    # verbatim (never a divergent synthesized copy that would fail M2d's loader).
    influence = [_org("org-bank-of-marin", "Bank of Marin")]
    export = {"org-bank-of-marin": {"id": "org-bank-of-marin",
                                    "display_label": "DIFFERENT LABEL", "ein": "999"}}

    nodes = build_org_stub_nodes(
        influence,
        recipient_org_ids={"org-bank-of-marin"},
        org_export_by_id=export,
    )

    assert nodes == [influence[0]]  # influence wins; export label/props ignored


def test_recipient_absent_from_both_fails_loud():
    with pytest.raises(ValueError, match="org-ghost"):
        build_org_stub_nodes([], recipient_org_ids={"org-ghost"}, org_export_by_id={})


def test_output_sorted_by_id_and_deterministic():
    influence = [_org("org-zeta", "Zeta"), _org("org-alpha", "Alpha")]
    export = {"org-mid": {"id": "org-mid", "display_label": "Mid"}}
    kwargs = dict(recipient_org_ids={"org-mid"}, org_export_by_id=export)

    first = build_org_stub_nodes(influence, **kwargs)
    second = build_org_stub_nodes(influence, **kwargs)

    assert [n["id"] for n in first] == ["org-alpha", "org-mid", "org-zeta"]
    assert first == second


def test_cli_writes_envelope_dir_two_runs_byte_identical(tmp_path):
    inf = tmp_path / "influence"
    inf.mkdir()
    (inf / "nodes.jsonl").write_text(
        json.dumps(_org("org-bank-of-marin", "Bank of Marin"), sort_keys=True) + "\n"
        + json.dumps({"id": "mf-1", "node_type": "MoneyFlow", "labels": ["MoneyFlow"],
                      "display_label": "x", "properties": {}}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (inf / "edges.jsonl").write_text("", encoding="utf-8")
    approved = tmp_path / "approved.jsonl"
    approved.write_text(
        json.dumps({"subject_ref": "marincontract-recipient-bank-of-marin",
                    "candidate_ref": "org-bank-of-marin", "status": "approved"}) + "\n"
        + json.dumps({"subject_ref": "marincontract-recipient-canal-alliance",
                      "candidate_ref": "org-canal-alliance", "status": "approved"}) + "\n",
        encoding="utf-8",
    )
    export = tmp_path / "orgs.json"
    export.write_text(json.dumps([
        {"id": "org-canal-alliance", "display_label": "Canal Alliance", "degree": 5},
    ]), encoding="utf-8")
    out = tmp_path / "org-stubs"

    main([
        "--influence-out", str(inf),
        "--approved-resolutions", str(approved),
        "--org-export", str(export),
        "--out-dir", str(out),
    ])

    nodes = [json.loads(l) for l in (out / "nodes.jsonl").read_text().splitlines() if l.strip()]
    ids = [n["id"] for n in nodes]
    assert ids == ["org-bank-of-marin", "org-canal-alliance"]  # sorted; MoneyFlow excluded
    assert (out / "edges.jsonl").read_text() == ""
    first_bytes = (out / "nodes.jsonl").read_bytes()
    main([
        "--influence-out", str(inf),
        "--approved-resolutions", str(approved),
        "--org-export", str(export),
        "--out-dir", str(out),
    ])
    assert (out / "nodes.jsonl").read_bytes() == first_bytes
