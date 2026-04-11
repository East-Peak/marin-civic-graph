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
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted"
SOURCE_ID = "san-rafael-city-council-meetings"
ENTRY_URL = "https://www.cityofsanrafael.org/city-council-meetings/"
USER_AGENT = "Mozilla/5.0"
WAVE_01_FLOOR = "2019-01-01"

YEAR_SECTION_RE = re.compile(
    r"(<h2[^>]*>(\d{4}) City Council Meeting Archive</h2>.*?)(?=<h2[^>]*>\d{4} City Council Meeting Archive</h2>|$)",
    re.S,
)
ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S)
ANCHOR_RE = re.compile(r"<a\b[^>]*href=(['\"])(.*?)\1[^>]*>(.*?)</a>", re.S | re.I)
DATE_RE = re.compile(r"([A-Za-z]+ \d{1,2}, \d{4})")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def page_modified_at(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']article:modified_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']dateModified["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1).strip()
    return None


def parse_meeting_date(title: str) -> str | None:
    match = DATE_RE.search(title)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def classify_meeting(title: str) -> tuple[str, list[str]]:
    title_lower = title.lower()
    flags: list[str] = []
    if "cancelled" in title_lower:
        flags.append("cancelled")
    if "revised" in title_lower:
        flags.append("revised")
    if "closed session" in title_lower:
        flags.append("closed_session")
    if "special retreat" in title_lower:
        flags.extend(["special", "retreat"])
    elif "special" in title_lower:
        flags.append("special")
    elif "retreat" in title_lower:
        flags.append("retreat")
    if "workshop" in title_lower:
        flags.append("workshop")
    if "study session" in title_lower:
        flags.append("study_session")

    if "cancelled" in flags:
        meeting_kind = "cancelled"
    elif "closed_session" in flags and "special" in flags:
        meeting_kind = "special_closed_session"
    elif "closed_session" in flags:
        meeting_kind = "closed_session"
    elif "retreat" in flags and "special" in flags:
        meeting_kind = "special_retreat"
    elif "special" in flags:
        meeting_kind = "special"
    elif "retreat" in flags:
        meeting_kind = "retreat"
    elif "workshop" in flags:
        meeting_kind = "workshop"
    elif "study_session" in flags:
        meeting_kind = "study_session"
    else:
        meeting_kind = "regular"

    return meeting_kind, sorted(set(flags))


def extract_tab_urls(row_html: str) -> dict[str, str | None]:
    tab_map = {
        "agenda": None,
        "agenda_packet": None,
        "minutes": None,
        "video": None,
    }
    for _, href, _ in ANCHOR_RE.findall(row_html):
        absolute_url = urljoin(ENTRY_URL, unescape(href))
        href_lower = absolute_url.lower()
        if "#tab-agenda-packet" in href_lower:
            tab_map["agenda_packet"] = absolute_url
        elif "#tab-agenda" in href_lower:
            tab_map["agenda"] = absolute_url
        elif "#tab-minutes" in href_lower:
            tab_map["minutes"] = absolute_url
        elif "#tab-video" in href_lower:
            tab_map["video"] = absolute_url
    return tab_map


def parse_row(row_html: str, archive_year: int, row_number: int) -> dict[str, Any] | None:
    if "<th" in row_html.lower():
        return None

    anchors = ANCHOR_RE.findall(row_html)
    if not anchors:
        return None

    _, first_href, first_text = anchors[0]
    title = strip_tags(first_text)
    if not title:
        return None

    meeting_page_url = urljoin(ENTRY_URL, unescape(first_href))
    meeting_date = parse_meeting_date(title)
    meeting_kind, flags = classify_meeting(title)
    tab_urls = extract_tab_urls(row_html)

    return {
        "meeting_id": f"meeting-{slugify(title)}",
        "archive_year": archive_year,
        "archive_row_number": row_number,
        "title": title,
        "meeting_date": meeting_date,
        "meeting_kind": meeting_kind,
        "flags": flags,
        "meeting_page_url": meeting_page_url,
        "artifacts": {
            key: {
                "available": value is not None,
                "url": value,
            }
            for key, value in tab_urls.items()
        },
    }


def build_year_summaries(meetings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for year in sorted({meeting["archive_year"] for meeting in meetings}, reverse=True):
        year_meetings = [meeting for meeting in meetings if meeting["archive_year"] == year]
        summaries.append(
            {
                "archive_year": year,
                "meeting_count": len(year_meetings),
                "with_agenda": sum(1 for meeting in year_meetings if meeting["artifacts"]["agenda"]["available"]),
                "with_packet": sum(1 for meeting in year_meetings if meeting["artifacts"]["agenda_packet"]["available"]),
                "with_minutes": sum(1 for meeting in year_meetings if meeting["artifacts"]["minutes"]["available"]),
                "with_video": sum(1 for meeting in year_meetings if meeting["artifacts"]["video"]["available"]),
                "meeting_kinds": count_values(meeting["meeting_kind"] for meeting in year_meetings),
            }
        )
    return summaries


def count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def parse_archive(html: str) -> dict[str, Any]:
    meetings: list[dict[str, Any]] = []
    discovered_years: list[int] = []
    skipped_pre_floor = 0

    for section_html, year_text in YEAR_SECTION_RE.findall(html):
        archive_year = int(year_text)
        if archive_year < 2019:
            skipped_pre_floor += 1
            continue
        discovered_years.append(archive_year)
        rows = ROW_RE.findall(section_html)
        row_number = 0
        for row_html in rows:
            parsed = parse_row(row_html, archive_year, row_number + 1)
            if parsed is None:
                continue
            row_number += 1
            meetings.append(parsed)

    return {
        "years_covered": sorted(discovered_years),
        "meeting_count": len(meetings),
        "meetings": meetings,
        "year_summaries": build_year_summaries(meetings),
        "meeting_kind_counts": count_values(meeting["meeting_kind"] for meeting in meetings),
        "artifact_coverage": {
            "agenda": sum(1 for meeting in meetings if meeting["artifacts"]["agenda"]["available"]),
            "agenda_packet": sum(1 for meeting in meetings if meeting["artifacts"]["agenda_packet"]["available"]),
            "minutes": sum(1 for meeting in meetings if meeting["artifacts"]["minutes"]["available"]),
            "video": sum(1 for meeting in meetings if meeting["artifacts"]["video"]["available"]),
        },
        "notes": [
            f"Wave-01 parsing floor is {WAVE_01_FLOOR}; the archive page already covers 2019 through the current year on one static page.",
            "Videos before 2019 are referenced by the archive page as living in a separate public portal and were not included in this first backfill execution.",
        ],
        "skipped_year_sections_before_floor": skipped_pre_floor,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


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
        "notes": [
            "Wave-01 execution capture for the San Rafael City Council archive page.",
            "Archive page contains inline year sections for 2019 through the current year.",
            "Videos before 2019 are referenced as living in a separate public portal and stay out of scope for this first pass.",
        ],
    }
    write_json(raw_dir / "manifest.json", manifest)

    parsed = parse_archive(html)
    extracted = {
        "source_id": SOURCE_ID,
        "capture_id": capture_id,
        "captured_at": captured_at,
        "entry_url": ENTRY_URL,
        "page_modified_at": page_modified_at(html),
        **parsed,
    }
    write_json(extracted_dir / f"{capture_date}.json", extracted)


if __name__ == "__main__":
    main()
