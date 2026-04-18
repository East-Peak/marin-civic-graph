import io
import json
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from normalize_campaign_finance import (
    parse_contributions,
    parse_expenditures,
    build_committee_node,
    build_moneyflow_node,
    build_contributor_node,
    slugify_name,
    normalize_campaign_source,
)


# ---------------------------------------------------------------------------
# Helpers for synthetic test data
# ---------------------------------------------------------------------------

def _make_test_zip(parent: Path, year: str, contributions=None, expenditures=None) -> Path:
    """Create a synthetic NetFile ZIP with Excel worksheets."""
    parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()

    ws_a = wb.active
    ws_a.title = "A-Contributions"
    ws_a.append(["Filer_ID", "Filer_NamL", "Committee_Type", "Tran_ID",
                 "Entity_Cd", "Tran_NamL", "Tran_NamF", "Tran_Amt1",
                 "Tran_Date", "Tran_Emp", "Tran_Occ", "Tran_City",
                 "Tran_State", "Tran_Zip4", "Elect_Date"])
    for row in (contributions or []):
        ws_a.append(row)

    ws_e = wb.create_sheet("E-Expenditure")
    ws_e.append(["Filer_ID", "Filer_NamL", "Committee_Type", "Tran_ID",
                 "Entity_Cd", "Payee_NamL", "Payee_NamF", "Amount",
                 "Expn_Date", "Payee_City", "Payee_State", "Payee_Zip4",
                 "Elect_Date", "Expn_Code", "Expn_Dscr"])
    for row in (expenditures or []):
        ws_e.append(row)

    xlsx_path = parent / "export.xlsx"
    wb.save(xlsx_path)
    zip_path = parent / f"{year}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(xlsx_path, "export.xlsx")
    return zip_path


def _make_capture(source_id: str, jurisdiction_id: str) -> dict:
    return {
        "source_id": source_id,
        "capture_id": f"{source_id}__2026-04-14",
        "jurisdiction_id": jurisdiction_id,
        "institution_id": f"org-{source_id}",
        "captured_at": "2026-04-14T00:00:00Z",
    }


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


class TestBuildMoneyflowNode:
    def test_contribution(self):
        node = build_moneyflow_node(
            filer_id=1461685, tran_id="1cVRUPUuwASA",
            amount=150.0, flow_date="2024-01-13",
            flow_type="contribution", source_schedule="A",
            capture_id="test",
        )
        assert node["id"] == "moneyflow-1461685-a-1cVRUPUuwASA"
        assert node["node_type"] == "MoneyFlow"
        assert node["properties"]["amount"] == 150.0
        assert node["properties"]["flow_type"] == "contribution"

    def test_expenditure(self):
        node = build_moneyflow_node(
            filer_id=1461685, tran_id="xyz",
            amount=500.0, flow_date="2024-03-01",
            flow_type="expenditure", source_schedule="E",
            capture_id="test",
        )
        assert node["properties"]["flow_type"] == "expenditure"


class TestBuildContributorNode:
    def test_individual_creates_person_with_cf_prefix(self):
        node = build_contributor_node(
            name_last="Cullen", name_first="Carleen",
            entity_cd="IND", capture_id="test",
        )
        assert node["id"] == "person-cf-cullen-carleen"
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

    def test_person_id_cannot_collide_with_form700(self):
        """Campaign finance person IDs must be namespaced to prevent cross-pipeline collision."""
        node = build_contributor_node(
            name_last="Colin", name_first="Kate",
            entity_cd="IND", capture_id="test",
        )
        assert node["id"].startswith("person-cf-"), (
            f"Campaign finance person ID must use 'cf' namespace: {node['id']}"
        )

    def test_com_entity_creates_org(self):
        node = build_contributor_node(
            name_last="Some PAC", name_first=None,
            entity_cd="COM", capture_id="test",
        )
        assert node["node_type"] == "Organization"


class TestParseContributions:
    def test_parses_real_data(self):
        # Use the actual 2024 Marin County export
        zip_path = Path("data/raw/marin-county-campaign-finance/2026-04-14/2024.zip")
        if not zip_path.exists():
            pytest.skip("Real data not available")
        rows = parse_contributions(zip_path)
        assert len(rows) > 1000
        row = rows[0]
        assert "filer_id" in row
        assert "tran_id" in row
        assert "amount" in row
        assert "contributor_last" in row


class TestParseExpenditures:
    def test_parses_real_data(self):
        zip_path = Path("data/raw/marin-county-campaign-finance/2026-04-14/2024.zip")
        if not zip_path.exists():
            pytest.skip("Real data not available")
        rows = parse_expenditures(zip_path)
        assert len(rows) > 500
        row = rows[0]
        assert "filer_id" in row
        assert "amount" in row
        assert "payee_last" in row


class TestRecordNodesCreated:
    """Each yearly ZIP export must produce a Record node for evidence chains."""

    def test_record_node_per_year(self, tmp_path):
        zip_path = _make_test_zip(tmp_path / "zips", "2024", contributions=[
            [1234, "Test PAC", "CTL", "TXN001", "IND", "Smith", "John", 100.0,
             "2024-01-15", "Acme", "Analyst", "Novato", "CA", "94945", "2024-11-05"],
        ])
        capture = _make_capture("test-source", "place-test")
        nodes, edges, report = normalize_campaign_source(capture, [zip_path], tmp_path / "out")
        record_nodes = [n for n in nodes if n["node_type"] == "Record"]
        assert len(record_nodes) == 1
        assert record_nodes[0]["id"] == "record-test-source-export-2024"

    def test_two_years_two_records(self, tmp_path):
        zip_2023 = _make_test_zip(tmp_path / "zips", "2023", contributions=[
            [1234, "Test PAC", "CTL", "TXN001", "IND", "Smith", "John", 50.0,
             "2023-06-01", None, None, None, None, None, None],
        ])
        zip_2024 = _make_test_zip(tmp_path / "zips2", "2024", contributions=[
            [1234, "Test PAC", "CTL", "TXN002", "IND", "Jones", "Mary", 75.0,
             "2024-03-15", None, None, None, None, None, None],
        ])
        capture = _make_capture("test-source", "place-test")
        nodes, edges, report = normalize_campaign_source(
            capture, [zip_2023, zip_2024], tmp_path / "out"
        )
        record_nodes = [n for n in nodes if n["node_type"] == "Record"]
        record_ids = {n["id"] for n in record_nodes}
        assert record_ids == {
            "record-test-source-export-2023",
            "record-test-source-export-2024",
        }

    def test_evidenced_by_targets_exist_in_nodes(self, tmp_path):
        zip_path = _make_test_zip(tmp_path / "zips", "2024", contributions=[
            [1234, "Test PAC", "CTL", "TXN001", "IND", "Smith", "John", 100.0,
             "2024-01-15", None, None, None, None, None, None],
        ])
        capture = _make_capture("test-source", "place-test")
        nodes, edges, report = normalize_campaign_source(capture, [zip_path], tmp_path / "out")
        node_ids = {n["id"] for n in nodes}
        evidence_targets = {
            e["target_id"] for e in edges
            if e["relationship_type"] == "EVIDENCED_BY"
        }
        assert evidence_targets, "Should have EVIDENCED_BY edges"
        missing = evidence_targets - node_ids
        assert not missing, f"EVIDENCED_BY targets missing from nodes: {missing}"


class TestMoneyFlowIdUniqueness:
    """MoneyFlow IDs must be unique across schedules."""

    def test_id_includes_schedule(self):
        node = build_moneyflow_node(
            filer_id=1234, tran_id="TXN001", amount=100.0,
            flow_date="2024-01-15", flow_type="contribution",
            source_schedule="A", capture_id="test",
        )
        assert "-a-" in node["id"], f"MoneyFlow ID should include schedule: {node['id']}"

    def test_same_tran_id_different_schedule_unique(self, tmp_path):
        zip_path = _make_test_zip(
            tmp_path / "zips", "2024",
            contributions=[
                [1234, "Test PAC", "CTL", "TXN001", "IND", "Smith", "John",
                 100.0, "2024-01-15", None, None, None, None, None, None],
            ],
            expenditures=[
                [1234, "Test PAC", "CTL", "TXN001", "OTH", "Vendor Inc", None,
                 200.0, "2024-02-01", None, None, None, None, "LIT", "Printing"],
            ],
        )
        capture = _make_capture("test-source", "place-test")
        nodes, edges, report = normalize_campaign_source(capture, [zip_path], tmp_path / "out")
        mf_nodes = [n for n in nodes if n["node_type"] == "MoneyFlow"]
        mf_ids = [n["id"] for n in mf_nodes]
        assert len(mf_ids) == 2
        assert len(set(mf_ids)) == 2, f"MoneyFlow IDs must be unique: {mf_ids}"


class TestOutputReferentialIntegrity:
    """All edge endpoints must reference nodes in the same output."""

    def test_all_edge_endpoints_exist(self, tmp_path):
        zip_path = _make_test_zip(tmp_path / "zips", "2024",
            contributions=[
                [1234, "Test PAC", "CTL", "TXN001", "IND", "Smith", "John",
                 100.0, "2024-01-15", None, None, None, None, None, None],
                [5678, "Other PAC", "CTL", "TXN002", "IND", "Jones", "Mary",
                 250.0, "2024-02-20", None, None, None, None, None, None],
            ],
            expenditures=[
                [1234, "Test PAC", "CTL", "TXN003", "OTH", "Print Shop", None,
                 500.0, "2024-03-01", None, None, None, None, "LIT", "Mailers"],
            ],
        )
        capture = _make_capture("test-source", "place-test")
        nodes, edges, report = normalize_campaign_source(capture, [zip_path], tmp_path / "out")
        node_ids = {n["id"] for n in nodes}
        for edge in edges:
            assert edge["source_id"] in node_ids, (
                f"Edge {edge['relationship_type']} has missing source: {edge['source_id']}"
            )
            assert edge["target_id"] in node_ids, (
                f"Edge {edge['relationship_type']} has missing target: {edge['target_id']}"
            )

    def test_no_duplicate_node_ids(self, tmp_path):
        zip_path = _make_test_zip(tmp_path / "zips", "2024",
            contributions=[
                [1234, "Test PAC", "CTL", "TXN001", "IND", "Smith", "John",
                 100.0, "2024-01-15", None, None, None, None, None, None],
                [1234, "Test PAC", "CTL", "TXN002", "IND", "Smith", "John",
                 200.0, "2024-03-15", None, None, None, None, None, None],
            ],
        )
        capture = _make_capture("test-source", "place-test")
        nodes, edges, report = normalize_campaign_source(capture, [zip_path], tmp_path / "out")
        node_ids = [n["id"] for n in nodes]
        dupes = [nid for nid in node_ids if node_ids.count(nid) > 1]
        assert not dupes, f"Duplicate node IDs: {set(dupes)}"

    def test_report_has_zero_broken_edges(self, tmp_path):
        zip_path = _make_test_zip(tmp_path / "zips", "2024", contributions=[
            [1234, "Test PAC", "CTL", "TXN001", "IND", "Smith", "John",
             100.0, "2024-01-15", None, None, None, None, None, None],
        ])
        capture = _make_capture("test-source", "place-test")
        nodes, edges, report = normalize_campaign_source(capture, [zip_path], tmp_path / "out")
        assert report.get("broken_edge_count", 0) == 0


class TestNormalizeCampaignSource:
    def test_produces_nodes_and_edges(self, tmp_path):
        zip_path = Path("data/raw/marin-county-campaign-finance/2026-04-14/2024.zip")
        if not zip_path.exists():
            pytest.skip("Real data not available")
        capture = {
            "source_id": "marin-county-campaign-finance",
            "capture_id": "marin-county-campaign-finance__2026-04-14",
            "jurisdiction_id": "place-marin-county",
            "institution_id": "org-marin-county-campaign-finance",
            "captured_at": "2026-04-14T00:00:00Z",
        }
        nodes, edges, report = normalize_campaign_source(
            capture, [zip_path], tmp_path,
        )
        assert len(nodes) > 100
        assert len(edges) > 100
        assert report["committee_count"] > 10
        assert report["moneyflow_count"] > 1000

    def test_writes_jsonl(self, tmp_path):
        zip_path = Path("data/raw/marin-county-campaign-finance/2026-04-14/2024.zip")
        if not zip_path.exists():
            pytest.skip("Real data not available")
        capture = {
            "source_id": "marin-county-campaign-finance",
            "capture_id": "marin-county-campaign-finance__2026-04-14",
            "jurisdiction_id": "place-marin-county",
            "institution_id": "org-marin-county-campaign-finance",
            "captured_at": "2026-04-14T00:00:00Z",
        }
        normalize_campaign_source(capture, [zip_path], tmp_path)
        assert (tmp_path / "nodes.jsonl").exists()
        assert (tmp_path / "edges.jsonl").exists()
