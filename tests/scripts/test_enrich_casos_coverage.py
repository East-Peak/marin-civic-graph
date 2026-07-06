"""Tests for scripts/enrich_casos_keys.py — Lane 2 Unit 6: coverage + CLI.

Coverage honesty (Predeclared 8): the report publishes Filings rows scanned,
the entity-number prefix-shape distribution + missing-number skips, candidate
pool size, name candidates queued, caps, `casos_row_conflict`,
`identity_key_conflict`, for-profit orgs still keyless, redaction counts,
`policy_version`, and the source-limitation note. The CLI streams the Filings
file and writes the review sidecar + coverage report with NO database access.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from enrich_casos_keys import (  # noqa: E402
    block_casos_against_existing,
    build_casos_coverage_report,
    main,
    scan_for_forbidden,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity_enrichment_casos"
FILINGS_SLICE = FIXTURES / "filings_slice.csv"

EXISTING = [
    {"id": "org-ghilotti-construction-company", "display_label": "Ghilotti Construction Company"},
    {"id": "org-ghilotti-construction", "display_label": "Ghilotti Construction"},
    {"id": "org-miller-pacific-engineering-group", "display_label": "Miller Pacific Engineering Group"},
    {"id": "org-unmatched-vendor", "display_label": "Totally Unmatched Vendor LLC"},
]


def test_block_returns_streaming_stats():
    result = block_casos_against_existing(FILINGS_SLICE.read_text().splitlines(), EXISTING)
    stats = result["stats"]
    assert stats["filings_rows_scanned"] >= 12
    assert stats["prefix_shapes"]["digits"] >= 1
    assert stats["prefix_shapes"]["b_prefixed"] == 1
    assert stats["skipped"]["entity_num_missing"] == 1


def test_coverage_report_publishes_all_honesty_fields():
    result = block_casos_against_existing(FILINGS_SLICE.read_text().splitlines(), EXISTING)
    report = build_casos_coverage_report(result, EXISTING)

    assert report["policy_version"] == "v1"
    assert "CA SOS" in report["source_limitation"]
    assert report["filings"]["rows_scanned"] >= 12
    assert report["filings"]["entity_num_missing"] == 1
    assert "b_prefixed" in report["filings"]["prefix_shapes"]
    assert report["resolution"]["name_candidates_queued"] >= 1
    assert report["resolution"]["candidate_pool_size"] >= 1
    # the keyless tail is published, never implied resolved
    assert report["existing_orgs"]["total"] == 4
    assert "org-unmatched-vendor" in report["existing_orgs"]["keyless_ids"]
    # the field is present (0 without live enrichment)
    assert report["enrichment"]["identity_key_conflict"] == 0
    # no live enrichment yet → no surfaced sos_id; redaction count is honest
    assert report["redaction"]["person_fields_published"] == 0


def test_coverage_counts_identity_key_conflict_from_enriched_refs():
    result = block_casos_against_existing(FILINGS_SLICE.read_text().splitlines(), EXISTING)
    enriched = [
        {"id": "org-a", "sos_id": "1819837"},
        {"id": "org-b", "identity_key_conflict": [{"key": "sos_id", "values": ["1", "2"]}]},
    ]
    report = build_casos_coverage_report(result, EXISTING, enriched_refs=enriched)
    assert report["enrichment"]["identity_key_conflict"] == 1
    assert report["enrichment"]["orgs_with_surfaced_sos_id"] == 1


def test_report_is_redaction_clean():
    result = block_casos_against_existing(FILINGS_SLICE.read_text().splitlines(), EXISTING)
    report = build_casos_coverage_report(result, EXISTING)
    assert scan_for_forbidden(report) == []


def test_cli_streams_and_writes_review_and_coverage_no_db(tmp_path):
    existing_path = tmp_path / "existing-orgs.json"
    existing_path.write_text(json.dumps(EXISTING), encoding="utf-8")
    review_dir = tmp_path / "review"

    rc = main([
        "--filings", str(FILINGS_SLICE),
        "--existing-orgs", str(existing_path),
        "--review-dir", str(review_dir),
    ])
    assert rc == 0

    coverage = json.loads((review_dir / "coverage-casos.json").read_text())
    assert coverage["filings"]["entity_num_missing"] == 1
    assert coverage["existing_orgs"]["total"] == 4

    candidates = [
        json.loads(line)
        for line in (review_dir / "resolution-candidates-casos.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert candidates
    assert all(c["status"] == "queued" for c in candidates)
    assert all("confidence" not in c for c in candidates)
    # the written sidecar + coverage carry no person/address/ZIP data
    assert scan_for_forbidden(candidates) == []
    assert scan_for_forbidden(coverage) == []
