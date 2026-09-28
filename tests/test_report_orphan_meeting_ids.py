"""Tests for scripts/report_orphan_meeting_ids.py — offline, read-only dry run."""

import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import report_orphan_meeting_ids as report
from adapters.meeting_ids import title_hash

SCRIPT = Path(report.__file__)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload)


def _capture(source_id, adapter, meetings, raw_artifact=None):
    return {
        "source_id": source_id,
        "adapter": adapter,
        "raw_artifact": raw_artifact,
        "meetings": meetings,
    }


ROSS_RAW = (
    '<table class="views-table cols-5"><tbody>'
    '<tr><td><span content="2026-04-29T18:00:00-07:00">x</span></td>'
    '<td><a href="/towncouncil/page/ross-town-council-meeting-10">Ross Town Council Meeting</a></td>'
    "<td></td><td></td><td></td></tr>"
    '<tr><td><span content="2026-05-19T18:00:00-07:00">x</span></td>'
    "<td>Advisory Design Review Group</td><td></td><td></td><td></td></tr>"
    "</tbody></table>"
)


def _data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    s = "sausalito-city-council"
    _write(
        data / "extracted" / s / "2026-04-14.json",
        _capture(s, "granicus", [
            {"meeting_id": f"meeting-{s}-1234", "clip_id": "1234", "event_id": None,
             "date": "2026-03-03", "title": "City Council"},
            {"meeting_id": f"meeting-{s}-2026-04-14-row-1", "clip_id": None, "event_id": "1126",
             "date": "2026-04-14", "title": "City Council"},
            {"meeting_id": f"meeting-{s}-2026-04-21-row-2", "clip_id": None, "event_id": None,
             "date": "2026-04-21", "title": "City Council"},
        ]),
    )
    r = "ross-town-council"
    _write(
        data / "extracted" / r / "2026-04-15.json",
        _capture(r, "drupal_ross", [
            {"meeting_id": f"meeting-{r}-2026-04-29-row-1", "date": "2026-04-29",
             "title": "Ross Town Council Meeting"},
            {"meeting_id": f"meeting-{r}-2026-05-19-row-2", "date": "2026-05-19",
             "title": "Advisory Design Review Group"},
        ], raw_artifact=f"data/raw/{r}/2026-04-15/source.html"),
    )
    _write(data / "raw" / r / "2026-04-15" / "source.html", ROSS_RAW)
    _write(
        data / "extracted" / r / "2026-03-01.json",
        _capture(r, "drupal_ross", [
            {"meeting_id": f"meeting-{r}-2026-03-12-row-1", "date": "2026-03-12",
             "title": "Ross Town Council Meeting"},
        ], raw_artifact=f"data/raw/{r}/2026-03-01/source.html"),
    )
    _write(data / "extracted" / "marin-ij-coverage" / "2026-04-10.json", [{"not": "meetings"}])
    _write(data / "extracted" / "README.md", "not a capture")
    return data


def _by_old_id(result):
    return {m["old_id"]: m for m in result["mappings"]}


class TestBuildReport:
    def test_maps_granicus_row_ids_to_stable_ids(self, tmp_path):
        s = "sausalito-city-council"
        mappings = _by_old_id(report.build_report(_data_dir(tmp_path)))
        assert mappings[f"meeting-{s}-2026-04-14-row-1"]["stable_id"] == f"meeting-{s}-event-1126"
        assert mappings[f"meeting-{s}-2026-04-21-row-2"]["stable_id"] == (
            f"meeting-{s}-2026-04-21-{title_hash('City Council')}"
        )
        assert mappings[f"meeting-{s}-2026-04-21-row-2"]["key"] == "title_hash"

    def test_native_ids_are_not_reported(self, tmp_path):
        result = report.build_report(_data_dir(tmp_path))
        assert "meeting-sausalito-city-council-1234" not in _by_old_id(result)
        assert result["changed_native_ids"] == []

    def test_ross_detail_url_recovered_from_raw_html(self, tmp_path):
        r = "ross-town-council"
        mappings = _by_old_id(report.build_report(_data_dir(tmp_path)))
        assert mappings[f"meeting-{r}-2026-04-29-row-1"]["stable_id"] == (
            f"meeting-{r}-towncouncil-page-ross-town-council-meeting-10"
        )
        assert mappings[f"meeting-{r}-2026-05-19-row-2"]["stable_id"] == (
            f"meeting-{r}-2026-05-19-{title_hash('Advisory Design Review Group')}"
        )

    def test_ross_rows_without_raw_html_are_unresolved_not_guessed(self, tmp_path):
        result = report.build_report(_data_dir(tmp_path))
        unresolved = {u["old_id"] for u in result["unresolved"]}
        assert unresolved == {"meeting-ross-town-council-2026-03-12-row-1"}
        assert "meeting-ross-town-council-2026-03-12-row-1" not in _by_old_id(result)

    def test_summary_counts_per_source(self, tmp_path):
        sources = report.build_report(_data_dir(tmp_path))["sources"]
        assert sources["sausalito-city-council"]["row_position_ids"] == 2
        assert sources["sausalito-city-council"]["mapped"] == 2
        assert sources["ross-town-council"]["row_position_ids"] == 3
        assert sources["ross-town-council"]["mapped"] == 2
        assert sources["ross-town-council"]["unresolved"] == 1
        assert "marin-ij-coverage" not in sources


class TestMain:
    def test_writes_report_to_out_path(self, tmp_path):
        out = tmp_path / "reports" / "orphans.json"
        assert report.main(["--data-dir", str(_data_dir(tmp_path)), "--out", str(out)]) == 0
        written = json.loads(out.read_text())
        assert written["graph_mutation"] == "none"
        assert len(written["mappings"]) == 4

    def test_never_touches_neo4j(self):
        tree = ast.parse(SCRIPT.read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any("neo4j" in name for name in imported)
