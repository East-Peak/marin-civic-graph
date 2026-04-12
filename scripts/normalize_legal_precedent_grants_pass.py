#!/usr/bin/env python3

from __future__ import annotations

import html
import json
import re
import subprocess
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

GRANTS_PASS_DOCKET_HTML = (
    ROOT / "data" / "raw" / "scotus-grants-pass-docket" / "2026-04-10" / "source.html"
)
GRANTS_PASS_DOCKET_MANIFEST = (
    ROOT / "data" / "raw" / "scotus-grants-pass-docket" / "2026-04-10" / "manifest.json"
)
GRANTS_PASS_DOCKET_TEXT = ROOT / "data" / "extracted" / "scotus-grants-pass-docket" / "source.txt"
GRANTS_PASS_DOCKET_EXTRACT = (
    ROOT / "data" / "extracted" / "scotus-grants-pass-docket" / "2026-04-12.json"
)

GRANTS_PASS_OPINION_PDF = (
    ROOT / "data" / "raw" / "scotus-grants-pass-opinion" / "2026-04-12" / "opinion.pdf"
)
GRANTS_PASS_OPINION_MANIFEST = (
    ROOT / "data" / "raw" / "scotus-grants-pass-opinion" / "2026-04-12" / "manifest.json"
)
GRANTS_PASS_OPINION_TEXT = (
    ROOT / "data" / "extracted" / "scotus-grants-pass-opinion" / "opinion.txt"
)
GRANTS_PASS_OPINION_EXTRACT = (
    ROOT / "data" / "extracted" / "scotus-grants-pass-opinion" / "2026-04-12.json"
)

SAN_RAFAEL_GRANTS_PASS_STATEMENT_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-grants-pass-statement" / "2026-04-10.json"
)
SAN_RAFAEL_GRANTS_PASS_EXPLAINER_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-grants-pass-explainer" / "2026-04-10.json"
)
SF_GRANTS_PASS_AMICUS_EXTRACT = (
    ROOT / "data" / "extracted" / "sf-city-attorney-grants-pass-amicus" / "2026-04-10.json"
)

OUTPUT_DIR = ROOT / "data" / "normalized" / "legal-precedent-02"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

CASE_STUDY_ID = "legal-precedent-02"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def ensure_docket_text() -> str:
    extractor = TextExtractor()
    extractor.feed(GRANTS_PASS_DOCKET_HTML.read_text())
    text = "\n".join(extractor.parts) + "\n"
    GRANTS_PASS_DOCKET_TEXT.parent.mkdir(parents=True, exist_ok=True)
    GRANTS_PASS_DOCKET_TEXT.write_text(text)
    return text


def pdfinfo_map(path: Path) -> dict[str, str]:
    output = subprocess.check_output(["pdfinfo", str(path)], text=True)
    mapping: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        mapping[key.strip()] = value.strip()
    return mapping


def extract_meta(html_text: str, name: str) -> str | None:
    match = re.search(
        rf"<META name=['\"]{re.escape(name)}['\"] content=['\"]([^'\"]+)['\"]>",
        html_text,
        re.IGNORECASE,
    )
    return html.unescape(match.group(1)) if match else None


def extract_opinion_url(html_text: str) -> str:
    match = re.search(
        r"https://www\.supremecourt\.gov/opinions/23pdf/23-175_19m2\.pdf",
        html_text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Could not find Grants Pass opinion URL in docket HTML")
    return match.group(0)


def build_docket_extract() -> dict:
    manifest = load_json(GRANTS_PASS_DOCKET_MANIFEST)
    html_text = GRANTS_PASS_DOCKET_HTML.read_text()
    text = ensure_docket_text()
    petitioner = extract_meta(html_text, "Petitioner")
    respondent = extract_meta(html_text, "Respondent")
    opinion_url = extract_opinion_url(html_text)

    return {
        "source_id": "scotus-grants-pass-docket",
        "capture_id": manifest["capture_id"],
        "capture_date": "2026-04-12",
        "entry_url": manifest["entry_url"],
        "fetch_strategy": manifest["fetch_strategy"],
        "generated_at": utc_now_iso(),
        "artifacts": [
            {
                "artifact_path": "data/raw/scotus-grants-pass-docket/2026-04-10/source.html",
                "content_type": "text/html",
                "artifact_type": "html",
                "title": "City of Grants Pass, Oregon, Petitioner v. Johnson et al. - Supreme Court Docket",
                "published_at": None,
                "text_path": "data/extracted/scotus-grants-pass-docket/source.txt",
                "word_count": len(text.split()),
                "docket_number": "23-175",
                "linked_opinion_url": opinion_url,
            }
        ],
        "candidate_signals": {
            "actor_hits": [petitioner, respondent],
            "place_hits": [
                "Grants Pass",
                "Oregon",
            ],
            "issue_hits": [
                "homelessness",
                "encampments",
                "camping ordinance",
                "public property",
                "Eighth Amendment",
            ],
            "legal_refs": [
                "No. 23-175",
                "petition for a writ of certiorari",
                "certiorari granted",
                "oral argument",
                "Judgment REVERSED and case REMANDED",
                "Martin v. Boise",
            ],
            "procedural_dates": [
                "2023-08-22 petition for certiorari filed",
                "2024-01-12 petition granted",
                "2024-04-22 oral argument",
                "2024-06-28 judgment reversed and remanded",
            ],
        },
        "notes": [
            "Official Supreme Court docket landing page captured as the proceeding and filing discovery surface for City of Grants Pass v. Johnson.",
            "This record anchors the cert petition, cert grant, oral argument, and opinion-release timeline without relying on secondary summaries.",
        ],
    }


def build_opinion_extract() -> dict:
    manifest = load_json(GRANTS_PASS_OPINION_MANIFEST)
    info = pdfinfo_map(GRANTS_PASS_OPINION_PDF)
    text = GRANTS_PASS_OPINION_TEXT.read_text()

    return {
        "source_id": "scotus-grants-pass-opinion",
        "capture_id": manifest["capture_id"],
        "capture_date": "2026-04-12",
        "entry_url": manifest["entry_url"],
        "fetch_strategy": manifest["fetch_strategy"],
        "generated_at": utc_now_iso(),
        "artifacts": [
            {
                "artifact_path": "data/raw/scotus-grants-pass-opinion/2026-04-12/opinion.pdf",
                "content_type": "application/pdf",
                "artifact_type": "pdf",
                "title": info.get("Title", "23-175 City of Grants Pass v. Johnson (06/28/2024)"),
                "published_at": "2024-06-28",
                "page_count": int(info["Pages"]),
                "court_name": "Supreme Court of the United States",
                "docket_number": "23-175",
                "text_path": "data/extracted/scotus-grants-pass-opinion/opinion.txt",
                "word_count": len(text.split()),
            }
        ],
        "candidate_signals": {
            "actor_hits": [
                "City of Grants Pass, Oregon",
                "Johnson et al.",
                "Gorsuch, J.",
            ],
            "place_hits": [
                "Grants Pass",
                "Oregon",
            ],
            "issue_hits": [
                "homelessness",
                "encampments",
                "camping ordinance",
                "public property",
                "Eighth Amendment",
            ],
            "legal_refs": [
                "No. 23-175",
                "certiorari to the United States Court of Appeals for the Ninth Circuit",
                "Martin v. Boise",
                "reversed and remanded",
            ],
            "procedural_dates": [
                "2024-04-22 argued",
                "2024-06-28 decided",
            ],
        },
        "notes": [
            "Official Supreme Court slip opinion PDF captured directly from the docket-linked opinion URL.",
            "This is the controlling precedent record for the repo's Grants Pass legal bundle.",
        ],
    }


def build_bundle() -> dict:
    statement = load_json(SAN_RAFAEL_GRANTS_PASS_STATEMENT_EXTRACT)
    explainer = load_json(SAN_RAFAEL_GRANTS_PASS_EXPLAINER_EXTRACT)
    sf_amicus = load_json(SF_GRANTS_PASS_AMICUS_EXTRACT)

    sf_title = html.unescape(sf_amicus["artifacts"][0]["title"])
    explainer_title = html.unescape(explainer["artifacts"][0]["title"])

    return {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "City of Grants Pass v. Johnson as the first normalized external controlling-precedent bundle",
            "official Supreme Court docket and slip-opinion records plus official San Rafael and San Francisco response records",
            "crosswalk from national precedent into San Rafael's June 28 and September 2 legal posture records and the August 19, 2024 decision chain",
            "local Boyd constraints remain separate and are referenced as related local context rather than collapsed into the Supreme Court case itself",
        ],
        "place_candidates": [
            {
                "id": "place-united-states",
                "name": "United States",
                "place_type": "country",
            },
            {
                "id": "place-oregon",
                "name": "Oregon",
                "place_type": "state",
                "jurisdiction_place_id": "place-united-states",
            },
            {
                "id": "place-grants-pass-oregon",
                "name": "Grants Pass",
                "place_type": "city",
                "jurisdiction_place_id": "place-oregon",
            },
            {
                "id": "place-california",
                "name": "California",
                "place_type": "state",
                "jurisdiction_place_id": "place-united-states",
            },
            {
                "id": "place-san-francisco",
                "name": "San Francisco",
                "place_type": "city",
                "jurisdiction_place_id": "place-california",
            },
            {
                "id": "place-san-rafael",
                "name": "San Rafael",
                "place_type": "city",
                "jurisdiction_place_id": "place-california",
            },
        ],
        "record_refs": [
            {
                "id": "record-scotus-grants-pass-docket-23-175",
                "record_class": "legal_record",
                "record_type": "docket_page",
                "title": "City of Grants Pass, Oregon, Petitioner v. Johnson et al. - Supreme Court Docket",
                "source_id": "scotus-grants-pass-docket",
                "artifact_path": "data/raw/scotus-grants-pass-docket/2026-04-10/source.html",
                "text_path": "data/extracted/scotus-grants-pass-docket/source.txt",
                "published_at": None,
                "court_name": "Supreme Court of the United States",
                "docket_number": "23-175",
                "case_ids": [
                    "case-city-of-grants-pass-v-johnson",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-grants-pass-oregon",
                    "place-oregon",
                ],
            },
            {
                "id": "record-scotus-grants-pass-opinion-2024-06-28",
                "record_class": "legal_record",
                "record_type": "slip_opinion",
                "title": "23-175 City of Grants Pass v. Johnson (06/28/2024)",
                "source_id": "scotus-grants-pass-opinion",
                "artifact_path": "data/raw/scotus-grants-pass-opinion/2026-04-12/opinion.pdf",
                "text_path": "data/extracted/scotus-grants-pass-opinion/opinion.txt",
                "published_at": "2024-06-28",
                "court_name": "Supreme Court of the United States",
                "docket_number": "23-175",
                "page_count": 74,
                "case_ids": [
                    "case-city-of-grants-pass-v-johnson",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-grants-pass-oregon",
                    "place-oregon",
                ],
            },
            {
                "id": "record-sf-city-attorney-grants-pass-amicus-post-2024-03-01",
                "record_class": "legal_record",
                "record_type": "amicus_announcement",
                "title": sf_title,
                "source_id": "sf-city-attorney-grants-pass-amicus",
                "artifact_path": "data/raw/sf-city-attorney-grants-pass-amicus/2026-04-10/source.html",
                "text_path": "data/extracted/sf-city-attorney-grants-pass-amicus/source.txt",
                "published_at": "2024-03-01",
                "case_ids": [
                    "case-city-of-grants-pass-v-johnson",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-san-francisco",
                    "place-california",
                ],
            },
        ],
        "institution_candidates": [
            {
                "id": "inst-united-states-supreme-court",
                "name": "Supreme Court of the United States",
                "institution_type": "court",
                "jurisdiction_place_id": "place-united-states",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                ],
            },
            {
                "id": "inst-city-of-grants-pass",
                "name": "City of Grants Pass",
                "institution_type": "municipality",
                "jurisdiction_place_id": "place-grants-pass-oregon",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                ],
            },
            {
                "id": "inst-city-and-county-of-san-francisco",
                "name": "City and County of San Francisco",
                "institution_type": "municipality",
                "jurisdiction_place_id": "place-san-francisco",
                "evidence_record_ids": [
                    "record-sf-city-attorney-grants-pass-amicus-post-2024-03-01",
                ],
            },
            {
                "id": "inst-city-of-san-rafael",
                "name": "City of San Rafael",
                "institution_type": "municipality",
                "jurisdiction_place_id": "place-san-rafael",
                "evidence_record_ids": [
                    "doc-2024-06-28-grants-pass-statement",
                    "record-san-rafael-grants-pass-explainer-2024-09-02",
                ],
            },
        ],
        "actor_candidates": [
            {
                "id": "actor-gloria-johnson-et-al",
                "name": "Gloria Johnson, et al.",
                "roles": [
                    "respondent_group",
                ],
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                ],
                "notes": [
                    "Conservative respondent-group actor for the first Grants Pass bundle; the full certified class roster is intentionally out of scope here.",
                ],
            },
            {
                "id": "actor-neil-m-gorsuch",
                "name": "Neil M. Gorsuch",
                "roles": [
                    "justice",
                ],
                "evidence_record_ids": [
                    "record-scotus-grants-pass-opinion-2024-06-28",
                    "record-scotus-grants-pass-docket-23-175",
                ],
            },
        ],
        "case_candidates": [
            {
                "id": "case-city-of-grants-pass-v-johnson",
                "name": "City of Grants Pass v. Johnson",
                "case_type": "supreme_court_public_camping_eighth_amendment_precedent",
                "court_name": "Supreme Court of the United States",
                "court_institution_id": "inst-united-states-supreme-court",
                "docket_number": "23-175",
                "status": "reversed_and_remanded",
                "filed_at": "2023-08-22",
                "closed_at": "2024-06-28",
                "record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                    "record-sf-city-attorney-grants-pass-amicus-post-2024-03-01",
                    "doc-2024-06-28-grants-pass-statement",
                    "record-san-rafael-grants-pass-explainer-2024-09-02",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-grants-pass-oregon",
                    "place-oregon",
                ],
                "related_decision_ids": [
                    "decision-2024-08-19-ordinance-2040-introduction",
                    "decision-2024-08-19-resolution-15336",
                ],
                "related_program_ids": [
                    "program-san-rafael-sanctioned-camping",
                ],
                "notes": [
                    "This bundle treats the Supreme Court docket and slip opinion as the authoritative Grants Pass precedent layer.",
                    "San Rafael's own June 28 statement and September 2 explainer are preserved as local response records, not as substitutes for the Supreme Court opinion.",
                ],
            }
        ],
        "proceeding_candidates": [
            {
                "id": "proceeding-grants-pass-cert-petition-filed-2023-08-22",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "proceeding_type": "cert_petition_filing",
                "occurred_at": "2023-08-22",
                "status": "filed",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                ],
            },
            {
                "id": "proceeding-grants-pass-cert-granted-2024-01-12",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "proceeding_type": "cert_grant",
                "occurred_at": "2024-01-12",
                "status": "granted",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                ],
            },
            {
                "id": "proceeding-grants-pass-oral-argument-2024-04-22",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "proceeding_type": "oral_argument",
                "occurred_at": "2024-04-22",
                "status": "heard",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                ],
            },
            {
                "id": "proceeding-grants-pass-opinion-2024-06-28",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "proceeding_type": "opinion",
                "occurred_at": "2024-06-28",
                "status": "reversed_and_remanded",
                "judge_actor_id": "actor-neil-m-gorsuch",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                ],
            },
        ],
        "case_participation_candidates": [
            {
                "id": "casepart-grants-pass-petitioner-city",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "institution_id": "inst-city-of-grants-pass",
                "role": "petitioner",
                "start_date": "2023-08-22",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                ],
            },
            {
                "id": "casepart-grants-pass-respondent-group",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "actor_id": "actor-gloria-johnson-et-al",
                "role": "respondent",
                "start_date": "2023-08-22",
                "evidence_record_ids": [
                    "record-scotus-grants-pass-docket-23-175",
                    "record-scotus-grants-pass-opinion-2024-06-28",
                ],
            },
            {
                "id": "casepart-grants-pass-sf-amicus",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "institution_id": "inst-city-and-county-of-san-francisco",
                "role": "amicus_curiae",
                "start_date": "2024-03-01",
                "evidence_record_ids": [
                    "record-sf-city-attorney-grants-pass-amicus-post-2024-03-01",
                ],
            },
        ],
        "methodology_findings": [
            {
                "id": "method-legal-precedent-02-opinion-first",
                "summary": "The first external precedent bundle starts from the official Supreme Court docket and slip opinion rather than from municipal explainers. That keeps the controlling rule and the local reaction records separate."
            },
            {
                "id": "method-legal-precedent-02-response-record-boundary",
                "summary": "San Rafael's statement and explainer and San Francisco's amicus announcement are modeled as institutional response records. They help explain local posture and advocacy, but they are not the precedent itself."
            },
            {
                "id": "method-legal-precedent-02-san-rafael-crosswalk",
                "summary": "The bundle crosswalks Grants Pass back into San Rafael only through official local records that explicitly discuss the case, then points forward into the August 19 ordinance, resolution, and sanctioned-camping response chain."
            },
        ],
        "crosswalks": [
            {
                "id": "crosswalk-grants-pass-to-san-rafael-posture",
                "case_id": "case-city-of-grants-pass-v-johnson",
                "related_case_ids": [
                    "case-boyd-v-city-of-san-rafael",
                ],
                "meeting_id": "meeting-2024-08-19-san-rafael-city-council",
                "agenda_item_id": "agenda-item-2024-08-19-5a",
                "decision_ids": [
                    "decision-2024-08-19-ordinance-2040-introduction",
                    "decision-2024-08-19-resolution-15336",
                ],
                "program_ids": [
                    "program-san-rafael-sanctioned-camping",
                ],
                "evidence_record_ids": [
                    "record-scotus-grants-pass-opinion-2024-06-28",
                    "doc-2024-06-28-grants-pass-statement",
                    "record-san-rafael-grants-pass-explainer-2024-09-02",
                    "doc-2024-08-19-item-5a-report",
                ],
                "summary": "San Rafael's June 28 statement and September 2 explainer treat Grants Pass as the Eighth Amendment posture change that cleared one Ninth Circuit obstacle, while the August 19 package shows the City still routing its local implementation through Boyd-specific ADA and state-created-danger constraints."
            }
        ],
        "open_questions": [
            {
                "id": "OQ-031",
                "status": "watch",
                "summary": "The Grants Pass bundle has the official Supreme Court docket and slip opinion, but it does not yet include the lower-court district and Ninth Circuit orders that the Supreme Court reversed and remanded.",
                "why_it_matters": "The current bundle is strong enough for precedent and local-posture joins. The remaining gap is comparison depth inside the underlying Martin-era lower-court chain, not whether the controlling Supreme Court record is missing.",
                "next_evidence": "Capture the district-court injunction and the Ninth Circuit opinion, then decide whether they should live in this bundle or a later lower-court companion bundle."
            }
        ],
        "notes": [
            f"Supreme Court docket extract artifact: {GRANTS_PASS_DOCKET_EXTRACT.relative_to(ROOT)}",
            f"Supreme Court opinion extract artifact: {GRANTS_PASS_OPINION_EXTRACT.relative_to(ROOT)}",
            f"San Rafael statement artifact: {Path(statement['artifacts'][0]['artifact_path'])}",
            f"San Rafael explainer title: {explainer_title}",
            "This bundle is normalized-only for now. It widens the legal lane from one local constraint case to one local case plus one controlling Supreme Court precedent.",
        ],
    }


def main() -> None:
    write_json(GRANTS_PASS_DOCKET_EXTRACT, build_docket_extract())
    write_json(GRANTS_PASS_OPINION_EXTRACT, build_opinion_extract())
    write_json(OUTPUT_PATH, build_bundle())


if __name__ == "__main__":
    main()
