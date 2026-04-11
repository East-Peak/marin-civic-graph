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
EXTRACTED_DIR = ROOT / "data" / "extracted" / "san-rafael-city-side-campaign-filings"

BASE_URL = "https://publicrecords.cityofsanrafael.org/WebLink/"
REPO_NAME = "CityofSanRafael"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "X-Lf-Suppress-Login-Redirect": "1",
}

DISCLOSURES_SOURCE_ID = "san-rafael-disclosures"

TOP_LEVEL_LABELS = {
    "View Financial Filings": "san-rafael-public-records-financial-filings-folder",
    "View Independent Expenditures Filings": "san-rafael-public-records-independent-expenditures-folder",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def clean_html_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<.*?>", "", value)
    value = html.unescape(value)
    return " ".join(value.split())


def entry_id_from_url(url: str) -> int | None:
    parsed = urllib.parse.urlparse(url)
    values = urllib.parse.parse_qs(parsed.query).get("id") or []
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def read_capture(source_id: str, capture_date: str) -> str:
    path = RAW_DIR / source_id / capture_date / "source.html"
    return path.read_text()


def load_discovered_election_pages(capture_date: str) -> list[dict[str, str]]:
    discovery_html_texts = [read_capture(page["source_id"], capture_date) for page in DISCOVERY_PAGES]
    return build_discovered_election_pages(discovery_html_texts)


def extract_top_level_destinations(disclosures_html: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'<a href="(?P<url>https://publicrecords\.cityofsanrafael\.org/WebLink/Browse\.aspx\?id=\d+[^"]*)"[^>]*>\s*'
        r'(?:.|\n)*?<div class="h4">(?P<label>[^<]+)</div>',
        re.I,
    )
    results: list[dict[str, Any]] = []
    for match in pattern.finditer(disclosures_html):
        label = clean_html_text(match.group("label"))
        source_id = TOP_LEVEL_LABELS.get(label)
        if source_id is None:
            continue
        url = html.unescape(match.group("url"))
        results.append(
            {
                "source_id": source_id,
                "label": label,
                "folder_url": url,
                "folder_entry_id": entry_id_from_url(url),
            }
        )
    return results


def extract_campaign_folder_inventory(
    election_html: str, source_id: str, election_label: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    section_label: str | None = None
    office_label: str | None = None
    lines = election_html.splitlines()
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        if section_match := re.search(
            r"<h[23]>(City of San Rafael Election|San Rafael City Schools|Board of Education Election)</h[23]>",
            line,
            re.I,
        ):
            section_label = clean_html_text(section_match.group(1))
        elif office_match := re.search(r"<h4>(.*?)</h4>", line, re.I):
            office_label = clean_html_text(office_match.group(1))
        elif "<p" in line:
            block_lines = [line]
            while idx + 1 < len(lines) and "</p>" not in lines[idx]:
                idx += 1
                block_lines.append(lines[idx])
            block = "\n".join(block_lines)
            if "Campaign Finance Documents" in block:
                name_match = re.search(
                    r"<(?:strong|b)>(?P<name>.*?)(?:<br\s*/?>)?\s*</(?:strong|b)>",
                    block,
                    re.S | re.I,
                )
                url_match = re.search(
                    r'href="(?P<url>https://publicrecords\.cityofsanrafael\.org/WebLink/Browse\.aspx\?id=\d+[^"]*)"[^>]*>Campaign Finance Documents</a>',
                    block,
                    re.S | re.I,
                )
                if name_match and url_match:
                    candidate_name = clean_html_text(name_match.group("name"))
                    folder_url = html.unescape(url_match.group("url"))
                    results.append(
                        {
                            "source_id": source_id,
                            "election_label": election_label,
                            "section_label": section_label,
                            "office_label": office_label,
                            "candidate_name": candidate_name,
                            "folder_url": folder_url,
                            "folder_entry_id": entry_id_from_url(folder_url),
                        }
                    )
        idx += 1

    return results


def extract_ie_resource(
    election_html: str, source_id: str, election_label: str
) -> dict[str, Any] | None:
    match = re.search(
        r'<a href="(?P<url>https?://publicrecords\.cityofsanrafael\.org/WebLink/DocView\.aspx\?id=\d+[^"]*)">'
        r"(?P<label>City of San Rafael\s*Independent Expenditure Ordinance)</a>",
        election_html,
        re.S | re.I,
    )
    if not match:
        return None
    url = html.unescape(match.group("url"))
    return {
        "source_id": source_id,
        "election_label": election_label,
        "label": clean_html_text(match.group("label")),
        "record_url": url,
        "record_entry_id": entry_id_from_url(url),
    }


def extract_ie_filing_folder(
    election_html: str, source_id: str, election_label: str
) -> dict[str, Any] | None:
    lines = election_html.splitlines()
    for idx, line in enumerate(lines):
        if "Independent Expenditure Filings" not in line:
            continue
        label = clean_html_text(line)
        for back in range(max(0, idx - 6), idx + 1):
            url_match = re.search(
                r'href="(?P<url>https?://publicrecords\.cityofsanrafael\.org/WebLink/Browse\.aspx\?id=\d+[^"]*)"',
                lines[back],
                re.I,
            )
            if url_match:
                url = html.unescape(url_match.group("url"))
                return {
                    "source_id": source_id,
                    "election_label": election_label,
                    "label": label,
                    "folder_url": url,
                    "folder_entry_id": entry_id_from_url(url),
                }
    return None


def extract_election_level_campaign_folder(
    election_html: str, source_id: str, election_label: str
) -> dict[str, Any] | None:
    lines = election_html.splitlines()
    labels = {
        "Campaign Finance Disclosure",
        "Campaign Finance Disclosures",
        "Campaign Finance Reporting",
        "Financial Filings",
    }
    for idx, line in enumerate(lines):
        clean = clean_html_text(line)
        if clean not in labels:
            continue
        for back in range(max(0, idx - 6), idx + 1):
            url_match = re.search(
                r'href="(?P<url>https?://publicrecords\.cityofsanrafael\.org/WebLink/Browse\.aspx\?id=\d+[^"]*)"',
                lines[back],
                re.I,
            )
            if url_match:
                url = html.unescape(url_match.group("url"))
                return {
                    "source_id": source_id,
                    "election_label": election_label,
                    "label": clean,
                    "folder_url": url,
                    "folder_entry_id": entry_id_from_url(url),
                }
    return None


class LaserficheProbeClient:
    def __init__(self) -> None:
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.opener.open(urllib.request.Request(BASE_URL, headers=USER_AGENT), timeout=20).read()

    def probe_folder_listing(self, entry_id: int) -> dict[str, Any]:
        payload = {
            "repoName": REPO_NAME,
            "entryId": entry_id,
            "startRow": 0,
            "endRow": 25,
            "sortColumn": None,
            "sortDirection": 0,
            "getNewListing": True,
            "displayInGridView": True,
        }
        request = urllib.request.Request(
            BASE_URL + "FolderListingService.aspx/GetFolderListing",
            data=json.dumps(payload).encode(),
            headers=JSON_HEADERS,
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read().decode("utf-8", "ignore")
            parsed = json.loads(raw)
            data = parsed.get("data") or {}
            return {
                "status": "ok",
                "request_payload": payload,
                "response": parsed,
                "failed": bool(data.get("failed")),
                "error_message": data.get("errMsg"),
                "total_entries": data.get("totalEntries"),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "request_payload": payload,
                "error": repr(exc),
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a derived inventory for San Rafael city-side campaign filing destinations."
    )
    parser.add_argument(
        "--capture-date",
        default=datetime.now().date().isoformat(),
        help="Capture date folder in YYYY-MM-DD format. Defaults to local today.",
    )
    parser.add_argument(
        "--skip-probes",
        action="store_true",
        help="Skip Laserfiche folder-listing probes and reuse existing raw probe captures.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    disclosures_html = read_capture(DISCLOSURES_SOURCE_ID, args.capture_date)
    top_level_destinations = extract_top_level_destinations(disclosures_html)
    discovered_pages = load_discovered_election_pages(args.capture_date)
    candidate_folders: list[dict[str, Any]] = []
    ie_resources: list[dict[str, Any]] = []
    ie_filing_folders: list[dict[str, Any]] = []
    election_level_campaign_folders: list[dict[str, Any]] = []
    campaign_page_inventory: list[dict[str, Any]] = []
    derived_from = [
        {
            "source_id": DISCLOSURES_SOURCE_ID,
            "path": f"data/raw/{DISCLOSURES_SOURCE_ID}/{args.capture_date}/source.html",
        }
    ]
    for page in DISCOVERY_PAGES:
        derived_from.append(
            {
                "source_id": page["source_id"],
                "path": f"data/raw/{page['source_id']}/{args.capture_date}/source.html",
            }
        )

    for page in discovered_pages:
        source_id = page["source_id"]
        election_html = read_capture(source_id, args.capture_date)
        match = re.search(r"<title>(.*?)</title>", election_html, re.S | re.I)
        election_label = clean_html_text(match.group(1)) if match else source_id
        derived_from.append(
            {
                "source_id": source_id,
                "path": f"data/raw/{source_id}/{args.capture_date}/source.html",
            }
        )
        page_candidate_folders = extract_campaign_folder_inventory(election_html, source_id, election_label)
        candidate_folders.extend(page_candidate_folders)
        ie_resource = extract_ie_resource(election_html, source_id, election_label)
        if ie_resource is not None:
            ie_resources.append(ie_resource)
        ie_filing_folder = extract_ie_filing_folder(election_html, source_id, election_label)
        if ie_filing_folder is not None:
            ie_filing_folders.append(ie_filing_folder)
        election_level_campaign_folder = extract_election_level_campaign_folder(
            election_html, source_id, election_label
        )
        if election_level_campaign_folder is not None:
            election_level_campaign_folders.append(election_level_campaign_folder)
        campaign_page_inventory.append(
            {
                "source_id": source_id,
                "entry_url": page["entry_url"],
                "election_label": election_label,
                "candidate_folder_count": len(page_candidate_folders),
                "has_election_level_campaign_folder": election_level_campaign_folder is not None,
                "has_independent_expenditure_resource": ie_resource is not None,
                "has_independent_expenditure_filing_folder": ie_filing_folder is not None,
                "campaign_signal_kind": (
                    "candidate_folders"
                    if page_candidate_folders
                    else "election_level_folder"
                    if election_level_campaign_folder is not None
                    else "none"
                ),
            }
        )

    top_level_probes: list[dict[str, Any]] = []
    sample_child_probe = None
    if args.skip_probes:
        for item in top_level_destinations:
            probe_path = RAW_DIR / item["source_id"] / args.capture_date / "folder-probe.json"
            if probe_path.exists():
                top_level_probes.append(
                    {
                        "source_id": item["source_id"],
                        "folder_entry_id": item.get("folder_entry_id"),
                        "probe": json.loads(probe_path.read_text()),
                    }
                )
        sample_child_path = EXTRACTED_DIR / f"{args.capture_date}.json"
        if sample_child_path.exists():
            prior_payload = json.loads(sample_child_path.read_text())
            sample_child_probe = prior_payload.get("sample_child_folder_probe")
    else:
        probe_client = LaserficheProbeClient()
        for item in top_level_destinations:
            entry_id = item.get("folder_entry_id")
            if entry_id is None:
                continue
            probe = probe_client.probe_folder_listing(entry_id)
            top_level_probes.append(
                {
                    "source_id": item["source_id"],
                    "folder_entry_id": entry_id,
                    "probe": probe,
                }
            )

            raw_dir = RAW_DIR / item["source_id"] / args.capture_date
            raw_dir.mkdir(parents=True, exist_ok=True)
            write_json(raw_dir / "folder-probe.json", probe)
            write_json(
                raw_dir / "manifest.json",
                {
                    "source_id": item["source_id"],
                    "capture_id": f"{item['source_id']}__{args.capture_date}",
                    "captured_at": utc_now_iso(),
                    "entry_url": item["folder_url"],
                    "fetch_strategy": "cookie_aware_json",
                    "artifacts": [
                        {"path": "folder-probe.json", "content_type": "application/json"},
                    ],
                    "notes": [
                        "Top-level public-records folder linked from the San Rafael disclosures page.",
                        "Probe captures whether the anonymous Laserfiche folder-listing JSON endpoint yields usable entries or an access/session failure.",
                    ],
                },
            )

        if candidate_folders and candidate_folders[0].get("folder_entry_id") is not None:
            sample = candidate_folders[0]
            sample_child_probe = {
                "candidate_name": sample["candidate_name"],
                "office_label": sample["office_label"],
                "folder_entry_id": sample["folder_entry_id"],
                "probe": probe_client.probe_folder_listing(sample["folder_entry_id"]),
            }

    if sample_child_probe is None and candidate_folders and candidate_folders[0].get("folder_entry_id") is not None:
        sample = candidate_folders[0]
        sample_child_probe = {
            "candidate_name": sample["candidate_name"],
            "office_label": sample["office_label"],
            "folder_entry_id": sample["folder_entry_id"],
            "probe": {
                "status": "skipped",
                "note": "Reused prior extracted sample-child probe because this run skipped live probes.",
            },
        }

    payload = {
        "capture_date": args.capture_date,
        "captured_at": utc_now_iso(),
        "derived_from": derived_from,
        "discovered_election_pages": discovered_pages,
        "election_page_inventory": campaign_page_inventory,
        "election_page_count": len(discovered_pages),
        "campaign_bearing_election_page_count": sum(
            1 for page in campaign_page_inventory if page["campaign_signal_kind"] != "none"
        ),
        "top_level_destinations": top_level_destinations,
        "top_level_folder_probes": top_level_probes,
        "candidate_folder_inventory": candidate_folders,
        "candidate_folder_count": len(candidate_folders),
        "election_level_campaign_filing_folders": election_level_campaign_folders,
        "election_level_campaign_filing_folder_count": len(election_level_campaign_folders),
        "independent_expenditure_resources": ie_resources,
        "independent_expenditure_filing_folders": ie_filing_folders,
        "independent_expenditure_filing_folder_count": len(ie_filing_folders),
        "sample_child_folder_probe": sample_child_probe,
        "notes": [
            "San Rafael city-side campaign filings are publicly routed through the disclosures page plus the city's own elections index pages.",
            "The current discovery backbone is `elections` and `past-elections`, which expose election landing pages from 2010 through 2026.",
            "Campaign-bearing pages currently include the June 7, 2016 page, the November 2011 through 2018 pages, and the November 2020 through 2024 pages. The June 8, 2010, November 2, 2010, June 5, 2018 special, and June 2, 2026 special pages do not currently expose campaign-filing destinations.",
            "The 2011 through 2018 election pages plus the June 7, 2016 page expose election-level campaign-finance filing folders, while the 2020, 2022, and 2024 election pages expose candidate-specific campaign-finance folder IDs.",
            "Until Laserfiche folder enumeration becomes reliably accessible, the safest backfill strategy is page-linked folder discovery plus record-level capture where direct document links are exposed.",
        ],
    }

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    write_json(EXTRACTED_DIR / f"{args.capture_date}.json", payload)

    print(f"Top-level destinations: {len(top_level_destinations)}")
    print(f"Candidate folders: {len(candidate_folders)}")
    if sample_child_probe is not None:
        print(
            "Sample child probe:",
            sample_child_probe["candidate_name"],
            sample_child_probe["probe"].get("status"),
        )


if __name__ == "__main__":
    main()
