#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted"
SOURCE_ID = "san-rafael-sei-netfile-portal"
ENTRY_URL = "https://public.netfile.com/pub/?AID=raf"
DISCOVERY_URLS = [
    "https://www.cityofsanrafael.org/disclosures/",
    "https://netfile.com/connect2/api/public/list/filing/rss/RAF/sei.xml",
]
USER_AGENT = "Mozilla/5.0"
DEFAULT_FLOOR_DATE = date(2019, 1, 1)
EXPORT_FILENAME = "form700-700-filers-export.xls"

INPUT_PATTERN = re.compile(
    r'<input[^>]*name="(?P<name>[^"]+)"[^>]*?(?:value="(?P<value>[^"]*)")?[^>]*>',
    re.I,
)
ROW_PATTERN = re.compile(
    r"<tr>\s*"
    r"<td>(?P<filer_name>[^<]+)</td>"
    r"<td>(?P<filed_at>\d{1,2}/\d{1,2}/\d{4})</td>"
    r"<td>(?P<statement_type>[^<]*)</td>"
    r"<td>(?P<job_title>[^<]*)</td>"
    r"<td>(?P<department>[^<]*)</td>"
    r"(?P<tail>.*?)"
    r"</tr>",
    re.I | re.S,
)
LINK_PATTERN = re.compile(r'<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<label>.*?)</a>', re.I | re.S)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_bytes(
    url: str,
    data: dict[str, str] | None = None,
    content_type: str | None = None,
) -> tuple[bytes, Any]:
    headers = {"User-Agent": USER_AGENT}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode() if data is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(), response.headers


def fetch_html(url: str, data: dict[str, str] | None = None) -> tuple[str, Any]:
    body, headers = fetch_bytes(url, data=data, content_type="application/x-www-form-urlencoded" if data else None)
    return body.decode("utf-8", "ignore"), headers


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def clean_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<.*?>", "", value)
    value = unescape(value)
    return " ".join(value.split())


def extract_inputs(html: str) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for match in INPUT_PATTERN.finditer(html):
        inputs[match.group("name")] = unescape(match.group("value") or "")
    return inputs


def build_export_form(initial_html: str, floor_date: date, ceiling_date: date) -> dict[str, str]:
    inputs = extract_inputs(initial_html)
    form = {
        key: value
        for key, value in inputs.items()
        if key.startswith("__")
        or "ClientState" in key
        or "calendar_" in key
        or "DropDown" in key
        or "searchSD" in key
        or "searchED" in key
        or "tbFilerName" in key
        or "searchJob" in key
        or "SEIDocumentListGrid" in key
        or "listExcelFormat" in key
    }
    form.update(
        {
            "ctl00$phBody$filingSearch$tbFilerName": "",
            "ctl00$phBody$filingSearch$searchJob": "",
            "ctl00$phBody$filingSearch$StatementTypeDropDown": "All",
            "ctl00$phBody$filingSearch$StatementTypeDropDown_Input": "All",
            "ctl00$phBody$filingSearch$FilerTypeDropDown": "700",
            "ctl00$phBody$filingSearch$FilerTypeDropDown_Input": "700 Filers Only",
            "ctl00$phBody$filingSearch$searchSD": floor_date.isoformat(),
            "ctl00$phBody$filingSearch$searchSD$dateInput": f"{floor_date.month}/{floor_date.day}/{floor_date.year}",
            "ctl00$phBody$filingSearch$searchED": ceiling_date.isoformat(),
            "ctl00$phBody$filingSearch$searchED$dateInput": f"{ceiling_date.month}/{ceiling_date.day}/{ceiling_date.year}",
            "ctl00$phBody$filingSearch$listExcelFormat": "2007",
            "ctl00$phBody$filingSearch$btnExportExcel2": "Export",
        }
    )
    return form


def parse_mmddyyyy(value: str) -> date:
    return datetime.strptime(value, "%m/%d/%Y").date()


def parse_links(row_tail: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in LINK_PATTERN.finditer(row_tail):
        href = urllib.parse.urljoin(ENTRY_URL, unescape(match.group("href")))
        links.append(
            {
                "url": href,
                "label": clean_text(match.group("label")),
            }
        )
    return links


def parse_export_rows(export_html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    key_counts: Counter[str] = Counter()
    for match in ROW_PATTERN.finditer(export_html):
        filed_at = parse_mmddyyyy(match.group("filed_at"))
        filer_name = clean_text(match.group("filer_name"))
        statement_type = clean_text(match.group("statement_type"))
        job_title = clean_text(match.group("job_title"))
        department = clean_text(match.group("department"))
        links = parse_links(match.group("tail"))
        base_key = (
            f"san-rafael-form700-{filed_at.isoformat()}-{slugify(filer_name)}-"
            f"{slugify(statement_type)}-{slugify(job_title)}-{slugify(department)}"
        )
        key_counts[base_key] += 1
        filing_key = base_key
        if key_counts[base_key] > 1:
            filing_key = f"{base_key}-row-{key_counts[base_key]}"
        rows.append(
            {
                "filing_key": filing_key,
                "base_filing_key": base_key,
                "filer_name": filer_name,
                "filed_at": filed_at.isoformat(),
                "statement_type": statement_type,
                "job_title": job_title,
                "department": department,
                "document_links": links,
                "document_link_count": len(links),
            }
        )
    return rows


def counter_to_sorted_dict(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


def build_summary(rows: list[dict[str, Any]], floor_date: date) -> dict[str, Any]:
    filing_dates = [date.fromisoformat(row["filed_at"]) for row in rows]
    in_scope_rows = [row for row in rows if date.fromisoformat(row["filed_at"]) >= floor_date]

    year_counts = Counter(filing_date.year for filing_date in filing_dates)
    wave_year_counts = Counter(date.fromisoformat(row["filed_at"]).year for row in in_scope_rows)
    statement_type_counts = Counter(row["statement_type"] for row in rows)
    wave_statement_type_counts = Counter(row["statement_type"] for row in in_scope_rows)
    direct_link_rows = [row for row in rows if row["document_link_count"] > 0]

    return {
        "visible_archive_start": min(filing_dates).isoformat() if filing_dates else None,
        "visible_archive_end": max(filing_dates).isoformat() if filing_dates else None,
        "full_export_row_count": len(rows),
        "wave_01_floor_date": floor_date.isoformat(),
        "wave_01_row_count": len(in_scope_rows),
        "pre_floor_row_count": len(rows) - len(in_scope_rows),
        "visible_archive_year_counts": counter_to_sorted_dict(year_counts),
        "wave_01_year_counts": counter_to_sorted_dict(wave_year_counts),
        "statement_type_counts": counter_to_sorted_dict(statement_type_counts),
        "wave_01_statement_type_counts": counter_to_sorted_dict(wave_statement_type_counts),
        "unique_filer_count": len({row["filer_name"] for row in rows}),
        "wave_01_unique_filer_count": len({row["filer_name"] for row in in_scope_rows}),
        "rows_with_direct_document_links": len(direct_link_rows),
        "rows_without_direct_document_links": len(rows) - len(direct_link_rows),
        "sample_direct_document_rows": direct_link_rows[:10],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture the San Rafael NetFile Form 700 historical backfill inventory."
    )
    parser.add_argument(
        "--capture-date",
        default=datetime.now().date().isoformat(),
        help="Capture date folder in YYYY-MM-DD format. Defaults to local today.",
    )
    parser.add_argument(
        "--floor-date",
        default=DEFAULT_FLOOR_DATE.isoformat(),
        help="Wave-01 floor date in YYYY-MM-DD format. Defaults to 2019-01-01.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    capture_date = args.capture_date
    floor_date = date.fromisoformat(args.floor_date)
    ceiling_date = datetime.now().date()
    captured_at = utc_now_iso()

    raw_dir = RAW_DIR / SOURCE_ID / capture_date
    extracted_dir = EXTRACTED_DIR / SOURCE_ID
    raw_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    source_html, _ = fetch_html(ENTRY_URL)
    (raw_dir / "source.html").write_text(source_html)

    export_form = build_export_form(source_html, floor_date, ceiling_date)
    export_bytes, export_headers = fetch_bytes(
        ENTRY_URL,
        data=export_form,
        content_type="application/x-www-form-urlencoded",
    )
    (raw_dir / EXPORT_FILENAME).write_bytes(export_bytes)
    export_html = export_bytes.decode("utf-8", "ignore")

    rows = parse_export_rows(export_html)
    summary = build_summary(rows, floor_date)

    manifest = {
        "source_id": SOURCE_ID,
        "capture_id": f"{SOURCE_ID}__{capture_date}",
        "captured_at": captured_at,
        "entry_url": ENTRY_URL,
        "fetch_strategy": "aspnet_form_post",
        "artifacts": [
            {
                "path": "source.html",
                "content_type": "text/html",
            },
            {
                "path": EXPORT_FILENAME,
                "content_type": export_headers.get_content_type(),
            },
        ],
        "discovery_urls": DISCOVERY_URLS,
        "notes": [
            "Wave-01 execution capture for San Rafael Form 700.",
            "The public NetFile surface supports an anonymous ASP.NET form-post export for 700 filers.",
            "The export currently behaves as a full visible-history inventory rather than honoring the supplied date window, so wave-01 filters to 2019-01-01 in extraction rather than at capture time.",
        ],
    }
    write_json(raw_dir / "manifest.json", manifest)

    extracted = {
        "source_id": SOURCE_ID,
        "capture_id": f"{SOURCE_ID}__{capture_date}",
        "captured_at": captured_at,
        "entry_url": ENTRY_URL,
        "floor_date": floor_date.isoformat(),
        "ceiling_date_submitted": ceiling_date.isoformat(),
        "filer_type_filter": "700 Filers Only",
        "statement_type_filter": "All",
        "export_artifact": EXPORT_FILENAME,
        "summary": summary,
        "filings": rows,
        "notes": [
            "This extraction is built from the public NetFile export response, which currently returns the full visible Form 700 history for 700 filers.",
            "Direct document URLs are only exposed for a minority of rows in the export HTML, usually amendment links; the mass historical inventory is therefore stronger than the mass direct-document layer.",
            "Wave-01 treats 2019-01-01 as the promotion floor even though the visible archive currently begins in 2018.",
        ],
    }
    write_json(extracted_dir / f"{capture_date}.json", extracted)


if __name__ == "__main__":
    main()
