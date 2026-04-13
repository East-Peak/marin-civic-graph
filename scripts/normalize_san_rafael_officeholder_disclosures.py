#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
FORM700_EXTRACT_PATH = (
    ROOT / "data" / "extracted" / "san-rafael-sei-netfile-portal" / "2026-04-12.json"
)
CANONICAL_SEEDS_PATH = ROOT / "data" / "normalized" / "canonical-seeds-san-rafael-01.json"
OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-officeholder-disclosures-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

BUNDLE_ID = "san-rafael-officeholder-disclosures-01__bundle-01"
CASE_STUDY_ID = "san-rafael-officeholder-disclosures-01"

FORM700_PORTAL_RECORD_ID = "record-san-rafael-form700-portal-2026-04-12"
FORM700_EXPORT_RECORD_ID = "record-san-rafael-form700-export-2026-04-12"

OFFICEHOLDER_FILER_TO_ACTOR = {
    "Colin, Catherine": "actor-kate-colin",
    "Llorens Gulati, Maika": "actor-maika-llorens-gulati",
    "Hill, Elias": "actor-eli-hill",
    "Bushey, Maribeth": "actor-maribeth-bushey",
    "Kertz, Rachel": "actor-rachel-kertz",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def disclosure_type(statement_type: str) -> str:
    return slugify(statement_type).replace("-", "_")


def filing_matches_current_office(row: dict[str, Any], seat_id: str) -> bool:
    parts = [row.get("job_title", ""), row.get("department", "")]
    haystack = " ".join(part.lower() for part in parts if part).strip()
    if seat_id == "seat-san-rafael-mayor-at-large":
        return "mayor" in haystack
    if seat_id.startswith("seat-san-rafael-city-council-"):
        return "city council" in haystack
    return False


def filing_matches_seat_service(
    row: dict[str, Any],
    seat_service: dict[str, Any],
    filed_at: date | None,
) -> bool:
    started_at = parse_iso_date(seat_service.get("started_at"))
    ended_at = parse_iso_date(seat_service.get("ended_at"))
    if filed_at is None or started_at is None or filed_at < started_at:
        return False
    if ended_at is not None and filed_at >= ended_at:
        return False
    return filing_matches_current_office(row, seat_service["seat_id"])


def build_record_refs() -> list[dict[str, Any]]:
    return [
        {
            "id": FORM700_PORTAL_RECORD_ID,
            "record_class": "financial_record",
            "record_type": "disclosure_portal",
            "source_id": "san-rafael-sei-netfile-portal",
            "artifact_path": "data/raw/san-rafael-sei-netfile-portal/2026-04-12/source.html",
        },
        {
            "id": FORM700_EXPORT_RECORD_ID,
            "record_class": "financial_record",
            "record_type": "form_700_export",
            "source_id": "san-rafael-sei-netfile-portal",
            "artifact_path": "data/raw/san-rafael-sei-netfile-portal/2026-04-12/form700-700-filers-export.xls",
        },
    ]


def main() -> None:
    form700_extract = json.loads(FORM700_EXTRACT_PATH.read_text())
    canonical_seeds = json.loads(CANONICAL_SEEDS_PATH.read_text())

    seat_services_by_actor: dict[str, list[dict[str, Any]]] = {}
    for seat_service in canonical_seeds["seat_service_candidates"]:
        if seat_service.get("status") not in {"current", "historical"}:
            continue
        actor_id = seat_service["actor_id"]
        seat_services_by_actor.setdefault(actor_id, []).append(seat_service)

    for actor_id, seat_services in seat_services_by_actor.items():
        seat_services.sort(key=lambda item: (item.get("started_at") or "", item["id"]))

    filing_candidates: list[dict[str, Any]] = []
    eid_candidates: list[dict[str, Any]] = []

    for row in form700_extract["filings"]:
        actor_id = OFFICEHOLDER_FILER_TO_ACTOR.get(row["filer_name"])
        if actor_id is None:
            continue

        filed_at = parse_iso_date(row["filed_at"])
        matching_services = [
            seat_service
            for seat_service in seat_services_by_actor.get(actor_id, [])
            if filing_matches_seat_service(row, seat_service, filed_at)
        ]
        if not matching_services:
            continue
        seat_service = matching_services[-1]
        seat_id = seat_service["seat_id"]
        continuity_status = (
            "current_officeholder_continuity"
            if seat_service.get("status") == "current"
            else "historical_officeholder_continuity"
        )

        filing_id = f"filing-{row['filing_key']}"
        eid_id = f"eid-{row['filing_key']}"
        common_properties = {
            "source_filer_name": row["filer_name"],
            "position_title": row.get("job_title") or None,
            "department_name": row.get("department") or None,
            "statement_type": row["statement_type"],
            "document_link_count": row["document_link_count"],
            "record_locator": row["filing_key"],
            "base_filing_key": row["base_filing_key"],
            "evidence_record_ids": [FORM700_EXPORT_RECORD_ID],
        }

        filing_candidates.append(
            {
                "id": filing_id,
                "filing_type": "form_700",
                "official_actor_id": actor_id,
                "official_seat_id": seat_id,
                "official_seat_service_id": seat_service["id"],
                "filing_institution_id": "inst-city-of-san-rafael",
                "filed_at": row["filed_at"],
                "status": continuity_status,
                **common_properties,
            }
        )

        eid_candidates.append(
            {
                "id": eid_id,
                "filer_actor_id": actor_id,
                "filing_institution_id": "inst-city-of-san-rafael",
                "seat_id": seat_id,
                "seat_service_id": seat_service["id"],
                "filing_id": filing_id,
                "disclosure_type": disclosure_type(row["statement_type"]),
                "filed_at": row["filed_at"],
                "status": continuity_status,
                **common_properties,
            }
        )

    filing_candidates.sort(key=lambda item: item["filed_at"])
    eid_candidates.sort(key=lambda item: item["filed_at"])

    per_actor_counts: dict[str, int] = {}
    for filing in filing_candidates:
        per_actor_counts[filing["official_actor_id"]] = per_actor_counts.get(filing["official_actor_id"], 0) + 1

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "historical_officeholder_continuity_extended",
        "generated_at": utc_now_iso(),
        "scope": [
            "Current San Rafael elected officeholder Form 700 continuity plus explicit 2020-2024 historical service windows for the current mayor, District 1, and District 4 officeholders",
            "Seat-service joins only where the filing date falls inside an explicit current or historical service window",
            "Export-backed filing and EconomicInterestDisclosure objects without broad staff or commission import",
            "No broad pre-2020 or non-city-office mapping until older San Rafael seat-service history is modeled more explicitly"
        ],
        "record_refs": build_record_refs(),
        "filing_candidates": filing_candidates,
        "economic_interest_disclosure_candidates": eid_candidates,
        "summary": {
            "export_wave_01_row_count": form700_extract["summary"]["wave_01_row_count"],
            "visible_archive_start": form700_extract["summary"]["visible_archive_start"],
            "visible_archive_end": form700_extract["summary"]["visible_archive_end"],
            "promoted_filing_count": len(filing_candidates),
            "promoted_disclosure_count": len(eid_candidates),
            "promoted_actor_count": len(per_actor_counts),
            "per_actor_filing_counts": dict(sorted(per_actor_counts.items())),
        },
        "open_questions": [
            {
                "id": "OQ-034",
                "status": "watch",
                "question": "How should pre-2020 or pre-district Form 700 rows for current San Rafael officeholders map once older seat structures and older term boundaries are modeled?",
            }
        ],
        "notes": [
            "This slice is intentionally narrower than the full Form 700 archive. It promotes only rows that resolve cleanly to existing canonical officeholders and explicit seat-service boundaries.",
            "The export workbook is the evidence record for this continuity layer. Direct row-level document recovery remains a separate adapter problem and is still tracked as a global watch item.",
            "Kate Colin, Maika Llorens Gulati, and Rachel Kertz now also have explicit 2020-12-07 historical service starts because the December 7, 2020 special City Council minutes record their oath of office.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
