#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
BASE_URL = "https://publicrecords.cityofsanrafael.org/WebLink/"
REPO_NAME = "CityofSanRafael"
SEARCH_SOURCE_ID = "san-rafael-public-records-form-803-search"
DEFAULT_TERMS = [
    '"Form 803"',
    '"Form 803 -"',
    '"Behested Payment Report"',
    "behested payment",
    "behested",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def parse_mmddyyyy(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_form_no(metadata_items: list[dict[str, Any]]) -> str | None:
    for item in metadata_items:
        if item.get("name") == "Form No.":
            values = item.get("values") or []
            if values:
                return str(values[0]).strip()
    return None


def is_form_803_result(item: dict[str, Any]) -> bool:
    form_no = extract_form_no(item.get("metadata") or [])
    if form_no == "Form 803":
        return True
    return str(item.get("name") or "").lower().startswith("form 803")


def filer_name_from_title(title: str) -> str:
    if " - " in title:
        return title.split(" - ", 1)[1].strip()
    return title.strip()


def signed_date_from_text(text: str) -> str | None:
    match = re.search(r"\n(\d{1,2}/\d{1,2}/\d{4})\s*\nExecuted on", text)
    if match:
        return parse_mmddyyyy(match.group(1))
    return None


def summarize_result(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data") or []
    return {
        "entry_id": item.get("entryId"),
        "name": item.get("name"),
        "entry_properties": item.get("entryProperties"),
        "template_name": data[2] if len(data) > 2 else None,
        "form_no": extract_form_no(item.get("metadata") or []),
    }


class LaserficheClient:
    def __init__(self) -> None:
        self.user_agent = {"User-Agent": "Mozilla/5.0"}
        self.json_headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "X-Lf-Suppress-Login-Redirect": "1",
        }
        self._reset_session()

    def _reset_session(self) -> None:
        last_error: Exception | None = None
        for attempt in range(5):
            self.cookie_jar = http.cookiejar.CookieJar()
            self.opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self.cookie_jar)
            )
            try:
                self.opener.open(
                    urllib.request.Request(BASE_URL, headers=self.user_agent),
                    timeout=30,
                ).read()
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(1)

        assert last_error is not None
        raise last_error

    def post_json(self, path: str, payload: dict[str, Any], retries: int = 5) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(retries):
            if attempt:
                time.sleep(1)
                self._reset_session()
            try:
                req = urllib.request.Request(
                    BASE_URL + path,
                    data=json.dumps(payload).encode(),
                    headers=self.json_headers,
                    method="POST",
                )
                with self.opener.open(req, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8", "ignore"))
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        assert last_error is not None
        raise last_error

    def search(self, term: str) -> dict[str, Any]:
        last_error: Exception | None = None
        payload = {
            "repoName": REPO_NAME,
            "searchSyn": term,
            "searchUuid": None,
            "sortColumn": None,
            "startIdx": 0,
            "endIdx": 50,
            "getNewListing": True,
            "sortOrder": 0,
            "displayInGridView": True,
        }
        for attempt in range(8):
            if attempt:
                time.sleep(1)
            self._reset_session()
            try:
                try:
                    rights_req = urllib.request.Request(
                        BASE_URL + "SearchService.aspx/HasSearchRights",
                        data=json.dumps({"repoName": REPO_NAME}).encode(),
                        headers=self.json_headers,
                        method="POST",
                    )
                    self.opener.open(rights_req, timeout=30).read()
                except Exception:  # noqa: BLE001
                    pass
                req = urllib.request.Request(
                    BASE_URL + "SearchService.aspx/GetSearchListing",
                    data=json.dumps(payload).encode(),
                    headers=self.json_headers,
                    method="POST",
                )
                with self.opener.open(req, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8", "ignore"))
            except Exception as exc:  # noqa: BLE001
                last_error = exc

        assert last_error is not None
        raise last_error

    def metadata(self, entry_id: int) -> dict[str, Any]:
        return self.post_json(
            "FolderListingService.aspx/GetMetaData",
            {"repoName": REPO_NAME, "entryId": entry_id},
        )

    def document_info(self, entry_id: int) -> dict[str, Any]:
        return self.post_json(
            "FolderListingService.aspx/GetDocumentInfo",
            {"repoName": REPO_NAME, "dId": entry_id},
        )

    def page_text(self, entry_id: int, page_num: int) -> dict[str, Any]:
        return self.post_json(
            "DocumentService.aspx/GetTextHtmlForPage",
            {
                "repoName": REPO_NAME,
                "documentId": entry_id,
                "pageNum": page_num,
                "showAnn": False,
                "searchUuid": "",
            },
        )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(scrub_volatile_fields(payload), indent=2) + "\n")


def scrub_volatile_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: scrub_volatile_fields(child)
            for key, child in value.items()
            if key not in {"__breach", "searchUUID"}
        }
    if isinstance(value, list):
        return [scrub_volatile_fields(item) for item in value]
    return value


def capture_search_census(client: LaserficheClient, capture_date: str) -> tuple[Path, dict[str, Any], dict[int, dict[str, Any]]]:
    search_dir = RAW_DIR / SEARCH_SOURCE_ID / capture_date
    search_dir.mkdir(parents=True, exist_ok=True)

    term_summaries: list[dict[str, Any]] = []
    discovered: dict[int, dict[str, Any]] = {}
    primary_payload: dict[str, Any] | None = None

    for idx, term in enumerate(DEFAULT_TERMS):
        try:
            payload = client.search(term)
            if idx == 0:
                primary_payload = payload
                write_json(search_dir / "search-results.json", payload)
            elif primary_payload is None:
                primary_payload = payload

            results = payload.get("data", {}).get("results", [])
            for item in results:
                if is_form_803_result(item):
                    discovered[int(item["entryId"])] = item

            term_summaries.append(
                {
                    "term": term,
                    "result_count": len(results),
                    "top_results": [summarize_result(item) for item in results[:10]],
                    "form_803_entry_ids": [
                        int(item["entryId"]) for item in results if is_form_803_result(item)
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001
            term_summaries.append(
                {
                    "term": term,
                    "result_count": None,
                    "top_results": [],
                    "form_803_entry_ids": [],
                    "error": repr(exc),
                }
            )

    summary_payload = {
        "source_id": SEARCH_SOURCE_ID,
        "captured_at": utc_now_iso(),
        "capture_date": capture_date,
        "terms": term_summaries,
        "discovered_form_803_records": [
            summarize_result(item) for _, item in sorted(discovered.items())
        ],
    }
    write_json(search_dir / "search-summary.json", summary_payload)

    if primary_payload is None:
        primary_payload = {
            "capture_error": "No discovery term completed successfully during this run.",
            "data": {"command": DEFAULT_TERMS[0], "results": []},
        }
        write_json(search_dir / "search-results.json", primary_payload)

    manifest = {
        "source_id": SEARCH_SOURCE_ID,
        "capture_id": f"{SEARCH_SOURCE_ID}__{capture_date}",
        "bundle_id": "campaign-finance-form-803-slice-01__bundle-01",
        "captured_at": utc_now_iso(),
        "entry_url": BASE_URL,
        "fetch_strategy": "cookie_aware_json",
        "artifacts": [
            {"path": "search-results.json", "content_type": "application/json"},
            {"path": "search-summary.json", "content_type": "application/json"},
        ],
        "notes": [
            "Public Laserfiche search backend used to query the San Rafael public-records corpus for Form 803 and behested-payment terms.",
            f"Current discovery census found {len(discovered)} actual Form 803 record(s).",
        ],
    }
    write_json(search_dir / "manifest.json", manifest)

    assert primary_payload is not None
    return search_dir, primary_payload, discovered


def capture_record(client: LaserficheClient, capture_date: str, item: dict[str, Any]) -> Path:
    entry_id = int(item["entryId"])
    title = str(item["name"])
    filer_name = filer_name_from_title(title)

    metadata_payload = client.metadata(entry_id)
    document_info_payload = client.document_info(entry_id)
    page_count = max(
        int(document_info_payload.get("data", {}).get("pageCount") or 0),
        int(item.get("thumbnailPageCount") or 0),
        1,
    )

    page_payloads: list[tuple[int, dict[str, Any]]] = []
    combined_text_parts: list[str] = []
    for page_num in range(1, page_count + 1):
        payload = client.page_text(entry_id, page_num)
        page_payloads.append((page_num, payload))
        combined_text_parts.append(str(payload.get("data", {}).get("text") or "").strip())

    combined_text = "\n\n".join(part for part in combined_text_parts if part)
    signed_date = signed_date_from_text(combined_text)
    if signed_date is None:
        created = str(metadata_payload.get("data", {}).get("created") or "")
        parsed_created = parse_mmddyyyy(created.split(" ")[0]) if created else None
        signed_date = parsed_created or "unknown-date"

    record_dir_name = f"san-rafael-{slugify(filer_name)}-form-803-{signed_date}"
    record_dir = RAW_DIR / record_dir_name / capture_date
    record_dir.mkdir(parents=True, exist_ok=True)

    write_json(record_dir / "metadata.json", metadata_payload)
    write_json(record_dir / "document-info.json", document_info_payload)
    for page_num, payload in page_payloads:
        write_json(record_dir / f"page-{page_num}-text.json", payload)
    (record_dir / "source.txt").write_text(combined_text.replace("\r\n", "\n").strip() + "\n")

    manifest = {
        "source_id": f"{record_dir_name}-{signed_date}" if record_dir_name.endswith("unknown-date") else record_dir_name,
        "capture_id": f"{record_dir_name}__{capture_date}",
        "bundle_id": "campaign-finance-form-803-slice-01__bundle-01",
        "captured_at": utc_now_iso(),
        "entry_url": f"{BASE_URL}DocView.aspx?id={entry_id}&dbid=0&repo={REPO_NAME}",
        "fetch_strategy": "cookie_aware_json",
        "artifacts": [
            {"path": "metadata.json", "content_type": "application/json"},
            {"path": "document-info.json", "content_type": "application/json"},
            *[
                {"path": f"page-{page_num}-text.json", "content_type": "application/json"}
                for page_num, _ in page_payloads
            ],
            {"path": "source.txt", "content_type": "text/plain"},
        ],
        "notes": [
            f"Official San Rafael public-records entry `{title}`.",
            "Metadata and OCR page text captured through Laserfiche JSON endpoints after establishing an anonymous public session.",
        ],
    }
    write_json(record_dir / "manifest.json", manifest)
    return record_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture San Rafael public-records Form 803 search results and discovered filings."
    )
    parser.add_argument(
        "--capture-date",
        default=datetime.now().date().isoformat(),
        help="Capture date folder in YYYY-MM-DD format. Defaults to local today.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = LaserficheClient()
    _, _, discovered = capture_search_census(client, args.capture_date)
    captured_dirs = [capture_record(client, args.capture_date, item) for _, item in sorted(discovered.items())]

    print(f"Captured {len(discovered)} Form 803 record(s) for {args.capture_date}.")
    for path in captured_dirs:
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
