import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from campaign_ledger import build_ledger, build_transactions
from normalize_campaign_finance import (
    build_committee_node,
    build_contributor_node,
    normalize_campaign_source,
    slugify_name,
)
from tests.netfile_workbooks import contribution, expenditure, filing, other, summary, write_export

CAPTURE = {
    "source_id": "test-source",
    "capture_id": "test-source__2026-04-14",
    "jurisdiction_id": "place-test",
    "institution_id": "org-test-source",
    "captured_at": "2026-04-14T00:00:00Z",
}
F1 = filing()


def _emit(tmp_path, sheets_by_year, out="out"):
    workbooks = [(f"test-source/2026-04-14/{year}.zip", write_export(tmp_path / "raw" / f"{year}.zip", sheets))
                 for year, sheets in sorted(sheets_by_year.items())]
    ledger = build_ledger("test-source", workbooks)
    build_transactions(ledger)
    nodes, edges, report = normalize_campaign_source(CAPTURE, ledger, tmp_path / out)
    return ledger, nodes, edges, report


def _flows(nodes):
    return {n["id"]: n for n in nodes if n["node_type"] == "MoneyFlow"}


class TestSlugifyName:
    def test_basic(self):
        assert slugify_name("Smith", "John") == "smith-john"

    def test_strips_whitespace(self):
        assert slugify_name("  Smith  ", "  John  ") == "smith-john"

    def test_last_only(self):
        assert slugify_name("Sticker Mule", None) == "sticker-mule"

    def test_special_chars(self):
        assert slugify_name("O'Brien", "Mary-Jane") == "obrien-mary-jane"


class TestBuildCommitteeNode:
    def test_creates_committee(self):
        node = build_committee_node(
            filer_id=1461685,
            filer_name="Friends of Heather McPhail Sridharan for Marin County Supervisor 2024",
            committee_type="CTL",
            jurisdiction_id="place-marin-county",
            capture_id="test__2026-04-14",
        )
        assert node["id"] == "committee-netfile-1461685"
        assert node["node_type"] == "Committee"
        assert node["labels"] == ["Committee"]
        assert node["properties"]["name"] == "Friends of Heather McPhail Sridharan for Marin County Supervisor 2024"
        assert node["properties"]["netfile_filer_id"] == 1461685

    def test_committee_has_jurisdiction(self):
        node = build_committee_node(1461685, "Test", "CTL", "place-marin-county", "test")
        assert node["properties"]["jurisdiction_id"] == "place-marin-county"


class TestBuildContributorNode:
    def test_individual_creates_person_with_the_live_id(self):
        node = build_contributor_node(
            name_last="Cullen", name_first="Carleen",
            entity_cd="IND", capture_id="test",
        )
        assert node["id"] == "person-cullen-carleen"
        assert node["node_type"] == "Person"
        assert node["labels"] == ["Person"]

    def test_committee_creates_org(self):
        node = build_contributor_node(
            name_last="Sticker Mule", name_first=None,
            entity_cd="OTH", capture_id="test",
        )
        assert node["id"] == "org-sticker-mule"
        assert node["node_type"] == "Organization"
        assert "Organization" in node["labels"]

    def test_person_ids_are_the_live_graphs(self):
        """The live graph holds every campaign Person as person-{slug} (the person-cf- namespace was never
        loaded). Keeping it preserves actor ids; the name-slug merge is a known defect owned by goals 3-4."""
        node = build_contributor_node(
            name_last="Colin", name_first="Kate",
            entity_cd="IND", capture_id="test",
        )
        assert node["id"] == "person-colin-kate"

    def test_com_entity_creates_org(self):
        node = build_contributor_node(
            name_last="Some PAC", name_first=None,
            entity_cd="COM", capture_id="test",
        )
        assert node["node_type"] == "Organization"



class TestMoneyFlows:
    def test_a_counted_contribution_keeps_the_live_id_and_shape(self, tmp_path):
        _, nodes, edges, _ = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "TXN001", 150, last="Smith", first="John", date="2024-01-13")],
            "Summary": [summary(F1, "A", "1", 150)]}})
        flow = _flows(nodes)["moneyflow-1400001-TXN001"]
        assert flow["properties"] == {"amount": 150.0, "flow_type": "contribution", "source_schedule": "A",
                                      "flow_date": "2024-01-13", "reported_entity_cd": "IND"}
        assert flow["display_label"] == "contribution $150.00"
        rels = {(e["source_id"], e["relationship_type"], e["target_id"]) for e in edges}
        assert ("person-smith-john", "FROM_SOURCE", "moneyflow-1400001-TXN001") in rels
        assert ("moneyflow-1400001-TXN001", "TO_TARGET", "committee-netfile-1400001") in rels
        assert len(rels) == 3  # plus the committee's IN_JURISDICTION; provenance stays in the private ledger

    def test_an_expenditure_flows_from_the_committee_to_the_payee(self, tmp_path):
        _, nodes, edges, _ = _emit(tmp_path, {"2024": {
            "E-Expenditure": [expenditure(F1, "E1", 500, payee="Example Print Co")],
            "Summary": [summary(F1, "E", "1", 500)]}})
        rels = {(e["source_id"], e["relationship_type"], e["target_id"]) for e in edges}
        assert ("committee-netfile-1400001", "FROM_SOURCE", "moneyflow-1400001-E1") in rels
        assert ("moneyflow-1400001-E1", "TO_TARGET", "org-example-print-co") in rels
        assert _flows(nodes)["moneyflow-1400001-E1"]["properties"]["flow_type"] == "expenditure"

    def test_a_duplicate_report_is_one_flow(self, tmp_path):
        pre = filing(rpt="2020-02-21", start="2020-01-19", thru="2020-02-15")
        cumulative = filing(report_num="001", rpt="2022-01-26", start="2019-12-01", thru="2021-11-18")
        ledger, nodes, _, _ = _emit(tmp_path, {
            "2020": {"A-Contributions": [contribution(pre, "UdUX", 7500)], "Summary": [summary(pre, "A", "1", 7500)]},
            "2021": {"A-Contributions": [contribution(cumulative, "UdUX", 7500)],
                     "Summary": [summary(cumulative, "A", "1", 7500)]}})
        assert list(_flows(nodes)) == ["moneyflow-1400001-UdUX"]
        assert {r["moneyflow_id"] for r in ledger.rows if r["schedule"]} == {"moneyflow-1400001-UdUX"}

    def test_nothing_new_is_published_no_record_nodes_or_evidence_edges(self, tmp_path):
        _, nodes, edges, _ = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10)], "Summary": [summary(F1, "A", "1", 10)]}})
        assert {n["node_type"] for n in nodes} == {"Place", "Committee", "Person", "MoneyFlow"}
        assert {e["relationship_type"] for e in edges} == {"FROM_SOURCE", "TO_TARGET", "IN_JURISDICTION"}

    def test_withheld_transactions_emit_no_flow_but_keep_their_actors(self, tmp_path):
        ledger, nodes, _, report = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 100, last="Roe", first="Sam")],
            "E-Expenditure": [expenditure(F1, "e1", 300), expenditure(F1, "e2", 300, Memo_Code="X"),
                              expenditure(F1, "e3", 0, payee="Zero Payee")],
            "Summary": [summary(F1, "E", "1", 300)]}})
        assert list(_flows(nodes)) == ["moneyflow-1400001-e1"]
        ids = {n["id"] for n in nodes}
        assert "person-roe-sam" in ids  # missing-oracle filing: flow withheld, actor kept (legacy actor set)
        assert "org-zero-payee" not in ids  # zero rows never made actors
        assert report["withheld"] == {"filing_not_validated": 1, "non_additive": 1, "zero_amount": 1}

    def test_out_of_scope_sheets_create_no_actors_or_flows(self, tmp_path):
        _, nodes, _, _ = _emit(tmp_path, {"2024": {
            "D-Expenditure": [other(F1, "D-Expenditure", "d1", 999, Payee_NamL="Other Committee")],
            "B1-Loans": [other(F1, "B1-Loans", "b1", 5000, Lndr_NamL="Lender Person")],
            "497": [{**F1, "Rec_Type": "RCPT", "Form_Type": "F497P1", "Tran_ID": "n1", "Amount": 1500,
                     "Enty_NamL": "Notice Donor"}],
            "Summary": [summary(F1, "A", "1", 0)]}})
        assert {n["node_type"] for n in nodes} == {"Place"}

    def test_committee_takes_the_first_seen_name_and_type(self, tmp_path):
        renamed = filing(name="Example for Council 2028", rpt="2024-06-01", start="2024-04-01", thru="2024-05-31",
                         committee_type="RCP")
        _, nodes, _, _ = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10), contribution(renamed, "a2", 20)],
            "Summary": [summary(F1, "A", "1", 10), summary(renamed, "A", "1", 20)]}})
        committee = next(n for n in nodes if n["node_type"] == "Committee")
        assert committee["properties"]["name"] == "Friends of Example for Council 2024"
        assert committee["properties"]["committee_type"] == "CTL"


    def test_committee_is_first_seen_from_a_schedule_row_not_other_sheets(self, tmp_path):
        _, nodes, _, _ = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution({**F1, "Committee_Type": "RCP"}, "a1", 10)],
            "D-Expenditure": [other({**F1, "Committee_Type": "CTL"}, "D-Expenditure", "d1", 5)],
            "Summary": [summary({**F1, "Committee_Type": "RCP"}, "A", "1", 10)]}})
        committee = next(n for n in nodes if n["node_type"] == "Committee")
        assert committee["properties"]["committee_type"] == "RCP"


DETAIL = {"Tran_Emp": "Example Co", "Tran_Occ": "Engineer", "Tran_City": "Sampleton", "Tran_State": "CA",
          "Tran_Zip4": "94999-0001"}


def _props(nodes, flow_id):
    return _flows(nodes)[flow_id]["properties"]


class TestContributorDetail:
    def test_an_individuals_flow_carries_its_details_as_reported(self, tmp_path):
        _, nodes, edges, _ = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10, Tran_Adr1="1 EXAMPLE ST", **DETAIL)],
            "Summary": [summary(F1, "A", "1", 10)]}})
        assert _props(nodes, "moneyflow-1400001-a1") == {
            "amount": 10.0, "flow_type": "contribution", "source_schedule": "A", "flow_date": "2024-01-05",
            "reported_entity_cd": "IND", "reported_occupation": "Engineer", "reported_employer": "Example Co",
            "reported_city": "Sampleton", "reported_state": "CA", "reported_zip5": "94999"}
        text = json.dumps([nodes, edges])
        assert "EXAMPLE ST" not in text and "94999-0001" not in text

    def test_details_are_never_put_on_the_person_or_made_into_entities(self, tmp_path):
        _, nodes, edges, _ = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10, **DETAIL),
                                contribution(F1, "a2", 20, **{**DETAIL, "Tran_Emp": "RETIRED"})],
            "Summary": [summary(F1, "A", "1", 30)]}})
        person = next(n for n in nodes if n["node_type"] == "Person")
        assert person["properties"] == {"name": "Pat Doe", "entity_cd": "IND"}
        assert {n["node_type"] for n in nodes} == {"Place", "Committee", "Person", "MoneyFlow"}
        assert "Example Co" not in json.dumps(edges) and "RETIRED" not in json.dumps(edges)

    def test_details_change_nothing_else_in_the_graph(self, tmp_path):
        bare = {"2024": {"A-Contributions": [contribution(F1, "a1", 10), contribution(F1, "a2", 5, entity="COM",
                                                                                       last="Example PAC")],
                         "Summary": [summary(F1, "A", "1", 15)]}}
        rich = {"2024": {"A-Contributions": [contribution(F1, "a1", 10, **DETAIL),
                                             contribution(F1, "a2", 5, entity="COM", last="Example PAC", **DETAIL)],
                         "Summary": [summary(F1, "A", "1", 15)]}}
        _, bare_nodes, bare_edges, _ = _emit(tmp_path / "bare", bare)
        _, rich_nodes, rich_edges, _ = _emit(tmp_path / "rich", rich)
        assert rich_edges == bare_edges
        strip = lambda nodes: [{**n, "properties": {k: v for k, v in n["properties"].items()
                                                    if not k.startswith("reported_") or k == "reported_entity_cd"}}
                               for n in nodes]
        assert strip(rich_nodes) == bare_nodes
        # A committee's contribution keeps exactly what it had.
        assert _props(rich_nodes, "moneyflow-1400001-a2") == _props(bare_nodes, "moneyflow-1400001-a2")
        assert "reported_entity_cd" not in _props(rich_nodes, "moneyflow-1400001-a2")

    def test_a_blank_entity_code_gets_no_details_despite_the_legacy_default(self, tmp_path):
        _, nodes, _, _ = _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10, entity=None, **DETAIL)],
            "Summary": [summary(F1, "A", "1", 10)]}})
        assert next(n for n in nodes if n["node_type"] == "Person")["properties"]["entity_cd"] == "IND"  # legacy
        assert not any(k.startswith("reported_") for k in _props(nodes, "moneyflow-1400001-a1"))

    def test_expenditures_get_no_details(self, tmp_path):
        _, nodes, _, _ = _emit(tmp_path, {"2024": {
            "E-Expenditure": [expenditure(F1, "e1", 50, entity="IND", Payee_City="Sampleton", Payee_Zip4="94999")],
            "Summary": [summary(F1, "E", "1", 50)]}})
        assert not any(k.startswith("reported_") for k in _props(nodes, "moneyflow-1400001-e1"))

    def test_duplicate_reports_share_details_and_conflicts_are_withheld_and_counted(self, tmp_path):
        pre = filing(rpt="2020-02-21", start="2020-01-19", thru="2020-02-15")
        cumulative = filing(report_num="001", rpt="2022-01-26", start="2019-12-01", thru="2021-11-18")
        ledger, nodes, _, _ = _emit(tmp_path, {
            "2020": {"A-Contributions": [contribution(pre, "U1", 75, **DETAIL)],
                     "Summary": [summary(pre, "A", "1", 75)]},
            "2021": {"A-Contributions": [contribution(cumulative, "U1", 75, **{**DETAIL, "Tran_Emp": "Other Co",
                                                                                "Tran_Zip4": "94999-0002"})],
                     "Summary": [summary(cumulative, "A", "1", 75)]}})
        props = _props(nodes, "moneyflow-1400001-U1")
        assert props["reported_occupation"] == "Engineer" and props["reported_city"] == "Sampleton"
        assert "reported_employer" not in props and "reported_zip5" not in props
        coverage = json.loads((tmp_path / "out" / "contributor-detail.json").read_text())
        assert coverage["flows"]["fields"]["employer"]["withheld"] == {"conflicting_reports": 1}
        assert coverage["conflicts"] == [{"moneyflow_id": "moneyflow-1400001-U1", "field": f,
                                          "rows": [r["row_ref"] for r in ledger.rows if r.get("tran_id") == "U1"]}
                                         for f in ("employer", "zip5")]
        # Each report's own value stays in the private ledger.
        assert sorted(r["reported"]["employer"] for r in ledger.rows if r.get("tran_id") == "U1") == \
            ["Example Co", "Other Co"]

    def test_coverage_reconciles_per_field_for_flows_and_rows(self, tmp_path):
        _emit(tmp_path, {"2024": {
            "A-Contributions": [contribution(F1, "a1", 10, **DETAIL),
                                contribution(F1, "a2", 10, **{**DETAIL, "Tran_Emp": "415-555-0199",
                                                              "Tran_Zip4": "9499", "Tran_Occ": None}),
                                contribution(F1, "a3", 10, **{**DETAIL, "Tran_Emp": "Exampleco.com"}),
                                contribution(F1, "a4", 10, entity="COM", last="Example PAC", **DETAIL)],
            "Summary": [summary(F1, "A", "1", 40)]}})
        coverage = json.loads((tmp_path / "out" / "contributor-detail.json").read_text())
        flows = coverage["flows"]
        assert flows["counted_schedule_a"] == 4 and flows["eligible"] == 3
        assert flows["ineligible"] == {"entity_code_not_ind": 1}
        assert flows["fields"]["employer"] == {"eligible": 3, "published": 1, "source_missing": 0,
                                               "withheld": {"phone": 1, "suspected_pii_unreviewed": 1}}
        assert flows["fields"]["occupation"] == {"eligible": 3, "published": 2, "source_missing": 1, "withheld": {}}
        assert flows["fields"]["zip5"] == {"eligible": 3, "published": 2, "source_missing": 0,
                                           "withheld": {"malformed_zip": 1}}
        for scope in ("flows", "rows"):
            for field, c in coverage[scope]["fields"].items():
                assert c["published"] + c["source_missing"] + sum(c["withheld"].values()) == c["eligible"], field
        assert coverage["rows"]["fields"]["employer"]["eligible"] == 3
        review = [json.loads(line) for line in (tmp_path / "out" / "contributor-detail-review.jsonl").open()]
        assert [(r["field"], r["value"], r["detectors"]) for r in review] == [("employer", "Exampleco.com",
                                                                              ["domain"])]


class TestOutputs:
    SHEETS = {"2024": {
        "A-Contributions": [contribution(F1, "a1", 100), contribution(filing(filer_id="1400009", name="Other PAC"),
                                                                       "a2", 250, last="Jones", first="Mary")],
        "E-Expenditure": [expenditure(F1, "e1", 500)],
        "Summary": [summary(F1, "A", "1", 100), summary(F1, "E", "1", 500),
                    summary(filing(filer_id="1400009", name="Other PAC"), "A", "1", 250)]}}

    def test_every_edge_endpoint_exists_and_ids_are_unique(self, tmp_path):
        _, nodes, edges, report = _emit(tmp_path, self.SHEETS)
        ids = [n["id"] for n in nodes]
        assert len(ids) == len(set(ids))
        assert all(e["source_id"] in ids and e["target_id"] in ids for e in edges)
        assert report["broken_edge_count"] == 0 and report["duplicate_id_count"] == 0

    def test_two_runs_into_empty_dirs_are_byte_identical(self, tmp_path):
        _emit(tmp_path / "r1", self.SHEETS, out="out")
        _emit(tmp_path / "r2", self.SHEETS, out="out")
        for name in ("nodes.jsonl", "edges.jsonl", "normalization-report.json"):
            assert (tmp_path / "r1" / "out" / name).read_bytes() == (tmp_path / "r2" / "out" / name).read_bytes()
