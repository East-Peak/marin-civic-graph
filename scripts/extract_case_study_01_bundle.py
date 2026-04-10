#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
EXTRACTED_DIR = ROOT / "data" / "extracted"
BUNDLE_ID = "san-rafael-homelessness-01__bundle-01"


ACTOR_PATTERNS = [
    "City of San Rafael",
    "San Rafael City Council",
    "City Manager Cristine Alilovich",
    "Cristine Alilovich",
    "John Stefanski",
    "Mel Burnette",
    "Bernadette Sullivan",
    "Lindsay Lara",
    "Robert Epstein",
    "Scott Emblidge",
    "Roy Leon",
    "Derek Johnson",
    "Christine Paquette",
    "Downtown Streets Team",
    "Defense Block Security",
    "FS Global",
    "Foege Schumann Global Disaster Solutions",
    "WeHope",
    "Other Junk Co.",
    "Ritter Center",
    "Homeward Bound",
    "St. Vincent de Paul",
    "California Homeless Union",
    "Marin County Health and Human Services",
    "Marin County Executive",
    "Marin County",
    "Cal ICH",
    "Legal Aid of Marin",
]

PLACE_PATTERNS = [
    "Mahon Creek Path",
    "Mahon Creek Path Area",
    "Mahon Creek",
    "Lindaro Street",
    "Andersen Drive",
    "Francisco Boulevard West",
    "Francisco Blvd West",
    "Albert Park",
    "Menzies Parking Lot",
    "350 Merrydale Road",
    "Lincoln Avenue",
    "Rice Drive",
    "Irwin Street",
    "Davidson Middle School",
    "Marin Academy",
]

ISSUE_PATTERNS = [
    "homelessness",
    "encampment",
    "camping ordinance",
    "sanctioned camping",
    "safe sleeping",
    "public property",
    "ERF3",
    "Encampment Resolution Fund",
    "Grants Pass",
    "Boyd",
    "Martin v. Boise",
]

LEGAL_PATTERNS = [
    r"Ordinance No\.?\s+\d+",
    r"Ordinance\s+\d+",
    r"Resolution No\.?\s+\d+",
    r"Resolution\s+\d+",
    r"ERF\d+",
    r"Grants Pass",
    r"Boyd v\. City of San Rafael",
    r"Martin v\. Boise",
]

MONEY_RE = re.compile(r"\$[0-9][0-9,]*(?:\.[0-9]{2})?")

FOCUSED_SIGNAL_STEMS = {
    "san-rafael-aug-19-2024-council-meeting": {
        "source",
        "minutes",
        "item-5a-report",
        "public-comment-gc-redacted",
        "public-comment-kf-redacted",
        "public-comment-av-redacted",
        "public-comment-jg-redacted",
        "public-comment-230-redact",
        "public-comment-ms",
        "public-comment-sl-redacted",
    }
}


def slug_stem(path: str) -> str:
    return Path(path).stem


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def keep_meaningful_link(url: str) -> bool:
    if not url.startswith("http"):
        return False
    lower = url.lower()
    if any(
        lower.endswith(ext)
        for ext in (".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".woff", ".woff2", ".xml")
    ):
        return False
    if any(
        host in lower
        for host in (
            "ajax.googleapis.com",
            "googletagmanager.com",
            "fonts.googleapis.com",
            "use.fontawesome.com",
        )
    ):
        return False
    return True


def normalize_money_values(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        cleaned = value.rstrip(",.")
        numeric = cleaned.replace("$", "").replace(",", "")
        try:
            amount = float(numeric)
        except ValueError:
            continue
        if amount < 1000:
            continue
        normalized.append(cleaned)
    return dedupe_keep_order(normalized)


class HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.in_style = False
        self.in_title = False
        self.text_chunks: list[str] = []
        self.title_chunks: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in {"script", "noscript", "style", "svg"}:
            if tag == "style":
                self.in_style = True
            else:
                self.in_script = True
        if tag == "title":
            self.in_title = True
        href = attrs_dict.get("href")
        if href:
            self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "noscript", "svg"}:
            self.in_script = False
        if tag == "style":
            self.in_style = False
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_script or self.in_style:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self.in_title:
            self.title_chunks.append(cleaned)
        self.text_chunks.append(cleaned)


def extract_article_json_ld(html: str) -> dict[str, Any]:
    matches = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for raw in matches:
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        objects: list[dict[str, Any]] = []
        if isinstance(parsed, dict):
            if isinstance(parsed.get("@graph"), list):
                objects.extend(obj for obj in parsed["@graph"] if isinstance(obj, dict))
            else:
                objects.append(parsed)
        for obj in objects:
            if obj.get("@type") == "Article":
                return obj
    return {}


def extract_html(raw_path: Path, output_txt: Path) -> dict[str, Any]:
    html = raw_path.read_text(encoding="utf-8", errors="ignore")
    parser = HtmlTextExtractor()
    parser.feed(html)
    text = unescape("\n".join(parser.text_chunks)).strip() + "\n"
    output_txt.write_text(text, encoding="utf-8")

    article_json = extract_article_json_ld(html)
    title = article_json.get("headline") or " ".join(parser.title_chunks).strip() or None
    published_at = article_json.get("datePublished")

    return {
        "artifact_type": "html",
        "title": title,
        "published_at": published_at,
        "text_path": str(output_txt.relative_to(ROOT)),
        "word_count": len(text.split()),
        "links": dedupe_keep_order([url for url in parser.links if keep_meaningful_link(url)]),
    }


def extract_pdf(raw_path: Path, output_txt: Path) -> dict[str, Any]:
    subprocess.run(
        ["pdftotext", "-layout", str(raw_path), str(output_txt)],
        check=True,
        cwd=ROOT,
    )
    text = output_txt.read_text(encoding="utf-8", errors="ignore")
    reader = PdfReader(str(raw_path))
    first_page = (reader.pages[0].extract_text() or "").strip() if reader.pages else ""

    return {
        "artifact_type": "pdf",
        "title": first_page.splitlines()[0] if first_page else None,
        "page_count": len(reader.pages),
        "text_path": str(output_txt.relative_to(ROOT)),
        "word_count": len(text.split()),
    }


def collect_signals(texts: list[str]) -> dict[str, list[str]]:
    combined = "\n".join(texts)
    money_values = normalize_money_values(MONEY_RE.findall(combined))

    actor_hits = [pattern for pattern in ACTOR_PATTERNS if pattern in combined]
    place_hits = [pattern for pattern in PLACE_PATTERNS if pattern in combined]
    issue_hits = [pattern for pattern in ISSUE_PATTERNS if pattern.lower() in combined.lower()]

    legal_refs: list[str] = []
    for pattern in LEGAL_PATTERNS:
        legal_refs.extend(re.findall(pattern, combined, flags=re.IGNORECASE))

    return {
        "money_values": money_values[:50],
        "actor_hits": dedupe_keep_order(actor_hits),
        "place_hits": dedupe_keep_order(place_hits),
        "issue_hits": dedupe_keep_order(issue_hits),
        "legal_refs": dedupe_keep_order(legal_refs),
    }


def extract_source(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_id = manifest["source_id"]
    capture_date = manifest["capture_id"].rsplit("__", 1)[-1]

    output_dir = EXTRACTED_DIR / source_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = output_dir / f"{capture_date}.json"

    artifact_outputs: list[dict[str, Any]] = []
    signal_texts: list[str] = []
    focused_stems = FOCUSED_SIGNAL_STEMS.get(source_id)

    raw_base = manifest_path.parent

    for artifact in manifest["artifacts"]:
        artifact_path = raw_base / artifact["path"]
        txt_name = f"{slug_stem(artifact['path'])}.txt"
        output_txt = output_dir / txt_name

        artifact_info: dict[str, Any] = {
            "artifact_path": str(artifact_path.relative_to(ROOT)),
            "content_type": artifact["content_type"],
        }

        if artifact["content_type"] == "text/html":
            artifact_info.update(extract_html(artifact_path, output_txt))
        elif artifact["content_type"] == "application/pdf":
            artifact_info.update(extract_pdf(artifact_path, output_txt))
        else:
            continue

        text = output_txt.read_text(encoding="utf-8", errors="ignore")
        stem = slug_stem(artifact["path"])
        if focused_stems is None or stem in focused_stems:
            signal_texts.append(text)
        artifact_outputs.append(artifact_info)

    result = {
        "source_id": source_id,
        "capture_id": manifest["capture_id"],
        "capture_date": capture_date,
        "bundle_id": manifest.get("bundle_id"),
        "entry_url": manifest["entry_url"],
        "fetch_strategy": manifest["fetch_strategy"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifact_outputs,
        "candidate_signals": collect_signals(signal_texts),
        "notes": manifest.get("notes", []),
    }

    output_json.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return result


def write_bundle_summary(results: list[dict[str, Any]]) -> None:
    summary_dir = EXTRACTED_DIR / "san-rafael-homelessness-01"
    summary_dir.mkdir(parents=True, exist_ok=True)

    all_money: list[str] = []
    all_actors: list[str] = []
    all_places: list[str] = []
    all_issues: list[str] = []
    all_legal: list[str] = []

    for result in results:
        signals = result["candidate_signals"]
        all_money.extend(signals["money_values"])
        all_actors.extend(signals["actor_hits"])
        all_places.extend(signals["place_hits"])
        all_issues.extend(signals["issue_hits"])
        all_legal.extend(signals["legal_refs"])

    summary = {
        "bundle_id": BUNDLE_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_ids": [result["source_id"] for result in results],
        "aggregate_signals": {
            "money_values": dedupe_keep_order(all_money),
            "actor_hits": dedupe_keep_order(all_actors),
            "place_hits": dedupe_keep_order(all_places),
            "issue_hits": dedupe_keep_order(all_issues),
            "legal_refs": dedupe_keep_order(all_legal),
        },
    }

    summary_path = summary_dir / "bundle-01-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    manifests = sorted(RAW_DIR.glob("*/2026-04-10/manifest.json"))
    selected = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("bundle_id") == BUNDLE_ID:
            selected.append(manifest_path)

    results = [extract_source(path) for path in selected]
    write_bundle_summary(results)


if __name__ == "__main__":
    main()
