#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = (
    ROOT / "data" / "extracted" / "san-rafael-city-side-campaign-filings" / "2026-04-11.json"
)
CANONICAL_SEEDS_PATH = ROOT / "data" / "normalized" / "canonical-seeds-san-rafael-01.json"
ELECTION_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-election-records-01" / "bundle-01.json"
)
OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-city-campaign-discovery-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

DISCOVERY_ARTIFACT_PATH = "data/extracted/san-rafael-city-side-campaign-filings/2026-04-11.json"

BUNDLE_ID = "san-rafael-city-campaign-discovery-01__bundle-01"
CASE_STUDY_ID = "san-rafael-city-campaign-discovery-01"

TOP_LEVEL_PAGE_RECORDS = [
    {
        "id": "record-san-rafael-disclosures-page",
        "record_class": "administrative_record",
        "record_type": "disclosure_index",
        "source_id": "san-rafael-disclosures",
        "artifact_path": "data/raw/san-rafael-disclosures/2026-04-11/source.html",
        "capture_status": "captured",
    },
    {
        "id": "record-san-rafael-elections-index-page",
        "record_class": "administrative_record",
        "record_type": "election_index",
        "source_id": "san-rafael-elections-index",
        "artifact_path": "data/raw/san-rafael-elections-index/2026-04-11/source.html",
        "capture_status": "captured",
    },
    {
        "id": "record-san-rafael-past-elections-page",
        "record_class": "administrative_record",
        "record_type": "election_index",
        "source_id": "san-rafael-past-elections",
        "artifact_path": "data/raw/san-rafael-past-elections/2026-04-11/source.html",
        "capture_status": "captured",
    },
]

ELECTION_SOURCE_TO_ID = {
    "san-rafael-november-8-2011-election": "election-2011-11-08-san-rafael-general",
    "san-rafael-november-5-2013-election": "election-2013-11-05-san-rafael-general",
    "san-rafael-november-3-2015-election": "election-2015-11-03-san-rafael-general",
    "san-rafael-june-7-2016-election": "election-2016-06-07-san-rafael-library-special",
    "san-rafael-november-7-2017-election": "election-2017-11-07-san-rafael-general",
    "san-rafael-november-6-2018-election": "election-2018-11-06-san-rafael-general",
    "san-rafael-november-3-2020-election": "election-2020-11-03-san-rafael-general",
    "san-rafael-november-8-2022-election": "election-2022-11-08-san-rafael-general",
    "san-rafael-november-5-2024-election": "election-2024-11-05-san-rafael-general",
}

CITY_OFFICE_SPECS = {
    "Mayoral Candidates": {
        "seat_id": "seat-san-rafael-mayor-at-large",
        "office_slug": "mayor",
    },
    "Councilmember District 1 Candidate": {
        "seat_id": "seat-san-rafael-city-council-district-1",
        "office_slug": "council-district-1",
    },
    "Councilmember District 2 Candidates:": {
        "seat_id": "seat-san-rafael-city-council-district-2",
        "office_slug": "council-district-2",
    },
    "Councilmember District 3 Candidates:": {
        "seat_id": "seat-san-rafael-city-council-district-3",
        "office_slug": "council-district-3",
    },
    "Councilmember District 4 Candidates": {
        "seat_id": "seat-san-rafael-city-council-district-4",
        "office_slug": "council-district-4",
    },
}

ACTOR_ID_OVERRIDES = {
    "Kate Colin": "actor-kate-colin",
    "Mahmoud Shirazi": "actor-mahmoud-shirazi",
    "Rachel Kertz": "actor-rachel-kertz",
    "Mark Galperin": "actor-mark-galperin",
    "Maika Llorens Gulati": "actor-maika-llorens-gulati",
    "Eli Hill": "actor-eli-hill",
    "Gerrod Herndon": "actor-gerrod-herndon",
    "Maribeth Bushey": "actor-maribeth-bushey",
    "Jonathan Frieman": "actor-jonathan-frieman",
    "John Gamblin": "actor-john-gamblin",
    "Greg Knell": "actor-greg-knell",
}

PAGE_RECORD_TYPE_OVERRIDES = {
    "san-rafael-november-5-2024-election": "election_results_page",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def page_record_id(source_id: str) -> str:
    return f"record-{source_id}-page"


def folder_record_id(source_id: str, label: str, suffix: str) -> str:
    return f"record-{source_id}-{slugify(label)}-{suffix}"


def candidate_folder_record_id(source_id: str, candidate_name: str) -> str:
    return f"record-{source_id}-{slugify(candidate_name)}-campaign-folder"


def unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def build_election_page_record(page: dict[str, Any]) -> dict[str, Any]:
    source_id = page["source_id"]
    record_type = PAGE_RECORD_TYPE_OVERRIDES.get(source_id, "election_page")
    artifact_path = f"data/raw/{source_id}/2026-04-11/source.html"
    record = {
        "id": page_record_id(source_id),
        "record_class": "administrative_record",
        "record_type": record_type,
        "source_id": source_id,
        "artifact_path": artifact_path,
        "capture_status": "captured",
        "title": page["election_label"],
        "entry_url": page["entry_url"],
    }
    election_id = ELECTION_SOURCE_TO_ID.get(source_id)
    if election_id is not None:
        record["election_ids"] = [election_id]
    return record


def build_folder_record(
    *,
    record_id: str,
    source_id: str,
    record_type: str,
    label: str,
    url_field: str,
    url_value: str,
    entry_id: int | None,
    linked_source_ids: list[str],
    election_ids: list[str],
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": record_id,
        "record_class": "financial_record",
        "record_type": record_type,
        "source_id": source_id,
        "artifact_path": DISCOVERY_ARTIFACT_PATH,
        "capture_status": "discovery_only",
        "label": label,
        url_field: url_value,
        "linked_from_source_ids": linked_source_ids,
        "election_ids": election_ids,
    }
    if entry_id is not None:
        record["entry_id"] = entry_id
    if extra_fields:
        record.update(extra_fields)
    return record


def main() -> None:
    extracted = read_json(INPUT_PATH)
    canonical = read_json(CANONICAL_SEEDS_PATH)
    election_bundle = read_json(ELECTION_BUNDLE_PATH)

    canonical_actor_ids = {actor["id"] for actor in canonical["actor_candidates"]}
    canonical_seat_ids = {seat["id"] for seat in canonical["seat_candidates"]}
    election_ids = {item["id"] for item in election_bundle["election_candidates"]}

    campaign_pages = [
        page
        for page in extracted["election_page_inventory"]
        if page["campaign_signal_kind"] != "none"
    ]

    record_refs: list[dict[str, Any]] = list(TOP_LEVEL_PAGE_RECORDS)
    record_refs.extend(build_election_page_record(page) for page in campaign_pages)

    top_level_destinations = extracted["top_level_destinations"]
    for destination in top_level_destinations:
        record_refs.append(
            build_folder_record(
                record_id=f"record-{destination['source_id']}",
                source_id=destination["source_id"],
                record_type="campaign_filing_folder",
                label=destination["label"],
                url_field="folder_url",
                url_value=destination["folder_url"],
                entry_id=destination["folder_entry_id"],
                linked_source_ids=["san-rafael-disclosures"],
                election_ids=[],
            )
        )

    for folder in extracted["election_level_campaign_filing_folders"]:
        election_id = ELECTION_SOURCE_TO_ID[folder["source_id"]]
        record_refs.append(
            build_folder_record(
                record_id=folder_record_id(folder["source_id"], folder["label"], "folder"),
                source_id="san-rafael-city-side-campaign-filings",
                record_type="campaign_filing_folder",
                label=folder["label"],
                url_field="folder_url",
                url_value=folder["folder_url"],
                entry_id=folder["folder_entry_id"],
                linked_source_ids=[folder["source_id"]],
                election_ids=[election_id],
                extra_fields={"election_label": folder["election_label"]},
            )
        )

    ordinance_resources = extracted["independent_expenditure_resources"]
    ordinance_by_entry: dict[int, dict[str, Any]] = {}
    for resource in ordinance_resources:
        entry_id = resource["record_entry_id"]
        bucket = ordinance_by_entry.setdefault(
            entry_id,
            {
                "linked_from_source_ids": [],
                "election_ids": [],
                "election_labels": [],
                "record_url": resource["record_url"],
                "label": resource["label"],
                "entry_id": entry_id,
            },
        )
        bucket["linked_from_source_ids"].append(resource["source_id"])
        bucket["election_ids"].append(ELECTION_SOURCE_TO_ID[resource["source_id"]])
        bucket["election_labels"].append(resource["election_label"])

    for entry_id, resource in ordinance_by_entry.items():
        record_refs.append(
            {
                "id": f"record-san-rafael-independent-expenditure-ordinance-{entry_id}",
                "entry_id": entry_id,
                "record_class": "legislative_record",
                "record_type": "ordinance",
                "source_id": "san-rafael-city-side-campaign-filings",
                "artifact_path": DISCOVERY_ARTIFACT_PATH,
                "capture_status": "discovered_direct_record",
                "title": resource["label"],
                "doc_url": resource["record_url"],
                "linked_from_source_ids": unique_preserve_order(resource["linked_from_source_ids"]),
                "election_ids": unique_preserve_order(resource["election_ids"]),
                "election_labels": unique_preserve_order(resource["election_labels"]),
            }
        )

    for folder in extracted["independent_expenditure_filing_folders"]:
        election_id = ELECTION_SOURCE_TO_ID[folder["source_id"]]
        record_refs.append(
            build_folder_record(
                record_id=folder_record_id(
                    folder["source_id"], "independent-expenditure-filings", "folder"
                ),
                source_id="san-rafael-city-side-campaign-filings",
                record_type="independent_expenditure_filing_folder",
                label=folder["label"],
                url_field="folder_url",
                url_value=folder["folder_url"],
                entry_id=folder["folder_entry_id"],
                linked_source_ids=[folder["source_id"]],
                election_ids=[election_id],
                extra_fields={"election_label": folder["election_label"]},
            )
        )

    actor_evidence: dict[str, list[str]] = defaultdict(list)
    actor_names: dict[str, str] = {}
    candidacy_candidates: list[dict[str, Any]] = []

    for folder in extracted["candidate_folder_inventory"]:
        election_id = ELECTION_SOURCE_TO_ID[folder["source_id"]]
        folder_record_id_value = candidate_folder_record_id(
            folder["source_id"], folder["candidate_name"]
        )
        city_office_spec = CITY_OFFICE_SPECS.get(folder["office_label"])

        extra_fields = {
            "election_label": folder["election_label"],
            "section_label": folder["section_label"],
            "office_label": folder["office_label"],
            "candidate_name": folder["candidate_name"],
        }

        if city_office_spec is not None:
            actor_id = ACTOR_ID_OVERRIDES[folder["candidate_name"]]
            extra_fields["candidate_actor_ids"] = [actor_id]
            extra_fields["seat_ids"] = [city_office_spec["seat_id"]]
            actor_evidence[actor_id].extend(
                [page_record_id(folder["source_id"]), folder_record_id_value]
            )
            actor_names[actor_id] = folder["candidate_name"]

        record_refs.append(
            build_folder_record(
                record_id=folder_record_id_value,
                source_id="san-rafael-city-side-campaign-filings",
                record_type="campaign_filing_folder",
                label=f"{folder['candidate_name']} campaign filings folder",
                url_field="folder_url",
                url_value=folder["folder_url"],
                entry_id=folder["folder_entry_id"],
                linked_source_ids=[folder["source_id"]],
                election_ids=[election_id],
                extra_fields=extra_fields,
            )
        )

        if city_office_spec is None:
            continue

        candidacy_year = election_id.split("-")[1]
        candidacy_candidates.append(
            {
                "id": (
                    f"candidacy-{slugify(folder['candidate_name'])}-"
                    f"san-rafael-{city_office_spec['office_slug']}-{candidacy_year}"
                ),
                "candidate_actor_id": actor_id,
                "seat_id": city_office_spec["seat_id"],
                "election_id": election_id,
                "result_status": "unknown",
                "evidence_record_ids": [
                    page_record_id(folder["source_id"]),
                    folder_record_id_value,
                ],
                "notes": (
                    "Promoted conservatively from a page-linked public-records folder "
                    "destination. This is a discovery-stage candidacy candidate, not yet "
                    "a filing-backed committee or result record."
                ),
            }
        )

    actor_candidates: list[dict[str, Any]] = []
    for actor_id, name in sorted(actor_names.items(), key=lambda item: item[1]):
        actor_candidate = {
            "id": actor_id,
            "name": name,
            "actor_type": "person",
            "evidence_record_ids": unique_preserve_order(actor_evidence[actor_id]),
        }
        if actor_id in canonical_actor_ids:
            actor_candidate["resolution_status"] = "reused_canonical_actor"
        else:
            actor_candidate["resolution_status"] = "discovery_candidate"
        actor_candidates.append(actor_candidate)

    election_refs = []
    for source_id, election_id in ELECTION_SOURCE_TO_ID.items():
        if source_id not in {page["source_id"] for page in campaign_pages}:
            continue
        if election_id not in election_ids:
            raise RuntimeError(f"Missing election dependency {election_id}")
        election_refs.append(
            {
                "id": election_id,
                "source_bundle_id": "san-rafael-election-records-01__bundle-01",
                "evidence_record_id": page_record_id(source_id),
            }
        )

    seat_refs = []
    used_seat_ids = unique_preserve_order(
        [candidate["seat_id"] for candidate in candidacy_candidates]
    )
    for seat_id in used_seat_ids:
        if seat_id not in canonical_seat_ids:
            raise RuntimeError(f"Missing seat dependency {seat_id}")
        seat_refs.append(
            {
                "id": seat_id,
                "source_bundle_id": "canonical-seeds-san-rafael-01",
            }
        )

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "San Rafael city-side campaign discovery spine built from the disclosures page and election landing pages",
            "campaign-bearing election pages, top-level public-records destinations, and page-linked filing-folder destinations",
            "city-office actor and candidacy candidates for the 2020, 2022, and 2024 mayoral and council races only",
            "conservative discovery-stage promotion that stops before Committee or Filing objects where direct filing contents are not yet captured",
        ],
        "record_refs": sorted(record_refs, key=lambda item: item["id"]),
        "election_refs": election_refs,
        "seat_refs": seat_refs,
        "actor_candidates": actor_candidates,
        "candidacy_candidates": sorted(candidacy_candidates, key=lambda item: item["id"]),
        "open_questions": [
            {
                "id": "OQ-020",
                "status": "watch",
                "question": "Can the top-level or child Laserfiche filing folders ever be enumerated anonymously, or should this bundle stay permanently page-linked?",
            },
            {
                "id": "OQ-021",
                "status": "watch",
                "question": "Should the malformed 2018 filing-folder URL be preserved verbatim or canonicalized to the correct Laserfiche repo parameter?",
            },
            {
                "id": "OQ-024",
                "status": "watch",
                "question": "When should school-board, city-attorney, and clerk-assessor campaign rows graduate from discovery-only folder records into their own canonical seat and candidacy layers?",
            },
        ],
        "notes": [
            "This bundle intentionally reuses page-level election IDs from the San Rafael election-record bundle and seat IDs from the canonical San Rafael identity bundle.",
            "The 27 candidate-folder destinations stay visible in the graph as record refs, but only the 15 city-office rows are promoted into actor and candidacy candidates in this slice.",
            "The independent-expenditure ordinance remains a discovered direct-record link, not a captured legislative record, until its own DocView artifact family is fetched.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
