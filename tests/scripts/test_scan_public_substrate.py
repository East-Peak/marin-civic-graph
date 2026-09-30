"""The artifact-wide contributor privacy scan, over real bakes of a small synthetic graph.

Every value is fictional (EXAMPLE/SAMPLE names, 555 phone numbers).
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

from bake_public_substrate import bake_substrate  # noqa: E402
from campaign_ledger import build_ledger, build_transactions, write_ledger  # noqa: E402
from cf_migration_plan import _bundle_props  # noqa: E402
from normalize_campaign_finance import normalize_campaign_source  # noqa: E402
from scan_public_substrate import main, scan  # noqa: E402
from tests.netfile_workbooks import contribution, filing, summary, write_export  # noqa: E402

F1 = filing()
BASE = {"Tran_Occ": "Engineer", "Tran_City": "Sampleton", "Tran_State": "CA", "Tran_Zip4": "94999"}
ROWS = [
    contribution(F1, "a1", 10, **{**BASE, "Tran_Emp": "Example Co", "Tran_Zip4": "94999-0001"}),
    contribution(F1, "a2", 10, last="Roe", **{**BASE, "Tran_Emp": "415-555-0199"}),
    contribution(F1, "a3", 10, last="Poe", **{**BASE, "Tran_Emp": "12 Sample Lane, Sampleton, CA 94999"}),
    contribution(F1, "a4", 10, last="Loe", **{**BASE, "Tran_Emp": "Exampleco.com"}),
    contribution(F1, "a5", 10, entity="COM", last="Example PAC", **{**BASE, "Tran_Emp": "Example Co"}),
]
OCR = {"id": "moneyflow-committee-example-1", "labels": ["MoneyFlow"], "properties": {
    "id": "moneyflow-committee-example-1", "amount": 50.0, "flow_type": "campaign_contribution",
    "source_schedule": "schedule_a", "display_label": "campaign_contribution $50.00",
    "address_raw": "77 SAMPLEWOOD LN, SAMPLETON CA 94999"}}
COMMERCIAL = {"id": "permit-marin-IN_C1_1", "labels": ["Project"], "properties": {
    "id": "permit-marin-IN_C1_1", "address": "1600 EXAMPLE HOLLOW DR, SAMPLETON, CA 94999",
    "display_label": "TI at 1600 EXAMPLE HOLLOW DR, SAMPLETON, CA 94999", "project_type": "building_permit",
    "source": "marin-county-socrata-permits", "type_permit": "COMMERCIAL"}}
REGISTRY = {"graph_node_types": {t: {} for t in ("Project", "MoneyFlow", "Person", "Organization", "Committee",
                                                  "Place")},
            "id_prefixes": {"permit-": "Project", "moneyflow-": "MoneyFlow", "person-": "Person", "org-": "Organization",
                            "committee-": "Committee", "place-": "Place"}}


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _bake(root: Path, nodes: list[dict], edges: list[dict]) -> Path:
    _jsonl(root / "export" / "nodes.jsonl", nodes)
    _jsonl(root / "export" / "edges.jsonl", edges)
    _jsonl(root / "overlay" / "nodes.jsonl", [])
    _jsonl(root / "overlay" / "edges.jsonl", [])
    (root / "registry.json").write_text(json.dumps(REGISTRY))
    bake_substrate(registry_path=root / "registry.json", sqlite_path=root / "public.sqlite",
                   report_path=root / "report.json", source="live-export", live_export_dir=root / "export",
                   attach_overlay_dir=root / "overlay")
    return root / "public.sqlite"


@pytest.fixture
def world(tmp_path):
    """A CF2 bundle, the candidate graph with details, and the baseline graph without them, both baked."""
    ledger = build_ledger("src", [("src/2026-04-14/2024.zip", write_export(tmp_path / "raw" / "2024.zip", {
        "A-Contributions": ROWS, "Summary": [summary(F1, "A", "1", 50)]}))])
    build_transactions(ledger)
    bundle = tmp_path / "bundle"
    write_ledger(ledger, bundle / "src")
    nodes, edges, _ = normalize_campaign_source(
        {"source_id": "src", "capture_id": "src__2026-04-14", "jurisdiction_id": "place-test",
         "institution_id": "org-test", "captured_at": "2026-04-14T00:00:00Z"}, ledger, bundle / "src")
    review = (REPO / "registry" / "contributor-detail-reviewed.json").read_bytes()
    (bundle / "src" / "manifest.json").write_text(json.dumps(
        {"capture_id": "src__2026-04-14", "inputs": [], "ledger_format": 2,
         "contributor_review": hashlib.sha256(review).hexdigest()}))
    live = [{"id": n["id"], "labels": n["labels"], "properties": _bundle_props(n)} for n in nodes]
    live_edges = [{"start_id": e["source_id"], "end_id": e["target_id"], "type": e["relationship_type"],
                   "properties": {}} for e in edges]
    bare = [{**n, "properties": {k: v for k, v in n["properties"].items() if not k.startswith("reported_")}}
            for n in live]
    world = {"tmp": tmp_path, "bundle": bundle, "live": live, "edges": live_edges}
    world["baseline"] = _bake(tmp_path / "baseline", [*bare, OCR, COMMERCIAL], live_edges)
    world["candidate"] = _bake(tmp_path / "candidate", [*live, OCR, COMMERCIAL], live_edges)
    return world


def _scan(world, sqlite=None, explain=()):
    return scan(sqlite or world["candidate"], world["baseline"], world["bundle"], world["tmp"] / "candidate" / "export",
                list(explain))


def test_a_clean_candidate_passes_every_gate(world):
    report = _scan(world)
    assert report["gate_a_prohibited_hits"] == []
    assert report["gate_b_new_findings"] == []
    assert report["gate_c_reconciliation_problems"] == []
    assert report["passed"]
    assert report["needles"] == {"ocr_address_raw": 2, "raw_zip4": 1, "shaped_employer": 1, "withheld_phone": 1,
                                 "withheld_street": 1}
    assert report["gate_a_preexisting_public_text"] == []
    assert report["coverage"]["src"]["eligible"] == 4
    assert report["coverage"]["src"]["fields"]["employer"] == {
        "published": 1, "withheld:phone": 1, "withheld:street": 1, "withheld:suspected_pii_unreviewed": 1}
    # The commercial permit's address is a baseline finding: Project exposure stays authoritative.
    assert report["baseline_findings"]["nodes:street"] >= 1


def test_the_published_details_are_really_in_the_artifact(world):
    with sqlite3.connect(world["candidate"]) as conn:
        props = json.loads(conn.execute("SELECT props FROM nodes WHERE id = 'moneyflow-1400001-a1'").fetchone()[0])
    assert props["reported_employer"] == "Example Co" and props["reported_zip5"] == "94999"


@pytest.mark.parametrize("where, value, kind", [
    ("name", "call 415-555-0199", "withheld_phone"),
    ("display_label", "Office at 12 Sample Lane, Sampleton, CA 94999", "withheld_street"),
    ("name", "mail to 94999-0001", "raw_zip4"),
    ("name", "Near 77 SAMPLEWOOD LN", "ocr_address_raw"),
])
def test_a_prohibited_value_anywhere_is_caught(world, where, value, kind):
    leaked = [{**COMMERCIAL, "properties": {**COMMERCIAL["properties"], where: value}}]
    sqlite_path = _bake(world["tmp"] / "leak", [*world["live"], OCR, *leaked], world["edges"])
    hits = _scan(world, sqlite_path)["gate_a_prohibited_hits"]
    assert any(h["kind"] == kind and h["row"] == COMMERCIAL["id"] for h in hits), hits


def test_a_suspected_value_is_caught_on_its_own_flow_but_is_an_ordinary_word_elsewhere(world):
    live = [{**n, "properties": {**n["properties"], "name": "Exampleco.com gift"}}
            if n["id"] == "moneyflow-1400001-a4" else n for n in world["live"]]
    elsewhere = [{**COMMERCIAL, "properties": {**COMMERCIAL["properties"], "name": "Exampleco.com office"}}]
    sqlite_path = _bake(world["tmp"] / "own", [*live, OCR, *elsewhere], world["edges"])
    hits = _scan(world, sqlite_path)["gate_a_prohibited_hits"]
    assert {h["row"] for h in hits} == {"moneyflow-1400001-a4"}


def test_a_new_detector_finding_must_be_explained(world):
    noisy = [{**COMMERCIAL, "properties": {**COMMERCIAL["properties"], "name": "Hotline 415-555-0100"}}]
    sqlite_path = _bake(world["tmp"] / "noisy", [*world["live"], OCR, *noisy], world["edges"])
    report = _scan(world, sqlite_path)
    assert report["gate_b_unexplained"] >= 1 and not report["passed"]
    explain = [{**{k: f[k] for k in ("surface", "path", "row", "detector", "span")},
                "reason": "a public business hotline"} for f in report["gate_b_new_findings"]]
    explained = _scan(world, sqlite_path, explain)
    assert explained["gate_b_unexplained"] == 0 and explained["passed"]
    assert {f["reason"] for f in explained["gate_b_new_findings"]} == {"a public business hotline"}


def test_an_artifact_that_differs_from_the_ledger_fails_reconciliation(world):
    live = [{**n, "properties": {**n["properties"], "reported_employer": "Other Co"}}
            if n["id"] == "moneyflow-1400001-a1" else n for n in world["live"]]
    sqlite_path = _bake(world["tmp"] / "drift", [*live, OCR], world["edges"])
    problems = _scan(world, sqlite_path)["gate_c_reconciliation_problems"]
    assert any(p.startswith("moneyflow-1400001-a1:") for p in problems)


def test_the_cli_runs_the_synthetic_controls_and_every_one_is_caught(world, capsys):
    out = world["tmp"] / "scan.json"
    assert main(["--sqlite", str(world["candidate"]), "--baseline", str(world["baseline"]),
                 "--bundle", str(world["bundle"]), "--export", str(world["tmp"] / "candidate" / "export"),
                 "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert len(report["controls"]) == 17
    assert {c["gate"] for c in report["controls"]} == {"a", "b", "c"}
    assert {c.get("detector") for c in report["controls"] if c["gate"] == "b"} == {
        "phone", "email", "url", "street", "zip4", "fts_stream_changed"}
    assert all(c["caught"] for c in report["controls"]), report["controls"]
    assert not (world["tmp"] / "scan-controls.sqlite").exists()
    assert "PASS" in capsys.readouterr().out


def test_an_ocr_address_is_a_needle_only_for_its_street(tmp_path):
    from scan_public_substrate import ocr_needles
    rows = [{**OCR, "id": f"moneyflow-committee-example-{i}",
             "properties": {**OCR["properties"], "address_raw": address}}
            for i, address in enumerate(["77 SAMPLEWOOD LN, SAMPLETON CA 94999", "Sampleton, CA 94999",
                                         "PO BOX 5, SAMPLETON", "12B Example Court", "Sampleton, CA 94999-0077"])]
    _jsonl(tmp_path / "nodes.jsonl", rows)
    assert ocr_needles(tmp_path) == {"77 samplewood ln": "ocr_address_raw", "77 samplewood": "ocr_address_raw",
                                     "12b example court": "ocr_address_raw", "12b example": "ocr_address_raw",
                                     "po box 5": "ocr_address_raw", "94999-0077": "raw_zip4"}


def test_a_city_withheld_for_its_state_and_zip_tail_is_not_a_global_needle(tmp_path):
    from scan_public_substrate import ledger_expectations
    ledger = build_ledger("src", [("src/2026-04-14/2024.zip", write_export(tmp_path / "raw" / "2024.zip", {
        "A-Contributions": [contribution(F1, "a1", 10, **{**BASE, "Tran_City": "Sampleton, CA 94999",
                                                          "Tran_Emp": "Clerk, 12 Sample Lane, Sampleton"})],
        "Summary": [summary(F1, "A", "1", 10)]}))])
    build_transactions(ledger)
    write_ledger(ledger, tmp_path / "bundle" / "src")
    expectations = ledger_expectations(tmp_path / "bundle", frozenset(), "city_zip")
    assert expectations["global"] == {"clerk, 12 sample lane, sampleton": "withheld_street",
                                      "12 sample lane": "shaped_employer"}
    assert "sampleton, ca 94999" in expectations["per_flow"]["moneyflow-1400001-a1"]


def test_a_contact_shape_is_a_needle_whatever_outcome_won(tmp_path):
    """Conflicting reports withhold a field as conflicting_reports; the phone inside one is still a global needle."""
    from scan_public_substrate import ledger_expectations
    pre = filing(rpt="2020-02-21", start="2020-01-19", thru="2020-02-15")
    cumulative = filing(report_num="001", rpt="2022-01-26", start="2019-12-01", thru="2021-11-18")
    ledger = build_ledger("src", [
        ("src/a/2020.zip", write_export(tmp_path / "raw" / "2020.zip", {
            "A-Contributions": [contribution(pre, "U1", 75, **{**BASE, "Tran_Emp": "Example Co, 415-555-0101"})],
            "Summary": [summary(pre, "A", "1", 75)]})),
        ("src/a/2021.zip", write_export(tmp_path / "raw" / "2021.zip", {
            "A-Contributions": [contribution(cumulative, "U1", 75, **{**BASE, "Tran_Emp": "Example Co"})],
            "Summary": [summary(cumulative, "A", "1", 75)]}))])
    build_transactions(ledger)
    write_ledger(ledger, tmp_path / "bundle" / "src")
    expectations = ledger_expectations(tmp_path / "bundle", frozenset(), "city_zip")
    assert expectations["global"] == {"415-555-0101": "shaped_employer"}
    assert "example co, 415-555-0101" in expectations["per_flow"]["moneyflow-1400001-U1"]


def test_json_keys_and_numbers_are_surfaces_and_explanations_need_a_reason(world):
    from scan_public_substrate import text_surfaces
    with sqlite3.connect(world["candidate"]) as conn:
        conn.execute("UPDATE nodes SET props = json_set(props, '$.\"415-555-0100\"', 94999) "
                     "WHERE id = 'moneyflow-1400001-a1'")
        texts = {(path, text) for table, path, row, _, text in text_surfaces(conn) if row == "moneyflow-1400001-a1"}
    assert ("props.{key}", "415-555-0100") in texts and ("props.415-555-0100", "94999") in texts
    with pytest.raises(ValueError, match="reason"):
        _scan(world, explain=[{"surface": "meta", "path": "value", "row": "x", "detector": "phone", "span": "x",
                               "reason": " "}])


def test_a_changed_span_or_an_extra_occurrence_is_new(world):
    from scan_public_substrate import detector_findings
    with sqlite3.connect(world["candidate"]) as conn:
        before = detector_findings(conn)
        conn.execute("INSERT INTO meta(key, value) VALUES ('x', 'see https://one.example.org and https://two.example.org')")
        after = detector_findings(conn)
    added = after - before
    assert {k[4] for k in added} == {"https://one.example.org", "https://two.example.org"}


def test_an_ocr_street_without_commas_is_still_a_needle_by_its_start(tmp_path):
    from scan_public_substrate import ocr_needles
    _jsonl(tmp_path / "nodes.jsonl", [{**OCR, "properties": {**OCR["properties"],
                                                             "address_raw": "77 Sample Ridge Sampleton CA 94999"}}])
    assert "77 sample" in ocr_needles(tmp_path)


def test_a_baseline_value_is_exempt_only_while_its_text_is_unchanged(world):
    from scan_public_substrate import scan
    base_nodes = [*world["live"], OCR, {**COMMERCIAL, "properties": {**COMMERCIAL["properties"],
                                                                      "name": "Office at 77 SAMPLEWOOD LN"}}]
    doubled = [*world["live"], OCR, {**COMMERCIAL, "properties": {**COMMERCIAL["properties"],
                                                                   "name": "Office at 77 SAMPLEWOOD LN, 77 SAMPLEWOOD LN"}}]
    baseline = _bake(world["tmp"] / "b2", base_nodes, world["edges"])
    same = _bake(world["tmp"] / "c2", base_nodes, world["edges"])
    changed = _bake(world["tmp"] / "c3", doubled, world["edges"])
    export = world["tmp"] / "candidate" / "export"
    unchanged = scan(same, baseline, world["bundle"], export, [])
    assert unchanged["gate_a_prohibited_hits"] == [] and unchanged["gate_a_preexisting_public_text"]
    assert scan(changed, baseline, world["bundle"], export, [])["gate_a_prohibited_hits"]


def test_the_control_matrix_is_complete_without_any_real_contributor_flow(world, tmp_path):
    from scan_public_substrate import REQUIRED_CONTROLS, run_controls
    controls = run_controls(world["baseline"], world["baseline"], world["bundle"],
                            world["tmp"] / "candidate" / "export", tmp_path / "scratch.sqlite")
    assert len(controls) == REQUIRED_CONTROLS == 17
    assert all(c["caught"] for c in controls), [c for c in controls if not c["caught"]]
