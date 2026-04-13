#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import html
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from san_rafael_city_campaign_loop_lib import (
    ROOT,
    current_capture_date,
    load_batch_filing_ids,
    load_latest_captures_by_entry,
    select_targets_from_filing_ids,
    write_json,
)


RAW_BASE_DIR = ROOT / "data" / "raw" / "san-rafael-city-campaign-form460-pdf-export"
EXTRACTED_DIR = ROOT / "data" / "extracted" / "san-rafael-city-campaign-form460-pdf-export"
NORMALIZED_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-form460-pdf-01" / "bundle-01.json"
)

BASE_URL = "https://publicrecords.cityofsanrafael.org/WebLink/"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "X-Lf-Suppress-Login-Redirect": "1",
}

DEFAULT_FILING_IDS = [
    "filing-san-rafael-campaign-entry-37677",
    "filing-san-rafael-campaign-entry-37685",
    "filing-san-rafael-campaign-entry-37365",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = html.unescape(value)
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "document"


def parse_filename(content_disposition: str | None, fallback_title: str, entry_id: int) -> str:
    filename = None
    if content_disposition:
        match = re.search(r"filename\\*=UTF-8''([^;]+)", content_disposition)
        if match:
            filename = urllib.parse.unquote(match.group(1))
        else:
            match = re.search(r'filename="?([^";]+)"?', content_disposition)
            if match:
                filename = urllib.parse.unquote(match.group(1))
    if not filename:
        filename = fallback_title + ".pdf"
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".pdf"
    return f"{entry_id}-{slugify(stem)}{suffix.lower()}"


def sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


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
        with self.opener.open(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))

    def download_bytes(self, url: str) -> tuple[bytes, dict[str, str]]:
        request = urllib.request.Request(url, headers=USER_AGENT)
        with self.opener.open(request, timeout=60) as response:
            body = response.read()
            headers = {
                "content_type": response.headers.get("Content-Type", ""),
                "content_disposition": response.headers.get("Content-Disposition", ""),
                "url": response.geturl(),
            }
        return body, headers


def safe_post_json(
    client: LaserficheClient,
    endpoint: str,
    payload: dict[str, Any],
    retries: int = 2,
    delay: float = 0.75,
) -> dict[str, Any]:
    last_error = None
    for _ in range(retries):
        try:
            return client.post_json(endpoint, payload)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("safe_post_json exhausted without response")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop-manifest", type=Path)
    parser.add_argument("--batch-id")
    parser.add_argument("--target-filing-id", action="append", default=[])
    parser.add_argument("--capture-date", default=current_capture_date())
    return parser.parse_args()


def resolve_filing_ids(args: argparse.Namespace) -> list[str]:
    if args.loop_manifest and args.batch_id:
        return load_batch_filing_ids(args.loop_manifest, args.batch_id)
    if args.target_filing_id:
        return list(args.target_filing_id)
    return list(DEFAULT_FILING_IDS)


def wait_for_export(
    client: LaserficheClient,
    token: str,
    max_polls: int = 20,
    delay_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    polls: list[dict[str, Any]] = []
    for _ in range(max_polls):
        response = client.post_json("ZipEntriesHandler.aspx/CheckExportStatus", {"token": token})
        payload = response.get("data", {})
        polls.append(payload)
        if payload.get("finished"):
            return polls
        time.sleep(delay_seconds)
    raise RuntimeError(f"export timeout for token {token}")


def capture_target(
    target: dict[str, Any],
    captured_at: str,
    raw_dir: Path,
    capture_date: str,
    max_attempts: int = 5,
) -> dict[str, Any]:
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            client = LaserficheClient()
            entry_id = target["entry_id"]
            client.warm_document(entry_id)
            export_rights = safe_post_json(
                client,
                "FolderListingService.aspx/GetExportRights",
                {"repoName": "CityofSanRafael"},
                retries=3,
                delay=1.0,
            )
            start_export = safe_post_json(
                client,
                "ZipEntriesHandler.aspx/StartExport",
                {
                    "vdirName": "WebLink",
                    "repoName": "CityofSanRafael",
                    "ids": [str(entry_id)],
                    "key": -1,
                    "watermarkIdx": -1,
                },
                retries=3,
                delay=1.0,
            )
            start_payload = start_export.get("data", {})
            if start_payload.get("errorMessage"):
                raise RuntimeError(start_payload["errorMessage"])
            if start_payload.get("needAuditReason") or start_payload.get("needWatermarkSelection"):
                raise RuntimeError(f"unexpected audit/watermark prompt for {entry_id}")
            token = start_payload.get("token")
            if not token:
                raise RuntimeError(f"missing export token for {entry_id}")

            polls = wait_for_export(client, token)
            body, download_headers = client.download_bytes(
                BASE_URL + f"ExportJobHandler.aspx/GetExportJob/?token={token}"
            )
            filename = parse_filename(
                download_headers.get("content_disposition"),
                target["record_ref"]["title"],
                entry_id,
            )
            pdf_path = raw_dir / filename
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(body)

            return {
                "captured_at": captured_at,
                "capture_date": capture_date,
                "status": "captured",
                "attempt_count": attempt,
                "target": target,
                "export_rights": export_rights.get("data", {}),
                "start_export": start_payload,
                "status_polls": polls,
                "download": {
                    "artifact_path": str(pdf_path.relative_to(ROOT)),
                    "filename": filename,
                    "byte_size": len(body),
                    "sha256": sha256_bytes(body),
                    **download_headers,
                },
            }
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            time.sleep(1.0)
    return {
        "captured_at": captured_at,
        "capture_date": capture_date,
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
    target = capture["target"]
    record_ref = target["record_ref"]
    filing_candidate = target["filing_candidate"]
    return {
        "entry_id": target["entry_id"],
        "label": target["label"],
        "record_id": record_ref["id"],
        "filing_id": filing_candidate["id"],
        "source_record_id": record_ref["id"],
        "committee_ids": record_ref.get("committee_ids", []),
        "candidate_actor_ids": record_ref.get("candidate_actor_ids", []),
        "status": "captured",
        "artifact_path": capture["download"]["artifact_path"],
        "content_type": capture["download"]["content_type"],
        "content_disposition": capture["download"]["content_disposition"],
        "byte_size": capture["download"]["byte_size"],
        "sha256": capture["download"]["sha256"],
        "attempt_count": capture.get("attempt_count"),
        "export_polls": len(capture["status_polls"]),
        "export_completion": capture["status_polls"][-1].get("completion"),
    }


def build_normalized_bundle(extracted_summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    record_refs = []
    capture_candidates = []
    for capture in results:
        if capture["status"] != "captured":
            continue
        summary = summarize_capture(capture)
        target = capture["target"]
        capture_date = capture["capture_date"]
        record_refs.append(
            {
                "id": f"record-san-rafael-campaign-pdf-entry-{target['entry_id']}",
                "record_class": "financial_record",
                "record_type": "campaign_filing_pdf_capture",
                "source_id": "san-rafael-city-campaign-form460-pdf-export",
                "artifact_path": summary["artifact_path"],
                "capture_status": "captured_via_public_export_job",
                "entry_id": target["entry_id"],
                "title": target["record_ref"]["title"],
                "content_type": summary["content_type"],
                "byte_size": summary["byte_size"],
                "sha256": summary["sha256"],
                "source_record_id": target["record_ref"]["id"],
                "source_filing_id": target["filing_candidate"]["id"],
            }
        )
        capture_candidates.append(
            {
                "id": f"filing-pdf-capture-{target['entry_id']}",
                "source_filing_id": target["filing_candidate"]["id"],
                "source_record_id": target["record_ref"]["id"],
                "pdf_record_id": f"record-san-rafael-campaign-pdf-entry-{target['entry_id']}",
                "status": "captured",
                "capture_method": "doc_warm_step_plus_zip_export_job",
                "artifact_path": summary["artifact_path"],
                "export_rights_confirmed": bool(capture["export_rights"].get("hasExportRights")),
                "evidence_record_ids": [
                    target["record_ref"]["id"],
                    f"record-san-rafael-campaign-pdf-entry-{target['entry_id']}",
                ],
            }
        )
    return {
        "case_study_id": "san-rafael-city-campaign-form460-pdf-01",
        "bundle_id": "san-rafael-city-campaign-form460-pdf-01__bundle-01",
        "status": "working",
        "generated_at": extracted_summary["captured_at"],
        "scope": [
            "Selected schedule-bearing San Rafael city-side Form 460 filings captured as raw PDFs through the public Laserfiche export path",
            "Actual PDF exports for three high-value 2024 filings using StartExport, CheckExportStatus, and ExportJobHandler",
            "Raw-artifact evidence for later exact-accounting QA and stronger filing preservation",
        ],
        "record_refs": record_refs,
        "filing_capture_candidates": capture_candidates,
        "notes": [
            "This bundle proves a repeatable raw PDF export path for selected city-side campaign filings.",
            "The public export route now exists independently of the OCR capture path.",
        ],
    }


def main() -> None:
    args = parse_args()
    captured_at = utc_now_iso()
    capture_date = args.capture_date
    raw_dir = RAW_BASE_DIR / capture_date
    extracted_path = EXTRACTED_DIR / f"{capture_date}.json"

    targets = select_targets_from_filing_ids(resolve_filing_ids(args))
    results = [capture_target(target, captured_at, raw_dir, capture_date) for target in targets]

    raw_results = {
        "captured_at": captured_at,
        "capture_date": capture_date,
        "source_id": "san-rafael-city-campaign-form460-pdf-export",
        "captures": results,
    }
    write_json(raw_dir / "results.json", raw_results)

    manifest = {
        "capture_date": capture_date,
        "captured_at": captured_at,
        "source_id": "san-rafael-city-campaign-form460-pdf-export",
        "derived_from": [
            "data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json",
        ],
        "artifacts": [
            {
                "path": f"data/raw/san-rafael-city-campaign-form460-pdf-export/{capture_date}/results.json",
                "description": "Export-token workflow results and download metadata for selected San Rafael Form 460 filing PDFs.",
            },
            *[
                {
                    "path": capture["download"]["artifact_path"],
                    "description": f"Raw PDF export for entry {capture['target']['entry_id']}.",
                }
                for capture in results
                if capture["status"] == "captured"
            ],
        ],
    }
    write_json(raw_dir / "manifest.json", manifest)

    summary = {
        "captured_at": captured_at,
        "capture_date": capture_date,
        "source_id": "san-rafael-city-campaign-form460-pdf-export",
        "successful_exports": sum(1 for item in results if item["status"] == "captured"),
        "items": [summarize_capture(capture) for capture in results],
    }
    write_json(extracted_path, summary)

    aggregate_results = list(load_latest_captures_by_entry(RAW_BASE_DIR).values())
    aggregate_summary = {
        "captured_at": captured_at,
        "capture_date": capture_date,
        "source_id": "san-rafael-city-campaign-form460-pdf-export",
        "successful_exports": sum(1 for item in aggregate_results if item["status"] == "captured"),
        "items": [summarize_capture(capture) for capture in aggregate_results],
    }
    write_json(NORMALIZED_PATH, build_normalized_bundle(aggregate_summary, aggregate_results))


if __name__ == "__main__":
    main()
