"""Campaign freshness in the bake: published only from a bundle the bake verifies against the export it bakes.

Fictional data throughout (tests/netfile_workbooks.py).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from bake_public_substrate import bake_substrate, main  # noqa: E402
from campaign_ledger import build_ledger, build_transactions, write_ledger  # noqa: E402
from cf_freshness import freshness  # noqa: E402
from cf_prepare import bundle_id  # noqa: E402
from cf_migration_plan import _bundle_props  # noqa: E402
from normalize_campaign_finance import normalize_campaign_source  # noqa: E402
from tests.netfile_workbooks import contribution, filing, summary, write_export  # noqa: E402

F1 = filing(rpt="2024-02-01")
F2 = filing(report_num="001", rpt="2024-10-03", start="2024-07-01", thru="2024-09-21")
REGISTRY = {"graph_node_types": {t: {} for t in ("MoneyFlow", "Person", "Organization", "Committee", "Place")},
            "id_prefixes": {"moneyflow-": "MoneyFlow", "person-": "Person", "org-": "Organization",
                            "committee-": "Committee", "place-": "Place"}}
def _selection(sha: str) -> dict:
    sources = {"src": {"name": "Example County", "jurisdiction_id": "place-test", "years": {
        "2022": {"status": "unavailable", "reason": "no export on file", "held": False},
        "2023": {"status": "unavailable", "reason": "confirmed unavailable", "held": False},
        "2024": {"status": "export", "capture": "2026-10-01", "sha256": sha, "held": True},  # a newer one held
    }}}
    return {"bundle_id": bundle_id(sources), "sources": sources}


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def world(tmp_path):
    rows = [contribution(F1, "a1", 10), contribution(F2, "a2", 20, last="Roe")]
    export_zip = write_export(tmp_path / "raw/2024.zip", {
        "A-Contributions": rows, "Summary": [summary(F1, "A", "1", 10), summary(F2, "A", "1", 20)]})
    sha = hashlib.sha256(export_zip.read_bytes()).hexdigest()
    ledger = build_ledger("src", [("src/2026-10-01/2024.zip", export_zip)])
    build_transactions(ledger)
    bundle = tmp_path / "bundle"
    write_ledger(ledger, bundle / "src")
    nodes, edges, _ = normalize_campaign_source(
        {"source_id": "src", "capture_id": "src__2026-10-01", "jurisdiction_id": "place-test",
         "institution_id": "org-test", "captured_at": "2026-10-01T00:00:00Z"}, ledger, bundle / "src")
    review = (REPO / "registry" / "contributor-detail-reviewed.json").read_bytes()
    (bundle / "src" / "manifest.json").write_text(json.dumps(
        {"capture_id": "src__2026-10-01", "ledger_format": 2, "contributor_review": hashlib.sha256(review).hexdigest(),
         "inputs": [{"path": "src/2026-10-01/2024.zip", "year": "2024", "sha256": sha, "coverage": "workbook"}]}))
    (bundle / "selection.json").write_text(json.dumps(_selection(sha)))
    live = [{"id": n["id"], "labels": n["labels"], "properties": _bundle_props(n)} for n in nodes]
    live_edges = [{"start_id": e["source_id"], "end_id": e["target_id"], "type": e["relationship_type"],
                   "properties": {}} for e in edges]
    _jsonl(tmp_path / "export/nodes.jsonl", live)
    _jsonl(tmp_path / "export/edges.jsonl", live_edges)
    _jsonl(tmp_path / "overlay/nodes.jsonl", [])
    _jsonl(tmp_path / "overlay/edges.jsonl", [])
    (tmp_path / "registry.json").write_text(json.dumps(REGISTRY))
    return {"tmp": tmp_path, "bundle": bundle, "live": live, "edges": live_edges, "sha": sha}


def _bake(world, *bundles: Path, name: str = "out") -> tuple[dict | None, dict]:
    out = world["tmp"] / name
    report = bake_substrate(registry_path=world["tmp"] / "registry.json", sqlite_path=out / "public.sqlite",
                            report_path=out / "report.json", source="live-export",
                            live_export_dir=world["tmp"] / "export", attach_overlay_dir=world["tmp"] / "overlay",
                            campaign_bundles=list(bundles))
    with sqlite3.connect(out / "public.sqlite") as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'campaign_freshness'").fetchone()
    return (json.loads(row[0]) if row else None), report


def test_freshness_comes_from_the_bundle_the_artifact_represents(world):
    published, report = _bake(world, world["bundle"])

    assert published == {"bundle_id": _selection(world["sha"])["bundle_id"], "sources": [{
        "source_id": "src", "name": "Example County", "jurisdiction_id": "place-test",
        "latest_report_date": "2024-10-03", "exports": [{"year": "2024", "export_date": "2026-10-01"}],
        "unavailable_years": ["2022", "2023"], "held_years": ["2024"]}]}
    assert report["campaign_freshness"]["verified_bundle"] == str(world["bundle"])


def test_a_bundle_the_graph_does_not_hold_publishes_no_freshness(world):
    stale = world["tmp"] / "export/nodes.jsonl"
    stale.write_text("".join(json.dumps(n) + "\n" for n in world["live"][:-1]))  # the graph lacks one node

    published, report = _bake(world, world["bundle"])

    assert published is None
    assert report["campaign_freshness"]["verified_bundle"] is None
    assert report["campaign_freshness"]["rejected"][0]["problems"] >= 1


def test_the_first_bundle_that_verifies_wins(world, tmp_path):
    other = tmp_path / "other-bundle"
    other.mkdir()  # no sources: the graph's campaign flows are not in it
    published, report = _bake(world, other, world["bundle"])
    assert published["bundle_id"] == _selection(world["sha"])["bundle_id"]
    assert report["campaign_freshness"]["rejected"][0]["bundle"] == str(other)


def test_a_bundle_without_its_selection_record_is_rejected(world):
    (world["bundle"] / "selection.json").unlink()
    published, report = _bake(world, world["bundle"])
    assert published is None and "selection.json" in report["campaign_freshness"]["rejected"][0]["reason"]


def test_no_bundle_no_key_and_the_bake_is_otherwise_unchanged(world):
    published, report = _bake(world, name="plain")
    with_bundle, _ = _bake(world, world["bundle"], name="with")
    assert published is None and "campaign_freshness" not in report
    with sqlite3.connect(world["tmp"] / "plain/public.sqlite") as a, \
            sqlite3.connect(world["tmp"] / "with/public.sqlite") as b:
        assert a.execute("SELECT * FROM nodes ORDER BY id").fetchall() == b.execute(
            "SELECT * FROM nodes ORDER BY id").fetchall()


def test_the_cli_takes_repeatable_campaign_bundles(world):
    out = world["tmp"] / "cli"
    assert main(["--source", "live-export", "--live-export-dir", str(world["tmp"] / "export"),
                 "--attach-overlay-dir", str(world["tmp"] / "overlay"), "--registry",
                 str(world["tmp"] / "registry.json"), "--sqlite", str(out / "public.sqlite"),
                 "--report", str(out / "report.json"), "--campaign-bundle", str(world["tmp"] / "nowhere"),
                 "--campaign-bundle", str(world["bundle"])]) == 0
    with sqlite3.connect(out / "public.sqlite") as conn:
        assert json.loads(conn.execute("SELECT value FROM meta WHERE key = 'campaign_freshness'").fetchone()[0])


def test_freshness_reads_only_the_bundle(world):
    fields = freshness(world["bundle"])
    assert fields["sources"][0]["latest_report_date"] == "2024-10-03"
    assert "filings through" not in json.dumps(fields)


@pytest.mark.parametrize("tamper,says", [
    ("extra-year", "manifest"),  # a label for an export the bundle never normalized
    ("other-sha", "manifest"),
    ("bundle-id", "bundle_id"),
])
def test_a_selection_that_does_not_match_its_bundle_publishes_nothing(world, tamper, says):
    selection = _selection(world["sha"])
    if tamper == "extra-year":
        selection["sources"]["src"]["years"]["2025"] = {"status": "export", "capture": "2026-04-14",
                                                        "sha256": "d" * 64, "held": False}
        selection["bundle_id"] = bundle_id(selection["sources"])
    elif tamper == "other-sha":
        selection["sources"]["src"]["years"]["2024"]["sha256"] = "e" * 64
        selection["bundle_id"] = bundle_id(selection["sources"])
    else:
        selection["bundle_id"] = "f" * 64
    (world["bundle"] / "selection.json").write_text(json.dumps(selection))

    published, report = _bake(world, world["bundle"])

    assert published is None and says in report["campaign_freshness"]["rejected"][0]["reason"]
