#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

CAMPAIGN_FILING_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-filings-01" / "bundle-01.json"
)
CAMPAIGN_IE_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-ie-01" / "bundle-01.json"
)
CAMPAIGN_FORM460_SCHEDULE_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-form460-schedules-01" / "bundle-01.json"
)

CAMPAIGN_DISCOVERY_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-discovery-01" / "bundle-01.json"
)
CAMPAIGN_FORM460_OCR_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-form460-ocr-01" / "bundle-01.json"
)
CAMPAIGN_FORM460_PDF_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-form460-pdf-01" / "bundle-01.json"
)

OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-city-campaign-records-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

CASE_STUDY_ID = "san-rafael-city-campaign-records-01"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def collect_record_ids(value: Any, sink: set[str]) -> None:
    if isinstance(value, str):
        if value.startswith("record-"):
            sink.add(value)
        return
    if isinstance(value, list):
        for item in value:
            collect_record_ids(item, sink)
        return
    if isinstance(value, dict):
        for item in value.values():
            collect_record_ids(item, sink)


def main() -> None:
    campaign_filings_bundle = load_json(CAMPAIGN_FILING_BUNDLE_PATH)
    campaign_ie_bundle = load_json(CAMPAIGN_IE_BUNDLE_PATH)
    form460_schedule_bundle = load_json(CAMPAIGN_FORM460_SCHEDULE_BUNDLE_PATH)

    discovery_bundle = load_json(CAMPAIGN_DISCOVERY_BUNDLE_PATH)
    ocr_bundle = load_json(CAMPAIGN_FORM460_OCR_BUNDLE_PATH)
    pdf_bundle = load_json(CAMPAIGN_FORM460_PDF_BUNDLE_PATH)

    existing_record_ids: set[str] = set()
    referenced_record_ids: set[str] = set()

    already_imported_bundles = [
        campaign_filings_bundle,
        campaign_ie_bundle,
        form460_schedule_bundle,
    ]
    for bundle in already_imported_bundles:
        for record_ref in bundle.get("record_refs", []):
            existing_record_ids.add(record_ref["id"])
        collect_record_ids(bundle, referenced_record_ids)

    target_record_ids = referenced_record_ids - existing_record_ids

    source_record_lookup: dict[str, dict[str, Any]] = {}
    source_bundle_name_by_id: dict[str, str] = {}
    for source_name, bundle in [
        ("san-rafael-city-campaign-discovery-01", discovery_bundle),
        ("san-rafael-city-campaign-form460-ocr-01", ocr_bundle),
        ("san-rafael-city-campaign-form460-pdf-01", pdf_bundle),
    ]:
        for record_ref in bundle.get("record_refs", []):
            source_record_lookup[record_ref["id"]] = record_ref
            source_bundle_name_by_id[record_ref["id"]] = source_name

    promoted_record_refs: list[dict[str, Any]] = []
    source_bundle_counts: dict[str, int] = {}
    missing_record_ids: list[str] = []
    for record_id in sorted(target_record_ids):
        record_ref = source_record_lookup.get(record_id)
        if record_ref is None:
            missing_record_ids.append(record_id)
            continue
        promoted_record_refs.append(record_ref)
        source_bundle_name = source_bundle_name_by_id[record_id]
        source_bundle_counts[source_bundle_name] = source_bundle_counts.get(source_bundle_name, 0) + 1

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "San Rafael city-side campaign folder records referenced from committee, filing, or candidacy objects already included in graph-v1",
            "San Rafael city-side Form 460 OCR capture records referenced from filing, money-flow, or validation objects already included in graph-v1",
            "San Rafael city-side Form 460 PDF export records referenced from filing, money-flow, or validation objects already included in graph-v1",
            "Evidence-completeness promotion only; this bundle adds durable Record nodes without importing discovery-stage actor, candidacy, or committee candidates",
        ],
        "record_refs": promoted_record_refs,
        "methodology_findings": [
            {
                "id": "method-campaign-records-v1-derived-from-live-references",
                "summary": "This bundle is derived from record IDs already referenced by the current San Rafael city-side campaign filing, IE, and Form 460 schedule bundles. It only promotes missing evidence records that are already part of the live graph-v1 citation chain."
            },
            {
                "id": "method-campaign-records-v1-source-breakdown",
                "summary": "Promoted record coverage by source bundle: "
                + ", ".join(f"{name}={count}" for name, count in sorted(source_bundle_counts.items()))
                if source_bundle_counts
                else "No source records were promoted."
            },
        ],
        "open_questions": [
            {
                "id": "OQ-028",
                "status": "watch" if missing_record_ids else "resolved",
                "summary": "Graph-v1 campaign evidence record completeness depends on promoting durable OCR/PDF/folder Record nodes for already-referenced campaign artifacts.",
                "missing_record_ids": missing_record_ids,
            }
        ],
        "notes": [
            "This bundle does not promote discovery-stage actors, committees, or candidacies from the city-side campaign discovery layer.",
            "The objective is evidence completeness for graph-v1, not broader campaign ontology expansion.",
            "If additional missing record IDs appear later, they should be treated as a separate evidence-bundle follow-up rather than folded back into the importer.",
        ],
    }

    write_json(OUTPUT_PATH, payload)


if __name__ == "__main__":
    main()
