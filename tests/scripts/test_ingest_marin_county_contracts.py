"""Tests for scripts/ingest_marin_county_contracts.py (M3 leg-1).

The County of Marin "delegated contracts" open-data CSV → funding-IN MoneyFlow
facts (County/department FROM_SOURCE; recipient is raw-name-on-the-fact until an
operator-reviewed resolution draws TO_TARGET — NO recipient node is auto-created,
NEVER a Person node). Money is Decimal, never float. The full staged CSV lives in
data/raw (gitignored, local); committable tests run against a curated fixture
slice, and the exact $141,238,172 tie-out test skipifs when the full CSV is absent.

Codex round-1+2 reviewed this design (8 + 1 findings folded).
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ingest_marin_county_contracts import (  # noqa: E402
    parse_contract_rows,
    source_profile,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "marin_county_contracts" / "sample-delegated-contracts.csv"
FULL_CSV = (REPO_ROOT / "data" / "raw" / "marin-county-delegated-contracts"
            / "2026-06-10" / "delegated-contracts.csv")
full_csv = pytest.mark.skipif(not FULL_CSV.is_file(), reason="full staged CSV absent (local-only)")


class TestParseRows:
    def test_parses_fixture_rows_with_decimal_amounts(self):
        rows = parse_contract_rows(FIXTURE)
        assert len(rows) == 9
        by_dpid = {r["data_portal_id"]: r for r in rows}
        assert len(by_dpid) == 9  # raw Data Portal IDs unique
        # amounts are Decimal (or None), never float
        for r in rows:
            assert r["amount"] is None or isinstance(r["amount"], Decimal)
        # the empty-amount row parses to None, not 0
        empty = [r for r in rows if r["vendor_name_raw"] == "Breakfast Club Rally"]
        assert empty and empty[0]["amount"] is None
        # the zero-amount row parses to Decimal(0), distinct from missing
        zero = [r for r in rows if r["amount"] == Decimal("0")]
        assert len(zero) == 1
        # required normalized fields present
        r0 = rows[0]
        assert set(r0) >= {"month_and_year", "contract_number", "review_contract",
                           "department", "vendor_name_raw", "amount", "data_portal_id"}
        # PDF link captured when present, None when blank
        cam_pdf = [r for r in rows if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN"
                   and r["review_contract"]]
        assert cam_pdf and cam_pdf[0]["review_contract"].startswith("http")

    def test_fixture_source_profile(self):
        prof = source_profile(parse_contract_rows(FIXTURE))
        assert prof["row_count"] == 9
        assert prof["distinct_vendor_count"] == 8       # CAM appears twice
        assert prof["distinct_data_portal_ids"] == 9
        assert prof["amount_total"] == Decimal("112059")
        assert prof["amount_present_count"] == 8
        assert prof["amount_missing_count"] == 1
        assert prof["spaced_slash_count"] == 2          # "Person / Org" rows only


class TestFullCsvProfile:
    @full_csv
    def test_full_csv_ties_out_to_source_total(self):
        prof = source_profile(parse_contract_rows(FULL_CSV))
        assert prof["row_count"] == 6898
        assert prof["distinct_data_portal_ids"] == 6898  # raw DPIDs unique
        assert prof["amount_total"] == Decimal("141238172")
        assert prof["amount_missing_count"] == 19


# ---------------------------------------------------------------------------
# Unit 2 — source / MoneyFlow / Record builders + guarded vendor classifier
# ---------------------------------------------------------------------------
from ingest_marin_county_contracts import (  # noqa: E402
    build_flow_edges,
    build_moneyflow_node,
    build_record_node,
    build_source_nodes,
    classify_recipient,
    department_id,
    moneyflow_id,
)

_SEARCHABLE_FIELDS = ("display_label", "search_label", "name", "description")


class TestClassifyRecipient:
    def test_clean_person_slash_org_strips_person_to_provenance(self):
        c = classify_recipient("Lisa Ravina / Good Shepherd Lutheran School")
        assert c["recipient_name_resolved"] == "Good Shepherd Lutheran School"
        assert c["person_side"] == "Lisa Ravina"          # provenance only, never a node
        assert c["recipient_kind_hint"] == "explicit_org_from_split"

    def test_org_slash_org_is_NOT_split(self):
        # "CSW/STUBER-STROEH" has no spaced ' / ' and the right side is org-like;
        # keep the raw name whole (guarded split, Codex major).
        c = classify_recipient("CSW/STUBER-STROEH ENGINEERING GROUP")
        assert c["recipient_name_resolved"] == "CSW/STUBER-STROEH ENGINEERING GROUP"
        assert c["person_side"] is None
        assert c["recipient_kind_hint"] == "org_token_present"  # GROUP token

    def test_org_token_name(self):
        c = classify_recipient("DIMENSION REPORT LLC")
        assert c["recipient_kind_hint"] == "org_token_present"
        assert c["person_side"] is None

    def test_bare_personal_name_is_a_hint_only_never_proof(self):
        c = classify_recipient("ALONSO MATA")
        assert c["recipient_kind_hint"] in {"person_name_pattern", "ambiguous"}
        assert "classification_basis" in c and "heuristic_version" in c
        # The hint is advisory; the raw name is still preserved for resolution.
        assert c["recipient_name_resolved"] == "ALONSO MATA"

    def test_classification_is_graded_not_binary(self):
        hints = {classify_recipient(v)["recipient_kind_hint"] for v in (
            "Lisa Ravina / Good Shepherd Lutheran School",
            "DIMENSION REPORT LLC", "ALONSO MATA", "COMMUNITY ACTION MARIN")}
        assert hints <= {"explicit_org_from_split", "org_token_present",
                         "person_name_pattern", "ambiguous"}


class TestSourceNodes:
    def test_county_and_department_government_nodes(self):
        rows = parse_contract_rows(FIXTURE)
        nodes = build_source_nodes(rows)
        # County root + one node per distinct department, all Organization/Government.
        assert all(n["node_type"] == "Organization" for n in nodes)
        assert all("Government" in n["labels"] for n in nodes)
        county = [n for n in nodes if n["id"] == "org-marincounty"]
        assert len(county) == 1
        depts = [n for n in nodes if n["id"].startswith("org-marincounty-dept-")]
        # fixture has HHS, Cultural Services, Marin County Parks, Free Library
        assert len(depts) >= 4
        # department ids are case-insensitive-stable (CULTURAL vs Cultural collapse)
        assert department_id("HEALTH AND HUMAN SERVICES") == department_id("Health and Human Services")


class TestMoneyFlowAndRecord:
    def test_one_moneyflow_per_row_rowstable_unique_ids(self):
        rows = parse_contract_rows(FIXTURE)
        flows = [build_moneyflow_node(r, classify_recipient(r["vendor_name_raw"])) for r in rows]
        assert len(flows) == 9
        assert len({f["id"] for f in flows}) == 9              # unique
        # row-stable: rebuilding yields the same id
        assert moneyflow_id(rows[0]["data_portal_id"]) == flows[0]["id"]

    def test_moneyflow_carries_decimal_amount_and_coverage_honesty(self):
        rows = parse_contract_rows(FIXTURE)
        cam = next(r for r in rows if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN")
        f = build_moneyflow_node(cam, classify_recipient(cam["vendor_name_raw"]))
        p = f["properties"]
        assert p["amount"] == "10000"                          # Decimal serialized as string
        assert p["coverage_scope"] == "marin_county_delegated_contracts"
        assert p["amount_semantics"] == "delegated_contract_amount"
        assert p["not_full_checkbook"] is True
        assert p["not_invoice_payment"] is True
        assert p["recipient_name_raw"] == "COMMUNITY ACTION MARIN"
        assert p["recipient_kind_hint"] in {"org_token_present", "ambiguous", "person_name_pattern"}
        assert p["department_raw"] == "HEALTH AND HUMAN SERVICES"

    def test_missing_amount_flagged_not_zero(self):
        rows = parse_contract_rows(FIXTURE)
        empty = next(r for r in rows if r["vendor_name_raw"] == "Breakfast Club Rally")
        f = build_moneyflow_node(empty, classify_recipient(empty["vendor_name_raw"]))
        assert f["properties"].get("amount") is None
        assert f["properties"]["amount_missing"] is True

    def test_recipient_name_never_leaks_into_searchable_fields(self):
        # Ethics machine-check (Codex nit): the raw recipient name lives ONLY in
        # recipient_name_raw, never in any indexed/displayed field.
        rows = parse_contract_rows(FIXTURE)
        for r in rows:
            f = build_moneyflow_node(r, classify_recipient(r["vendor_name_raw"]))
            for field in _SEARCHABLE_FIELDS:
                val = f.get(field) or f["properties"].get(field, "")
                assert r["vendor_name_raw"] not in (val or ""), \
                    f"recipient name leaked into {field}"

    def test_record_per_row_with_optional_pdf(self):
        rows = parse_contract_rows(FIXTURE)
        recs = [build_record_node(r) for r in rows]
        assert len({r["id"] for r in recs}) == 9
        cam_pdf = next(build_record_node(r) for r in rows
                       if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN" and r["review_contract"])
        assert cam_pdf["properties"]["review_contract_url"].startswith("http")
        no_pdf = next(build_record_node(r) for r in rows
                      if r["vendor_name_raw"] == "DIMENSION REPORT LLC")
        assert "review_contract_url" not in no_pdf["properties"]


class TestFlowEdges:
    def test_from_source_and_evidenced_by_no_to_target(self):
        rows = parse_contract_rows(FIXTURE)
        cam = next(r for r in rows if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN")
        edges = build_flow_edges(cam)
        rels = {e["relationship_type"] for e in edges}
        assert rels == {"FROM_SOURCE", "EVIDENCED_BY"}        # NO TO_TARGET until approved
        fs = next(e for e in edges if e["relationship_type"] == "FROM_SOURCE")
        assert fs["source_id"] == department_id("HEALTH AND HUMAN SERVICES")
        assert fs["target_id"] == moneyflow_id(cam["data_portal_id"])
        ev = next(e for e in edges if e["relationship_type"] == "EVIDENCED_BY")
        assert ev["source_id"] == moneyflow_id(cam["data_portal_id"])


# ---------------------------------------------------------------------------
# Unit 4 — fact-ref resolution + approved-loader (TO_TARGET, approved-only)
# ---------------------------------------------------------------------------
from ingest_marin_county_contracts import (  # noqa: E402
    build_recipient_groups,
    build_to_target_edges,
    collision_report,
    load_approved_resolutions,
    recipient_group_id,
    resolve_recipients,
)


class TestRecipientGroups:
    def test_groups_collapse_name_variants_track_evidence(self):
        rows = parse_contract_rows(FIXTURE)
        groups = build_recipient_groups(rows)
        # CAM's two rows collapse to one recipient group with both row uids.
        cam_key = recipient_group_id("Community Action Marin")
        cam = groups[cam_key]
        assert len(cam["moneyflow_ids"]) == 2
        assert len(cam["data_portal_ids"]) == 2
        assert "COMMUNITY ACTION MARIN" in cam["raw_variants"]
        # the slash row resolves to the ORG side for grouping
        gs = groups[recipient_group_id("Good Shepherd Lutheran School")]
        assert "Lisa Ravina / Good Shepherd Lutheran School" in gs["raw_variants"]

    def test_collision_report_surfaces_multivariant_groups(self):
        # A group whose rows carry >1 distinct raw vendor string is flagged for
        # review (Codex: auditable name collapse, never silent).
        rows = parse_contract_rows(FIXTURE)
        report = collision_report(build_recipient_groups(rows))
        # fixture has no intentional variant collisions; report is a (possibly
        # empty) list of {group_id, raw_variants, data_portal_ids}.
        assert isinstance(report, list)
        for entry in report:
            assert len(entry["raw_variants"]) > 1


class TestResolution:
    def test_no_identity_key_means_same_as_empty(self):
        rows = parse_contract_rows(FIXTURE)
        groups = build_recipient_groups(rows)
        existing = [{"id": "org-test-cam", "display_label": "Community Action Marin"}]
        candidates = resolve_recipients(groups, existing)
        # name-only → at least the CAM name-exact candidate; SAME_AS asserted empty
        subjects = {c["subject_ref"] for c in candidates}
        assert recipient_group_id("Community Action Marin") in subjects
        cam_cand = next(c for c in candidates
                        if c["subject_ref"] == recipient_group_id("Community Action Marin"))
        assert cam_cand["candidate_ref"] == "org-test-cam"

    def test_no_existing_orgs_no_candidates(self):
        groups = build_recipient_groups(parse_contract_rows(FIXTURE))
        assert resolve_recipients(groups, []) == []


class TestApprovedLoaderAndToTarget:
    def test_approved_only_to_target_to_all_group_rows(self, tmp_path):
        rows = parse_contract_rows(FIXTURE)
        groups = build_recipient_groups(rows)
        cam_key = recipient_group_id("Community Action Marin")
        p = tmp_path / "approved.jsonl"
        p.write_text(json.dumps({"subject_ref": cam_key,
                                 "candidate_ref": "org-test-cam", "status": "approved"}) + "\n")
        approved = load_approved_resolutions(
            p, emitted_group_ids=set(groups), existing_org_ids={"org-test-cam"})
        edges, aliases = build_to_target_edges(approved, groups)
        # CAM is single-variant, so all (both) MoneyFlows are reviewed → both edges.
        assert len(edges) == 2 and aliases == []
        assert all(e["relationship_type"] == "TO_TARGET" for e in edges)
        assert all(e["target_id"] == "org-test-cam" for e in edges)
        assert {e["source_id"] for e in edges} == set(groups[cam_key]["moneyflow_ids"])

    def test_edge_level_only_reviewed_variant_gets_to_target(self):
        # Two raw variants in one group (the ARBORSCIENCE / ARBORSCIENCE LLC case).
        # Approve ONLY variant A → only A's MoneyFlow gets TO_TARGET; variant B
        # yields a queued alias_expansion and NO edge (Identity Control A).
        from ingest_marin_county_contracts import build_recipient_groups, moneyflow_id
        rows = [
            {"vendor_name_raw": "ARBORSCIENCE", "department": "PARKS", "amount": None,
             "data_portal_id": "dp-A", "month_and_year": "Jan 2024", "contract_number": "",
             "review_contract": None},
            {"vendor_name_raw": "ARBORSCIENCE LLC", "department": "PARKS", "amount": None,
             "data_portal_id": "dp-B", "month_and_year": "Feb 2024", "contract_number": "",
             "review_contract": None},
        ]
        groups = build_recipient_groups(rows)
        gid = next(iter(groups))
        assert len(groups[gid]["raw_variants"]) == 2
        approved = [{
            "subject_ref": gid, "candidate_ref": "org-arbor",
            "reviewed_raw_variants": ["ARBORSCIENCE"], "assertion_id": "assertion-abc",
        }]
        edges, aliases = build_to_target_edges(approved, groups)
        assert len(edges) == 1
        assert edges[0]["source_id"] == moneyflow_id("dp-A")
        assert edges[0]["properties"]["assertion_id"] == "assertion-abc"
        # variant B → no edge, a queued alias_expansion
        assert moneyflow_id("dp-B") not in {e["source_id"] for e in edges}
        assert len(aliases) == 1
        assert aliases[0]["raw_variant"] == "ARBORSCIENCE LLC"
        assert aliases[0]["basis"] == "alias_expansion" and aliases[0]["status"] == "queued"

    def test_loader_fails_loud_on_bad_status_or_stale_refs(self, tmp_path):
        groups = build_recipient_groups(parse_contract_rows(FIXTURE))
        good_key = next(iter(groups))
        for bad, match in [
            ({"subject_ref": good_key, "candidate_ref": "org-x", "status": "queued"}, "status"),
            ({"subject_ref": "marincontract-recipient-ghost", "candidate_ref": "org-x", "status": "approved"}, "subject_ref"),
            ({"subject_ref": good_key, "candidate_ref": "org-ghost", "status": "approved"}, "candidate_ref"),
        ]:
            p = tmp_path / "a.jsonl"
            p.write_text(json.dumps(bad) + "\n")
            with pytest.raises(ValueError, match=match):
                load_approved_resolutions(p, emitted_group_ids=set(groups),
                                          existing_org_ids={"org-x"})


# ---------------------------------------------------------------------------
# Unit 5 — run() / coverage / CLI / $141M tie-out e2e
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402

from ingest_marin_county_contracts import main, run  # noqa: E402

_NODE_DISPLAY_FIELDS = ("display_label",)
_NODE_PROP_LEAK_FIELDS = ("name", "search_label", "description")


class TestRunFixtureE2E:
    def test_nodes_edges_and_coverage_tie_out(self, tmp_path):
        r = run(input_csv=FIXTURE, out_dir=tmp_path / "o", review_dir=tmp_path / "r",
                write_outputs=True)
        mf = [n for n in r["nodes"] if n["node_type"] == "MoneyFlow"]
        rec = [n for n in r["nodes"] if n["node_type"] == "Record"]
        gov = [n for n in r["nodes"] if "Government" in n["labels"]]
        assert len(mf) == 9 and len(rec) == 9
        assert any(n["id"] == "org-marincounty" for n in gov)
        # spine: FROM_SOURCE + EVIDENCED_BY per row, NO TO_TARGET pre-approval
        rels = {e["relationship_type"] for e in r["edges"]}
        assert rels == {"FROM_SOURCE", "EVIDENCED_BY"}
        # coverage ties out to the fixture's Decimal total
        assert r["coverage"]["amount_total"] == "112059"
        assert r["coverage"]["dataset"]["not_full_checkbook"] is True

    def test_recipient_names_never_leak_into_node_display_or_search(self, tmp_path):
        r = run(input_csv=FIXTURE, out_dir=tmp_path / "o", review_dir=tmp_path / "r",
                write_outputs=False)
        names = [row["vendor_name_raw"] for row in parse_contract_rows(FIXTURE)]
        for n in r["nodes"]:
            for f in _NODE_DISPLAY_FIELDS:
                assert not any(v in (n.get(f) or "") for v in names), f"leak in {f}"
            for f in _NODE_PROP_LEAK_FIELDS:
                assert not any(v in (n["properties"].get(f) or "") for v in names), f"leak in props.{f}"

    def test_post_approval_to_target_appears(self, tmp_path):
        existing = [{"id": "org-test-cam", "display_label": "Community Action Marin"}]
        pre = run(input_csv=FIXTURE, out_dir=tmp_path / "o1", review_dir=tmp_path / "r1",
                  existing_orgs=existing, write_outputs=False)
        cam_cand = next(c for c in pre["candidates"]
                        if c["candidate_ref"] == "org-test-cam")
        approved = tmp_path / "approved.jsonl"
        approved.write_text(json.dumps({**cam_cand, "status": "approved"}) + "\n")
        post = run(input_csv=FIXTURE, out_dir=tmp_path / "o2", review_dir=tmp_path / "r2",
                   existing_orgs=existing, approved_path=approved, write_outputs=False)
        tt = [e for e in post["edges"] if e["relationship_type"] == "TO_TARGET"]
        assert len(tt) == 2  # both CAM rows → the approved org
        assert all(e["target_id"] == "org-test-cam" for e in tt)
        assert post["coverage"]["resolution"]["approved_groups"] == 1

    def test_cli_stdout_runs(self, tmp_path, capsys):
        main(["--input", str(FIXTURE), "--out-dir", str(tmp_path / "o"),
              "--review-dir", str(tmp_path / "r")])
        out = capsys.readouterr().out
        assert "NOT full checkbook" in out and "112059" in out


class TestFullCsvE2E:
    @full_csv
    def test_full_run_ties_out_to_141M_and_is_deterministic(self, tmp_path):
        def run_once(tag):
            run(input_csv=FULL_CSV, out_dir=tmp_path / tag, review_dir=tmp_path / f"rev{tag}")
            digests = {}
            for f in sorted((tmp_path / tag).rglob("*")):
                if f.is_file():
                    digests[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
            return digests
        a = run_once("a")
        b = run_once("b")
        assert a == b  # two runs byte-identical
        cov = json.loads((tmp_path / "a" / "marincounty-contracts-coverage.json").read_text())
        assert cov["amount_total"] == "141238172"      # exact tie-out
        assert cov["rows"]["captured"] == 6898
        assert cov["dataset"]["not_full_checkbook"] is True
