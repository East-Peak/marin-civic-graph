#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

ELECTION_PAGES = [
    {
        "source_id": "san-rafael-november-3-2020-election",
        "label": "San Rafael November 3 2020 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-3-2020-election/",
    },
    {
        "source_id": "san-rafael-november-8-2022-election",
        "label": "San Rafael November 8 2022 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-8-2022-election/",
    },
    {
        "source_id": "san-rafael-november-5-2024-election",
        "label": "San Rafael November 5 2024 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-5-2024-election/",
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def extract_title(html_text: str) -> str | None:
    match = re.search(r"<title>(.*?)</title>", html_text, re.S | re.I)
    return match.group(1).strip() if match else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture San Rafael election landing pages.")
    parser.add_argument(
        "--capture-date",
        default=datetime.now().date().isoformat(),
        help="Capture date folder in YYYY-MM-DD format. Defaults to local today.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for page in ELECTION_PAGES:
        html_text = fetch_html(page["entry_url"])
        capture_dir = RAW_DIR / page["source_id"] / args.capture_date
        capture_dir.mkdir(parents=True, exist_ok=True)
        (capture_dir / "source.html").write_text(html_text)
        write_json(
            capture_dir / "manifest.json",
            {
                "source_id": page["source_id"],
                "capture_id": f"{page['source_id']}__{args.capture_date}",
                "captured_at": utc_now_iso(),
                "entry_url": page["entry_url"],
                "fetch_strategy": "static_html",
                "artifacts": [
                    {"path": "source.html", "content_type": "text/html"},
                ],
                "notes": [
                    page["label"],
                    f"Captured title: {extract_title(html_text)}",
                ],
            },
        )
        print(page["source_id"])


if __name__ == "__main__":
    main()
