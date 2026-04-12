#!/usr/bin/env python3

from __future__ import annotations

import html
import http.cookiejar
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
FILING_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-filings-01" / "bundle-01.json"
)
RAW_DIR = ROOT / "data" / "raw" / "san-rafael-city-campaign-form460-ocr" / "2026-04-12"
EXTRACTED_PATH = (
    ROOT / "data" / "extracted" / "san-rafael-city-campaign-form460-ocr" / "2026-04-12.json"
)
NORMALIZED_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-form460-ocr-01" / "bundle-01.json"
)

BASE_URL = "https://publicrecords.cityofsanrafael.org/WebLink/"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "X-Lf-Suppress-Login-Redirect": "1",
}

TARGETS = [
    {
        "entry_id": 37677,
        "record_id": "record-san-rafael-campaign-filing-entry-37677",
        "filing_id": "filing-san-rafael-campaign-entry-37677",
        "label": "Kate Colin 2024 first preelection Form 460",
    },
    {
        "entry_id": 37685,
        "record_id": "record-san-rafael-campaign-filing-entry-37685",
        "filing_id": "filing-san-rafael-campaign-entry-37685",
        "label": "Rachel Kertz 2024 preelection Form 460",
    },
    {
        "entry_id": 37365,
        "record_id": "record-san-rafael-campaign-filing-entry-37365",
        "filing_id": "filing-san-rafael-campaign-entry-37365",
        "label": "Rachel Kertz 2024 semiannual Form 460",
    },
]

SCHEDULE_PATTERN = re.compile(r"\bSchedule\s+([A-I])\b", re.IGNORECASE)
FORM_PATTERN = re.compile(r"\bForm\s+(\d+[A-Z]?)\b", re.IGNORECASE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r", "")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


class LaserficheClient:
    def __init__(self) -> None:
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.opener.open(urllib.request.Request(BASE_URL, headers=USER_AGENT), timeout=30).read()

    def warm_document(self, entry_id: int) -> None:
        request = urllib.request.Request(
            BASE_URL + f"DocView.aspx?id={entry_id}&dbid=0&repo=CityofSanRafael",
            headers=USER_AGENT,
        )
        self.opener.open(request, timeout=30).read()

    def post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            BASE_URL + endpoint,
            data=json.dumps(payload).encode(),
            headers=JSON_HEADERS,
            method="POST",
        )
        with self.opener.open(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))


def select_targets() -> list[dict[str, Any]]:
    filing_bundle = json.loads(FILING_BUNDLE_PATH.read_text())
    record_refs = {item["entry_id"]: item for item in filing_bundle["record_refs"]}
    filing_candidates = {item["record_id"]: item for item in filing_bundle["filing_candidates"]}
    targets = []
    for target in TARGETS:
        record_ref = record_refs[target["entry_id"]]
        filing_candidate = filing_candidates[target["record_id"]]
        merged = dict(target)
        merged["record_ref"] = record_ref
        merged["filing_candidate"] = filing_candidate
        targets.append(merged)
    return targets


def safe_post_json(
    client: LaserficheClient,
    endpoint: str,
    payload: dict[str, Any],
    retries: int = 1,
    delay: float = 0.75,
) -> dict[str, Any] | None:
    last_error = None
    for _ in range(retries):
        try:
            return client.post_json(endpoint, payload)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(delay)
    if last_error is not None:
        return None
    return None


def capture_target(target: dict[str, Any], max_attempts: int = 5) -> dict[str, Any]:
    last_error = None
    for attempt in range(1, max_attempts + 1):
        client = LaserficheClient()
        try:
            entry_id = target["entry_id"]
            client.warm_document(entry_id)
            metadata = safe_post_json(
                client,
                "FolderListingService.aspx/GetMetaData",
                {"repoName": "CityofSanRafael", "entryId": entry_id},
                retries=2,
            )
            document_info = safe_post_json(
                client,
                "FolderListingService.aspx/GetDocumentInfo",
                {"repoName": "CityofSanRafael", "dId": entry_id},
                retries=2,
            )
            basic_info = safe_post_json(
                client,
                "DocumentService.aspx/GetBasicDocumentInfo",
                {"repoName": "CityofSanRafael", "entryId": entry_id},
                retries=2,
            )
            page_count = (
                (basic_info or {}).get("data", {}).get("pageCount")
                or (document_info or {}).get("data", {}).get("pageCount")
                or target["record_ref"].get("page_count")
                or 0
            )
            if page_count <= 0:
                raise RuntimeError(f"page_count unavailable for {entry_id}")

            pages = []
            for page_num in range(1, page_count + 1):
                page = safe_post_json(
                    client,
                    "DocumentService.aspx/GetTextHtmlForPage",
                    {
                        "repoName": "CityofSanRafael",
                        "documentId": entry_id,
                        "pageNum": page_num,
                        "showAnn": False,
                        "searchUuid": "",
                    },
                    retries=3,
                    delay=1.0,
                )
                if page is None:
                    raise RuntimeError(f"ocr unavailable for entry {entry_id} page {page_num}")
                text = page.get("data", {}).get("text", "")
                pages.append(
                    {
                        "page_num": page_num,
                        "text": clean_text(text),
                    }
                )

            return {
                "status": "captured",
                "attempt_count": attempt,
                "target": target,
                "metadata": metadata,
                "document_info": document_info,
                "basic_info": basic_info,
                "pages": pages,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            time.sleep(1.0)
    return {
        "status": "failed",
        "attempt_count": max_attempts,
        "target": target,
        "error": last_error,
    }


def summarize_capture(capture: dict[str, Any]) -> dict[str, Any]:
    if capture["status"] != "captured":
        return {
            "entry_id": capture["target"]["entry_id"],
            "label": capture["target"]["label"],
            "status": "failed",
            "error": capture.get("error"),
        }

    metadata = (capture.get("metadata") or {}).get("data", {})
    basic = (capture.get("basic_info") or {}).get("data", {})
    pages = capture["pages"]
    combined = "\n\n".join(page["text"] for page in pages)
    schedules = sorted(
        {f"Schedule {match.group(1).upper()}" for match in SCHEDULE_PATTERN.finditer(combined)}
    )
    form_match = FORM_PATTERN.search(basic.get("name") or "")

    return {
        "entry_id": capture["target"]["entry_id"],
        "label": capture["target"]["label"],
        "record_id": capture["target"]["record_id"],
        "filing_id": capture["target"]["filing_id"],
        "status": "captured",
        "attempt_count": capture["attempt_count"],
        "title": basic.get("name"),
        "form_type": form_match.group(0) if form_match else None,
        "template_name": metadata.get("templateName"),
        "created_at": metadata.get("created"),
        "modified_at": metadata.get("modified"),
        "path": metadata.get("path"),
        "page_count": basic.get("pageCount") or len(pages),
        "available_schedules": schedules,
        "page_previews": [
            {
                "page_num": page["page_num"],
                "preview": page["text"][:240],
            }
            for page in pages[:3]
        ],
    }


def build_normalized_bundle(captures: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    filing_capture_candidates = []
    record_refs = []
    for capture in captures:
        if capture["status"] != "captured":
            continue
        target = capture["target"]
        summary = summarize_capture(capture)
        record_refs.append(
            {
                "id": f"record-san-rafael-campaign-ocr-entry-{target['entry_id']}",
                "record_class": "financial_record",
                "record_type": "campaign_filing_ocr_capture",
                "source_id": "san-rafael-city-campaign-form460-ocr",
                "artifact_path": "data/raw/san-rafael-city-campaign-form460-ocr/2026-04-12/results.json",
                "capture_status": "captured_via_doc_warm_step",
                "entry_id": target["entry_id"],
                "title": summary["title"],
                "page_count": summary["page_count"],
                "source_record_id": target["record_id"],
                "source_filing_id": target["filing_id"],
                "available_schedules": summary["available_schedules"],
            }
        )
        filing_capture_candidates.append(
            {
                "id": f"filing-capture-{target['entry_id']}",
                "source_filing_id": target["filing_id"],
                "source_record_id": target["record_id"],
                "ocr_record_id": f"record-san-rafael-campaign-ocr-entry-{target['entry_id']}",
                "status": "captured",
                "capture_method": "doc_warm_step_plus_document_service",
                "page_count": summary["page_count"],
                "available_schedules": summary["available_schedules"],
                "evidence_record_ids": [
                    target["record_id"],
                    f"record-san-rafael-campaign-ocr-entry-{target['entry_id']}",
                ],
            }
        )

    return {
        "case_study_id": "san-rafael-city-campaign-form460-ocr-01",
        "bundle_id": "san-rafael-city-campaign-form460-ocr-01__bundle-01",
        "status": "working",
        "generated_at": generated_at,
        "scope": [
            "Selected schedule-bearing San Rafael city-side Form 460 filings captured through the doc-specific warm-step path",
            "Metadata, page count, and full OCR text preservation for three high-value 2024 filings",
            "Support for later schedule extraction without claiming raw PDF export is solved",
        ],
        "record_refs": record_refs,
        "filing_capture_candidates": filing_capture_candidates,
        "notes": [
            "This bundle proves a repeatable OCR-text path for selected filings after a doc-specific warm step.",
            "It does not claim that raw PDF export or page-image download is publicly solved.",
        ],
    }


def main() -> None:
    targets = select_targets()
    captured_at = utc_now_iso()
    captures = [capture_target(target) for target in targets]

    raw_payload = {
        "captured_at": captured_at,
        "capture_date": "2026-04-12",
        "source_id": "san-rafael-city-campaign-form460-ocr",
        "captures": captures,
    }
    extracted_payload = {
        "captured_at": captured_at,
        "capture_date": "2026-04-12",
        "source_id": "san-rafael-city-campaign-form460-ocr",
        "summary_count": len(captures),
        "filing_summaries": [summarize_capture(capture) for capture in captures],
        "notes": [
            "These captures depend on a doc-specific warm step before the public document services respond correctly.",
            "The OCR path is now strong enough for selective Form 460 extraction.",
        ],
    }
    manifest = {
        "capture_date": "2026-04-12",
        "captured_at": captured_at,
        "source_id": "san-rafael-city-campaign-form460-ocr",
        "derived_from": [
            "data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json",
        ],
        "artifacts": [
            {
                "path": "data/raw/san-rafael-city-campaign-form460-ocr/2026-04-12/results.json",
                "description": "Metadata, document info, basic info, and per-page OCR text for selected San Rafael Form 460 filings.",
            }
        ],
    }

    write_json(RAW_DIR / "results.json", raw_payload)
    write_json(RAW_DIR / "manifest.json", manifest)
    write_json(EXTRACTED_PATH, extracted_payload)
    write_json(NORMALIZED_PATH, build_normalized_bundle(captures, captured_at))


if __name__ == "__main__":
    main()
