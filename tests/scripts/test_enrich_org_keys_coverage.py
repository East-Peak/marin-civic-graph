"""Tests for scripts/enrich_org_keys.py — Unit 4: coverage report + CLI.

Lane 1, Unit 4 (Predeclared 7, 9 / COMPLETION 5). Coverage honesty: the report
publishes BMF rows parsed, EIN-deterministic matches, name candidates queued,
`bmf_row_conflict`, `identity_key_conflict`, and the existing-orgs keyless tail —
so the tail is PUBLISHED, never silently implied resolved — stamped with the
`policy_version` and the BMF source-limitation note.

The CLI runs parse → resolve → coverage and writes the review sidecar + report
under a review dir. It touches NO database — the enriched live export is the
operator step, never run here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from enrich_org_keys import (  # noqa: E402
    bmf_org_ref,
    build_coverage_report,
    main,
    parse_bmf_csv,
    resolve_registry_refs,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity_enrichment"
BMF_SLICE = FIXTURES / "eo_bmf_marin_slice.csv"


def test_coverage_report_publishes_all_honesty_fields():
    parse = parse_bmf_csv(BMF_SLICE)
    existing = [{"id": "org-existing-marin-builders", "display_label": "Marin Builders Association"}]
    resolve = resolve_registry_refs(parse["refs"], existing)
    report = build_coverage_report(parse, resolve, existing)

    assert report["policy_version"] == "v1"
    assert "IRS-recognized exempt orgs" in report["source_limitation"]
    # BMF honesty
    assert report["bmf"]["registry_orgs_keyed"] == 5
    assert report["bmf"]["rows_skipped_ein_not_9_digits"] == 1
    assert report["bmf"]["bmf_row_conflict"] == 1
    # resolution honesty — the no-EIN existing org is a queued name candidate
    assert report["resolution"]["ein_deterministic_matches"] == 0
    assert report["resolution"]["name_candidates_queued"] >= 1
    # the keyless tail is published, never implied resolved
    assert report["existing_orgs"]["total"] == 1
    assert report["existing_orgs"]["keyless_tail"] == 1
    # the field is always present (0 without live enrichment)
    assert report["enrichment"]["identity_key_conflict"] == 0


def test_coverage_counts_identity_key_conflict_from_enriched_refs():
    parse = parse_bmf_csv(BMF_SLICE)
    resolve = resolve_registry_refs(parse["refs"], [])
    enriched_refs = [
        {"id": "org-a", "ein": "941415040"},
        {"id": "org-b", "identity_key_conflict": [
            {"key": "ein", "reason": "identity_key_conflict", "values": ["1", "2"]}
        ]},
    ]
    report = build_coverage_report(parse, resolve, [], enriched_refs=enriched_refs)
    assert report["enrichment"]["identity_key_conflict"] == 1
    assert report["enrichment"]["orgs_with_surfaced_key"] == 1


def test_deterministic_match_counts_in_report():
    """A constructed keyed existing org → the EIN-deterministic match shows up
    and that org is NOT counted in the keyless tail."""
    registry = [bmf_org_ref({
        "EIN": "941415040", "NAME": "MARIN BUILDERS ASSOCIATION",
        "CITY": "SAN RAFAEL", "STATE": "CA", "SUBSECTION": "06",
    })]
    existing = [{"id": "org-existing-mb", "display_label": "Marin Builders Association", "ein": "941415040"}]
    parse = {"refs": registry, "skipped": [], "conflicts": []}
    resolve = resolve_registry_refs(registry, existing)
    report = build_coverage_report(parse, resolve, existing)
    assert report["resolution"]["ein_deterministic_matches"] == 1
    assert report["existing_orgs"]["keyless_tail"] == 0


def test_cli_writes_review_and_coverage_no_db(tmp_path):
    existing_path = tmp_path / "existing-orgs.json"
    existing_path.write_text(json.dumps([
        {"id": "org-existing-marin-builders", "display_label": "Marin Builders Association"},
    ]), encoding="utf-8")
    review_dir = tmp_path / "review"

    rc = main([
        "--bmf", str(BMF_SLICE),
        "--existing-orgs", str(existing_path),
        "--review-dir", str(review_dir),
    ])
    assert rc == 0

    coverage = json.loads((review_dir / "coverage-bmf.json").read_text())
    assert coverage["bmf"]["registry_orgs_keyed"] == 5
    assert coverage["existing_orgs"]["keyless_tail"] == 1

    candidates = [
        json.loads(line)
        for line in (review_dir / "resolution-candidates-bmf.jsonl").read_text().splitlines()
        if line.strip()
    ]
    # every review artifact carries signal_strength, never confidence
    assert candidates
    assert all("confidence" not in c for c in candidates)
    assert all("signal_strength" in c for c in candidates if "signals" in c)
