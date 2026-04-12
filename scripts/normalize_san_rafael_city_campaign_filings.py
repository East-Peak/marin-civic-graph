#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RAW_CAPTURE_PATH = (
    ROOT / "data" / "raw" / "san-rafael-city-campaign-folder-listings" / "2026-04-12" / "folder-listings.json"
)
DISCOVERY_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-discovery-01" / "bundle-01.json"
)
OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-city-campaign-filings-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

BUNDLE_ID = "san-rafael-city-campaign-filings-01__bundle-01"
CASE_STUDY_ID = "san-rafael-city-campaign-filings-01"
RAW_ARTIFACT_PATH = "data/raw/san-rafael-city-campaign-folder-listings/2026-04-12/folder-listings.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_filing_type(title: str) -> str:
    match = re.search(r"\bForm\s+(\d+[A-Z]?)\b", title, re.I)
    if match:
        return f"form_{match.group(1).lower()}"
    return "campaign_filing_document"


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p")
        return dt.date().isoformat()
    except ValueError:
        return None


def build_doc_url(entry_id: int) -> str:
    return (
        "https://publicrecords.cityofsanrafael.org/WebLink/DocView.aspx"
        f"?id={entry_id}&dbid=0&repo=CityofSanRafael"
    )


def main() -> None:
    raw_capture = json.loads(RAW_CAPTURE_PATH.read_text())
    discovery_bundle = json.loads(DISCOVERY_BUNDLE_PATH.read_text())

    discovery_candidacy_by_folder: dict[str, dict[str, Any]] = {}
    for candidacy in discovery_bundle["candidacy_candidates"]:
        for record_id in candidacy["evidence_record_ids"]:
            if record_id.startswith("record-san-rafael-") and record_id.endswith("-campaign-folder"):
                discovery_candidacy_by_folder[record_id] = candidacy

    committee_candidates: list[dict[str, Any]] = []
    filing_candidates: list[dict[str, Any]] = []
    record_refs: list[dict[str, Any]] = []
    candidacy_candidates: list[dict[str, Any]] = []

    for folder_capture in raw_capture["folder_captures"]:
        folder_record = folder_capture["folder_record"]
        response_data = folder_capture["response"]["data"]
        if response_data.get("failed"):
            continue
        if not folder_record.get("candidate_actor_ids"):
            continue

        folder_record_id = folder_record["id"]
        folder_name = response_data.get("name") or folder_record["label"]
        candidate_actor_id = folder_record["candidate_actor_ids"][0]
        election_id = folder_record["election_ids"][0]
        committee_id = f"committee-{slugify(folder_name)}"

        committee_candidates.append(
            {
                "id": committee_id,
                "name": folder_name,
                "committee_type": "candidate_linked_committee",
                "jurisdiction_place_id": "place-san-rafael",
                "controlling_actor_id": candidate_actor_id,
                "primary_election_id": election_id,
                "source_system_ref": f"laserfiche-folder:{folder_record['entry_id']}",
                "evidence_record_ids": [folder_record_id],
            }
        )

        discovery_candidacy = discovery_candidacy_by_folder.get(folder_record_id)
        if discovery_candidacy is not None:
            candidacy_enrichment = dict(discovery_candidacy)
            candidacy_enrichment["committee_id"] = committee_id
            if folder_record_id not in candidacy_enrichment["evidence_record_ids"]:
                candidacy_enrichment["evidence_record_ids"].append(folder_record_id)
            candidacy_enrichment["notes"] = (
                "Enriched from the public Laserfiche folder listing. The committee boundary "
                "is now explicit, but filing contents still depend on the folder-listing path "
                "rather than direct filing-document capture."
            )
            candidacy_candidates.append(candidacy_enrichment)

        for row in response_data.get("results") or []:
            entry_id = row["entryId"]
            title = row["name"]
            filing_type = parse_filing_type(title)
            record_id = f"record-san-rafael-campaign-filing-entry-{entry_id}"
            filing_id = f"filing-san-rafael-campaign-entry-{entry_id}"
            row_data = row.get("data") or []
            page_count = row_data[1] if len(row_data) > 1 else None
            template_name = row_data[2] if len(row_data) > 2 else None
            posted_at = parse_date(row_data[10] if len(row_data) > 10 else None)

            record_refs.append(
                {
                    "id": record_id,
                    "entry_id": entry_id,
                    "record_class": "financial_record",
                    "record_type": filing_type,
                    "source_id": "san-rafael-city-campaign-folder-listings",
                    "artifact_path": RAW_ARTIFACT_PATH,
                    "capture_status": "captured_from_folder_listing",
                    "title": title,
                    "doc_url": build_doc_url(entry_id),
                    "page_count": page_count,
                    "template_name": template_name,
                    "folder_record_id": folder_record_id,
                    "candidate_actor_ids": [candidate_actor_id],
                    "committee_ids": [committee_id],
                    "election_ids": [election_id],
                    "seat_ids": folder_record.get("seat_ids", []),
                }
            )

            filing_candidate = {
                "id": filing_id,
                "filing_type": filing_type,
                "committee_id": committee_id,
                "filer_actor_id": candidate_actor_id,
                "election_id": election_id,
                "posted_at": posted_at,
                "status": "captured_from_public_folder_listing",
                "record_id": record_id,
                "title": title,
                "evidence_record_ids": [folder_record_id, record_id],
            }
            if "amendment" in title.lower():
                filing_candidate["is_amendment"] = True
            filing_candidates.append(filing_candidate)

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "San Rafael city-office campaign folders with successful public Laserfiche folder-listing capture",
            "committee promotion from explicit candidate folder titles",
            "filing promotion from public folder-listing document rows with direct entry ids and DocView paths",
            "conservative candidacy enrichment that adds committee joins without pretending the full filing documents are already captured",
        ],
        "record_refs": sorted(record_refs, key=lambda item: item["entry_id"]),
        "committee_candidates": sorted(committee_candidates, key=lambda item: item["id"]),
        "filing_candidates": sorted(filing_candidates, key=lambda item: item["id"]),
        "candidacy_candidates": sorted(candidacy_candidates, key=lambda item: item["id"]),
        "open_questions": [
            {
                "id": "OQ-025",
                "status": "watch",
                "question": "What is the repeatable public path from city-side campaign filing entry ids to raw filing artifacts such as PDF, OCR text, or stable document metadata beyond the folder listing itself?",
            }
        ],
        "notes": [
            "This bundle promotes only city-office candidate folders where both the candidate and the seat boundary are already known from the discovery layer.",
            "School-board, city-attorney, clerk-assessor, election-level folder, and independent-expenditure folder rows remain outside this filing bundle until their office or committee boundaries are clearer.",
            "The filing records currently rest on public folder-listing evidence plus derived DocView paths; direct filing-document capture is a separate next step.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
