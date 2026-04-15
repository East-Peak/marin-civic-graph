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
