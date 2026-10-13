"""The totals guard: a case load may not move any public money total unless intended and free of double counting."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from bake_public_substrate import bake_substrate  # noqa: E402
from case_totals_guard import double_count_problems, guard, main, money_surface, surface_changes  # noqa: E402

REGISTRY = {"graph_node_types": {"Organization": {}, "MoneyFlow": {}, "Agreement": {}, "Committee": {},
                                 "Program": {}},
            "id_prefixes": {"org-": "Organization", "moneyflow-": "MoneyFlow", "agreement-": "Agreement",
                            "committee-": "Committee", "program-": "Program"}}


def _n(id_, labels, **props):
    return {"id": id_, "labels": labels, "properties": {"id": id_, **props}}


def _e(s, t, rel, **props):
    return {"start_id": s, "end_id": t, "type": rel, "properties": props}


def _base_graph():
    nodes = [_n("org-example-fund", ["Organization"], name="Example Fund"),
             _n("org-sample-agency", ["Organization"], name="Sample Housing Agency"),
             _n("committee-netfile-7", ["Committee"], name="Example Committee"),
             _n("moneyflow-7-a1", ["MoneyFlow"], amount=125.0, flow_type="contribution", flow_date="2030-01-05"),
             _n("agreement-sample-grant", ["Agreement"], name="Sample grant", authorized_amount="100.00")]
    edges = [_e("org-example-fund", "moneyflow-7-a1", "FROM_SOURCE"),
             _e("moneyflow-7-a1", "committee-netfile-7", "TO_TARGET")]
    return nodes, edges


def _grant_flow(id_, stage):
    return _n(id_, ["MoneyFlow"], amount=100.0, flow_type="grant", money_stage=stage, funds_class="private",
              agreement_id="agreement-sample-grant", flow_date="2030-02-01")


def _with_grant(nodes, edges, *stages):
    nodes, edges = list(nodes), list(edges)
    for i, stage in enumerate(stages):
        fid = f"moneyflow-case-grant-{i}"
        nodes.append(_grant_flow(fid, stage))
        edges += [_e("org-example-fund", fid, "FROM_SOURCE"), _e(fid, "org-sample-agency", "TO_TARGET"),
                  _e(fid, "agreement-sample-grant", "RELATES_TO_AGREEMENT")]
    return nodes, edges


def _loader_edge(e):
    """The attach overlay's own edge format."""
    return {"source_id": e["start_id"], "relationship_type": e["type"], "target_id": e["end_id"],
            "properties": e["properties"]}


def _write_export(d: Path, nodes, edges):
    d.mkdir(parents=True)
    (d / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (d / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))


def _bake(tmp_path: Path, name: str, nodes, edges, overlay_edges=()) -> tuple[Path, Path]:
    root = tmp_path / name
    _write_export(root / "export", nodes, edges)
    _write_export(root / "overlay", [], [_loader_edge(e) for e in overlay_edges])  # the stamped SAME_AS authority
    registry = root / "node-types.json"
    registry.write_text(json.dumps(REGISTRY))
    bake_substrate(registry_path=registry, sqlite_path=root / "public.sqlite", report_path=root / "report.json",
                   source="live-export", live_export_dir=root / "export", attach_overlay_dir=root / "overlay")
    return root / "public.sqlite", root / "export"


def _rollup(db: Path, org: str):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT money_in_total, money_out_total FROM money_rollups WHERE org_id = ?",
                            (org,)).fetchone()


class TestDoubleCounting:
    def test_100_authorization_plus_100_disbursement_bakes_to_200_and_the_guard_catches_it(self, tmp_path):
        base_db, _ = _bake(tmp_path, "base", *_base_graph())
        cand_db, cand_export = _bake(tmp_path, "cand", *_with_grant(*_base_graph(), "authorization", "disbursement"))
        assert _rollup(cand_db, "org-sample-agency") == (200.0, 0.0)  # the bake cannot tell the stages apart
        problems = guard(base_db, cand_db, cand_export, intended=[])
        joined = "\n".join(problems)
        assert "moneyflow-case-grant-0" in joined and "moneyflow-case-grant-1" in joined
        assert "authorization" in joined

    def test_intending_the_change_does_not_bless_the_double_count(self, tmp_path):
        base_db, _ = _bake(tmp_path, "base", *_base_graph())
        cand_db, cand_export = _bake(tmp_path, "cand", *_with_grant(*_base_graph(), "authorization", "disbursement"))
        assert any("authorization" in p for p in guard(base_db, cand_db, cand_export,
                                                        intended=_intend(base_db, cand_db)))

    def test_holding_the_authorization_back_leaves_one_100_disbursement(self, tmp_path):
        base_db, _ = _bake(tmp_path, "base", *_base_graph())
        cand_db, cand_export = _bake(tmp_path, "cand", *_with_grant(*_base_graph(), "disbursement"))
        assert _rollup(cand_db, "org-sample-agency") == (100.0, 0.0)
        assert guard(base_db, cand_db, cand_export, intended=_intend(base_db, cand_db)) == []

    def test_one_intended_disbursement_passes(self, tmp_path):
        base_db, _ = _bake(tmp_path, "base", *_base_graph())
        cand_db, cand_export = _bake(tmp_path, "cand", *_with_grant(*_base_graph(), "disbursement"))
        assert guard(base_db, cand_db, cand_export, intended=_intend(base_db, cand_db)) == []
        assert guard(base_db, cand_db, cand_export, intended=[]) != []  # but never silently

    def test_an_intended_change_must_match_its_exact_values(self, tmp_path):
        base_db, _ = _bake(tmp_path, "base", *_base_graph())
        cand_db, cand_export = _bake(tmp_path, "cand", *_with_grant(*_base_graph(), "disbursement"))
        intended = _intend(base_db, cand_db)
        for change in intended:
            if change["surface"] == "money_rollups":
                change["after"] = change["after"].replace("100.0", "90.0")
        assert any("money_rollups" in p for p in guard(base_db, cand_db, cand_export, intended=intended))

    def test_missing_filing_provenance_never_means_same_filing(self):
        nodes, edges = _base_graph()
        nodes.append(_n("moneyflow-7-a2", ["MoneyFlow"], amount=125.0, flow_type="contribution",
                        flow_date="2030-01-06"))
        edges += [_e("org-example-fund", "moneyflow-7-a2", "FROM_SOURCE"),
                  _e("moneyflow-7-a2", "committee-netfile-7", "TO_TARGET")]
        assert double_count_problems(nodes, edges)

    def test_same_stage_duplicate_reports_are_caught(self, tmp_path):
        nodes, edges = _base_graph()
        nodes.append(_n("moneyflow-8-e1", ["MoneyFlow"], amount=125.0, flow_type="expenditure",
                        flow_date="2030-01-03"))
        edges += [_e("org-example-fund", "moneyflow-8-e1", "FROM_SOURCE"),
                  _e("moneyflow-8-e1", "committee-netfile-7", "TO_TARGET")]
        problems = double_count_problems(*_read(nodes, edges))
        assert any("moneyflow-7-a1" in p and "moneyflow-8-e1" in p for p in problems)

    def test_duplicates_across_a_stamped_identity_link_are_caught(self):
        nodes, edges = _base_graph()
        nodes += [_n("org-example-fund-alias", ["Organization"], name="Example Fund Inc"),
                  _n("moneyflow-8-e1", ["MoneyFlow"], amount=125.0, flow_type="expenditure", flow_date="2030-01-06")]
        edges += [_e("org-example-fund-alias", "moneyflow-8-e1", "FROM_SOURCE"),
                  _e("moneyflow-8-e1", "committee-netfile-7", "TO_TARGET"),
                  _e("org-example-fund", "org-example-fund-alias", "SAME_AS", assertion_id="assertion-1")]
        assert double_count_problems(*_read(nodes, edges))
        edges[-1] = _e("org-example-fund", "org-example-fund-alias", "SAME_AS")  # unstamped: the bake ignores it
        assert not double_count_problems(*_read(nodes, edges))


def _read(nodes, edges):
    return nodes, edges


def _intend(base_db, cand_db):
    """An intended-changes list that states every change's exact before/after values."""
    return [{"surface": s, "key": k, "before": b, "after": a}
            for s, k, b, a in surface_changes(money_surface(base_db), money_surface(cand_db))]


class TestInvariant:
    def test_a_new_identity_link_without_new_flows_fails(self, tmp_path):
        nodes, edges = _base_graph()
        base_db, _ = _bake(tmp_path, "base", nodes, edges)
        cand_db, cand_export = _bake(tmp_path, "cand", nodes, edges, overlay_edges=[
            _e("org-example-fund", "org-sample-agency", "SAME_AS", assertion_id="assertion-2")])
        assert any("identity_links" in p for p in guard(base_db, cand_db, cand_export, intended=[]))

    def test_an_intended_identity_link_that_joins_duplicates_is_still_caught(self, tmp_path):
        nodes, edges = _base_graph()
        nodes += [_n("org-example-fund-alias", ["Organization"], name="Example Fund Inc"),
                  _n("moneyflow-8-e1", ["MoneyFlow"], amount=125.0, flow_type="expenditure", flow_date="2030-01-06",
                     filing_id="filing-8")]
        nodes[3]["properties"]["filing_id"] = "filing-7"
        edges += [_e("org-example-fund-alias", "moneyflow-8-e1", "FROM_SOURCE"),
                  _e("moneyflow-8-e1", "committee-netfile-7", "TO_TARGET")]
        base_db, _ = _bake(tmp_path, "base", nodes, edges)
        link = _e("org-example-fund", "org-example-fund-alias", "SAME_AS", assertion_id="assertion-3")
        cand_db, cand_export = _bake(tmp_path, "cand", nodes, edges, overlay_edges=[link])
        problems = guard(base_db, cand_db, cand_export, intended=_intend(base_db, cand_db))
        assert any("moneyflow-7-a1" in p and "moneyflow-8-e1" in p for p in problems)

    def test_a_join_key_on_a_flow_neighbour_fails(self, tmp_path):
        # local-pressure ranking selects Programs by place keys and sums their adjacent flows
        nodes, edges = _base_graph()
        nodes.append(_n("program-sample", ["Program"], name="Sample program"))
        edges.append(_e("program-sample", "moneyflow-7-a1", "RELATES_TO_PROGRAM"))
        base_db, _ = _bake(tmp_path, "base", nodes, edges)
        cand = [*nodes[:-1], _n("program-sample", ["Program"], name="Sample program",
                                primary_place_id="place-sample")]
        cand_db, cand_export = _bake(tmp_path, "cand", cand, edges)
        assert any("flow_neighbours" in p for p in guard(base_db, cand_db, cand_export, intended=[]))

    def test_offsetting_amounts_fail_though_the_net_is_unchanged(self, tmp_path):
        nodes, edges = _base_graph()
        base_db, _ = _bake(tmp_path, "base", nodes, edges)
        extra = [_n("moneyflow-case-plus", ["MoneyFlow"], amount=50.0, flow_type="grant"),
                 _n("moneyflow-case-minus", ["MoneyFlow"], amount=-50.0, flow_type="grant")]
        more = [_e("org-example-fund", "moneyflow-case-plus", "FROM_SOURCE"),
                _e("org-example-fund", "moneyflow-case-minus", "FROM_SOURCE")]
        cand_db, cand_export = _bake(tmp_path, "cand", nodes + extra, edges + more)
        problems = guard(base_db, cand_db, cand_export, intended=[])
        assert any("moneyflow-case-plus" in p for p in problems)

    def test_a_new_edge_onto_an_existing_flow_fails(self, tmp_path):
        nodes, edges = _base_graph()
        base_db, _ = _bake(tmp_path, "base", nodes, edges)
        cand_db, cand_export = _bake(tmp_path, "cand", nodes, edges + [
            _e("moneyflow-7-a1", "agreement-sample-grant", "RELATES_TO_AGREEMENT")])
        assert any("flow_edges" in p for p in guard(base_db, cand_db, cand_export, intended=[]))

    def test_a_money_property_on_another_node_fails(self, tmp_path):
        nodes, edges = _base_graph()
        base_db, _ = _bake(tmp_path, "base", nodes, edges)
        cand = [*nodes[:-1], _n("agreement-sample-grant", ["Agreement"], name="Sample grant", amount="100.00")]
        cand_db, cand_export = _bake(tmp_path, "cand", cand, edges)
        assert any("money_props" in p for p in guard(base_db, cand_db, cand_export, intended=[]))

    def test_non_money_additions_pass(self, tmp_path):
        nodes, edges = _base_graph()
        base_db, _ = _bake(tmp_path, "base", nodes, edges)
        cand_db, cand_export = _bake(tmp_path, "cand", nodes + [_n("org-new-board", ["Organization"], name="Board")],
                                     edges + [_e("org-new-board", "agreement-sample-grant", "RELATES_TO_AGREEMENT")])
        assert guard(base_db, cand_db, cand_export, intended=[]) == []


class TestCli:
    def test_exit_codes(self, tmp_path):
        base_db, base_export = _bake(tmp_path, "base", *_base_graph())
        cand_db, cand_export = _bake(tmp_path, "cand", *_with_grant(*_base_graph(), "authorization"))
        intended = tmp_path / "intended.json"
        intended.write_text("[]")
        assert main(["--baseline-db", str(base_db), "--candidate-db", str(base_db), "--candidate-export",
                     str(base_export), "--intended", str(intended)]) == 0
        assert main(["--baseline-db", str(base_db), "--candidate-db", str(cand_db), "--candidate-export",
                     str(cand_export), "--intended", str(intended)]) == 1
