# Meeting Normalization Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Granicus and CivicPlus adapter output into settled-ontology JSONL and load Meeting, Record, Organization, and Place nodes into Neo4j AuraDB.

**Architecture:** A normalizer script reads adapter extracted JSON, produces settled-format JSONL (same format `load_neo4j_v2.py` expects), and optionally loads directly into Neo4j. Skips the old projection builder — new data uses the settled ontology from the start.

**Tech Stack:** Python 3, pytest, neo4j driver (for --load flag)

**Spec:** `docs/specs/2026-04-14-meeting-normalization-pipeline-design.md`

---

## File Structure

```
scripts/
  normalize_meetings.py             # Reads adapter JSON, writes settled-format JSONL
tests/
  test_normalize_meetings.py        # Unit + integration tests
```

---

### Task 1: Meeting normalizer core logic

**Files:**
- Create: `scripts/normalize_meetings.py`
- Create: `tests/test_normalize_meetings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_normalize_meetings.py`:

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from normalize_meetings import (
    normalize_source,
    build_meeting_node,
    build_record_node,
    build_institution_stub,
    build_place_stub,
    build_edges,
)


@pytest.fixture
def sample_capture():
    return {
        "capture_id": "novato-city-council__2026-04-14",
        "source_id": "novato-city-council",
        "adapter": "granicus",
        "variant": "modern",
        "captured_at": "2026-04-14T18:30:00Z",
        "url": "https://novato.granicus.com/ViewPublisher.php?view_id=7",
        "jurisdiction_id": "place-novato",
        "institution_id": "org-novato-city-council",
        "raw_artifact": "data/raw/novato-city-council/2026-04-14/source.html",
        "meeting_count": 2,
        "artifact_counts": {"agenda": 2, "minutes": 1, "video": 1},
        "meetings": [
            {
                "meeting_id": "meeting-novato-city-council-2193",
                "date": "2024-03-12",
                "title": "Regular City Council Meeting",
                "meeting_type": "regular",
                "institution_id": "org-novato-city-council",
                "artifacts": {
                    "agenda": {"available": True, "url": "https://novato.granicus.com/AgendaViewer.php?view_id=7&clip_id=2193"},
                    "minutes": {"available": True, "url": "https://novato.granicus.com/MinutesViewer.php?view_id=7&clip_id=2193"},
                    "video": {"available": True, "url": "//novato.granicus.com/MediaPlayer.php?view_id=7&clip_id=2193"},
                },
                "source_row_number": 1,
                "clip_id": "2193",
            },
            {
                "meeting_id": "meeting-novato-city-council-2192",
                "date": "2024-02-27",
                "title": "Special Meeting",
                "meeting_type": "special",
                "institution_id": "org-novato-city-council",
                "artifacts": {
                    "agenda": {"available": True, "url": "https://novato.granicus.com/AgendaViewer.php?view_id=7&clip_id=2192"},
                    "minutes": {"available": False, "url": None},
                    "video": {"available": False, "url": None},
                },
                "source_row_number": 2,
                "clip_id": "2192",
            },
        ],
        "record_refs": [
            {
                "id": "record-novato-city-council-archive-page-2026-04-14",
                "record_type": "meeting_archive_page",
                "source_id": "novato-city-council",
                "artifact_path": "data/raw/novato-city-council/2026-04-14/source.html",
                "captured_at": "2026-04-14T18:30:00Z",
            }
        ],
        "errors": [],
    }


class TestBuildMeetingNode:
    def test_produces_settled_format(self, sample_capture):
        meeting = sample_capture["meetings"][0]
        node = build_meeting_node(meeting, sample_capture)
        assert node["id"] == "meeting-novato-city-council-2193"
        assert node["node_type"] == "Meeting"
        assert node["labels"] == ["Meeting"]
        assert node["properties"]["meeting_date"] == "2024-03-12"
        assert node["properties"]["meeting_type"] == "regular"
        assert node["properties"]["institution_id"] == "org-novato-city-council"
        assert node["qa_lane"] is False

    def test_display_label_format(self, sample_capture):
        meeting = sample_capture["meetings"][0]
        node = build_meeting_node(meeting, sample_capture)
        assert "Novato" in node["display_label"] or "2024-03-12" in node["display_label"]


class TestBuildRecordNode:
    def test_archive_page_record(self, sample_capture):
        ref = sample_capture["record_refs"][0]
        node = build_record_node(ref, sample_capture)
        assert node["id"] == "record-novato-city-council-archive-page-2026-04-14"
        assert node["node_type"] == "Record"
        assert node["labels"] == ["Record"]
        assert node["properties"]["record_type"] == "meeting_archive_page"

    def test_artifact_record(self, sample_capture):
        meeting = sample_capture["meetings"][0]
        node = build_record_node(
            {"id": f"record-novato-city-council-2193-agenda",
             "record_type": "meeting_agenda",
             "source_id": "novato-city-council",
             "source_url": meeting["artifacts"]["agenda"]["url"],
             "captured_at": sample_capture["captured_at"]},
            sample_capture,
        )
        assert node["node_type"] == "Record"
        assert "source_url" in node["properties"]


class TestBuildInstitutionStub:
    def test_creates_organization_government(self, sample_capture):
        node = build_institution_stub(sample_capture)
        assert node["id"] == "org-novato-city-council"
        assert node["node_type"] == "Organization"
        assert "Government" in node["labels"]
        assert "Organization" in node["labels"]


class TestBuildPlaceStub:
    def test_creates_place(self, sample_capture):
        node = build_place_stub(sample_capture)
        assert node["id"] == "place-novato"
        assert node["node_type"] == "Place"
        assert node["properties"]["place_type"] == "city"


class TestBuildEdges:
    def test_meeting_to_institution(self, sample_capture):
        meeting = sample_capture["meetings"][0]
        edges = build_edges(meeting, sample_capture)
        inst_edges = [e for e in edges if e["relationship_type"] == "AT_INSTITUTION"]
        assert len(inst_edges) == 1
        assert inst_edges[0]["target_id"] == "org-novato-city-council"

    def test_meeting_to_jurisdiction(self, sample_capture):
        meeting = sample_capture["meetings"][0]
        edges = build_edges(meeting, sample_capture)
        juris_edges = [e for e in edges if e["relationship_type"] == "IN_JURISDICTION"]
        assert len(juris_edges) == 1
        assert juris_edges[0]["target_id"] == "place-novato"

    def test_meeting_to_evidence(self, sample_capture):
        meeting = sample_capture["meetings"][0]
        edges = build_edges(meeting, sample_capture)
        ev_edges = [e for e in edges if e["relationship_type"] == "EVIDENCED_BY"]
        # 3 available artifacts (agenda, minutes, video) = 3 evidence edges
        assert len(ev_edges) == 3

    def test_no_evidence_for_unavailable_artifacts(self, sample_capture):
        meeting = sample_capture["meetings"][1]  # Special meeting — only agenda available
        edges = build_edges(meeting, sample_capture)
        ev_edges = [e for e in edges if e["relationship_type"] == "EVIDENCED_BY"]
        assert len(ev_edges) == 1  # Only agenda


class TestNormalizeSource:
    def test_produces_nodes_and_edges(self, sample_capture, tmp_path):
        nodes, edges, report = normalize_source(sample_capture, tmp_path)
        assert len(nodes) > 0
        assert len(edges) > 0

    def test_includes_meeting_nodes(self, sample_capture, tmp_path):
        nodes, edges, report = normalize_source(sample_capture, tmp_path)
        meeting_nodes = [n for n in nodes if n["node_type"] == "Meeting"]
        assert len(meeting_nodes) == 2

    def test_includes_institution_and_place(self, sample_capture, tmp_path):
        nodes, edges, report = normalize_source(sample_capture, tmp_path)
        org_nodes = [n for n in nodes if n["node_type"] == "Organization"]
        place_nodes = [n for n in nodes if n["node_type"] == "Place"]
        assert len(org_nodes) == 1
        assert len(place_nodes) == 1

    def test_includes_record_nodes(self, sample_capture, tmp_path):
        nodes, edges, report = normalize_source(sample_capture, tmp_path)
        record_nodes = [n for n in nodes if n["node_type"] == "Record"]
        # 1 archive page + artifact records for available URLs
        assert len(record_nodes) >= 1

    def test_writes_jsonl_files(self, sample_capture, tmp_path):
        normalize_source(sample_capture, tmp_path)
        assert (tmp_path / "nodes.jsonl").exists()
        assert (tmp_path / "edges.jsonl").exists()
        assert (tmp_path / "normalization-report.json").exists()

    def test_report_has_counts(self, sample_capture, tmp_path):
        nodes, edges, report = normalize_source(sample_capture, tmp_path)
        assert "node_count" in report
        assert "edge_count" in report
        assert report["node_count"] == len(nodes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /<repo> && python -m pytest tests/test_normalize_meetings.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement normalize_meetings.py**

Create `scripts/normalize_meetings.py`:

```python
#!/usr/bin/env python3
"""Normalize adapter meeting output into settled-ontology JSONL for Neo4j loading.

Reads extracted JSON from Granicus/CivicPlus adapters and produces:
  - nodes.jsonl (Meeting, Record, Organization, Place nodes)
  - edges.jsonl (AT_INSTITUTION, IN_JURISDICTION, EVIDENCED_BY)
  - normalization-report.json
"""

from __future__ import annotations

import argparse
import json
import glob
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent

# Maps source_id patterns to human-readable institution display names
INSTITUTION_DISPLAY = {
    "org-marin-county-board-of-supervisors": "Marin County Board of Supervisors",
    "org-novato-city-council": "Novato City Council",
    "org-sausalito-city-council": "Sausalito City Council",
    "org-corte-madera-town-council": "Corte Madera Town Council",
    "org-mill-valley-committees": "Mill Valley Committees",
}

PLACE_DISPLAY = {
    "place-marin-county": ("Marin County", "county"),
    "place-novato": ("Novato", "city"),
    "place-sausalito": ("Sausalito", "city"),
    "place-corte-madera": ("Corte Madera", "city"),
    "place-mill-valley": ("Mill Valley", "city"),
}

ARTIFACT_RECORD_TYPES = {
    "agenda": "meeting_agenda",
    "minutes": "meeting_minutes",
    "video": "meeting_video",
    "packet": "meeting_packet",
    "captions": "meeting_captions",
    "mp3": "meeting_audio",
    "mp4": "meeting_video_file",
}


def _node(id: str, node_type: str, labels: list[str], display_label: str,
          properties: dict, capture: dict, section: str = "meeting_candidates",
          status: str | None = None) -> dict:
    return {
        "id": id,
        "node_type": node_type,
        "labels": labels,
        "display_label": display_label,
        "promotion_state": "promoted",
        "source_bundle_ids": [capture["capture_id"]],
        "source_sections": [section],
        "source_status": status,
        "properties": properties,
        "qa_lane": False,
    }


def _edge(source_id: str, source_type: str, target_id: str, target_type: str,
          rel_type: str, capture: dict, properties: dict | None = None) -> dict:
    return {
        "source_id": source_id,
        "source_node_type": source_type,
        "target_id": target_id,
        "target_node_type": target_type,
        "relationship_type": rel_type,
        "source_bundle_ids": [capture["capture_id"]],
        "source_fields": ["normalize_meetings"],
        "properties": properties or {},
    }


def build_meeting_node(meeting: dict, capture: dict) -> dict:
    source_id = capture["source_id"]
    title = meeting.get("title") or "Meeting"
    date = meeting.get("date") or ""
    display = f"{title} — {date}" if date else title

    props = {
        "meeting_date": date,
        "meeting_type": meeting.get("meeting_type", "other"),
        "title": title,
        "institution_id": capture["institution_id"],
        "jurisdiction_id": capture["jurisdiction_id"],
    }
    if meeting.get("clip_id"):
        props["clip_id"] = meeting["clip_id"]
    if meeting.get("agenda_id"):
        props["agenda_id"] = meeting["agenda_id"]
    if meeting.get("category"):
        props["category"] = meeting["category"]

    return _node(
        id=meeting["meeting_id"],
        node_type="Meeting",
        labels=["Meeting"],
        display_label=display,
        properties=props,
        capture=capture,
        status=f"captured_from_{capture.get('adapter', 'unknown')}",
    )


def build_record_node(ref: dict, capture: dict) -> dict:
    props = {
        "record_type": ref.get("record_type", "unknown"),
        "source_id": ref.get("source_id", capture["source_id"]),
    }
    if ref.get("artifact_path"):
        props["artifact_path"] = ref["artifact_path"]
    if ref.get("source_url"):
        props["source_url"] = ref["source_url"]
    if ref.get("captured_at"):
        props["captured_at"] = ref["captured_at"]
    if ref.get("year"):
        props["year"] = ref["year"]

    return _node(
        id=ref["id"],
        node_type="Record",
        labels=["Record"],
        display_label=ref.get("record_type", ref["id"]),
        properties=props,
        capture=capture,
        section="record_refs",
        status="captured",
    )


def build_institution_stub(capture: dict) -> dict:
    inst_id = capture["institution_id"]
    display = INSTITUTION_DISPLAY.get(inst_id, inst_id.replace("org-", "").replace("-", " ").title())
    return _node(
        id=inst_id,
        node_type="Organization",
        labels=["Organization", "Government"],
        display_label=display,
        properties={
            "name": display,
            "subtype": "government",
            "jurisdiction_id": capture["jurisdiction_id"],
        },
        capture=capture,
        section="institution_stubs",
        status="stub_from_adapter_config",
    )


def build_place_stub(capture: dict) -> dict:
    place_id = capture["jurisdiction_id"]
    display, place_type = PLACE_DISPLAY.get(place_id, (place_id.replace("place-", "").replace("-", " ").title(), "city"))
    return _node(
        id=place_id,
        node_type="Place",
        labels=["Place"],
        display_label=display,
        properties={"name": display, "place_type": place_type},
        capture=capture,
        section="place_stubs",
        status="stub_from_adapter_config",
    )


def build_edges(meeting: dict, capture: dict) -> list[dict]:
    edges = []
    mid = meeting["meeting_id"]

    # Meeting → Organization
    edges.append(_edge(mid, "Meeting", capture["institution_id"], "Organization",
                       "AT_INSTITUTION", capture))

    # Meeting → Place
    edges.append(_edge(mid, "Meeting", capture["jurisdiction_id"], "Place",
                       "IN_JURISDICTION", capture))

    # Meeting → Record (evidence for each available artifact)
    for art_type, art in meeting.get("artifacts", {}).items():
        if art.get("available") and art.get("url"):
            record_id = f"record-{capture['source_id']}-{meeting['meeting_id'].split('meeting-')[-1]}-{art_type}"
            edges.append(_edge(mid, "Meeting", record_id, "Record",
                               "EVIDENCED_BY", capture))

    return edges


def normalize_source(capture: dict, output_dir: Path) -> tuple[list[dict], list[dict], dict]:
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes: list[dict] = []
    edges: list[dict] = []

    # Institution and Place stubs
    nodes.append(build_institution_stub(capture))
    nodes.append(build_place_stub(capture))

    # Organization → Place edge
    edges.append(_edge(capture["institution_id"], "Organization",
                       capture["jurisdiction_id"], "Place",
                       "IN_JURISDICTION", capture))

    # Archive page record
    for ref in capture.get("record_refs", []):
        nodes.append(build_record_node(ref, capture))

    # Meetings + per-meeting artifact records + edges
    for meeting in capture.get("meetings", []):
        nodes.append(build_meeting_node(meeting, capture))
        meeting_edges = build_edges(meeting, capture)
        edges.extend(meeting_edges)

        # Create Record nodes for available artifacts
        for art_type, art in meeting.get("artifacts", {}).items():
            if art.get("available") and art.get("url"):
                mid_suffix = meeting["meeting_id"].split("meeting-")[-1]
                record_id = f"record-{capture['source_id']}-{mid_suffix}-{art_type}"
                record_type = ARTIFACT_RECORD_TYPES.get(art_type, f"meeting_{art_type}")
                nodes.append(build_record_node(
                    {"id": record_id, "record_type": record_type,
                     "source_id": capture["source_id"],
                     "source_url": art["url"],
                     "captured_at": capture["captured_at"]},
                    capture,
                ))

    # Write JSONL
    with open(output_dir / "nodes.jsonl", "w") as f:
        for node in nodes:
            f.write(json.dumps(node, sort_keys=True) + "\n")
    with open(output_dir / "edges.jsonl", "w") as f:
        for edge in edges:
            f.write(json.dumps(edge, sort_keys=True) + "\n")

    report = {
        "source_id": capture["source_id"],
        "capture_id": capture["capture_id"],
        "normalized_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meeting_count": len(capture.get("meetings", [])),
        "record_count": len([n for n in nodes if n["node_type"] == "Record"]),
    }
    with open(output_dir / "normalization-report.json", "w") as f:
        json.dump(report, indent=2, fp=f)
        f.write("\n")

    return nodes, edges, report


def find_latest_capture(source_id: str) -> Path | None:
    pattern = str(ROOT / "data" / "extracted" / source_id / "*.json")
    files = sorted(glob.glob(pattern))
    return Path(files[-1]) if files else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize adapter meeting output to settled-ontology JSONL")
    parser.add_argument("--source", help="Source ID to normalize")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Normalize all available sources")
    parser.add_argument("--load", action="store_true", help="Load into Neo4j after normalization")
    args = parser.parse_args()

    import yaml
    sources = []
    for registry_file in (ROOT / "registry").glob("*-sources.yaml"):
        with open(registry_file) as f:
            data = yaml.safe_load(f)
        sources.extend(data.get("sources", []))

    if args.source:
        targets = [s for s in sources if s["id"] == args.source]
        if not targets:
            print(f"Unknown source: {args.source}", file=sys.stderr)
            sys.exit(1)
    elif args.all_sources:
        targets = sources
    else:
        print("Specify --source <id> or --all", file=sys.stderr)
        sys.exit(1)

    for source_config in targets:
        source_id = source_config["id"]
        capture_path = find_latest_capture(source_id)
        if not capture_path:
            print(f"  No captures found for {source_id}, skipping")
            continue

        print(f"\nNormalizing: {source_id}")
        print(f"  Capture: {capture_path}")

        capture = json.loads(capture_path.read_text())
        if capture.get("meeting_count", 0) == 0:
            print(f"  No meetings in capture, skipping")
            continue

        output_dir = ROOT / "data" / "normalized" / f"{source_id}-meetings"
        nodes, edges, report = normalize_source(capture, output_dir)

        print(f"  Nodes: {report['node_count']}")
        print(f"  Edges: {report['edge_count']}")
        print(f"  Meetings: {report['meeting_count']}")
        print(f"  Records: {report['record_count']}")
        print(f"  Output: {output_dir}")

        if args.load:
            from load_neo4j_v2 import load_nodes as neo4j_load_nodes, load_edges as neo4j_load_edges, apply_schema
            from neo4j import GraphDatabase

            uri = os.getenv("NEO4J_URI")
            user = os.getenv("NEO4J_USER")
            password = os.getenv("NEO4J_PASSWORD")
            if not all([uri, user, password]):
                print("  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD required for --load", file=sys.stderr)
                continue

            driver = GraphDatabase.driver(uri, auth=(user, password))
            try:
                print(f"  Loading into Neo4j...")
                neo4j_load_nodes(driver, nodes)
                neo4j_load_edges(driver, edges)
                print(f"  Loaded.")
            finally:
                driver.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /<repo> && python -m pytest tests/test_normalize_meetings.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /<repo> && python -m pytest tests/ -v`
Expected: All 266+ tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/normalize_meetings.py tests/test_normalize_meetings.py
git commit -m "feat: add meeting normalization pipeline (adapter output → settled-ontology JSONL)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Normalize all sources and load into Neo4j

**Files:**
- No new files — execution task

- [ ] **Step 1: Run all unit tests**

Run: `cd /<repo> && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Normalize Marin County BOS**

Run: `python scripts/normalize_meetings.py --source marin-county-bos`
Expected: ~317 meetings normalized, nodes.jsonl + edges.jsonl written

- [ ] **Step 3: Normalize Novato**

Run: `python scripts/normalize_meetings.py --source novato-city-council`
Expected: ~409 meetings normalized

- [ ] **Step 4: Normalize all remaining sources**

Run: `python scripts/normalize_meetings.py --all`
Expected: All 5 sources normalized (Sausalito, Corte Madera, Mill Valley + the ones already done get overwritten idempotently)

- [ ] **Step 5: Load all normalized data into Neo4j**

Run with --load flag (requires NEO4J_* env vars):
```bash
export NEO4J_URI="neo4j+s://<INSTANCE-ID>.databases.neo4j.io"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="<from Desktop file>"

python scripts/normalize_meetings.py --all --load
```

Expected: New nodes loaded into AuraDB

- [ ] **Step 6: Verify in Neo4j**

Run verification script + ad-hoc queries:
```bash
python scripts/verify_neo4j_v2.py
```

Then check new data:
```python
# Count meetings by jurisdiction
MATCH (m:Meeting)-[:AT_INSTITUTION]->(o:Organization)
RETURN o.name, count(m) AS meetings
ORDER BY meetings DESC

# Verify Place nodes
MATCH (p:Place) RETURN p.name, p.place_type

# Verify Organization:Government nodes
MATCH (o:Organization:Government) RETURN o.name
```

Expected: Novato, Sausalito, Corte Madera, Mill Valley, Marin County BOS meetings all present alongside existing San Rafael data. San Rafael verification checks still pass.

- [ ] **Step 7: Commit and push**

```bash
git add docs/specs/2026-04-14-meeting-normalization-pipeline-design.md docs/superpowers/plans/2026-04-14-meeting-normalization-pipeline.md
git commit -m "feat: meeting normalization pipeline — 5 jurisdictions loaded into Neo4j

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

git push
```

---

## Build Verification

1. `python -m pytest tests/ -v` — all tests pass
2. `python scripts/normalize_meetings.py --all` — all 5 sources normalized
3. Neo4j has Meeting nodes from Novato, Sausalito, Corte Madera, Mill Valley, Marin County BOS
4. Neo4j has Organization:Government nodes for each institution
5. Neo4j has Place nodes for each jurisdiction
6. Existing San Rafael verification checks still pass (20/20)
7. Running normalization + load twice produces the same graph (idempotent)
