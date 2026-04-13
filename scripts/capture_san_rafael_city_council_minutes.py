#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted"
PAGE_EXTRACT_DIR = EXTRACTED_DIR / "san-rafael-city-council-meeting-pages"

SOURCE_ID = "san-rafael-city-council-minutes"
USER_AGENT = "Mozilla/5.0"

ALL_CAPS_HEADING_RE = re.compile(r"^[A-Z0-9/&'()., \-–]+:?$")
SECTION_RE = re.compile(r"^(?P<number>\d+)\.\s+(?P<title>.+?)(?::)?$")
SUBITEM_RE = re.compile(r"^(?P<letter>[a-z])\.\s+(?P<title>.+)$")
MOTION_RE = re.compile(
    r"^(?P<mover_role>Councilmember|Mayor(?: Pro Tem)?|Vice Mayor)\s+"
    r"(?P<mover>.+?)\s+moved\s+and\s+"
    r"(?P<seconder_role>Councilmember|Mayor(?: Pro Tem)?|Vice Mayor)\s+"
    r"(?P<seconder>.+?)\s+seconded\s+to\s+(?P<action>.+)$",
    re.IGNORECASE,
)
VOTE_LINE_RE = re.compile(
    r"^(?P<vote>AYES|NOES|ABSENT|ABSTAIN):\s*Councilmembers?:\s*(?P<names>.+)$",
    re.IGNORECASE,
)
RESOLUTION_RE = re.compile(r"\bRESOLUTION\s*([0-9]{4,6})\b", re.IGNORECASE)
OUTCOME_RE = re.compile(
    r"^(Approved|Accepted|Adopted|Introduced|Received|Removed|Rejected|Continued|Appointed)\b",
    re.IGNORECASE,
)
PAGE_FOOTER_RE = re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE)
STANDALONE_PAGE_RE = re.compile(r"^\d+$")


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def latest_json(directory: Path) -> Path:
    candidates = sorted(directory.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No JSON files found in {directory}")
    return candidates[-1]


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {403, 500, 502, 503, 504} or attempt == 3:
                raise
            time.sleep(0.5 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == 3:
                raise
            time.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def compact_spaces(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def clean_line(line: str) -> str | None:
    stripped = line.rstrip()
    if not stripped.strip():
        return None
    if PAGE_FOOTER_RE.match(stripped.strip()):
        return None
    if STANDALONE_PAGE_RE.match(stripped.strip()):
        return None
    return compact_spaces(stripped)


def is_all_caps_heading(line: str) -> bool:
    if len(line) < 4:
        return False
    if not ALL_CAPS_HEADING_RE.match(line):
        return False
    if line.startswith("RESOLUTION") or line.startswith("AN ORDINANCE"):
        return False
    if line.endswith("."):
        return False
    if SECTION_RE.match(line) or SUBITEM_RE.match(line):
        return False
    return any(ch.isalpha() for ch in line)


def normalize_vote_name(raw_name: str) -> str:
    name = compact_spaces(raw_name)
    name = re.sub(r"^(Councilmember|Mayor(?: Pro Tem)?|Vice Mayor)\s+", "", name, flags=re.IGNORECASE)
    name = name.strip(" ,.;:-")
    return name


def split_vote_names(raw_value: str) -> list[str]:
    value = compact_spaces(raw_value)
    if value.lower() == "none":
        return []
    value = value.replace("&", ",")
    value = re.sub(r"\band\b", ",", value, flags=re.IGNORECASE)
    parts = [normalize_vote_name(part) for part in value.split(",")]
    return [part for part in parts if part]


def normalize_heading_title(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip(":").title()


def parse_motion(line: str) -> dict[str, str] | None:
    match = MOTION_RE.match(line)
    if not match:
        return None
    return {
        "moved_by_raw": normalize_vote_name(match.group("mover")),
        "seconded_by_raw": normalize_vote_name(match.group("seconder")),
        "motion_text": compact_spaces(match.group("action")).rstrip("."),
    }


def parse_vote_line(line: str) -> tuple[str, list[str]] | None:
    match = VOTE_LINE_RE.match(line)
    if not match:
        return None
    vote_bucket = match.group("vote").lower()
    return vote_bucket, split_vote_names(match.group("names"))


def classify_outcome(outcome_text: str, resolution_numbers: list[str]) -> tuple[str, str]:
    outcome = outcome_text.lower()
    if "introduced the ordinance" in outcome:
        return "ordinance_introduction", "introduced"
    if "adopted resolution" in outcome or resolution_numbers:
        return "resolution_adoption", "adopted"
    if "approved minutes" in outcome or "approved as submitted" in outcome:
        return "minutes_approval", "approved"
    if "approved staff recommendation" in outcome:
        return "staff_recommendation_approval", "approved"
    if "accepted report" in outcome:
        return "report_acceptance", "accepted"
    if outcome.startswith("received"):
        return "direction_or_receipt", "received"
    if outcome.startswith("removed"):
        return "agenda_removal", "removed"
    if outcome.startswith("continued"):
        return "continuance", "continued"
    if outcome.startswith("appointed") or outcome.startswith("appoin"):
        return "appointment", "appointed"
    if outcome.startswith("approved"):
        return "approval", "approved"
    if outcome.startswith("accepted"):
        return "acceptance", "accepted"
    return "decision", "recorded"


def classify_motion_only_decision(title: str, motion_text: str) -> tuple[str, str]:
    title_lower = title.lower()
    motion_lower = motion_text.lower()
    if "consent" in title_lower or "consent calendar" in motion_lower:
        return "consent_calendar_approval", "approved"
    if "electronic and paperless filing" in motion_lower:
        return "ordinance_introduction", "introduced"
    return "motion_approval", "approved"


def parse_minutes_text(text: str) -> dict[str, Any]:
    cleaned_lines = [line for raw_line in text.splitlines() if (line := clean_line(raw_line))]

    blocks: list[dict[str, Any]] = []
    current_heading: str | None = None
    current_section: dict[str, Any] | None = None
    current_subitem: dict[str, Any] | None = None

    def start_block(block: dict[str, Any]) -> None:
        blocks.append(block)

    for line in cleaned_lines:
        if is_all_caps_heading(line):
            current_heading = normalize_heading_title(line)
            continue

        section_match = SECTION_RE.match(line)
        if section_match:
            current_subitem = None
            current_section = {
                "item_key": section_match.group("number"),
                "block_type": "section",
                "section_number": section_match.group("number"),
                "item_number": section_match.group("number"),
                "item_letter": None,
                "title": compact_spaces(section_match.group("title")).rstrip(":"),
                "heading": current_heading,
                "parent_item_key": None,
                "subitem_keys": [],
                "lines": [],
            }
            start_block(current_section)
            continue

        subitem_match = SUBITEM_RE.match(line)
        if subitem_match and current_section:
            current_subitem = {
                "item_key": f"{current_section['section_number']}{subitem_match.group('letter')}",
                "block_type": "subitem",
                "section_number": current_section["section_number"],
                "item_number": f"{current_section['section_number']}.{subitem_match.group('letter')}",
                "item_letter": subitem_match.group("letter"),
                "title": compact_spaces(subitem_match.group("title")).rstrip(":"),
                "heading": current_heading or current_section.get("heading"),
                "parent_item_key": current_section["item_key"],
                "subitem_keys": [],
                "lines": [],
            }
            current_section["subitem_keys"].append(current_subitem["item_key"])
            start_block(current_subitem)
            continue

        target = current_subitem or current_section
        if target:
            target["lines"].append(line)

    parsed_items: list[dict[str, Any]] = []
    for block in blocks:
        motion: dict[str, str] | None = None
        vote_summary = {"ayes": [], "noes": [], "absent": [], "abstain": []}
        outcome_lines: list[str] = []
        resolution_numbers: list[str] = []

        for line in block["lines"]:
            if motion is None:
                motion = parse_motion(line)

            vote_line = parse_vote_line(line)
            if vote_line:
                vote_bucket, names = vote_line
                vote_summary[vote_bucket] = names

            for match in RESOLUTION_RE.finditer(line):
                number = match.group(1)
                if number not in resolution_numbers:
                    resolution_numbers.append(number)

            if OUTCOME_RE.match(line) and not line.upper().startswith("APPROVED THIS "):
                outcome_lines.append(line.rstrip("."))

        parsed_items.append(
            {
                "item_key": block["item_key"],
                "block_type": block["block_type"],
                "section_number": block["section_number"],
                "item_number": block["item_number"],
                "item_letter": block["item_letter"],
                "title": block["title"],
                "heading": block["heading"],
                "parent_item_key": block["parent_item_key"],
                "subitem_keys": block["subitem_keys"],
                "motion": motion,
                "vote_summary": vote_summary,
                "outcome_lines": outcome_lines,
                "resolution_numbers": resolution_numbers,
                "line_count": len(block["lines"]),
            }
        )

    return {
        "line_count": len(cleaned_lines),
        "agenda_items": parsed_items,
    }


def extract_pdf_text(pdf_path: Path, text_path: Path) -> tuple[str, int]:
    subprocess.run(["pdftotext", "-layout", str(pdf_path), str(text_path)], check=True, cwd=ROOT)
    text = text_path.read_text(encoding="utf-8", errors="ignore")
    page_count = len(PdfReader(str(pdf_path)).pages)
    return text, page_count


def capture_one(meeting: dict[str, Any], pdf_dir: Path, text_dir: Path) -> dict[str, Any]:
    minutes_url = meeting["minutes_download_url"]
    pdf_filename = f"{meeting['meeting_id']}.pdf"
    text_filename = f"{meeting['meeting_id']}.txt"
    pdf_path = pdf_dir / pdf_filename
    text_path = text_dir / text_filename

    if not pdf_path.exists():
        pdf_path.write_bytes(fetch_bytes(minutes_url))

    text, page_count = extract_pdf_text(pdf_path, text_path)
    parsed = parse_minutes_text(text)

    return {
        "meeting_id": meeting["meeting_id"],
        "meeting_date": meeting["meeting_date"],
        "meeting_kind": meeting["meeting_kind"],
        "meeting_page_record_id": meeting["record_id"],
        "meeting_page_url": meeting["meeting_page_url"],
        "minutes_record_id": meeting["meeting_id"].replace("meeting-", "record-", 1) + "-minutes",
        "minutes_url": minutes_url,
        "pdf_artifact_path": str(pdf_path.relative_to(ROOT)),
        "text_artifact_path": str(text_path.relative_to(ROOT)),
        "page_count": page_count,
        "line_count": parsed["line_count"],
        "agenda_items": parsed["agenda_items"],
        "summary": {
            "agenda_item_count": len(parsed["agenda_items"]),
            "decision_signal_item_count": sum(
                1
                for item in parsed["agenda_items"]
                if item["motion"] or item["outcome_lines"] or item["resolution_numbers"]
            ),
            "vote_signal_item_count": sum(
                1 for item in parsed["agenda_items"] if any(item["vote_summary"].values())
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture and parse San Rafael City Council minutes PDFs.")
    parser.add_argument("--capture-date", default=datetime.now().date().isoformat())
    parser.add_argument("--meeting-pages-extract", default=None)
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args()

    meeting_pages_extract = (
        Path(args.meeting_pages_extract).resolve()
        if args.meeting_pages_extract
        else latest_json(PAGE_EXTRACT_DIR)
    )
    meeting_pages_payload = load_json(meeting_pages_extract)

    capture_dir = RAW_DIR / SOURCE_ID / args.capture_date
    pdf_dir = capture_dir / "pdfs"
    text_dir = EXTRACTED_DIR / SOURCE_ID / args.capture_date / "texts"
    summary_path = EXTRACTED_DIR / SOURCE_ID / f"{args.capture_date}.json"
    manifest_path = capture_dir / "manifest.json"

    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    meetings = [
        meeting
        for meeting in meeting_pages_payload["meeting_pages"]
        if meeting.get("minutes_download_url")
    ]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_map = {executor.submit(capture_one, meeting, pdf_dir, text_dir): meeting for meeting in meetings}
        for future in as_completed(future_map):
            meeting = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "meeting_id": meeting["meeting_id"],
                        "minutes_url": meeting["minutes_download_url"],
                        "error": repr(exc),
                    }
                )

    results.sort(key=lambda item: (item["meeting_date"], item["meeting_id"]))
    record_ids = [result["minutes_record_id"] for result in results]

    summary_payload = {
        "source_id": SOURCE_ID,
        "capture_id": f"{SOURCE_ID}__{args.capture_date}",
        "captured_at": utc_now_iso(),
        "meeting_pages_extract_path": str(meeting_pages_extract.relative_to(ROOT)),
        "meeting_minutes_count": len(results),
        "error_count": len(errors),
        "summary": {
            "years_covered": sorted({int(result["meeting_date"][:4]) for result in results if result["meeting_date"]}),
            "meetings_with_vote_signals": sum(
                1 for result in results if result["summary"]["vote_signal_item_count"] > 0
            ),
            "meetings_with_decision_signals": sum(
                1 for result in results if result["summary"]["decision_signal_item_count"] > 0
            ),
            "agenda_item_count": sum(result["summary"]["agenda_item_count"] for result in results),
            "page_count": sum(result["page_count"] for result in results),
        },
        "minutes_records": results,
        "errors": errors,
    }

    manifest_payload = {
        "source_id": SOURCE_ID,
        "capture_id": f"{SOURCE_ID}__{args.capture_date}",
        "captured_at": utc_now_iso(),
        "entry_extract_path": str(meeting_pages_extract.relative_to(ROOT)),
        "fetch_strategy": "meeting_page_inventory_to_minutes_pdf_capture",
        "meeting_count": len(results),
        "error_count": len(errors),
        "artifacts": [
            {
                "path": str((ROOT / result["pdf_artifact_path"]).relative_to(capture_dir)),
                "content_type": "application/pdf",
                "meeting_id": result["meeting_id"],
            }
            for result in results
        ],
        "notes": [
            "Minutes PDFs are captured from the linked San Rafael meeting-page inventory.",
            "Plain-text extraction uses `pdftotext -layout` for more stable agenda and vote parsing than pypdf alone.",
            f"Minutes record ids captured: {len(record_ids)}",
        ],
    }

    write_json(summary_path, summary_payload)
    write_json(manifest_path, manifest_payload)


if __name__ == "__main__":
    main()
