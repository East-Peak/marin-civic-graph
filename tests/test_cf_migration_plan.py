"""The campaign-finance migration plan: an explicit op list whose application to the baseline is the candidate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cf_migration_plan import apply_ops, plan_ops, verify_candidate


def _live(id_, labels, **props):
    return {"id": id_, "labels": labels, "properties": {"id": id_, **props}}


def _flow_live(id_, amount, **extra):
    return _live(id_, ["MoneyFlow"], amount=amount, flow_type="contribution", source_schedule="A",
                 flow_date="2024-01-05", display_label=f"contribution ${amount:.2f}", promotion_state="promoted",
                 **extra)


def _flow_bundle(id_, amount):
    return {"id": id_, "node_type": "MoneyFlow", "labels": ["MoneyFlow"], "display_label": f"contribution ${amount:.2f}",
            "promotion_state": "promoted",
            "properties": {"amount": amount, "flow_type": "contribution", "source_schedule": "A",
                           "flow_date": "2024-01-05"}}


def _actor_bundle(id_, node_type, name):
    return {"id": id_, "node_type": node_type, "labels": [node_type], "display_label": name,
            "promotion_state": "promoted", "properties": {"name": name}}


def _e(s, t, rel):
    return {"start_id": s, "end_id": t, "type": rel, "properties": {}}


def _be(s, t, rel):
    return {"source_id": s, "target_id": t, "relationship_type": rel, "properties": {}}


BASELINE_NODES = [
    _flow_live("moneyflow-1-kept", 10.0, embedding_hash="abc", cluster_id=7),
    _flow_live("moneyflow-1-changed", 20.0),
    _flow_live("moneyflow-1-gone", 30.0),
    _live("moneyflow-contract-9", ["MoneyFlow"], amount=99.0, flow_type="delegated_contract"),
    _live("committee-netfile-1", ["Committee"], name="Committee One", search_rank=3),
    _live("person-cf-doe-pat", ["Person"], name="Pat Doe"),
    _live("decision-1", ["Decision"], title="A vote"),
]
BASELINE_EDGES = [
    _e("person-cf-doe-pat", "moneyflow-1-kept", "FROM_SOURCE"),
    _e("moneyflow-1-kept", "committee-netfile-1", "TO_TARGET"),
    _e("moneyflow-1-changed", "committee-netfile-1", "TO_TARGET"),
    _e("moneyflow-1-gone", "committee-netfile-1", "TO_TARGET"),
    _e("decision-1", "moneyflow-1-gone", "AUTHORIZED"),  # another pipeline's edge onto a retired flow
    _e("moneyflow-contract-9", "committee-netfile-1", "TO_TARGET"),
]
BUNDLE_NODES = [
    _flow_bundle("moneyflow-1-kept", 10.0),
    _flow_bundle("moneyflow-1-changed", 25.0),
    _flow_bundle("moneyflow-1-new", 40.0),
    _actor_bundle("committee-netfile-1", "Committee", "Committee One (renamed)"),
    _actor_bundle("person-cf-doe-pat", "Person", "Pat Doe"),
    _actor_bundle("person-cf-roe-sam", "Person", "Sam Roe"),
    _actor_bundle("record-src-export-2024", "Record", "src export 2024"),
]
BUNDLE_EDGES = [
    _be("person-cf-doe-pat", "moneyflow-1-kept", "FROM_SOURCE"),
    _be("moneyflow-1-kept", "committee-netfile-1", "TO_TARGET"),
    _be("moneyflow-1-changed", "committee-netfile-1", "TO_TARGET"),
    _be("person-cf-roe-sam", "moneyflow-1-new", "FROM_SOURCE"),
    _be("moneyflow-1-new", "committee-netfile-1", "TO_TARGET"),
    _be("moneyflow-1-new", "record-src-export-2024", "EVIDENCED_BY"),
]


def _plan():
    return plan_ops(BASELINE_NODES, BASELINE_EDGES, BUNDLE_NODES, BUNDLE_EDGES)


class TestPlanOps:
    def test_flows_are_retired_added_changed_or_retained(self):
        ops = _plan()
        assert ops["retire_nodes"] == ["moneyflow-1-gone"]
        assert [n["id"] for n in ops["add_nodes"]] == ["moneyflow-1-new", "person-cf-roe-sam", "record-src-export-2024"]
        assert ops["set_props"] == {"moneyflow-1-changed": {"set": {"amount": 25.0, "display_label": "contribution $25.00"},
                                                            "remove": []}}
        assert ops["summary"]["retained_nodes"] == 3  # kept flow + the two existing actors

    def test_existing_actors_are_never_rewritten(self):
        ops = _plan()
        assert "committee-netfile-1" not in ops["set_props"]
        assert ops["summary"]["shared_actors_touched"] == ["committee-netfile-1", "person-cf-doe-pat"]

    def test_edges_are_retired_explicitly_including_other_pipelines_edges_on_retired_flows(self):
        ops = _plan()
        assert ops["retire_edges"] == [
            {"start_id": "decision-1", "end_id": "moneyflow-1-gone", "type": "AUTHORIZED"},
            {"start_id": "moneyflow-1-gone", "end_id": "committee-netfile-1", "type": "TO_TARGET"}]
        assert ops["summary"]["external_edges_on_retired"] == [
            {"start_id": "decision-1", "end_id": "moneyflow-1-gone", "type": "AUTHORIZED"}]
        assert len(ops["add_edges"]) == 3

    def test_non_campaign_flows_are_out_of_scope(self):
        ops = _plan()
        touched = {e["start_id"] for e in ops["retire_edges"]} | set(ops["retire_nodes"]) | set(ops["set_props"])
        assert "moneyflow-contract-9" not in touched

    def test_a_dropped_owned_property_is_removed(self):
        baseline = [_flow_live("moneyflow-1-kept", 10.0)]
        bundle = [_flow_bundle("moneyflow-1-kept", 10.0)]
        del bundle[0]["properties"]["flow_date"]
        ops = plan_ops(baseline, [], bundle, [])
        assert ops["set_props"] == {"moneyflow-1-kept": {"set": {}, "remove": ["flow_date"]}}


class TestLiveIdentityDecisions:
    """Live keeps a deduplicated alias node (dedup_superseded_by) and rewires its edges to the canonical."""

    BASE = [_flow_live("moneyflow-1-kept", 10.0),
            _live("org-alias", ["Organization"], name="Alias", dedup_superseded_by="org-canonical"),
            _live("org-canonical", ["Organization"], name="Canonical"),
            _live("committee-netfile-1", ["Committee"], name="Committee One")]
    BASE_EDGES = [_e("org-canonical", "moneyflow-1-kept", "FROM_SOURCE"),
                  _e("moneyflow-1-kept", "committee-netfile-1", "TO_TARGET")]
    BUNDLE = [_flow_bundle("moneyflow-1-kept", 10.0), _flow_bundle("moneyflow-1-new", 5.0),
              _actor_bundle("org-alias", "Organization", "Alias"),
              _actor_bundle("committee-netfile-1", "Committee", "Committee One")]
    BUNDLE_EDGES = [_be("org-alias", "moneyflow-1-kept", "FROM_SOURCE"),
                    _be("moneyflow-1-kept", "committee-netfile-1", "TO_TARGET"),
                    _be("org-alias", "moneyflow-1-new", "FROM_SOURCE"),
                    _be("moneyflow-1-new", "committee-netfile-1", "TO_TARGET")]

    def test_bundle_endpoints_resolve_through_live_dedup_decisions(self):
        ops = plan_ops(self.BASE, self.BASE_EDGES, self.BUNDLE, self.BUNDLE_EDGES)
        assert ops["retire_edges"] == []
        assert {"start_id": "org-canonical", "end_id": "moneyflow-1-new", "type": "FROM_SOURCE"} in ops["add_edges"]
        assert not [e for e in ops["add_edges"] if e["start_id"] == "org-alias"]
        assert ops["summary"]["endpoints_resolved"] == 2
        nodes, edges = apply_ops(self.BASE, self.BASE_EDGES, ops)
        assert verify_candidate(nodes, edges, self.BUNDLE, self.BUNDLE_EDGES) == []


class TestApplyOps:
    def test_applying_the_ops_to_the_baseline_yields_the_bundle(self):
        ops = _plan()
        nodes, edges = apply_ops(BASELINE_NODES, BASELINE_EDGES, ops)
        assert verify_candidate(nodes, edges, BUNDLE_NODES, BUNDLE_EDGES) == []
        by_id = {n["id"]: n for n in nodes}
        assert by_id["moneyflow-1-kept"]["properties"]["embedding_hash"] == "abc"  # non-owned props survive
        assert by_id["moneyflow-1-changed"]["properties"]["amount"] == 25.0
        assert by_id["committee-netfile-1"]["properties"]["name"] == "Committee One"  # actor untouched
        assert "moneyflow-1-gone" not in by_id and "moneyflow-contract-9" in by_id
        assert not [e for e in edges if "moneyflow-1-gone" in (e["start_id"], e["end_id"])]

    def test_verify_catches_a_candidate_that_drifted(self):
        ops = _plan()
        ops["retire_nodes"] = []
        nodes, edges = apply_ops(BASELINE_NODES, BASELINE_EDGES, ops)
        problems = verify_candidate(nodes, edges, BUNDLE_NODES, BUNDLE_EDGES)
        assert any("moneyflow-1-gone" in p for p in problems)


def _write_jsonl(path, rows):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows))


def _dirs(tmp_path):
    baseline, bundle = tmp_path / "baseline", tmp_path / "bundle"
    _write_jsonl(baseline / "nodes.jsonl", sorted(BASELINE_NODES, key=lambda n: n["id"]))
    _write_jsonl(baseline / "edges.jsonl", sorted(BASELINE_EDGES, key=lambda e: (e["start_id"], e["type"], e["end_id"])))
    _write_jsonl(bundle / "src" / "nodes.jsonl", BUNDLE_NODES)
    _write_jsonl(bundle / "src" / "edges.jsonl", BUNDLE_EDGES)
    return baseline, bundle


class TestCli:
    def test_writes_ops_candidate_report_and_plan(self, tmp_path):
        import json
        from cf_migration_plan import main
        baseline, bundle = _dirs(tmp_path)
        out = tmp_path / "plan"
        assert main(["--baseline", str(baseline), "--bundle", str(bundle), "--out", str(out)]) == 0
        assert sorted(p.name for p in out.iterdir()) == [
            "candidate", "migration-plan.md", "migration-report.json", "ops.json"]
        report = json.loads((out / "migration-report.json").read_text())
        assert report["baseline"]["sha256"]["nodes.jsonl"]
        assert report["amounts"]["contribution"] == {"baseline": "60.00", "candidate": "75.00", "delta": "15.00"}
        assert report["verification"] == []
        plan = (out / "migration-plan.md").read_text()
        assert "moneyflow-1-gone" in plan and "DETACH DELETE" in plan and "rollback" in plan.lower()

    def test_the_candidate_passes_the_post_load_check_and_the_baseline_fails_it(self, tmp_path, capsys):
        from cf_migration_plan import main
        baseline, bundle = _dirs(tmp_path)
        out = tmp_path / "plan"
        main(["--baseline", str(baseline), "--bundle", str(bundle), "--out", str(out)])
        assert main(["--check-live", str(out / "candidate"), "--bundle", str(bundle)]) == 0
        assert main(["--check-live", str(baseline), "--bundle", str(bundle)]) == 1
        assert "moneyflow-1-gone" in capsys.readouterr().err

    def test_an_unchanged_graph_round_trips_byte_for_byte(self, tmp_path):
        from cf_migration_plan import write_export
        baseline, _ = _dirs(tmp_path)
        write_export(tmp_path / "copy", BASELINE_NODES, BASELINE_EDGES)
        for name in ("nodes.jsonl", "edges.jsonl"):
            assert (tmp_path / "copy" / name).read_bytes() == (baseline / name).read_bytes()

    def test_refuses_to_write_inside_the_repo(self, tmp_path, capsys):
        from cf_migration_plan import ROOT, main
        baseline, bundle = _dirs(tmp_path)
        assert main(["--baseline", str(baseline), "--bundle", str(bundle), "--out", str(ROOT / "data" / "x")]) == 1
        assert "refusing" in capsys.readouterr().err


class FakeTx:
    """Records statements and answers each with the row count it was asked to touch."""

    def __init__(self, short_on=None):
        self.ran, self.short_on = [], short_on

    def run(self, query, **params):
        self.ran.append((query, params))
        expected = len(params.get("rows", []))
        count = expected - 1 if self.short_on and self.short_on in query else expected

        class Result:
            def single(self_inner):
                return {"n": count}
        return Result()


class TestTransactionStatements:
    def test_statements_consume_the_ops_format_in_dependency_order(self):
        from cf_migration_plan import migration_statements
        stmts = migration_statements(_plan())
        kinds = [s["step"] for s in stmts]
        assert kinds == ["retire_edges", "retire_nodes", "add_nodes:MoneyFlow", "add_nodes:Person",
                         "add_nodes:Record", "set_props", "add_edges:EVIDENCED_BY", "add_edges:FROM_SOURCE",
                         "add_edges:TO_TARGET"]
        edge_rows = next(s for s in stmts if s["step"] == "add_edges:FROM_SOURCE")["params"]["rows"]
        assert edge_rows == [{"start_id": "person-cf-roe-sam", "end_id": "moneyflow-1-new"}]
        assert "MERGE (n:MoneyFlow {id: row.id})" in stmts[2]["query"]

    def test_apply_runs_every_statement_on_the_one_transaction_it_is_given(self):
        from cf_migration_plan import apply_in_transaction
        tx = FakeTx()
        counts = apply_in_transaction(tx, _plan())
        assert len(tx.ran) == 9 and counts["retire_nodes"] == 1

    def test_a_short_count_stops_before_anything_else_runs(self):
        import pytest
        from cf_migration_plan import MigrationError, apply_in_transaction
        tx = FakeTx(short_on="DETACH DELETE")
        with pytest.raises(MigrationError, match="retire_nodes"):
            apply_in_transaction(tx, _plan())
        assert len(tx.ran) == 2  # the caller's transaction is then rolled back, never committed

    def test_a_property_key_that_is_not_an_identifier_is_refused(self):
        import pytest
        from cf_migration_plan import MigrationError, migration_statements
        ops = _plan()
        ops["set_props"]["moneyflow-1-changed"]["remove"] = ["x` DETACH DELETE n //"]
        with pytest.raises(MigrationError):
            migration_statements(ops)
