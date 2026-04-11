#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from san_rafael_election_pages import DISCOVERY_PAGES, build_discovered_election_pages


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted" / "san-rafael-election-direct-records"
BASE_URL = "https://publicrecords.cityofsanrafael.org/WebLink/"
REPO_NAME = "CityofSanRafael"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "X-Lf-Suppress-Login-Redirect": "1",
}
DOCVIEW_LINK_PATTERN = re.compile(
    r'<a\s+href="(?P<url>https?://publicrecords\.cityofsanrafael\.org/WebLink/DocView\.aspx\?[^"]+)"[^>]*>(?P<label>.*?)</a>',
    re.I | re.S,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def read_capture(source_id: str, capture_date: str) -> str:
    path = RAW_DIR / source_id / capture_date / "source.html"
    return path.read_text()


def load_discovered_election_pages(capture_date: str) -> list[dict[str, str]]:
    discovery_html_texts = [read_capture(page["source_id"], capture_date) for page in DISCOVERY_PAGES]
    return build_discovered_election_pages(discovery_html_texts)


def entry_id_from_url(url: str) -> int | None:
    parsed = urllib.parse.urlparse(url)
    values = urllib.parse.parse_qs(parsed.query).get("id") or []
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def canonical_doc_url(url: str) -> str:
    clean = html.unescape(url).strip()
    if clean.startswith("http://"):
        clean = "https://" + clean[len("http://") :]
    parsed = urllib.parse.urlparse(clean)
    query = urllib.parse.parse_qs(parsed.query)
    entry_values = query.get("id") or []
    if not entry_values:
        return clean
    entry_id = entry_values[0]
    return (
        "https://publicrecords.cityofsanrafael.org/WebLink/"
        f"DocView.aspx?id={entry_id}&dbid=0&repo=CityofSanRafael"
    )


def clean_anchor_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<.*?>", "", value)
    value = html.unescape(value)
    return " ".join(value.split())


def extract_docview_links(html_text: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    ordered: list[dict[str, str]] = []
    for match in DOCVIEW_LINK_PATTERN.finditer(html_text):
        clean_url = canonical_doc_url(match.group("url"))
        if clean_url in seen:
            continue
        seen.add(clean_url)
        ordered.append(
            {
                "doc_url": clean_url,
                "anchor_text": clean_anchor_text(match.group("label")),
            }
        )
    return ordered


def metadata_field_map(metadata_payload: dict[str, Any]) -> dict[str, list[str]]:
    fields = {}
    for item in (metadata_payload.get("data") or {}).get("fInfo", []):
        name = item.get("name")
        if name is None:
            continue
        fields[str(name)] = [str(value) for value in (item.get("values") or [])]
    return fields


class LaserficheRecordClient:
    def __init__(self) -> None:
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.bootstrap()

    def bootstrap(self) -> None:
        self.opener.open(urllib.request.Request(BASE_URL, headers=USER_AGENT), timeout=30).read()

    def touch_doc(self, doc_url: str) -> None:
        self.opener.open(urllib.request.Request(doc_url, headers=USER_AGENT), timeout=30).read()

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            BASE_URL + path,
            data=json.dumps(payload).encode(),
            headers=JSON_HEADERS,
            method="POST",
        )
        with self.opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))

    def capture_record(self, entry_id: int, doc_url: str) -> dict[str, Any]:
        try:
            self.touch_doc(doc_url)
            metadata = self.post_json(
                "FolderListingService.aspx/GetMetaData",
                {"repoName": REPO_NAME, "entryId": entry_id},
            )
            document_info = self.post_json(
                "FolderListingService.aspx/GetDocumentInfo",
                {"repoName": REPO_NAME, "dId": entry_id},
            )
            page_count = int((document_info.get("data") or {}).get("pageCount") or 0)
            pages = []
            for page_num in range(1, page_count + 1):
                page_payload = self.post_json(
                    "DocumentService.aspx/GetTextHtmlForPage",
                    {
                        "repoName": REPO_NAME,
                        "documentId": entry_id,
                        "pageNum": page_num,
                        "showAnn": False,
                        "searchUuid": "",
                    },
                )
                page_data = page_payload.get("data") or {}
                pages.append(
                    {
                        "page_num": page_num,
                        "text": page_data.get("text"),
                    }
                )

            return {
                "entry_id": entry_id,
                "doc_url": doc_url,
                "capture_status": "captured",
                "metadata": metadata,
                "document_info": document_info,
                "pages": pages,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "entry_id": entry_id,
                "doc_url": doc_url,
                "capture_status": "error",
                "error": repr(exc),
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture direct DocView records exposed on San Rafael election pages.")
    parser.add_argument(
        "--capture-date",
        default=datetime.now().date().isoformat(),
        help="Capture date folder in YYYY-MM-DD format. Defaults to local today.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    discovered_pages = load_discovered_election_pages(args.capture_date)
    record_map: dict[int, dict[str, Any]] = {}

    for page in discovered_pages:
        html_text = read_capture(page["source_id"], args.capture_date)
        for item in extract_docview_links(html_text):
            doc_url = item["doc_url"]
            entry_id = entry_id_from_url(doc_url)
            if entry_id is None:
                continue
            record = record_map.setdefault(
                entry_id,
                {
                    "entry_id": entry_id,
                    "doc_url": doc_url,
                    "linked_from": [],
                },
            )
            record["linked_from"].append(
                {
                    "source_id": page["source_id"],
                    "entry_url": page["entry_url"],
                    "label": page["label"],
                    "anchor_text": item["anchor_text"],
                }
            )

    client = LaserficheRecordClient()
    captured_records: list[dict[str, Any]] = []
    extracted_records: list[dict[str, Any]] = []
    for entry_id in sorted(record_map):
        seed = record_map[entry_id]
        captured = client.capture_record(entry_id, seed["doc_url"])
        captured["linked_from"] = seed["linked_from"]
        captured_records.append(captured)

        metadata = captured.get("metadata") or {}
        doc_info = captured.get("document_info") or {}
        path = ((metadata.get("data") or {}).get("path") or "").strip()
        extracted_records.append(
            {
                "entry_id": entry_id,
                "doc_url": seed["doc_url"],
                "capture_status": captured.get("capture_status"),
                "error": captured.get("error"),
                "linked_from_source_ids": [item["source_id"] for item in seed["linked_from"]],
                "linked_from": seed["linked_from"],
                "path": path,
                "template_name": (metadata.get("data") or {}).get("templateName"),
                "metadata_fields": metadata_field_map(metadata),
                "page_count": (doc_info.get("data") or {}).get("pageCount"),
                "first_page_text_excerpt": ((captured.get("pages") or [{}])[0].get("text") or "")[:500],
            }
        )

    raw_dir = RAW_DIR / "san-rafael-election-direct-records" / args.capture_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        raw_dir / "records.json",
        {
            "source_id": "san-rafael-election-direct-records",
            "capture_date": args.capture_date,
            "captured_at": utc_now_iso(),
            "record_count": len(captured_records),
            "captured_record_count": sum(
                1 for item in captured_records if item.get("capture_status") == "captured"
            ),
            "error_record_count": sum(
                1 for item in captured_records if item.get("capture_status") == "error"
            ),
            "records": captured_records,
        },
    )
    write_json(
        raw_dir / "manifest.json",
        {
            "source_id": "san-rafael-election-direct-records",
            "capture_id": f"san-rafael-election-direct-records__{args.capture_date}",
            "captured_at": utc_now_iso(),
            "entry_url": "derived-from-election-pages",
            "fetch_strategy": "docview_shell_plus_json_followup",
            "artifacts": [
                {"path": "records.json", "content_type": "application/json"},
            ],
            "notes": [
                "Derived record family for direct DocView records linked from San Rafael election landing pages.",
                "Capture path is DocView page touch first, then Laserfiche JSON metadata/document-info/page-text endpoints.",
                "Some records may remain direct-link inventory only when the public Laserfiche JSON endpoints return HTTP 500 for that entry.",
            ],
        },
    )

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    write_json(
        EXTRACTED_DIR / f"{args.capture_date}.json",
        {
            "capture_date": args.capture_date,
            "captured_at": utc_now_iso(),
            "derived_from": [
                {
                    "source_id": page["source_id"],
                    "path": f"data/raw/{page['source_id']}/{args.capture_date}/source.html",
                }
                for page in discovered_pages
            ],
            "record_count": len(extracted_records),
            "captured_record_count": sum(
                1 for item in extracted_records if item.get("capture_status") == "captured"
            ),
            "error_record_count": sum(
                1 for item in extracted_records if item.get("capture_status") == "error"
            ),
            "records": extracted_records,
            "notes": [
                "This slice captures only direct DocView records that San Rafael election pages expose publicly.",
                "Candidate campaign filing folders remain a separate page-linked discovery problem; this slice does not imply folder enumeration is solved.",
                "The public page-linked record set is still useful even when JSON follow-up fails, because the election pages preserve anchor text and record URLs for those records.",
            ],
        },
    )

    print(f"Captured direct election records: {len(captured_records)}")


if __name__ == "__main__":
    main()
