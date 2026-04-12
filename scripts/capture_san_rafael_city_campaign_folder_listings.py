#!/usr/bin/env python3

from __future__ import annotations

import http.cookiejar
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DISCOVERY_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-discovery-01" / "bundle-01.json"
)
RAW_DIR = ROOT / "data" / "raw" / "san-rafael-city-campaign-folder-listings" / "2026-04-12"
EXTRACTED_PATH = (
    ROOT / "data" / "extracted" / "san-rafael-city-campaign-folder-listings" / "2026-04-12.json"
)

BASE_URL = "https://publicrecords.cityofsanrafael.org/WebLink/"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "X-Lf-Suppress-Login-Redirect": "1",
}


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

    def get_folder_listing(self, entry_id: int, end: int = 200) -> dict[str, Any]:
        payload = {
            "repoName": "CityofSanRafael",
            "folderId": entry_id,
            "getNewListing": True,
            "start": 0,
            "end": end,
            "sortColumn": None,
            "sortAscending": False,
        }
        request = urllib.request.Request(
            BASE_URL + "FolderListingService.aspx/GetFolderListing2",
            data=json.dumps(payload).encode(),
            headers=JSON_HEADERS,
            method="POST",
        )
        with self.opener.open(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))


def summarize_capture(folder_record: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data", {})
    results = data.get("results") or []
    return {
        "folder_record_id": folder_record["id"],
        "entry_id": folder_record.get("entry_id"),
        "record_type": folder_record["record_type"],
        "label": folder_record.get("label"),
        "candidate_name": folder_record.get("candidate_name"),
        "candidate_actor_ids": folder_record.get("candidate_actor_ids", []),
        "election_ids": folder_record.get("election_ids", []),
        "success": not bool(data.get("failed")),
        "folder_name": data.get("name"),
        "total_entries": data.get("totalEntries"),
        "result_count": len(results),
        "failed": data.get("failed"),
        "err_msg": data.get("errMsg"),
        "sample_document_names": [item.get("name") for item in results[:5]],
    }


def main() -> None:
    discovery_bundle = json.loads(DISCOVERY_BUNDLE_PATH.read_text())
    target_records = [
        record
        for record in discovery_bundle["record_refs"]
        if record.get("entry_id") is not None
        and record["record_type"] in {"campaign_filing_folder", "independent_expenditure_filing_folder"}
    ]

    client = LaserficheClient()
    captured_at = utc_now_iso()
    folder_captures: list[dict[str, Any]] = []
    extracted_summaries: list[dict[str, Any]] = []

    for folder_record in target_records:
        entry_id = folder_record["entry_id"]
        response = client.get_folder_listing(entry_id)
        data = response.get("data", {})
        if data.get("failed") and (data.get("totalEntries") or 0) > 0:
            response = client.get_folder_listing(entry_id, end=max(200, int(data["totalEntries"])))
        folder_captures.append(
            {
                "folder_record_id": folder_record["id"],
                "folder_record": folder_record,
                "response": response,
            }
        )
        extracted_summaries.append(summarize_capture(folder_record, response))

    raw_payload = {
        "captured_at": captured_at,
        "derived_from": str(DISCOVERY_BUNDLE_PATH.relative_to(ROOT)),
        "folder_capture_count": len(folder_captures),
        "folder_captures": folder_captures,
    }

    successful = [item for item in extracted_summaries if item["success"]]
    extracted_payload = {
        "captured_at": captured_at,
        "capture_date": "2026-04-12",
        "derived_from": [str(DISCOVERY_BUNDLE_PATH.relative_to(ROOT))],
        "target_folder_count": len(target_records),
        "successful_folder_count": len(successful),
        "failed_folder_count": len(target_records) - len(successful),
        "total_listed_documents": sum(item["result_count"] for item in successful),
        "folder_summaries": extracted_summaries,
    }

    manifest = {
        "capture_date": "2026-04-12",
        "captured_at": captured_at,
        "source_id": "san-rafael-city-campaign-folder-listings",
        "derived_from": ["data/normalized/san-rafael-city-campaign-discovery-01/bundle-01.json"],
        "artifacts": [
            {
                "path": "data/raw/san-rafael-city-campaign-folder-listings/2026-04-12/folder-listings.json",
                "description": "Anonymous Laserfiche folder-listing responses for San Rafael campaign filing folders.",
            }
        ],
    }

    write_json(RAW_DIR / "folder-listings.json", raw_payload)
    write_json(RAW_DIR / "manifest.json", manifest)
    write_json(EXTRACTED_PATH, extracted_payload)


if __name__ == "__main__":
    main()
