import io
import json
import sys
import zipfile
from pathlib import Path

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
        assert node["id"] == "moneyflow-1461685-1cVRUPUuwASA"
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
    def test_individual_creates_person(self):
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
