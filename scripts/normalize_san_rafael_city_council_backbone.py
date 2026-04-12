#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_EXTRACT_DIR = ROOT / "data" / "extracted" / "san-rafael-city-council-meetings"
PAGE_EXTRACT_DIR = ROOT / "data" / "extracted" / "san-rafael-city-council-meeting-pages"
ARCHIVE_RAW_HTML = ROOT / "data" / "raw" / "san-rafael-city-council-meetings" / "2026-04-11" / "source.html"
OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-city-council-backbone-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

CASE_STUDY_ID = "san-rafael-city-council-backbone-01"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"
ARCHIVE_RECORD_ID = "record-san-rafael-city-council-archive-page"

MEETING_TYPE_MAP = {
    "regular": "regular_meeting",
    "closed_session": "closed_session",
    "special": "special_meeting",
    "special_closed_session": "special_closed_session",
    "special_retreat": "special_retreat",
    "retreat": "retreat",
    "study_session": "study_session",
    "workshop": "workshop",
    "cancelled": "cancelled_meeting",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latest_json(directory: Path) -> Path:
    candidates = sorted(directory.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No JSON files found in {directory}")
    return candidates[-1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def build_archive_record_ref(archive_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ARCHIVE_RECORD_ID,
        "record_class": "meeting_record",
        "record_type": "meeting_archive_page",
        "source_id": "san-rafael-city-council-meetings",
        "artifact_path": str(ARCHIVE_RAW_HTML.relative_to(ROOT)),
        "source_url": archive_payload["entry_url"],
        "title": "San Rafael City Council meetings archive page",
        "capture_status": "captured_html",
        "years_covered": archive_payload.get("years_covered", []),
        "meeting_count": archive_payload.get("meeting_count"),
    }


def build_page_record_ref(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page["record_id"],
        "record_class": "meeting_record",
        "record_type": "meeting_page",
        "source_id": "san-rafael-city-council-meeting-pages",
        "artifact_path": page["artifact_path"],
        "meeting_id": page["meeting_id"],
        "source_url": page["meeting_page_url"],
        "title": page.get("page_title") or page["title"],
        "capture_status": "captured_html",
        "meeting_kind": page["meeting_kind"],
        "published_at": page.get("published_at"),
        "modified_at": page.get("modified_at"),
        "agenda_download_url": page.get("agenda_download_url"),
        "agenda_packet_download_url": page.get("agenda_packet_download_url"),
        "minutes_download_url": page.get("minutes_download_url"),
        "video_url": page.get("video_url"),
        "agenda_item_marker_count": page.get("agenda_item_marker_count", 0),
    }


def build_meeting_candidate(page: dict[str, Any]) -> dict[str, Any]:
    meeting_type = MEETING_TYPE_MAP.get(page["meeting_kind"], page["meeting_kind"])
    meeting_candidate = {
        "id": page["meeting_id"],
        "title": "San Rafael City Council meeting",
        "meeting_date": page.get("meeting_date"),
        "meeting_type": meeting_type,
        "institution_id": "inst-san-rafael-city-council",
        "status": "captured_from_meeting_page",
        "meeting_page_url": page["meeting_page_url"],
        "archive_meeting_page_url": page["archive_meeting_page_url"],
        "flags": page.get("flags", []),
        "evidence_record_ids": [page["record_id"], ARCHIVE_RECORD_ID],
        "agenda_item_marker_count": page.get("agenda_item_marker_count", 0),
        "agenda_pdf_url": page.get("agenda_download_url"),
        "agenda_packet_url": page.get("agenda_packet_download_url"),
        "minutes_url": page.get("minutes_download_url"),
        "video_url": page.get("video_url"),
        "has_agenda_tab": page["artifact_availability"]["agenda_tab"],
        "has_agenda_packet_tab": page["artifact_availability"]["agenda_packet_tab"],
        "has_minutes_tab": page["artifact_availability"]["minutes_tab"],
        "has_video_tab": page["artifact_availability"]["video_tab"],
    }
    if page.get("starts_at"):
        meeting_candidate["starts_at"] = page["starts_at"]
    return meeting_candidate


def main() -> None:
    archive_payload = load_json(latest_json(ARCHIVE_EXTRACT_DIR))
    page_payload = load_json(latest_json(PAGE_EXTRACT_DIR))

    record_refs = [build_archive_record_ref(archive_payload)]
    meeting_candidates: list[dict[str, Any]] = []

    for page in page_payload["meeting_pages"]:
        record_refs.append(build_page_record_ref(page))
        meeting_candidates.append(build_meeting_candidate(page))

    meeting_type_counts: dict[str, int] = {}
    for meeting in meeting_candidates:
        meeting_type = meeting["meeting_type"]
        meeting_type_counts[meeting_type] = meeting_type_counts.get(meeting_type, 0) + 1

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "San Rafael City Council 2019+ meeting-page-backed meeting and evidence-record backbone",
            "Meeting-page-backed agenda/packet/minutes/video URL continuity without citywide decision extraction",
            "First breadth-sprint checkpoint for meeting density before broader county widening",
        ],
        "record_refs": record_refs,
        "meeting_candidates": meeting_candidates,
        "methodology_findings": [
            {
                "id": "method-council-backbone-meeting-pages-before-citywide-decisions",
                "summary": "This bundle promotes captured council meeting pages and meeting nodes across the full 2019+ archive inventory. It does not promote citywide agenda items, decisions, or votes until the captured meeting pages and linked minutes can be parsed more deeply."
            },
            {
                "id": "method-council-backbone-keeps-linked-artifacts-lightweight",
                "summary": "Agenda, agenda-packet, minutes, and video URLs are preserved on the meeting and meeting-page record objects in this first pass. Separate linked Record nodes for those artifacts can be added later if they materially improve graph queries."
            },
        ],
        "open_questions": [
            {
                "id": "OQ-033",
                "status": "open",
                "summary": "The San Rafael council breadth slice now has a real meeting and evidence backbone, but it still needs agenda-item, decision, and vote extraction from captured meeting pages and linked minutes before the citywide decision timeline query can fully pass.",
            }
        ],
        "notes": [
            f"Archive inventory source: {page_payload['archive_extract_path']}",
            f"Captured meeting-page count: {page_payload['meeting_page_count']}",
            "Meeting nodes reuse the canonical `inst-san-rafael-city-council` institution rather than introducing a second city-council namespace.",
        ],
        "summary": {
            "meeting_count": len(meeting_candidates),
            "record_count": len(record_refs),
            "meeting_type_counts": dict(sorted(meeting_type_counts.items())),
            "meetings_with_starts_at": sum(1 for meeting in meeting_candidates if meeting.get("starts_at")),
            "meetings_with_minutes_url": sum(1 for meeting in meeting_candidates if meeting.get("minutes_url")),
            "meetings_with_agenda_packet_url": sum(
                1 for meeting in meeting_candidates if meeting.get("agenda_packet_url")
            ),
            "meetings_with_video_url": sum(1 for meeting in meeting_candidates if meeting.get("video_url")),
        },
    }

    write_json(OUTPUT_PATH, payload)


if __name__ == "__main__":
    main()
