#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted"

ARCHIVE_SOURCE_ID = "san-rafael-city-council-meetings"
SOURCE_ID = "san-rafael-city-council-meeting-pages"
USER_AGENT = "Mozilla/5.0"
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
META_CONTENT_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?P<name>[^"\']+)["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
    re.I | re.S,
)
CANONICAL_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I | re.S)
ANCHOR_RE = re.compile(r"<a\b[^>]*href=(['\"])(.*?)\1[^>]*>(.*?)</a>", re.I | re.S)
IFRAME_SRC_RE = re.compile(r"<iframe\b[^>]*src=(['\"])(.*?)\1", re.I | re.S)
DATE_TIME_RE = re.compile(
    r"Date and time:\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s*([ap]\.?m\.?)",
    re.I,
)
TAB_IDS = [
    "tab-agenda",
    "tab-agenda-packet",
    "tab-minutes",
    "tab-video",
]
MEETING_KIND_SUFFIX = {
    "cancelled": "cancelled",
    "closed_session": "closed-session",
    "special": "special",
    "special_closed_session": "special-closed-session",
    "special_retreat": "special-retreat",
    "retreat": "retreat",
    "study_session": "study-session",
    "workshop": "workshop",
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


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {500, 502, 503, 504} or attempt == 3:
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


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(value).split())


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def stable_meeting_id(meeting_date: str | None, meeting_kind: str, title: str) -> str:
    if not meeting_date:
        return f"meeting-{slugify(title)}"
    base = f"meeting-{meeting_date}-san-rafael-city-council"
    suffix = MEETING_KIND_SUFFIX.get(meeting_kind)
    return f"{base}-{suffix}" if suffix else base


def stable_record_id(meeting_id: str) -> str:
    return meeting_id.replace("meeting-", "record-", 1) + "-page"


def extract_title(html: str) -> str | None:
    match = TITLE_RE.search(html)
    return strip_tags(match.group(1)) if match else None


def extract_meta_map(html: str) -> dict[str, str]:
    meta_map: dict[str, str] = {}
    for match in META_CONTENT_RE.finditer(html):
        meta_map[match.group("name").lower()] = unescape(match.group("content")).strip()
    return meta_map


def extract_canonical_url(html: str, fallback_url: str) -> str:
    match = CANONICAL_RE.search(html)
    return unescape(match.group(1)).strip() if match else fallback_url


def find_tab_sections(html: str) -> dict[str, str]:
    positions: list[tuple[int, str]] = []
    for tab_id in TAB_IDS:
        match = re.search(rf'id=["\']{re.escape(tab_id)}["\']', html, re.I)
        if match:
            positions.append((match.start(), tab_id))
    positions.sort()
    sections: dict[str, str] = {}
    for index, (start, tab_id) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(html)
        sections[tab_id] = html[start:end]
    return sections


def extract_download_url(section_html: str, base_url: str) -> str | None:
    candidates: list[str] = []
    for _, href, inner_html in ANCHOR_RE.findall(section_html):
        absolute_url = urljoin(base_url, unescape(href))
        if absolute_url.startswith("#"):
            continue
        text = strip_tags(inner_html).lower()
        if text == "download" or text.startswith("download "):
            candidates.append(absolute_url)
    return candidates[0] if candidates else None


def extract_video_url(section_html: str, base_url: str) -> str | None:
    iframe = IFRAME_SRC_RE.search(section_html)
    if iframe:
        return urljoin(base_url, unescape(iframe.group(2)))
    for _, href, inner_html in ANCHOR_RE.findall(section_html):
        absolute_url = urljoin(base_url, unescape(href))
        text = strip_tags(inner_html).lower()
        if "youtube" in absolute_url.lower() or "webinar" in text or "watch" in text:
            return absolute_url
    return None


def parse_starts_at(html: str, meta_map: dict[str, str], fallback_date: str | None) -> str | None:
    search_spaces = [meta_map.get("og:description", ""), html]
    for text in search_spaces:
        if not text:
            continue
        match = DATE_TIME_RE.search(unescape(text))
        if not match:
            continue
        date_text, time_text, am_pm = match.groups()
        naive = datetime.strptime(f"{date_text} {time_text} {am_pm.lower()}", "%Y-%m-%d %H:%M %p")
        localized = naive.replace(tzinfo=PACIFIC_TZ)
        return localized.isoformat()
    if fallback_date:
        return f"{fallback_date}T18:00:00{datetime.fromisoformat(fallback_date).replace(tzinfo=PACIFIC_TZ).strftime('%z')[:3]}:{datetime.fromisoformat(fallback_date).replace(tzinfo=PACIFIC_TZ).strftime('%z')[3:]}"
    return None


def agenda_item_marker_count(agenda_text: str) -> int:
    markers = re.findall(r"\b\d+\.[A-Za-z]\b", agenda_text)
    return len(set(markers))


def parse_page(meeting: dict[str, Any], html: str) -> dict[str, Any]:
    stable_id = stable_meeting_id(meeting.get("meeting_date"), meeting["meeting_kind"], meeting["title"])
    record_id = stable_record_id(stable_id)
    meta_map = extract_meta_map(html)
    canonical_url = extract_canonical_url(html, meeting["meeting_page_url"])
    sections = find_tab_sections(html)
    agenda_text = strip_tags(sections.get("tab-agenda", ""))
    agenda_packet_section = sections.get("tab-agenda-packet", "")
    minutes_section = sections.get("tab-minutes", "")
    video_section = sections.get("tab-video", "")

    page_payload = {
        "source_meeting_id": meeting["meeting_id"],
        "meeting_id": stable_id,
        "record_id": record_id,
        "title": meeting["title"],
        "page_title": extract_title(html),
        "meeting_page_url": canonical_url,
        "archive_meeting_page_url": meeting["meeting_page_url"],
        "meeting_date": meeting.get("meeting_date"),
        "meeting_kind": meeting["meeting_kind"],
        "flags": meeting.get("flags", []),
        "starts_at": parse_starts_at(html, meta_map, meeting.get("meeting_date")),
        "published_at": meta_map.get("article:published_time") or meta_map.get("article:published"),
        "modified_at": meta_map.get("article:modified_time"),
        "agenda_download_url": extract_download_url(sections.get("tab-agenda", ""), canonical_url),
        "agenda_packet_download_url": extract_download_url(agenda_packet_section, canonical_url),
        "minutes_download_url": extract_download_url(minutes_section, canonical_url),
        "video_url": extract_video_url(video_section, canonical_url) or meeting["artifacts"]["video"]["url"],
        "agenda_text_excerpt": agenda_text[:600] if agenda_text else None,
        "agenda_item_marker_count": agenda_item_marker_count(agenda_text),
        "artifact_availability": {
            "agenda_tab": bool(sections.get("tab-agenda")),
            "agenda_packet_tab": bool(agenda_packet_section),
            "minutes_tab": bool(minutes_section),
            "video_tab": bool(video_section),
            "agenda_pdf": bool(extract_download_url(sections.get("tab-agenda", ""), canonical_url)),
            "agenda_packet_pdf": bool(extract_download_url(agenda_packet_section, canonical_url)),
            "minutes_pdf": bool(extract_download_url(minutes_section, canonical_url)),
            "video_link": bool(extract_video_url(video_section, canonical_url) or meeting["artifacts"]["video"]["url"]),
        },
        "archive_artifacts": meeting["artifacts"],
    }
    return page_payload


def capture_one(meeting: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    html = fetch_html(meeting["meeting_page_url"])
    page_payload = parse_page(meeting, html)
    return meeting["meeting_id"], page_payload, html


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--archive-extract", default=None)
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()

    archive_extract_path = (
        Path(args.archive_extract).resolve()
        if args.archive_extract
        else latest_json(EXTRACTED_DIR / ARCHIVE_SOURCE_ID)
    )
    archive_payload = load_json(archive_extract_path)
    meetings = archive_payload["meetings"]

    capture_date = args.capture_date
    captured_at = utc_now_iso()
    capture_id = f"{SOURCE_ID}__{capture_date}"

    raw_dir = RAW_DIR / SOURCE_ID / capture_date
    pages_dir = raw_dir / "pages"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    meeting_pages: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        future_map = {executor.submit(capture_one, meeting): meeting for meeting in meetings}
        for future in as_completed(future_map):
            meeting = future_map[future]
            try:
                _, page_payload, html = future.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "source_meeting_id": meeting["meeting_id"],
                        "meeting_page_url": meeting["meeting_page_url"],
                        "error": str(exc),
                    }
                )
                continue

            html_filename = page_payload["record_id"] + ".html"
            html_path = pages_dir / html_filename
            html_path.write_text(html)
            page_payload["artifact_path"] = str(html_path.relative_to(ROOT))
            meeting_pages.append(page_payload)

    meeting_pages.sort(key=lambda item: (item.get("meeting_date") or "", item["meeting_id"]))

    extracted_payload = {
        "source_id": SOURCE_ID,
        "capture_id": capture_id,
        "captured_at": captured_at,
        "archive_extract_path": str(archive_extract_path.relative_to(ROOT)),
        "meeting_page_count": len(meeting_pages),
        "error_count": len(errors),
        "summary": {
            "years_covered": archive_payload.get("years_covered", []),
            "meeting_kind_counts": archive_payload.get("meeting_kind_counts", {}),
            "pages_with_agenda_pdf": sum(1 for page in meeting_pages if page["artifact_availability"]["agenda_pdf"]),
            "pages_with_agenda_packet_pdf": sum(
                1 for page in meeting_pages if page["artifact_availability"]["agenda_packet_pdf"]
            ),
            "pages_with_minutes_pdf": sum(1 for page in meeting_pages if page["artifact_availability"]["minutes_pdf"]),
            "pages_with_video_link": sum(1 for page in meeting_pages if page["artifact_availability"]["video_link"]),
            "pages_with_starts_at": sum(1 for page in meeting_pages if page.get("starts_at")),
            "pages_with_agenda_markers": sum(1 for page in meeting_pages if page["agenda_item_marker_count"] > 0),
        },
        "meeting_pages": meeting_pages,
        "errors": errors,
        "notes": [
            "This capture stores raw meeting-page HTML for the 2019+ San Rafael City Council archive inventory.",
            "The extracted payload preserves direct packet/minutes URLs exposed on the meeting pages without yet promoting those linked artifacts into separate Record nodes.",
            "Agenda text is extracted only as lightweight page metadata in this layer; agenda-item and vote extraction remains a later pass.",
        ],
    }

    manifest_payload = {
        "source_id": SOURCE_ID,
        "capture_id": capture_id,
        "captured_at": captured_at,
        "archive_extract_path": str(archive_extract_path.relative_to(ROOT)),
        "meeting_page_count": len(meeting_pages),
        "error_count": len(errors),
        "pages_dir": str(pages_dir.relative_to(ROOT)),
        "sample_records": [
            {
                "meeting_id": page["meeting_id"],
                "record_id": page["record_id"],
                "artifact_path": page["artifact_path"],
                "meeting_page_url": page["meeting_page_url"],
            }
            for page in meeting_pages[:10]
        ],
    }

    write_json(raw_dir / "manifest.json", manifest_payload)
    write_json(EXTRACTED_DIR / SOURCE_ID / f"{capture_date}.json", extracted_payload)


if __name__ == "__main__":
    main()
