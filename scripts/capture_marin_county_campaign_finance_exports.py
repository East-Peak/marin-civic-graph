#!/usr/bin/env python3

from __future__ import annotations

import argparse
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted"
SOURCE_ID = "marin-county-campaign-finance-yearly-exports"
ENTRY_URL = "https://public.netfile.com/pub2/?aid=CMAR"
DISCOVERY_URLS = [
    "https://netfile.com/agency/cmar/",
    "https://public.netfile.com/pub2/?aid=CMAR",
]
USER_AGENT = "Mozilla/5.0"
WAVE_01_FLOOR_YEAR = 2019
EXPORT_TARGET = "ctl00$phBody$GetExcelAmend"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_bytes(url: str, data: bytes | None = None, content_type: str | None = None) -> tuple[bytes, Any]:
    headers = {"User-Agent": USER_AGENT}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(), response.headers


def fetch_html(url: str) -> str:
    body, _ = fetch_bytes(url)
    return body.decode("utf-8", "ignore")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def parse_hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
    return match.group(1) if match else ""


def parse_year_options(html: str) -> list[int]:
    years = [int(value) for value in re.findall(r'<option value="(\d{4})">', html)]
    return sorted(set(years), reverse=True)


def parse_election_labels(html: str) -> list[str]:
    labels = re.findall(r'<span class="rtIn">([^<]+)</span>', html)
    cleaned = []
    for label in labels:
        text = " ".join(label.split())
        if text:
            cleaned.append(text)
    return cleaned


def content_disposition_filename(headers: Any) -> str | None:
    disposition = headers.get("Content-Disposition")
    if not disposition:
        return None
    match = re.search(r'filename=([^;]+)', disposition)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def workbook_sheet_names(workbook_bytes: bytes) -> list[str]:
    inner = zipfile.ZipFile(io.BytesIO(workbook_bytes))
    xml = inner.read("xl/workbook.xml").decode("utf-8", "ignore")
    return re.findall(r'<sheet name="([^"]+)"', xml)


def export_for_year(html: str, year: int) -> tuple[bytes, Any]:
    form = {
        "__EVENTTARGET": EXPORT_TARGET,
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": parse_hidden(html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": parse_hidden(html, "__VIEWSTATEGENERATOR"),
        "ctl00$phBody$DateSelect": str(year),
    }
    data = urllib.parse.urlencode(form).encode()
    return fetch_bytes(ENTRY_URL, data=data, content_type="application/x-www-form-urlencoded")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--floor-year", type=int, default=WAVE_01_FLOOR_YEAR)
    args = parser.parse_args()

    capture_date = args.capture_date
    captured_at = utc_now_iso()
    raw_dir = RAW_DIR / SOURCE_ID / capture_date
    extracted_dir = EXTRACTED_DIR / SOURCE_ID
    raw_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    html = fetch_html(ENTRY_URL)
    (raw_dir / "source.html").write_text(html)

    all_years = parse_year_options(html)
    export_years = [year for year in all_years if year >= args.floor_year]
    election_labels = parse_election_labels(html)

    artifacts: list[dict[str, Any]] = [
        {
            "path": "source.html",
            "content_type": "text/html",
        }
    ]
    exports: list[dict[str, Any]] = []

    for year in export_years:
        zip_bytes, headers = export_for_year(html, year)
        zip_name = content_disposition_filename(headers) or f"{year}.zip"
        artifact_name = f"{year}-amended.zip"
        (raw_dir / artifact_name).write_bytes(zip_bytes)

        outer = zipfile.ZipFile(io.BytesIO(zip_bytes))
        workbook_name = outer.namelist()[0]
        workbook_bytes = outer.read(workbook_name)
        sheet_names = workbook_sheet_names(workbook_bytes)

        artifacts.append(
            {
                "path": artifact_name,
                "content_type": "application/zip",
                "source_year": year,
                "export_mode": "amended_only",
                "response_filename": zip_name,
            }
        )
        exports.append(
            {
                "year": year,
                "export_mode": "amended_only",
                "zip_path": artifact_name,
                "zip_filename": zip_name,
                "zip_bytes": len(zip_bytes),
                "inner_workbook_filename": workbook_name,
                "inner_workbook_bytes": len(workbook_bytes),
                "sheet_names": sheet_names,
                "sheet_count": len(sheet_names),
            }
        )

    manifest = {
        "source_id": SOURCE_ID,
        "capture_id": f"{SOURCE_ID}__{capture_date}",
        "captured_at": captured_at,
        "entry_url": ENTRY_URL,
        "fetch_strategy": "aspnet_form_post",
        "artifacts": artifacts,
        "discovery_urls": DISCOVERY_URLS,
        "notes": [
            "Wave-01 execution capture for Marin County campaign finance yearly exports.",
            "This workflow uses the public NetFile year-select export with amended-only mode.",
            "RSS remains the change feed; yearly export is the historical backfill surface.",
        ],
    }
    write_json(raw_dir / "manifest.json", manifest)

    extracted = {
        "source_id": SOURCE_ID,
        "capture_id": f"{SOURCE_ID}__{capture_date}",
        "captured_at": captured_at,
        "entry_url": ENTRY_URL,
        "backfill_floor_year": args.floor_year,
        "available_export_years": all_years,
        "captured_export_years": export_years,
        "export_mode": "amended_only",
        "postback_target": EXPORT_TARGET,
        "export_count": len(exports),
        "exports": exports,
        "election_label_count": len(election_labels),
        "election_labels": election_labels,
        "notes": [
            "The public portal also supports GetExcel (all versions), but wave-01 uses amended-only exports as the cleaner historical baseline.",
            "The yearly export dropdown currently reaches back to 1997, but wave-01 only captures 2019 and later.",
        ],
    }
    write_json(extracted_dir / f"{capture_date}.json", extracted)


if __name__ == "__main__":
    main()
