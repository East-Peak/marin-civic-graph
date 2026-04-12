#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
EXTRACTED_PATH = (
    ROOT / "data" / "extracted" / "san-rafael-election-direct-records" / "2026-04-11.json"
)
OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-election-records-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"
RAW_ARTIFACT_PATH = "data/raw/san-rafael-election-direct-records/2026-04-11/records.json"

BUNDLE_ID = "san-rafael-election-records-01__bundle-01"
CASE_STUDY_ID = "san-rafael-election-records-01"
SOURCE_ID = "san-rafael-election-direct-records"

ELECTION_SPECS = {
    "san-rafael-june-8-2010-election": {
        "id": "election-2010-06-08-san-rafael-library-special",
        "title": "June 8, 2010 San Rafael library special election",
        "election_type": "special_municipal",
        "election_date": "2010-06-08",
        "status": "certified",
        "notes": "Page-level election object for the 2010 library parcel-tax special election.",
    },
    "san-rafael-november-2-2010-election": {
        "id": "election-2010-11-02-san-rafael-paramedic-special",
        "title": "November 2, 2010 San Rafael paramedic special election",
        "election_type": "special_municipal",
        "election_date": "2010-11-02",
        "status": "certified",
        "notes": "Page-level election object for the 2010 paramedic special election.",
    },
    "san-rafael-november-8-2011-election": {
        "id": "election-2011-11-08-san-rafael-general",
        "title": "November 8, 2011 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2011-11-08",
        "status": "certified",
    },
    "san-rafael-november-5-2013-election": {
        "id": "election-2013-11-05-san-rafael-general",
        "title": "November 5, 2013 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2013-11-05",
        "status": "certified",
    },
    "san-rafael-november-3-2015-election": {
        "id": "election-2015-11-03-san-rafael-general",
        "title": "November 3, 2015 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2015-11-03",
        "status": "cancelled_without_ballot",
        "notes": "The election was called, then cancelled after unopposed appointments were approved.",
    },
    "san-rafael-june-7-2016-election": {
        "id": "election-2016-06-07-san-rafael-library-special",
        "title": "June 7, 2016 San Rafael library special election",
        "election_type": "special_municipal",
        "election_date": "2016-06-07",
        "status": "certified",
    },
    "san-rafael-november-7-2017-election": {
        "id": "election-2017-11-07-san-rafael-general",
        "title": "November 7, 2017 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2017-11-07",
        "status": "cancelled",
    },
    "san-rafael-june-5-2018-special-municipal-election": {
        "id": "election-2018-06-05-san-rafael-measure-g-special",
        "title": "June 5, 2018 San Rafael Measure G special election",
        "election_type": "special_municipal",
        "election_date": "2018-06-05",
        "status": "certified",
    },
    "san-rafael-november-6-2018-election": {
        "id": "election-2018-11-06-san-rafael-general",
        "title": "November 6, 2018 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2018-11-06",
        "status": "certified",
    },
    "san-rafael-november-3-2020-election": {
        "id": "election-2020-11-03-san-rafael-general",
        "title": "November 3, 2020 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2020-11-03",
        "status": "certified",
    },
    "san-rafael-november-8-2022-election": {
        "id": "election-2022-11-08-san-rafael-general",
        "title": "November 8, 2022 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2022-11-08",
        "status": "certified",
    },
    "san-rafael-november-5-2024-election": {
        "id": "election-2024-11-05-san-rafael-general",
        "title": "November 5, 2024 San Rafael general municipal election",
        "election_type": "general_municipal",
        "election_date": "2024-11-05",
        "status": "certified",
        "related_canonical_election_ids": [
            "election-2024-11-05-san-rafael-mayor-general",
            "election-2024-11-05-san-rafael-council-district-1-general",
            "election-2024-11-05-san-rafael-council-district-4-general",
        ],
        "notes": "This is a page-level umbrella election object for direct record joins. Seat-specific 2024 elections already exist in the canonical seed bundle.",
    },
    "san-rafael-june-2-2026-special-municipal-election": {
        "id": "election-2026-06-02-san-rafael-library-special",
        "title": "June 2, 2026 San Rafael library special election",
        "election_type": "special_municipal",
        "election_date": "2026-06-02",
        "status": "scheduled",
    },
}

DECISION_SPECS = [
    {
        "id": "decision-2010-06-08-san-rafael-library-special-call",
        "decision_type": "call_special_election",
        "title": "Call the June 8, 2010 special election for the library parcel-tax measure",
        "status": "adopted",
        "election_id": "election-2010-06-08-san-rafael-library-special",
        "record_entry_ids": [15680],
    },
    {
        "id": "decision-2010-06-08-san-rafael-library-special-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the June 8, 2010 special election",
        "status": "certified",
        "election_id": "election-2010-06-08-san-rafael-library-special",
        "record_entry_ids": [15684],
    },
    {
        "id": "decision-2010-11-02-san-rafael-paramedic-special-call",
        "decision_type": "call_special_election",
        "title": "Call the November 2, 2010 special election for the paramedic tax measure",
        "status": "adopted",
        "election_id": "election-2010-11-02-san-rafael-paramedic-special",
        "record_entry_ids": [7341, 15687],
    },
    {
        "id": "decision-2010-11-02-san-rafael-paramedic-special-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the November 2, 2010 special election",
        "status": "certified",
        "election_id": "election-2010-11-02-san-rafael-paramedic-special",
        "record_entry_ids": [15686],
    },
    {
        "id": "decision-2011-11-08-san-rafael-general-call",
        "decision_type": "call_election",
        "title": "Call the November 8, 2011 general municipal election",
        "status": "adopted",
        "election_id": "election-2011-11-08-san-rafael-general",
        "record_entry_ids": [7098, 15689],
    },
    {
        "id": "decision-2011-11-08-san-rafael-general-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the November 8, 2011 general municipal election",
        "status": "certified",
        "election_id": "election-2011-11-08-san-rafael-general",
        "record_entry_ids": [4496],
    },
    {
        "id": "decision-2013-11-05-san-rafael-general-call",
        "decision_type": "call_election",
        "title": "Call the November 5, 2013 general municipal election and submit Measure E to the voters",
        "status": "adopted",
        "election_id": "election-2013-11-05-san-rafael-general",
        "record_entry_ids": [4958, 6720],
    },
    {
        "id": "decision-2013-11-05-san-rafael-general-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the November 5, 2013 general municipal election",
        "status": "certified",
        "election_id": "election-2013-11-05-san-rafael-general",
        "record_entry_ids": [5146, 6779],
    },
    {
        "id": "decision-2015-11-03-san-rafael-general-call",
        "decision_type": "call_election",
        "title": "Call the November 3, 2015 general municipal election",
        "status": "adopted",
        "election_id": "election-2015-11-03-san-rafael-general",
        "record_entry_ids": [5717],
    },
    {
        "id": "decision-2015-11-03-san-rafael-general-cancel-and-appoint",
        "decision_type": "appoint_unopposed_candidates",
        "title": "Appoint unopposed candidates and cancel the November 3, 2015 election",
        "status": "adopted",
        "election_id": "election-2015-11-03-san-rafael-general",
        "record_entry_ids": [5873],
    },
    {
        "id": "decision-2016-06-07-san-rafael-library-special-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the June 7, 2016 library special election",
        "status": "certified",
        "election_id": "election-2016-06-07-san-rafael-library-special",
        "record_entry_ids": [12054],
    },
    {
        "id": "decision-2017-11-07-san-rafael-general-cancel",
        "decision_type": "cancel_election",
        "title": "Cancel the November 7, 2017 general municipal election",
        "status": "adopted",
        "election_id": "election-2017-11-07-san-rafael-general",
        "record_entry_ids": [21179],
    },
    {
        "id": "decision-2018-06-05-san-rafael-measure-g-call",
        "decision_type": "call_special_election",
        "title": "Call the June 5, 2018 special election for Measure G",
        "status": "adopted",
        "election_id": "election-2018-06-05-san-rafael-measure-g-special",
        "record_entry_ids": [22166],
    },
    {
        "id": "decision-2018-06-05-san-rafael-measure-g-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the June 5, 2018 Measure G special election",
        "status": "certified",
        "election_id": "election-2018-06-05-san-rafael-measure-g-special",
        "record_entry_ids": [24697, 24710],
    },
    {
        "id": "decision-2018-11-06-san-rafael-general-call",
        "decision_type": "call_election",
        "title": "Call the November 6, 2018 general municipal election",
        "status": "adopted",
        "election_id": "election-2018-11-06-san-rafael-general",
        "record_entry_ids": [24131, 24145],
    },
    {
        "id": "decision-2018-11-06-san-rafael-general-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the November 6, 2018 general municipal election",
        "status": "certified",
        "election_id": "election-2018-11-06-san-rafael-general",
        "record_entry_ids": [25815],
    },
    {
        "id": "decision-2020-11-03-san-rafael-general-call",
        "decision_type": "call_election",
        "title": "Call the November 3, 2020 general municipal election",
        "status": "adopted",
        "election_id": "election-2020-11-03-san-rafael-general",
        "record_entry_ids": [29206],
    },
    {
        "id": "decision-2020-11-03-san-rafael-general-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the November 3, 2020 general municipal election",
        "status": "certified",
        "election_id": "election-2020-11-03-san-rafael-general",
        "record_entry_ids": [32407],
    },
    {
        "id": "decision-2024-11-05-san-rafael-initiative-submission",
        "decision_type": "submit_initiative_to_voters",
        "title": "Order submission of the Albert Park library initiative to the November 5, 2024 ballot",
        "status": "adopted",
        "election_id": "election-2024-11-05-san-rafael-general",
        "record_entry_ids": [37027, 37028],
    },
    {
        "id": "decision-2024-11-05-san-rafael-general-results",
        "decision_type": "declare_election_results",
        "title": "Declare canvass of returns for the November 5, 2024 general municipal election",
        "status": "certified",
        "election_id": "election-2024-11-05-san-rafael-general",
        "record_entry_ids": [40185],
    },
    {
        "id": "decision-2026-06-02-san-rafael-library-special-call",
        "decision_type": "call_special_election",
        "title": "Call the June 2, 2026 special election for the library services parcel-tax measure",
        "status": "adopted",
        "election_id": "election-2026-06-02-san-rafael-library-special",
        "record_entry_ids": [41989, 41998],
        "notes": "Entry 41989 already contains the staff report, Resolution 15511, and the full text of the measure. Entry 41998 remains an uncaptured direct-record holdout.",
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_records() -> dict[str, Any]:
    return json.loads(EXTRACTED_PATH.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def record_id(entry_id: int) -> str:
    return f"record-san-rafael-election-entry-{entry_id}"


def meeting_id(meeting_date: str) -> str:
    return f"meeting-{meeting_date}-san-rafael-city-council"


def parse_meeting_date(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalized_anchor(record: dict[str, Any]) -> str:
    linked_from = record.get("linked_from") or []
    if not linked_from:
        return ""
    return str(linked_from[0].get("anchor_text") or "").strip()


def path_basename(record: dict[str, Any]) -> str:
    path = str(record.get("path") or "").strip()
    if not path:
        return ""
    return path.split("\\")[-1].strip()


def looks_like_date_label(value: str) -> bool:
    if not value:
        return False
    normalized = value.replace(",", "").replace("–", " ").replace("-", " ").strip()
    parts = normalized.split()
    months = {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
    if len(parts) == 3 and parts[0].lower() in months:
        return parts[1].isdigit() and parts[2].isdigit()
    return False


def best_record_title(record: dict[str, Any]) -> str:
    anchor = normalized_anchor(record)
    generic_labels = {"approved", "resolution", "ordinance"}
    if anchor and anchor.lower() not in generic_labels and not looks_like_date_label(anchor):
        return anchor

    basename = path_basename(record)
    if basename:
        return basename

    if anchor:
        return anchor

    return f"Election record {record['entry_id']}"


def detect_record_class(record: dict[str, Any]) -> tuple[str, str]:
    anchor = normalized_anchor(record).lower()
    excerpt = str(record.get("first_page_text_excerpt") or "").lower()
    template_name = str(record.get("template_name") or "")

    if "impartial analysis" in anchor or "impartial analysis" in excerpt:
        return ("legislative_record", "impartial_analysis")
    if "initiative measure to be submitted directly to the voters" in excerpt:
        return ("legislative_record", "initiative_text")
    if "ordinance no." in excerpt or anchor.startswith("ordinance"):
        return ("legislative_record", "ordinance")
    if "resolution no." in excerpt or "resolution" in anchor:
        return ("legislative_record", "resolution")
    if "clerk's certificate" in excerpt:
        return ("legislative_record", "clerks_certificate")
    if template_name == "Council Staff Reports":
        return ("meeting_record", "agenda_report")
    return ("administrative_record", "election_record")


def meeting_type_for_records(records: list[dict[str, Any]]) -> str:
    for record in records:
        excerpt = str(record.get("first_page_text_excerpt") or "").upper()
        if "SPECIAL" in excerpt:
            return "special"
    return "regular"


def main() -> None:
    extracted = load_records()
    records = extracted["records"]
    record_map = {int(record["entry_id"]): record for record in records}
    decision_id_by_entry_id: dict[int, list[str]] = {}
    for spec in DECISION_SPECS:
        for entry_id in spec["record_entry_ids"]:
            decision_id_by_entry_id.setdefault(entry_id, []).append(spec["id"])

    record_refs = []
    meeting_records: dict[str, list[dict[str, Any]]] = {}
    source_to_record_ids: dict[str, list[str]] = {source_id: [] for source_id in ELECTION_SPECS}

    for record in records:
        entry_id = int(record["entry_id"])
        rec_id = record_id(entry_id)
        meeting_value = (record.get("metadata_fields") or {}).get("Date - Meeting") or []
        date_iso = parse_meeting_date(meeting_value[0] if meeting_value else None)
        if date_iso:
            meeting_records.setdefault(date_iso, []).append(record)

        linked_source_ids = sorted(
            {str(item["source_id"]) for item in (record.get("linked_from") or []) if item.get("source_id")}
        )
        election_ids = []
        for source_id in linked_source_ids:
            source_to_record_ids.setdefault(source_id, []).append(rec_id)
            election_spec = ELECTION_SPECS.get(source_id)
            if election_spec:
                election_ids.append(election_spec["id"])

        rec_class, rec_type = detect_record_class(record)
        record_ref = {
            "id": rec_id,
            "entry_id": entry_id,
            "record_class": rec_class,
            "record_type": rec_type,
            "source_id": SOURCE_ID,
            "artifact_path": RAW_ARTIFACT_PATH,
            "capture_status": record.get("capture_status"),
            "doc_url": record.get("doc_url"),
            "template_name": record.get("template_name"),
            "title": best_record_title(record),
            "page_anchor_text": normalized_anchor(record),
            "linked_from_source_ids": linked_source_ids,
            "election_ids": election_ids,
            "decision_ids": decision_id_by_entry_id.get(entry_id, []),
        }
        if date_iso:
            record_ref["meeting_date"] = date_iso
            record_ref["meeting_id"] = meeting_id(date_iso)
        if record.get("error"):
            record_ref["error"] = record["error"]
        record_refs.append(record_ref)

    meeting_candidates = []
    for date_iso in sorted(meeting_records):
        evidence_ids = [record_id(int(item["entry_id"])) for item in meeting_records[date_iso]]
        meeting_candidates.append(
            {
                "id": meeting_id(date_iso),
                "title": "San Rafael City Council meeting",
                "meeting_date": date_iso,
                "meeting_type": meeting_type_for_records(meeting_records[date_iso]),
                "institution_id": "inst-san-rafael-city-council",
                "status": "derived_from_record_metadata",
                "evidence_record_ids": sorted(evidence_ids),
            }
        )

    election_candidates = []
    for source_id, spec in ELECTION_SPECS.items():
        candidate = {
            "id": spec["id"],
            "title": spec["title"],
            "jurisdiction_id": "place-san-rafael",
            "election_type": spec["election_type"],
            "election_date": spec["election_date"],
            "status": spec["status"],
            "source_page_source_id": source_id,
            "evidence_record_ids": sorted(source_to_record_ids.get(source_id, [])),
        }
        if spec.get("notes"):
            candidate["notes"] = spec["notes"]
        if spec.get("related_canonical_election_ids"):
            candidate["related_canonical_election_ids"] = spec["related_canonical_election_ids"]
        election_candidates.append(candidate)

    decision_candidates = []
    for spec in DECISION_SPECS:
        spec_records = [record_map[entry_id] for entry_id in spec["record_entry_ids"] if entry_id in record_map]
        decided_at = None
        meeting_id_value = None
        for record in spec_records:
            meeting_value = (record.get("metadata_fields") or {}).get("Date - Meeting") or []
            candidate_date = parse_meeting_date(meeting_value[0] if meeting_value else None)
            if candidate_date:
                decided_at = candidate_date
                meeting_id_value = meeting_id(candidate_date)
                break

        candidate = {
            "id": spec["id"],
            "decision_type": spec["decision_type"],
            "institution_id": "inst-san-rafael-city-council",
            "title": spec["title"],
            "status": spec["status"],
            "election_id": spec["election_id"],
            "record_ids": [record_id(entry_id) for entry_id in spec["record_entry_ids"]],
        }
        if decided_at:
            candidate["decided_at"] = decided_at
            candidate["meeting_id"] = meeting_id_value
        if spec.get("notes"):
            candidate["notes"] = spec["notes"]
        candidate["evidence_summary"] = (
            f"Promoted from {len(spec['record_entry_ids'])} page-linked election records "
            "captured from the public San Rafael election pages."
        )
        decision_candidates.append(candidate)

    bundle = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "page-linked San Rafael election records",
            "page-level election objects from 2010 through 2026",
            "council-meeting joins for election actions",
            "conservative promotion of election-call, results, cancellation, and unopposed-appointment decisions",
        ],
        "record_refs": sorted(record_refs, key=lambda item: item["entry_id"]),
        "place_candidates": [
            {
                "id": "place-san-rafael",
                "name": "San Rafael",
                "place_type": "city",
            }
        ],
        "institution_candidates": [
            {
                "id": "inst-city-of-san-rafael",
                "name": "City of San Rafael",
                "institution_type": "city_government",
            },
            {
                "id": "inst-san-rafael-city-council",
                "name": "San Rafael City Council",
                "institution_type": "council",
                "parent_institution_id": "inst-city-of-san-rafael",
            },
            {
                "id": "inst-san-rafael-city-clerk",
                "name": "San Rafael City Clerk",
                "institution_type": "filing_officer",
                "parent_institution_id": "inst-city-of-san-rafael",
            },
        ],
        "meeting_candidates": meeting_candidates,
        "election_candidates": election_candidates,
        "decision_candidates": decision_candidates,
        "open_questions": [
            {
                "id": "OQ-022",
                "status": "watch",
                "summary": "Entry 41998 still fails on the public Laserfiche JSON path even though entry 41989 already preserves the 2026 call-election resolution text inside the attached staff-report record.",
            }
        ],
        "notes": [
            "This bundle keeps all 37 page-linked election records as record refs, even when the JSON follow-up failed for a direct record.",
            "The 2024 page-level election object is intentionally broader than the seat-specific 2024 election records already present in the canonical seed bundle.",
            "Some older legislative records preserve ordinance or initiative text rather than a discrete council action. Those remain record-level objects unless an explicit action record is also present.",
        ],
    }

    write_json(OUTPUT_PATH, bundle)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
