# Campaign Finance Normalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse NetFile campaign finance Excel exports (A-Contributions + E-Expenditure) into Committee, MoneyFlow, Person, and Organization nodes and load into Neo4j.

**Architecture:** Same normalize → JSONL → `load_neo4j_v2.py` pattern as meetings. One normalizer script reads ZIP exports, parses Excel with openpyxl, produces settled-format JSONL. Strict red/green TDD.

**Tech Stack:** Python 3, pytest, openpyxl (already installed), zipfile (stdlib)

**Spec:** `docs/specs/2026-04-15-campaign-finance-normalization-design.md`

---

## File Structure

```
scripts/
  normalize_campaign_finance.py     # Reads NetFile ZIPs, writes settled-format JSONL
tests/
  test_normalize_campaign_finance.py
```

---

### Task 1: Campaign finance normalizer

**Files:**
- Create: `scripts/normalize_campaign_finance.py`
- Create: `tests/test_normalize_campaign_finance.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_normalize_campaign_finance.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_normalize_campaign_finance.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement normalize_campaign_finance.py**

Create `scripts/normalize_campaign_finance.py`. Key functions:

**`slugify_name(last, first)`** — lowercase, strip special chars, join with hyphen.

**`parse_contributions(zip_path)`** — open ZIP, find xlsx, read A-Contributions sheet with openpyxl, return list of dicts with: filer_id, filer_name, committee_type, tran_id, contributor_last, contributor_first, amount, flow_date, entity_cd, employer, occupation, city, state, zip, elect_date.

**`parse_expenditures(zip_path)`** — same but for E-Expenditure sheet, using Payee_NamL/F instead of Tran_NamL/F.

**`build_committee_node(filer_id, filer_name, committee_type, jurisdiction_id, capture_id)`** — returns settled-format node dict. ID: `committee-netfile-{filer_id}`.

**`build_moneyflow_node(filer_id, tran_id, amount, flow_date, flow_type, source_schedule, capture_id)`** — returns MoneyFlow node. ID: `moneyflow-{filer_id}-{tran_id}`.

**`build_contributor_node(name_last, name_first, entity_cd, capture_id)`** — returns Person node for IND entity_cd, Organization node for COM/OTH/SCC.

**`normalize_campaign_source(capture, zip_paths, output_dir)`** — orchestrates:
1. Parse all ZIPs for contributions + expenditures
2. Build Committee nodes (dedup by filer_id)
3. Build MoneyFlow nodes (one per row)
4. Build contributor Person/Org stub nodes (dedup by slug)
5. Build edges: FROM_SOURCE, TO_TARGET, EVIDENCED_BY, IN_JURISDICTION
6. Write JSONL + report

CLI with `--source` and `--all` flags, plus `--load` for Neo4j.

The script reads the NetFile capture JSON to find which ZIPs were downloaded, then parses each one.

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_normalize_campaign_finance.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v`
Expected: All 315+ PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/normalize_campaign_finance.py tests/test_normalize_campaign_finance.py
git commit -m "feat: add campaign finance normalizer (NetFile Excel → Committee/MoneyFlow/Person nodes)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Normalize all years and load into Neo4j

- [ ] **Step 1: Normalize Marin County (all 8 years)**

Run: `python scripts/normalize_campaign_finance.py --source marin-county-campaign-finance`
Expected: Thousands of nodes across committees, money flows, and contributors

- [ ] **Step 2: Normalize Novato (all 8 years)**

Run: `python scripts/normalize_campaign_finance.py --source novato-campaign-finance`

- [ ] **Step 3: Load into Neo4j**

```bash
export NEO4J_URI="neo4j+s://<INSTANCE-ID>.databases.neo4j.io"
export NEO4J_USER="neo4j"  
export NEO4J_PASSWORD="<from Desktop file>"

python scripts/normalize_campaign_finance.py --source marin-county-campaign-finance --load
python scripts/normalize_campaign_finance.py --source novato-campaign-finance --load
```

- [ ] **Step 4: Verify**

```bash
python scripts/verify_neo4j_v2.py
```

Plus ad-hoc queries:
```cypher
MATCH (mf:MoneyFlow)-[:TO_TARGET]->(c:Committee)
WHERE mf.amount > 1000
RETURN c.name, count(mf) AS contributions, sum(mf.amount) AS total
ORDER BY total DESC LIMIT 10

MATCH (p:Person)-[:FROM_SOURCE]-(mf:MoneyFlow)-[:TO_TARGET]->(c:Committee)
WITH p, count(DISTINCT c) AS committee_count
WHERE committee_count > 1
RETURN p.name, committee_count ORDER BY committee_count DESC LIMIT 10
```

- [ ] **Step 5: Commit and push**

```bash
git add docs/specs/2026-04-15-campaign-finance-normalization-design.md docs/superpowers/plans/2026-04-15-campaign-finance-normalization.md
git commit -m "feat: campaign finance loaded — Marin County + Novato contributions and expenditures

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
git push
```
