#!/usr/bin/env python3

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "san-rafael-city-campaign-document-probe" / "2026-04-12"
EXTRACTED_PATH = (
    ROOT / "data" / "extracted" / "san-rafael-city-campaign-document-probe" / "2026-04-12.json"
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
        "label": "Kate Colin 2024 first preelection Form 460",
        "record_id": "record-san-rafael-campaign-filing-entry-37677",
    },
    {
        "entry_id": 37685,
        "label": "Rachel Kertz 2024 preelection Form 460",
        "record_id": "record-san-rafael-campaign-filing-entry-37685",
    },
    {
        "entry_id": 37365,
        "label": "Rachel Kertz 2024 semiannual Form 460",
        "record_id": "record-san-rafael-campaign-filing-entry-37365",
    },
    {
        "entry_id": 32165,
        "label": "SR Chamber of Commerce PAC supporting John Gamblin Form 496",
        "record_id": "record-san-rafael-ie-filing-entry-32165",
    },
    {
        "entry_id": 32292,
        "label": "WHINE PAC supporting Rachel Kertz Form 496",
        "record_id": "record-san-rafael-ie-filing-entry-32292",
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


class LaserficheClient:
    def __init__(self) -> None:
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.opener.open(urllib.request.Request(BASE_URL, headers=USER_AGENT), timeout=30).read()

    def get_docview(self, entry_id: int) -> dict[str, Any]:
        request = urllib.request.Request(
            BASE_URL + f"DocView.aspx?id={entry_id}&dbid=0&repo=CityofSanRafael",
            headers=USER_AGENT,
        )
        with self.opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8", "ignore")
        return {
            "status": response.status,
            "final_url": response.geturl(),
            "title": "Sign In" if "<title>Sign In</title>" in body else "",
            "login_limited": "[9030]" in body or "<title>Sign In</title>" in body,
            "body_excerpt": body[:400],
        }

    def post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            BASE_URL + endpoint,
            data=json.dumps(payload).encode(),
            headers=JSON_HEADERS,
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read().decode("utf-8", "ignore")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
            return {
                "status": response.status,
                "ok": True,
                "payload": payload,
                "body": parsed if parsed is not None else body[:1000],
            }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")
            return {
                "status": exc.code,
                "ok": False,
                "payload": payload,
                "body": body[:1000],
            }


def summarize_result(target: dict[str, Any], raw_result: dict[str, Any]) -> dict[str, Any]:
    basic = raw_result["basic_document_info"]
    basic_body = basic.get("body", {})
    basic_data = basic_body.get("data", {}) if isinstance(basic_body, dict) else {}
    return {
        "entry_id": target["entry_id"],
        "label": target["label"],
        "record_id": target["record_id"],
        "docview_status": raw_result["docview"]["status"],
        "docview_final_url": raw_result["docview"]["final_url"],
        "docview_login_limited": raw_result["docview"]["login_limited"],
        "basic_document_info_status": basic["status"],
        "basic_document_info_page_count": basic_data.get("pageCount"),
        "basic_document_info_has_imaged_pages": basic_data.get("hasImagedPages"),
        "basic_document_info_extension": basic_data.get("extension"),
        "folder_document_info_status": raw_result["folder_document_info"]["status"],
        "metadata_status": raw_result["metadata"]["status"],
        "text_page_status": raw_result["text_page"]["status"],
        "usable_public_artifact_path": not raw_result["docview"]["login_limited"]
        and basic_data.get("pageCount")
        not in (None, 0),
        "probe_outcome": "listing_only_boundary"
        if raw_result["docview"]["login_limited"]
        and raw_result["folder_document_info"]["status"] >= 500
        and raw_result["metadata"]["status"] >= 500
        else "needs_review",
    }


def main() -> None:
    client = LaserficheClient()
    captured_at = utc_now_iso()
    results = []
    for target in TARGETS:
        entry_id = target["entry_id"]
        results.append(
            {
                "entry_id": entry_id,
                "label": target["label"],
                "record_id": target["record_id"],
                "docview": client.get_docview(entry_id),
                "basic_document_info": client.post_json(
                    "DocumentService.aspx/GetBasicDocumentInfo",
                    {"repoName": "CityofSanRafael", "entryId": entry_id},
                ),
                "folder_document_info": client.post_json(
                    "FolderListingService.aspx/GetDocumentInfo",
                    {"repoName": "CityofSanRafael", "dId": entry_id},
                ),
                "metadata": client.post_json(
                    "FolderListingService.aspx/GetMetaData",
                    {"repoName": "CityofSanRafael", "entryId": entry_id},
                ),
                "text_page": client.post_json(
                    "DocumentService.aspx/GetTextHtmlForPage",
                    {
                        "repoName": "CityofSanRafael",
                        "documentId": entry_id,
                        "pageNum": 1,
                        "showAnn": False,
                        "searchUuid": "",
                    },
                ),
            }
        )

    raw_payload = {
        "captured_at": captured_at,
        "capture_date": "2026-04-12",
        "source_id": "san-rafael-city-campaign-document-probe",
        "results": results,
    }
    extracted_payload = {
        "captured_at": captured_at,
        "capture_date": "2026-04-12",
        "source_id": "san-rafael-city-campaign-document-probe",
        "summary_count": len(results),
        "probe_summaries": [summarize_result(target, result) for target, result in zip(TARGETS, results)],
        "notes": [
            "This is a methodological probe, not a filing-content extraction layer.",
            "The current public evidence boundary is stronger at folder-listing level than at raw filing-document level.",
        ],
    }
    manifest = {
        "capture_date": "2026-04-12",
        "captured_at": captured_at,
        "source_id": "san-rafael-city-campaign-document-probe",
        "artifacts": [
            {
                "path": "data/raw/san-rafael-city-campaign-document-probe/2026-04-12/results.json",
                "description": "Public document-service probe results for selected San Rafael campaign filing entry ids.",
            }
        ],
    }

    write_json(RAW_DIR / "results.json", raw_payload)
    write_json(RAW_DIR / "manifest.json", manifest)
    write_json(EXTRACTED_PATH, extracted_payload)


if __name__ == "__main__":
    main()
