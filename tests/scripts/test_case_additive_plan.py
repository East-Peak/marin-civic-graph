"""The additive case planner: a case bundle may only add nodes, edges and properties to the baseline."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from case_additive_plan import (  # noqa: E402
    AdditivePlanError,
    StatementCountError,
    apply_additive,
    apply_in_transaction,
    main,
    plan_additive,
    statements,
    verify_additive,
    write_export,
)


def _n(id_, labels, **props):
    return {"id": id_, "labels": labels, "properties": {"id": id_, **props}}


def _e(s, t, rel, **props):
    return {"start_id": s, "end_id": t, "type": rel, "properties": props}


def _baseline():
    nodes = [
        _n("moneyflow-7-a1", ["MoneyFlow"], amount=125.0, flow_type="contribution", flow_date="2026-01-05"),
        _n("committee-netfile-7", ["Committee"], name="Example Committee", committee_type="BMC"),
        _n("org-example-fund", ["Organization"], name="Example Fund"),
        _n("person-sample-official", ["Person"], name="Sample Official"),
        _n("decision-sample-board-1", ["Decision"], title="Approve a sample grant"),
    ]
    edges = [
        _e("org-example-fund", "moneyflow-7-a1", "FROM_SOURCE"),
        _e("moneyflow-7-a1", "committee-netfile-7", "TO_TARGET"),
        _e("person-sample-official", "decision-sample-board-1", "CAST_VOTE", vote="aye",
           provenance="record-sample-minutes"),
    ]
    return nodes, edges


def _case():
    nodes = [
        _n("election-2030-11-05-sample-measure", ["Election"], title="Sample measure", election_date="2030-11-05",
           election_type="county_measure"),
        _n("record-sample-measure-page", ["Record"], record_type="measure_page", sha256="ab" * 32),
        # An existing node gaining one property it does not have yet.
        _n("committee-netfile-7", ["Committee"], primary_election_id="election-2030-11-05-sample-measure"),
    ]
    edges = [
        _e("committee-netfile-7", "election-2030-11-05-sample-measure", "PRIMARY_FOR_ELECTION",
           position="support", basis="record-sample-measure-page"),
        _e("election-2030-11-05-sample-measure", "record-sample-measure-page", "EVIDENCED_BY"),
        _e("person-sample-official", "decision-sample-board-2", "CAST_VOTE", vote="no",
           provenance="record-sample-minutes-2"),
    ]
    nodes.append(_n("decision-sample-board-2", ["Decision"], title="Accept a sample fund"))
    return nodes, edges


def _plan():
    (bn, be), (cn, ce) = _baseline(), _case()
    return plan_additive(bn, be, cn, ce)


class TestPlan:
    def test_only_additions(self):
        ops = _plan()
        assert [n["id"] for n in ops["add_nodes"]] == [
            "decision-sample-board-2", "election-2030-11-05-sample-measure", "record-sample-measure-page"]
        assert ops["add_props"] == {"committee-netfile-7": {"primary_election_id": "election-2030-11-05-sample-measure"}}
        assert len(ops["add_edges"]) == 3
        assert set(ops) == {"add_nodes", "add_props", "add_edges", "summary"}

    def test_an_unrelated_contribution_is_never_retired(self):
        (bn, be), _ = _baseline(), None
        cand_nodes, cand_edges = apply_additive(bn, be, _plan())
        ids = {n["id"] for n in cand_nodes}
        assert "moneyflow-7-a1" in ids
        assert _e("org-example-fund", "moneyflow-7-a1", "FROM_SOURCE") in cand_edges

    def test_edge_properties_survive_planning_and_candidate(self):
        bn, be = _baseline()
        ops = _plan()
        vote = [e for e in ops["add_edges"] if e["type"] == "CAST_VOTE"]
        assert vote[0]["properties"] == {"vote": "no", "provenance": "record-sample-minutes-2"}
        cand_nodes, cand_edges = apply_additive(bn, be, ops)
        old = [e for e in cand_edges if e["end_id"] == "decision-sample-board-1"]
        new = [e for e in cand_edges if e["end_id"] == "decision-sample-board-2"]
        assert old[0]["properties"] == {"vote": "aye", "provenance": "record-sample-minutes"}
        assert new[0]["properties"] == {"vote": "no", "provenance": "record-sample-minutes-2"}

    def test_restating_baseline_values_is_a_noop(self):
        bn, be = _baseline()
        ops = plan_additive(bn, be, [_n("org-example-fund", ["Organization"], name="Example Fund")],
                            [_e("org-example-fund", "moneyflow-7-a1", "FROM_SOURCE")])
        assert ops["add_nodes"] == [] and ops["add_props"] == {} and ops["add_edges"] == []
        assert ops["summary"]["noop_nodes"] == 1 and ops["summary"]["noop_edges"] == 1


class TestRefusals:
    def _refused(self, case_nodes, case_edges, needle):
        bn, be = _baseline()
        with pytest.raises(AdditivePlanError) as err:
            plan_additive(bn, be, case_nodes, case_edges)
        assert needle in str(err.value)

    def test_changing_an_existing_property(self):
        self._refused([_n("org-example-fund", ["Organization"], name="Renamed Fund")], [], "would change")

    def test_changing_existing_labels(self):
        self._refused([_n("org-example-fund", ["Organization", "Nonprofit"])], [], "labels")

    def test_changing_an_existing_edge_property(self):
        self._refused([], [_e("person-sample-official", "decision-sample-board-1", "CAST_VOTE", vote="no",
                                 provenance="record-sample-minutes")], "edge")

    def test_dangling_endpoint(self):
        self._refused([], [_e("org-example-fund", "record-nowhere", "EVIDENCED_BY")], "endpoint")

    def test_nested_value(self):
        self._refused([_n("record-x", ["Record"], detail={"a": 1})], [], "Neo4j")

    def test_mixed_list_value(self):
        self._refused([_n("record-x", ["Record"], detail=[1, "a"])], [], "Neo4j")

    def test_null_value(self):
        self._refused([_n("record-x", ["Record"], detail=None)], [], "Neo4j")

    def test_null_edge_value(self):
        self._refused([], [_e("org-example-fund", "committee-netfile-7", "RELATED_TO", basis=None)], "Neo4j")

    def test_out_of_range_integer(self):
        self._refused([_n("record-x", ["Record"], count=2 ** 63)], [], "Neo4j")

    def test_no_labels(self):
        self._refused([_n("record-x", [])], [], "label")

    def test_duplicate_case_node(self):
        self._refused([_n("record-x", ["Record"]), _n("record-x", ["Record"])], [], "duplicate")

    def test_duplicate_case_edge(self):
        e = _e("org-example-fund", "committee-netfile-7", "RELATED_TO")
        self._refused([], [e, e], "duplicate")

    def test_property_id_must_match_envelope(self):
        node = _n("record-x", ["Record"])
        node["properties"]["id"] = "record-y"
        self._refused([node], [], "id")

    def test_duplicate_baseline_edges_are_refused(self):
        bn, be = _baseline()
        with pytest.raises(AdditivePlanError, match="duplicate"):
            plan_additive(bn, be + [be[0]], [], [])


class TestVerify:
    def test_the_candidate_verifies(self):
        bn, be = _baseline()
        cn, ce = _case()
        cand = apply_additive(bn, be, _plan())
        assert verify_additive(*cand, bn, be, cn, ce) == []

    def test_a_missing_node_property_fails(self):
        bn, be = _baseline()
        cn, ce = _case()
        nodes, edges = apply_additive(bn, be, _plan())
        for n in nodes:
            if n["id"] == "election-2030-11-05-sample-measure":
                del n["properties"]["election_date"]
        assert any("election_date" in p for p in verify_additive(nodes, edges, bn, be, cn, ce))

    def test_a_wrong_edge_property_fails(self):
        bn, be = _baseline()
        cn, ce = _case()
        nodes, edges = apply_additive(bn, be, _plan())
        for e in edges:
            if e["end_id"] == "decision-sample-board-2":
                e["properties"]["vote"] = "aye"
        assert any("CAST_VOTE" in p for p in verify_additive(nodes, edges, bn, be, cn, ce))

    def test_a_dropped_edge_property_fails(self):
        bn, be = _baseline()
        cn, ce = _case()
        nodes, edges = apply_additive(bn, be, _plan())
        for e in edges:
            if e["type"] == "PRIMARY_FOR_ELECTION":
                e["properties"] = {}
        assert any("PRIMARY_FOR_ELECTION" in p for p in verify_additive(nodes, edges, bn, be, cn, ce))

    def test_a_duplicated_candidate_node_fails(self):
        bn, be = _baseline()
        cn, ce = _case()
        nodes, edges = apply_additive(bn, be, _plan())
        bad = {**nodes[0], "properties": {**nodes[0]["properties"], "name": "Wrong"}}
        assert any("duplicate" in p for p in verify_additive([bad, *nodes], edges, bn, be, cn, ce))

    def test_a_touched_baseline_property_fails(self):
        bn, be = _baseline()
        cn, ce = _case()
        nodes, edges = apply_additive(bn, be, _plan())
        for n in nodes:
            if n["id"] == "moneyflow-7-a1":
                n["properties"]["amount"] = 126.0
        assert any("baseline" in p for p in verify_additive(nodes, edges, bn, be, cn, ce))

    def test_a_retired_baseline_edge_fails(self):
        bn, be = _baseline()
        cn, ce = _case()
        nodes, edges = apply_additive(bn, be, _plan())
        edges = [e for e in edges if e["type"] != "FROM_SOURCE"]
        assert any("baseline" in p for p in verify_additive(nodes, edges, bn, be, cn, ce))

    def test_the_untouched_baseline_reexports_identically(self, tmp_path):
        bn, be = _baseline()
        base_sha = write_export(tmp_path / "base", bn, be)
        nodes, edges = apply_additive(bn, be, _plan())
        assert write_export(tmp_path / "cand", nodes, edges) != base_sha
        ops = _plan()
        added = {n["id"] for n in ops["add_nodes"]}
        added_edges = {(e["start_id"], e["type"], e["end_id"]) for e in ops["add_edges"]}
        rest_nodes = []
        for n in nodes:
            if n["id"] in added:
                continue
            props = {k: v for k, v in n["properties"].items() if k not in ops["add_props"].get(n["id"], {})}
            rest_nodes.append({**n, "properties": props})
        rest_edges = [e for e in edges if (e["start_id"], e["type"], e["end_id"]) not in added_edges]
        assert write_export(tmp_path / "rest", rest_nodes, rest_edges) == base_sha


class FakeTx:
    """Counts rows the way Neo4j would for the rendered statements, against an in-memory graph."""

    def __init__(self, existing_ids=(), existing_edges=(), short_on=None, over_on=None):
        self.existing_ids, self.existing_edges = set(existing_ids), set(existing_edges)
        self.short_on, self.over_on = short_on, over_on
        self.ran = []

    def run(self, query, **params):
        self.ran.append((query, params))
        rows = params["rows"]
        if query.startswith("UNWIND $rows AS id OPTIONAL MATCH"):
            n = sum(1 for r in rows if r in self.existing_ids)
        elif "OPTIONAL MATCH (s {id: e.start_id})-[r]->" in query:
            n = sum(1 for r in rows if (r["start_id"], r["type"], r["end_id"]) in self.existing_edges)
        else:
            n = len(rows)
        if self.short_on and self.short_on in query:
            n -= 1
        if self.over_on and self.over_on in query:
            n += 1
        return _Single(n)


class _Single:
    def __init__(self, n):
        self.n = n

    def single(self):
        return {"n": self.n}


class TestCypher:
    def test_edges_carry_their_properties(self):
        create = [s for s in statements(_plan()) if s["step"].startswith("add_edges:CAST_VOTE")]
        assert create[0]["params"]["rows"][0]["props"] == {"vote": "no", "provenance": "record-sample-minutes-2"}
        assert "SET r = e.props" in create[0]["query"]

    def test_prop_additions_filter_before_set(self):
        stmt = [s for s in statements(_plan()) if s["step"].startswith("add_prop:")][0]
        q = stmt["query"]
        assert q.index("WHERE") < q.index("SET") and "IS NULL" in q

    def test_nodes_are_created_not_merged(self):
        for s in statements(_plan()):
            assert "MERGE" not in s["query"] and "DELETE" not in s["query"] and "REMOVE" not in s["query"]

    def test_applies_with_exact_counts(self):
        counts = apply_in_transaction(FakeTx(), _plan())
        assert counts["add_nodes:Election"] == 1

    def test_an_existing_id_aborts_before_any_write(self):
        tx = FakeTx(existing_ids={"record-sample-measure-page"})
        with pytest.raises(StatementCountError, match="precheck"):
            apply_in_transaction(tx, _plan())
        assert all("CREATE" not in q for q, _ in tx.ran)

    def test_an_existing_edge_aborts_before_any_write(self):
        tx = FakeTx(existing_edges={("committee-netfile-7", "PRIMARY_FOR_ELECTION",
                                     "election-2030-11-05-sample-measure")})
        with pytest.raises(StatementCountError, match="precheck"):
            apply_in_transaction(tx, _plan())

    @pytest.mark.parametrize("kw", [{"short_on": "CREATE (n"}, {"over_on": "CREATE (n"},
                                    {"short_on": "IS NULL"}, {"over_on": "SET r = e.props"}])
    def test_any_count_off_plan_raises(self, kw):
        with pytest.raises(StatementCountError):
            apply_in_transaction(FakeTx(**kw), _plan())


class TestCli:
    def _write(self, d, nodes, edges):
        write_export(d, nodes, edges)  # export_live_graph's exact format, as a real baseline is

    def test_writes_plan_and_candidate_under_the_staging_root(self, tmp_path, monkeypatch):
        import case_additive_plan
        monkeypatch.setattr(case_additive_plan, "STAGING_ROOT", tmp_path)
        bn, be = _baseline()
        cn, ce = _case()
        self._write(tmp_path / "baseline", bn, be)
        self._write(tmp_path / "bundle", cn, ce)
        out = tmp_path / "plan"
        assert main(["--baseline", str(tmp_path / "baseline"), "--case", str(tmp_path / "bundle"),
                     "--out", str(out)]) == 0
        report = json.loads((out / "plan-report.json").read_text())
        assert report["verification"] == [] and report["baseline_reexport_identical"] is True
        assert (out / "candidate" / "nodes.jsonl").is_file() and (out / "ops.json").is_file()
        assert main(["--check-baseline", str(tmp_path / "baseline"), "--plan", str(out)]) == 0
        (tmp_path / "baseline" / "edges.jsonl").write_text("")
        assert main(["--check-baseline", str(tmp_path / "baseline"), "--plan", str(out)]) == 1

    def test_refuses_an_output_outside_the_staging_root(self, tmp_path, monkeypatch):
        import case_additive_plan
        monkeypatch.setattr(case_additive_plan, "STAGING_ROOT", tmp_path / "staging")
        bn, be = _baseline()
        self._write(tmp_path / "baseline", bn, be)
        self._write(tmp_path / "bundle", [], [])
        assert main(["--baseline", str(tmp_path / "baseline"), "--case", str(tmp_path / "bundle"),
                     "--out", str(tmp_path / "elsewhere")]) == 1
