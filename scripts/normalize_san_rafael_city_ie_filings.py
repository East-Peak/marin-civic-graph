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
OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-city-campaign-ie-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

BUNDLE_ID = "san-rafael-city-campaign-ie-01__bundle-01"
CASE_STUDY_ID = "san-rafael-city-campaign-ie-01"
RAW_ARTIFACT_PATH = "data/raw/san-rafael-city-campaign-folder-listings/2026-04-12/folder-listings.json"
TITLE_PATTERN = re.compile(
    r"Form\s+496\s*-?\s*(?P<committee>.+?)\s+(?P<stance>Supporting|Opposing)\s+(?P<target>.+?)\s*\((?P<date>[^)]+)\)",
    re.IGNORECASE,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m-%d-%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    return None


def build_doc_url(entry_id: int) -> str:
    return (
        "https://publicrecords.cityofsanrafael.org/WebLink/DocView.aspx"
        f"?id={entry_id}&dbid=0&repo=CityofSanRafael"
    )


def main() -> None:
    raw_capture = json.loads(RAW_CAPTURE_PATH.read_text())
    discovery_bundle = json.loads(DISCOVERY_BUNDLE_PATH.read_text())

    actor_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for record in discovery_bundle["record_refs"]:
        if (
            record.get("record_type") == "campaign_filing_folder"
            and record.get("candidate_name")
            and record.get("candidate_actor_ids")
            and record.get("election_ids")
            and record.get("seat_ids")
        ):
            actor_lookup[(record["candidate_name"], record["election_ids"][0])] = {
                "candidate_actor_id": record["candidate_actor_ids"][0],
                "seat_id": record["seat_ids"][0],
            }

    committee_candidates_by_id: dict[str, dict[str, Any]] = {}
    filing_candidates: list[dict[str, Any]] = []
    record_refs: list[dict[str, Any]] = []

    for folder_capture in raw_capture["folder_captures"]:
        folder_record = folder_capture["folder_record"]
        if folder_record.get("record_type") != "independent_expenditure_filing_folder":
            continue
        response_data = folder_capture["response"]["data"]
        if response_data.get("failed"):
            continue

        election_id = folder_record["election_ids"][0]
        folder_record_id = folder_record["id"]
        for row in response_data.get("results") or []:
            title = row["name"]
            match = TITLE_PATTERN.search(title)
            if not match:
                continue

            committee_name = match.group("committee").strip()
            target_name = match.group("target").strip()
            target_ref = actor_lookup.get((target_name, election_id))
            if target_ref is None:
                continue

            committee_id = f"committee-{slugify(committee_name)}-{election_id.replace('election-', '')}-ie"
            committee_actor_id = f"actor-{slugify(committee_name)}"
            entry_id = row["entryId"]
            row_data = row.get("data") or []
            page_count = row_data[1] if len(row_data) > 1 else None
            template_name = row_data[2] if len(row_data) > 2 else None
            posted_at = parse_date(row_data[10] if len(row_data) > 10 else None)

            committee_candidates_by_id.setdefault(
                committee_id,
                {
                    "id": committee_id,
                    "name": committee_name,
                    "committee_type": "outside_spending_committee",
                    "actor_candidate_id": committee_actor_id,
                    "jurisdiction_place_id": "place-san-rafael",
                    "primary_election_id": election_id,
                    "source_system_ref": f"laserfiche-folder:{folder_record['entry_id']}",
                    "evidence_record_ids": [folder_record_id],
                },
            )

            record_id = f"record-san-rafael-ie-filing-entry-{entry_id}"
            filing_id = f"filing-san-rafael-ie-entry-{entry_id}"
            record_refs.append(
                {
                    "id": record_id,
                    "entry_id": entry_id,
                    "record_class": "financial_record",
                    "record_type": "form_496",
                    "source_id": "san-rafael-city-campaign-folder-listings",
                    "artifact_path": RAW_ARTIFACT_PATH,
                    "capture_status": "captured_from_folder_listing",
                    "title": title,
                    "doc_url": build_doc_url(entry_id),
                    "page_count": page_count,
                    "template_name": template_name,
                    "folder_record_id": folder_record_id,
                    "committee_ids": [committee_id],
                    "target_actor_ids": [target_ref["candidate_actor_id"]],
                    "election_ids": [election_id],
                    "seat_ids": [target_ref["seat_id"]],
                }
            )
            stance = match.group("stance").strip().lower()
            if stance == "supporting":
                stance = "support"
            elif stance == "opposing":
                stance = "oppose"

            filing_candidates.append(
                {
                    "id": filing_id,
                    "filing_type": "form_496",
                    "committee_id": committee_id,
                    "committee_actor_id": committee_actor_id,
                    "election_id": election_id,
                    "target_actor_id": target_ref["candidate_actor_id"],
                    "target_seat_id": target_ref["seat_id"],
                    "stance": stance,
                    "posted_at": posted_at,
                    "status": "captured_from_public_folder_listing",
                    "record_id": record_id,
                    "title": title,
                    "evidence_record_ids": [folder_record_id, record_id],
                }
            )

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "San Rafael page-linked independent expenditure filing folders with successful public folder-listing capture",
            "outside-spending committee promotion from explicit Form 496 filing titles",
            "target-candidate and target-seat joins where the IE title matches an existing San Rafael city-office candidacy",
        ],
        "record_refs": sorted(record_refs, key=lambda item: item["entry_id"]),
        "committee_candidates": sorted(committee_candidates_by_id.values(), key=lambda item: item["id"]),
        "filing_candidates": sorted(filing_candidates, key=lambda item: item["id"]),
        "notes": [
            "This bundle is title-level independent-expenditure normalization, not schedule-level amount extraction.",
            "The current public filing layer supports committee-target overlap and filing chronology, but not yet raw artifact recovery or contribution/expenditure amount parsing.",
            "Only city-office targets with known candidate and seat joins are promoted here.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
