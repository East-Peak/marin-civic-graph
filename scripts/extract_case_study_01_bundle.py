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
NORMALIZED_DIR = ROOT / "data" / "normalized"
BUNDLE_ID = "san-rafael-homelessness-01__bundle-01"
CASE_STUDY_ID = "san-rafael-homelessness-01"
ITEM_5A_SOURCE_ID = "san-rafael-aug-19-2024-council-meeting"
ITEM_5A_SOURCE_RECORD_ID = "doc-2024-08-19-item-5a-report"
ITEM_5A_RAW_PDF = RAW_DIR / ITEM_5A_SOURCE_ID / "2026-04-10" / "item-5a-report.pdf"
ITEM_5A_EXTRACTED_DIR = EXTRACTED_DIR / ITEM_5A_SOURCE_ID
CASE_STUDY_NORMALIZED_DIR = NORMALIZED_DIR / CASE_STUDY_ID


@dataclass(frozen=True)
class RecordSplitSpec:
    id: str
    slug: str
    record_class: str
    record_type: str
    title: str
    start_page: int
    end_page: int
    decision_ids: tuple[str, ...] = ()
    related_moneyflow_ids: tuple[str, ...] = ()
    actor_ids: tuple[str, ...] = ()
    issue_ids: tuple[str, ...] = ()
    place_ids: tuple[str, ...] = ()
    attached_to_record_id: str | None = None
    decision_relationship_type: str | None = None
    notes: tuple[str, ...] = ()


ITEM_5A_RECORD_SPLIT_SPECS = [
    RecordSplitSpec(
        id="record-2024-08-19-ordinance-2040-text",
        slug="ordinance-2040",
        record_class="legislative_record",
        record_type="ordinance_text",
        title="Ordinance No. 2040 amending Chapter 19.50 to regulate camping on public property",
        start_page=19,
        end_page=25,
        decision_ids=("decision-2024-08-19-ordinance-2040-introduction",),
        issue_ids=("issue-homelessness", "issue-encampments", "issue-camping-ordinance"),
        place_ids=("place-san-rafael",),
        decision_relationship_type="record_introduces_decision",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-resolution-15336-text",
        slug="resolution-15336",
        record_class="legislative_record",
        record_type="resolution_text",
        title=(
            "Resolution No. 15336 appropriating $2,256,400 and authorizing "
            "$2,002,400 for ERF3 and other homelessness services"
        ),
        start_page=26,
        end_page=27,
        decision_ids=("decision-2024-08-19-resolution-15336",),
        issue_ids=("issue-homelessness", "issue-encampments"),
        place_ids=("place-mahon-creek-path",),
        decision_relationship_type="record_authorizes_decision",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-resolution-15336-attachment-a-budget-amendment",
        slug="resolution-15336-attachment-a-budget-amendment",
        record_class="legislative_record",
        record_type="budget_amendment_resolution_attachment",
        title="Attachment A budget amendment resolution for fiscal year 2023-24 appropriations and transfers",
        start_page=28,
        end_page=28,
        attached_to_record_id="record-2024-08-19-resolution-15336-text",
        notes=(
            "Attachment A is embedded in the packet as a child record of Resolution 15336.",
            "The extracted page does not show a visible resolution number.",
        ),
    ),
    RecordSplitSpec(
        id="record-2024-08-19-contract-defense-block-security",
        slug="contract-defense-block-security",
        record_class="contract_record",
        record_type="professional_services_agreement",
        title="Defense Block Security agreement for security services in sanctioned camps",
        start_page=29,
        end_page=45,
        decision_ids=("decision-2024-08-19-resolution-15336",),
        related_moneyflow_ids=("moneyflow-2024-08-19-defense-block-contract",),
        actor_ids=("actor-defense-block-security",),
        issue_ids=("issue-homelessness", "issue-encampments"),
        place_ids=("place-mahon-creek-path",),
        attached_to_record_id="record-2024-08-19-resolution-15336-text",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-contract-other-junk-co",
        slug="contract-other-junk-co",
        record_class="contract_record",
        record_type="services_contract",
        title="The Other Junk Co. contract for encampment trash removal services",
        start_page=46,
        end_page=55,
        decision_ids=("decision-2024-08-19-resolution-15336",),
        related_moneyflow_ids=("moneyflow-2024-08-19-other-junk-contract",),
        actor_ids=("actor-other-junk-co",),
        issue_ids=("issue-homelessness", "issue-encampments"),
        place_ids=("place-mahon-creek-path",),
        attached_to_record_id="record-2024-08-19-resolution-15336-text",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-contract-wehope",
        slug="contract-wehope",
        record_class="contract_record",
        record_type="services_contract",
        title="WeHope contract for FY 2024-25 mobile shower services",
        start_page=56,
        end_page=62,
        decision_ids=("decision-2024-08-19-resolution-15336",),
        related_moneyflow_ids=("moneyflow-2024-08-19-wehope-contract",),
        actor_ids=("actor-wehope",),
        issue_ids=("issue-homelessness",),
        attached_to_record_id="record-2024-08-19-resolution-15336-text",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-contract-downtown-streets-team",
        slug="contract-downtown-streets-team",
        record_class="contract_record",
        record_type="professional_services_agreement",
        title=(
            "Downtown Streets Team agreement for implementation and management "
            "of employment development and volunteer work"
        ),
        start_page=63,
        end_page=78,
        decision_ids=("decision-2024-08-19-resolution-15336",),
        related_moneyflow_ids=("moneyflow-2024-08-19-dst-contract",),
        actor_ids=("actor-downtown-streets-team",),
        issue_ids=("issue-homelessness",),
        attached_to_record_id="record-2024-08-19-resolution-15336-text",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-sanctioned-camp-site-plan",
        slug="sanctioned-camp-site-plan",
        record_class="program_record",
        record_type="site_plan",
        title="Sanctioned encampment site plan with 47 total campsites",
        start_page=79,
        end_page=79,
        issue_ids=("issue-homelessness", "issue-encampments"),
        place_ids=("place-mahon-creek-path",),
        attached_to_record_id="record-2024-08-19-resolution-15336-text",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-sanctioned-camp-code-of-conduct",
        slug="sanctioned-camp-code-of-conduct",
        record_class="program_record",
        record_type="code_of_conduct",
        title="Draft code of conduct for the San Rafael sanctioned camping area",
        start_page=80,
        end_page=81,
        issue_ids=("issue-homelessness", "issue-encampments"),
        place_ids=("place-mahon-creek-path",),
        attached_to_record_id="record-2024-08-19-resolution-15336-text",
    ),
    RecordSplitSpec(
        id="record-2024-08-19-item-5a-correspondence-packet",
        slug="item-5a-correspondence-packet",
        record_class="meeting_record",
        record_type="public_correspondence_packet",
        title="Public correspondence packet attached to August 19, 2024 item 5.a",
        start_page=82,
        end_page=97,
        issue_ids=("issue-homelessness", "issue-encampments"),
        attached_to_record_id=ITEM_5A_SOURCE_RECORD_ID,
    ),
]

ITEM_5A_UNRESOLVED_GAPS = [
    (
        "The staff report discusses a proposed FS Global Solutions contract, but the packet does not "
        "appear to include a discrete FS Global contract exhibit in pages 19-97."
    ),
]


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


def extract_pdf_page_range_text(reader: PdfReader, start_page: int, end_page: int) -> str:
    pages: list[str] = []
    for index in range(start_page - 1, end_page):
        text = (reader.pages[index].extract_text() or "").strip()
        if text:
            pages.append(text)
    return "\n\n".join(pages).strip() + "\n"


def first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return None


def write_json_if_changed(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    comparison_payload = dict(payload)
    comparison_payload.pop("generated_at", None)

    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        comparison_existing = dict(existing)
        comparison_existing.pop("generated_at", None)
        if comparison_existing == comparison_payload:
            return existing

    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return payload


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

    if manifest["fetch_strategy"].startswith("citation_only"):
        raise ValueError(f"citation-only source requires a dedicated extractor: {source_id}")

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

    return write_json_if_changed(output_json, result)


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
    write_json_if_changed(summary_path, summary)


def write_item_5a_record_splits() -> None:
    ITEM_5A_EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    CASE_STUDY_NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(ITEM_5A_RAW_PDF))
    extracted_records: list[dict[str, Any]] = []
    normalized_records: list[dict[str, Any]] = []
    record_relationships: list[dict[str, str]] = []

    raw_pdf_rel = str(ITEM_5A_RAW_PDF.relative_to(ROOT))
    extracted_json_path = ITEM_5A_EXTRACTED_DIR / "item-5a-record-splits.json"
    normalized_json_path = CASE_STUDY_NORMALIZED_DIR / "aug-19-item-5a-record-splits.json"

    for spec in ITEM_5A_RECORD_SPLIT_SPECS:
        text = extract_pdf_page_range_text(reader, spec.start_page, spec.end_page)
        text_filename = f"item-5a-{spec.slug}.txt"
        text_path = ITEM_5A_EXTRACTED_DIR / text_filename
        text_path.write_text(text, encoding="utf-8")

        text_rel = str(text_path.relative_to(ROOT))
        extracted_record = {
            "id": spec.id,
            "record_class": spec.record_class,
            "record_type": spec.record_type,
            "title": spec.title,
            "page_range": {
                "start": spec.start_page,
                "end": spec.end_page,
            },
            "text_path": text_rel,
            "word_count": len(text.split()),
            "first_line": first_nonempty_line(text),
        }
        extracted_records.append(extracted_record)

        normalized_record = {
            "id": spec.id,
            "status": "derived_candidate",
            "record_class": spec.record_class,
            "record_type": spec.record_type,
            "title": spec.title,
            "publisher": "City of San Rafael",
            "published_at": "2024-08-19",
            "source_tier": "official",
            "source_record_id": ITEM_5A_SOURCE_RECORD_ID,
            "artifact_paths": [raw_pdf_rel],
            "text_path": text_rel,
            "page_range": {
                "start": spec.start_page,
                "end": spec.end_page,
            },
            "word_count": len(text.split()),
            "meeting_id": "meeting-2024-08-19-san-rafael-city-council",
            "agenda_item_id": "agenda-item-2024-08-19-5a",
            "decision_ids": list(spec.decision_ids),
            "related_moneyflow_ids": list(spec.related_moneyflow_ids),
            "actor_ids": list(spec.actor_ids),
            "issue_ids": list(spec.issue_ids),
            "place_ids": list(spec.place_ids),
            "notes": list(spec.notes),
        }
        normalized_records.append(normalized_record)

        record_relationships.append(
            {
                "source_record_id": spec.id,
                "relationship_type": "record_extracts_from_record",
                "target_record_id": ITEM_5A_SOURCE_RECORD_ID,
            }
        )

        if spec.attached_to_record_id:
            record_relationships.append(
                {
                    "source_record_id": spec.id,
                    "relationship_type": "record_attached_to_record",
                    "target_record_id": spec.attached_to_record_id,
                }
            )

        if spec.decision_relationship_type:
            for decision_id in spec.decision_ids:
                record_relationships.append(
                    {
                        "source_record_id": spec.id,
                        "relationship_type": spec.decision_relationship_type,
                        "target_decision_id": decision_id,
                    }
                )

    extracted_payload = {
        "source_id": ITEM_5A_SOURCE_ID,
        "bundle_id": BUNDLE_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "derived_from_record_id": ITEM_5A_SOURCE_RECORD_ID,
        "derived_from_artifact_path": raw_pdf_rel,
        "record_splits": extracted_records,
        "unresolved_gaps": ITEM_5A_UNRESOLVED_GAPS,
    }
    write_json_if_changed(extracted_json_path, extracted_payload)

    normalized_payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "derived_candidate_record_splits",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "derived_from_record_id": ITEM_5A_SOURCE_RECORD_ID,
        "record_refs": normalized_records,
        "record_relationships": record_relationships,
        "unresolved_gaps": ITEM_5A_UNRESOLVED_GAPS,
    }
    write_json_if_changed(normalized_json_path, normalized_payload)


def main() -> None:
    manifests = sorted(RAW_DIR.glob("*/2026-04-10/manifest.json"))
    selected = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("bundle_id") == BUNDLE_ID:
            selected.append(manifest_path)

    filtered = []
    for path in selected:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["fetch_strategy"].startswith("citation_only"):
            continue
        filtered.append(path)

    results = [extract_source(path) for path in filtered]
    write_bundle_summary(results)
    write_item_5a_record_splits()


if __name__ == "__main__":
    main()
