#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted"
SOURCE_ID = "marin-county-bos-meetings"
ENTRY_URL = "https://marin.granicus.com/ViewPublisher.php?view_id=33"
DISCOVERY_URL = "https://www.marincounty.gov/departments/board/board-supervisors-meetings"
USER_AGENT = "Mozilla/5.0"
WAVE_01_FLOOR_YEAR = 2019

YEAR_SECTION_RE = re.compile(
    r"<!--\s*(20\d{2}) Start\s*-->(.*?)(?=<!--\s*20\d{2} Start\s*-->|$)",
    re.S,
)
ROW_RE = re.compile(r"<tr class=\"listingRow\">.*?</tr>", re.S)
TD_RE = re.compile(r"<td class=\"listItem\".*?>(.*?)</td>", re.S)
ANCHOR_RE = re.compile(r"<a\b[^>]*href=(['\"])(.*?)\1[^>]*>(.*?)</a>", re.S | re.I)
HREF_RE = re.compile(r"href=(['\"])(.*?)\1", re.S | re.I)
ONCLICK_URL_RE = re.compile(r"window\.open\('([^']+)'", re.I)
DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*([AP]M)", re.I)
HIDDEN_EPOCH_RE = re.compile(r"<span[^>]*>\s*(\d{10})\s*</span>")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_mmddyy(value: str) -> str | None:
    match = DATE_RE.search(value)
    if not match:
        return None
    month, day, year = match.groups()
    return datetime.strptime(f"{month}/{day}/{year}", "%m/%d/%y").date().isoformat()


def extract_hidden_epoch(value: str) -> int | None:
    match = HIDDEN_EPOCH_RE.search(value)
    if not match:
        return None
    return int(match.group(1))


def extract_time_text(value: str) -> str | None:
    match = TIME_RE.search(strip_tags(value))
    if not match:
        return None
    return f"{match.group(1)} {match.group(2).upper()}"


def normalize_url(href: str | None) -> str | None:
    if not href:
        return None
    href = unescape(href).strip()
    if href in {"#", ""} or href.startswith("javascript:"):
        return None
    return urljoin(ENTRY_URL, href)


def extract_href(cell_html: str) -> str | None:
    match = HREF_RE.search(cell_html)
    if not match:
        return None
    return normalize_url(match.group(2))


def extract_onclick_url(cell_html: str) -> str | None:
    match = ONCLICK_URL_RE.search(cell_html)
    if not match:
        return None
    return normalize_url(match.group(1))


def extract_query_id(url: str | None, key: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get(key)
    if not values:
        return None
    return values[0]


def classify_meeting(name: str) -> tuple[str, list[str]]:
    lower = name.lower()
    flags: list[str] = []
    if "truth act" in lower:
        flags.append("truth_act_forum")
    if "joint" in lower:
        flags.append("joint_meeting")
    if "planning commission" in lower:
        flags.append("planning_commission")
    if "budget" in lower:
        flags.append("budget")
    if "closed session" in lower:
        flags.append("closed_session")
    if "special" in lower:
        flags.append("special")
    if "retreat" in lower:
        flags.append("retreat")
    if "hearing" in lower:
        flags.append("hearing")
    if "board of supervisors" in lower or "bos meeting" in lower:
        flags.append("board_meeting")

    if "truth_act_forum" in flags:
        meeting_kind = "truth_act_forum"
    elif "joint_meeting" in flags:
        meeting_kind = "joint_meeting"
    elif "budget" in flags:
        meeting_kind = "budget"
    elif "special" in flags and "closed_session" in flags:
        meeting_kind = "special_closed_session"
    elif "closed_session" in flags:
        meeting_kind = "closed_session"
    elif "special" in flags:
        meeting_kind = "special"
    elif "retreat" in flags:
        meeting_kind = "retreat"
    elif "hearing" in flags:
        meeting_kind = "hearing"
    elif "board_meeting" in flags:
        meeting_kind = "regular"
    else:
        meeting_kind = "other"

    return meeting_kind, sorted(set(flags))


def parse_archive_row(row_html: str, archive_year: int, row_number: int) -> dict[str, Any] | None:
    cells = TD_RE.findall(row_html)
    if len(cells) < 6:
        return None

    month_cell, name_cell, date_cell, agenda_cell, minutes_cell, video_cell, *rest = cells
    captions_cell = rest[0] if len(rest) >= 1 else ""
    mp3_cell = rest[1] if len(rest) >= 2 else ""
    mp4_cell = rest[2] if len(rest) >= 3 else ""

    month_label = strip_tags(month_cell)
    name = strip_tags(name_cell)
    if not name:
        return None

    meeting_date = parse_mmddyy(date_cell)
    time_text = extract_time_text(date_cell)
    source_sort_epoch = extract_hidden_epoch(date_cell)
    meeting_kind, flags = classify_meeting(name)

    agenda_url = extract_href(agenda_cell)
    minutes_url = extract_href(minutes_cell)
    video_url = extract_onclick_url(video_cell)
    captions_url = extract_href(captions_cell)
    mp3_url = extract_href(mp3_cell)
    mp4_url = extract_href(mp4_cell)

    clip_id = (
        extract_query_id(agenda_url, "clip_id")
        or extract_query_id(minutes_url, "clip_id")
        or extract_query_id(video_url, "clip_id")
        or extract_query_id(captions_url, "clip_id")
    )

    meeting_id_suffix = clip_id or f"{archive_year}-{row_number:03d}"

    return {
        "meeting_id": f"meeting-marin-county-bos-{meeting_id_suffix}",
        "record_status": "archived",
        "archive_year": archive_year,
        "archive_row_number": row_number,
        "source_sort_epoch": source_sort_epoch,
        "month_label": month_label,
        "title": name,
        "meeting_date": meeting_date,
        "meeting_time_text": time_text,
        "meeting_kind": meeting_kind,
        "flags": flags,
        "clip_id": clip_id,
        "artifacts": {
            "agenda": {"available": agenda_url is not None, "url": agenda_url},
            "minutes": {"available": minutes_url is not None, "url": minutes_url},
            "video": {"available": video_url is not None, "url": video_url},
            "captions": {"available": captions_url is not None, "url": captions_url},
            "mp3": {"available": mp3_url is not None, "url": mp3_url},
            "mp4": {"available": mp4_url is not None, "url": mp4_url},
        },
    }


def parse_upcoming_row(row_html: str, row_number: int) -> dict[str, Any] | None:
    cells = TD_RE.findall(row_html)
    if len(cells) < 3:
        return None

    name_cell, date_cell, agenda_cell, *rest = cells
    ecomments_cell = rest[0] if rest else ""
    name = strip_tags(name_cell)
    if not name:
        return None

    meeting_date = parse_mmddyy(date_cell)
    time_text = extract_time_text(date_cell)
    source_sort_epoch = extract_hidden_epoch(date_cell)
    meeting_kind, flags = classify_meeting(name)
    agenda_url = extract_href(agenda_cell)
    event_id = extract_query_id(agenda_url, "event_id")
    ecomments_url = extract_href(ecomments_cell)

    meeting_id_suffix = event_id or f"upcoming-{row_number:03d}"
    return {
        "meeting_id": f"meeting-marin-county-bos-{meeting_id_suffix}",
        "record_status": "upcoming",
        "upcoming_row_number": row_number,
        "source_sort_epoch": source_sort_epoch,
        "title": name,
        "meeting_date": meeting_date,
        "meeting_time_text": time_text,
        "meeting_kind": meeting_kind,
        "flags": flags,
        "event_id": event_id,
        "artifacts": {
            "agenda": {"available": agenda_url is not None, "url": agenda_url},
            "ecomment": {"available": ecomments_url is not None, "url": ecomments_url},
        },
    }


def count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def build_year_summaries(meetings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for year in sorted({meeting["archive_year"] for meeting in meetings}, reverse=True):
        year_meetings = [meeting for meeting in meetings if meeting["archive_year"] == year]
        summaries.append(
            {
                "archive_year": year,
                "meeting_count": len(year_meetings),
                "with_agenda": sum(1 for meeting in year_meetings if meeting["artifacts"]["agenda"]["available"]),
                "with_minutes": sum(1 for meeting in year_meetings if meeting["artifacts"]["minutes"]["available"]),
                "with_video": sum(1 for meeting in year_meetings if meeting["artifacts"]["video"]["available"]),
                "with_captions": sum(1 for meeting in year_meetings if meeting["artifacts"]["captions"]["available"]),
                "with_mp3": sum(1 for meeting in year_meetings if meeting["artifacts"]["mp3"]["available"]),
                "with_mp4": sum(1 for meeting in year_meetings if meeting["artifacts"]["mp4"]["available"]),
                "meeting_kinds": count_values([meeting["meeting_kind"] for meeting in year_meetings]),
            }
        )
    return summaries


def parse_archive(html: str) -> dict[str, Any]:
    upcoming_section = re.search(r'<div class="archive" id="upcoming".*?<tbody>(.*?)</tbody>', html, re.S)
    upcoming_events: list[dict[str, Any]] = []
    if upcoming_section:
        row_number = 0
        for row_html in ROW_RE.findall(upcoming_section.group(1)):
            parsed = parse_upcoming_row(row_html, row_number + 1)
            if parsed is None:
                continue
            row_number += 1
            upcoming_events.append(parsed)

    archived_meetings: list[dict[str, Any]] = []
    years_covered: set[int] = set()
    for year_text, section_html in YEAR_SECTION_RE.findall(html):
        archive_year = int(year_text)
        if archive_year < WAVE_01_FLOOR_YEAR:
            continue
        years_covered.add(archive_year)
        row_number = 0
        for row_html in ROW_RE.findall(section_html):
            parsed = parse_archive_row(row_html, archive_year, row_number + 1)
            if parsed is None:
                continue
            row_number += 1
            archived_meetings.append(parsed)

    year_summaries = build_year_summaries(archived_meetings)
    return {
        "years_covered": sorted(years_covered),
        "upcoming_event_count": len(upcoming_events),
        "archive_meeting_count": len(archived_meetings),
        "upcoming_events": upcoming_events,
        "archived_meetings": archived_meetings,
        "year_summaries": year_summaries,
        "archive_meeting_kind_counts": count_values([meeting["meeting_kind"] for meeting in archived_meetings]),
        "upcoming_meeting_kind_counts": count_values([meeting["meeting_kind"] for meeting in upcoming_events]),
        "archive_artifact_coverage": {
            "agenda": sum(1 for meeting in archived_meetings if meeting["artifacts"]["agenda"]["available"]),
            "minutes": sum(1 for meeting in archived_meetings if meeting["artifacts"]["minutes"]["available"]),
            "video": sum(1 for meeting in archived_meetings if meeting["artifacts"]["video"]["available"]),
            "captions": sum(1 for meeting in archived_meetings if meeting["artifacts"]["captions"]["available"]),
            "mp3": sum(1 for meeting in archived_meetings if meeting["artifacts"]["mp3"]["available"]),
            "mp4": sum(1 for meeting in archived_meetings if meeting["artifacts"]["mp4"]["available"]),
        },
        "notes": [
            f"Wave-01 parsing floor is {WAVE_01_FLOOR_YEAR}; the direct Granicus BOS archive already covers 2019 through the current year.",
            "The County shell page is a discovery surface only; the official Granicus publisher view is the actual archive backbone.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-date", default=datetime.now(timezone.utc).date().isoformat())
    args = parser.parse_args()

    capture_date = args.capture_date
    captured_at = utc_now_iso()
    capture_id = f"{SOURCE_ID}__{capture_date}"

    raw_dir = RAW_DIR / SOURCE_ID / capture_date
    extracted_dir = EXTRACTED_DIR / SOURCE_ID
    raw_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    html = fetch_html(ENTRY_URL)
    (raw_dir / "source.html").write_text(html)

    manifest = {
        "source_id": SOURCE_ID,
        "capture_id": capture_id,
        "captured_at": captured_at,
        "entry_url": ENTRY_URL,
        "fetch_strategy": "static_html",
        "artifacts": [
            {
                "path": "source.html",
                "content_type": "text/html",
            }
        ],
        "discovered_from_url": DISCOVERY_URL,
        "notes": [
            "Wave-01 execution capture for the Marin County Board of Supervisors direct Granicus archive.",
            "The County shell page points to this direct official publisher view for meeting agendas, minutes, and videos.",
            "This first pass captures the upcoming-events table plus archive years 2019 through the current year.",
        ],
    }
    write_json(raw_dir / "manifest.json", manifest)

    extracted = {
        "source_id": SOURCE_ID,
        "capture_id": capture_id,
        "captured_at": captured_at,
        "entry_url": ENTRY_URL,
        "discovery_url": DISCOVERY_URL,
        **parse_archive(html),
    }
    write_json(extracted_dir / f"{capture_date}.json", extracted)


if __name__ == "__main__":
    main()
