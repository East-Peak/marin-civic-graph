#!/usr/bin/env python3

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

BOYD_DISMISSAL_ORDER_PDF = (
    ROOT / "data" / "raw" / "san-rafael-boyd-dismissal-order" / "2026-04-12" / "order.pdf"
)
BOYD_DISMISSAL_ORDER_MANIFEST = (
    ROOT / "data" / "raw" / "san-rafael-boyd-dismissal-order" / "2026-04-12" / "manifest.json"
)
BOYD_DISMISSAL_ORDER_TEXT = (
    ROOT / "data" / "extracted" / "san-rafael-boyd-dismissal-order" / "order.txt"
)
BOYD_DISMISSAL_ORDER_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-boyd-dismissal-order" / "2026-04-12.json"
)
BOYD_TRO_ORDER_MANIFEST = (
    ROOT / "data" / "raw" / "san-rafael-boyd-tro-order" / "2026-04-12" / "manifest.json"
)
BOYD_TRO_ORDER_TEXT = ROOT / "data" / "extracted" / "san-rafael-boyd-tro-order" / "order.txt"
BOYD_TRO_ORDER_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-boyd-tro-order" / "2026-04-12.json"
)
BOYD_PI_ORDER_MANIFEST = (
    ROOT / "data" / "raw" / "san-rafael-boyd-preliminary-injunction-order" / "2026-04-12" / "manifest.json"
)
BOYD_PI_ORDER_TEXT = (
    ROOT / "data" / "extracted" / "san-rafael-boyd-preliminary-injunction-order" / "order.txt"
)
BOYD_PI_ORDER_EXTRACT = (
    ROOT
    / "data"
    / "extracted"
    / "san-rafael-boyd-preliminary-injunction-order"
    / "2026-04-12.json"
)

BOYD_RELEASE_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-boyd-dismissal-news-release" / "2026-04-10.json"
)
GRANTS_PASS_STATEMENT_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-grants-pass-statement" / "2026-04-10.json"
)
GRANTS_PASS_EXPLAINER_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-grants-pass-explainer" / "2026-04-10.json"
)
STAFF_REPORT_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-aug-19-2024-staff-report" / "2026-04-10.json"
)
SANCTIONED_CAMPING_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-sanctioned-camping-area" / "2026-04-10.json"
)

OUTPUT_DIR = ROOT / "data" / "normalized" / "legal-precedent-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

CASE_STUDY_ID = "legal-precedent-01"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def build_order_extract(
    *,
    source_id: str,
    manifest_path: Path,
    text_path: Path,
    artifact_path: str,
    title: str,
    published_at: str,
    page_count: int,
    notes: list[str],
    actor_hits: list[str],
    issue_hits: list[str],
    legal_refs: list[str],
    procedural_dates: list[str],
) -> dict:
    manifest = load_json(manifest_path)
    text = text_path.read_text()
    word_count = len(text.split())

    return {
        "source_id": source_id,
        "capture_id": manifest["capture_id"],
        "capture_date": "2026-04-12",
        "entry_url": manifest["entry_url"],
        "fetch_strategy": manifest["fetch_strategy"],
        "generated_at": utc_now_iso(),
        "artifacts": [
            {
                "artifact_path": "data/raw/san-rafael-boyd-dismissal-order/2026-04-12/order.pdf",
                "artifact_path": artifact_path,
                "content_type": "application/pdf",
                "artifact_type": "pdf",
                "title": title,
                "published_at": published_at,
                "page_count": page_count,
                "court_name": "U.S. District Court, Northern District of California",
                "docket_number": "23-cv-04085-EMC",
                "text_path": str(text_path.relative_to(ROOT)),
                "word_count": word_count,
            }
        ],
        "candidate_signals": {
            "actor_hits": actor_hits,
            "place_hits": [
                "San Rafael",
                "Mahon Creek Path",
            ],
            "issue_hits": issue_hits,
            "legal_refs": legal_refs,
            "procedural_dates": procedural_dates,
        },
        "notes": notes,
    }


def build_bundle() -> dict:
    # Load the existing extracts so the bundle records exactly which evidence surfaces exist.
    boyd_release = load_json(BOYD_RELEASE_EXTRACT)
    grants_pass_statement = load_json(GRANTS_PASS_STATEMENT_EXTRACT)
    grants_pass_explainer = load_json(GRANTS_PASS_EXPLAINER_EXTRACT)
    staff_report = load_json(STAFF_REPORT_EXTRACT)
    sanctioned_camping = load_json(SANCTIONED_CAMPING_EXTRACT)

    return {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "Boyd v. City of San Rafael as the first normalized local legal-constraint bundle",
            "three public filed-order records for the TRO, preliminary injunction, and dismissal stages plus official city-side legal response records",
            "joins back into the August 19, 2024 ordinance / resolution / sanctioned-camping chain",
            "Grants Pass included only as linked official precedent context already cited by San Rafael",
        ],
        "place_candidates": [
            {
                "id": "place-california",
                "name": "California",
                "place_type": "state",
            },
            {
                "id": "place-san-rafael",
                "name": "San Rafael",
                "place_type": "city",
            },
            {
                "id": "place-mahon-creek-path",
                "name": "Mahon Creek Path",
                "place_type": "corridor",
                "jurisdiction_place_id": "place-san-rafael",
            },
        ],
        "record_refs": [
            {
                "id": "record-san-rafael-boyd-tro-order-2023-08-16",
                "record_class": "legal_record",
                "record_type": "temporary_restraining_order",
                "title": "Order Granting Plaintiffs' Motion for a Temporary Restraining Order",
                "source_id": "san-rafael-boyd-tro-order",
                "artifact_path": "data/raw/san-rafael-boyd-tro-order/2026-04-12/order.pdf",
                "text_path": "data/extracted/san-rafael-boyd-tro-order/order.txt",
                "published_at": "2023-08-16",
                "court_name": "U.S. District Court, Northern District of California",
                "docket_number": "23-cv-04085-EMC",
                "page_count": 16,
                "case_ids": [
                    "case-boyd-v-city-of-san-rafael",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-san-rafael",
                    "place-mahon-creek-path",
                ],
            },
            {
                "id": "record-san-rafael-boyd-preliminary-injunction-order-2023-10-19",
                "record_class": "legal_record",
                "record_type": "preliminary_injunction_order",
                "title": "Order Granting in Part and Denying in Part Plaintiffs' Motion for Preliminary Injunction",
                "source_id": "san-rafael-boyd-preliminary-injunction-order",
                "artifact_path": "data/raw/san-rafael-boyd-preliminary-injunction-order/2026-04-12/order.pdf",
                "text_path": "data/extracted/san-rafael-boyd-preliminary-injunction-order/order.txt",
                "published_at": "2023-10-19",
                "court_name": "U.S. District Court, Northern District of California",
                "docket_number": "23-cv-04085-EMC",
                "page_count": 50,
                "case_ids": [
                    "case-boyd-v-city-of-san-rafael",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-san-rafael",
                    "place-mahon-creek-path",
                ],
            },
            {
                "id": "record-san-rafael-boyd-dismissal-order-2024-08-07",
                "record_class": "legal_record",
                "record_type": "dismissal_order",
                "title": "Order Granting Defendant's Motion to Dismiss",
                "source_id": "san-rafael-boyd-dismissal-order",
                "artifact_path": "data/raw/san-rafael-boyd-dismissal-order/2026-04-12/order.pdf",
                "text_path": "data/extracted/san-rafael-boyd-dismissal-order/order.txt",
                "published_at": "2024-08-07",
                "court_name": "U.S. District Court, Northern District of California",
                "docket_number": "23-cv-04085-EMC",
                "page_count": 9,
                "case_ids": [
                    "case-boyd-v-city-of-san-rafael",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-san-rafael",
                    "place-mahon-creek-path",
                ],
            },
            {
                "id": "record-san-rafael-grants-pass-explainer-2024-09-02",
                "record_class": "legal_record",
                "record_type": "official_legal_explainer",
                "title": html.unescape(grants_pass_explainer["artifacts"][0]["title"]),
                "source_id": "san-rafael-grants-pass-explainer",
                "artifact_path": "data/raw/san-rafael-grants-pass-explainer/2026-04-10/source.html",
                "text_path": "data/extracted/san-rafael-grants-pass-explainer/source.txt",
                "published_at": "2024-09-02",
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-san-rafael",
                    "place-mahon-creek-path",
                ],
                "related_case_ids": [
                    "case-boyd-v-city-of-san-rafael",
                ],
            },
            {
                "id": "record-san-rafael-sanctioned-camping-area-page",
                "record_class": "program_record",
                "record_type": "official_program_page",
                "title": sanctioned_camping["artifacts"][0]["title"],
                "source_id": "san-rafael-sanctioned-camping-area",
                "artifact_path": "data/raw/san-rafael-sanctioned-camping-area/2026-04-10/source.html",
                "text_path": "data/extracted/san-rafael-sanctioned-camping-area/source.txt",
                "published_at": None,
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                ],
                "place_ids": [
                    "place-san-rafael",
                    "place-mahon-creek-path",
                ],
                "related_case_ids": [
                    "case-boyd-v-city-of-san-rafael",
                ],
                "related_program_ids": [
                    "program-san-rafael-sanctioned-camping",
                ],
            },
        ],
        "institution_candidates": [
            {
                "id": "inst-city-of-san-rafael",
                "name": "City of San Rafael",
                "institution_type": "municipality",
                "jurisdiction_place_id": "place-san-rafael",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-tro-order-2023-08-16",
                    "record-san-rafael-boyd-preliminary-injunction-order-2023-10-19",
                    "doc-2024-08-08-boyd-dismissal-release",
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
            {
                "id": "inst-us-district-court-ndca",
                "name": "U.S. District Court, Northern District of California",
                "institution_type": "court",
                "jurisdiction_place_id": "place-california",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-tro-order-2023-08-16",
                    "record-san-rafael-boyd-preliminary-injunction-order-2023-10-19",
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
        ],
        "actor_candidates": [
            {
                "id": "actor-shaleeta-boyd-et-al",
                "name": "Shaleeta Boyd, et al.",
                "roles": [
                    "plaintiff_group",
                ],
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                    "doc-2024-08-08-boyd-dismissal-release",
                ],
                "notes": [
                    "Conservative plaintiff-group actor for the first legal bundle; full plaintiff roster and counsel layer still need docket-level capture.",
                ],
            },
            {
                "id": "actor-trina-l-thompson",
                "name": "Trina L. Thompson",
                "roles": [
                    "judge",
                ],
                "evidence_record_ids": [
                    "record-san-rafael-boyd-tro-order-2023-08-16",
                ],
            },
            {
                "id": "actor-edward-m-chen",
                "name": "Edward M. Chen",
                "roles": [
                    "judge",
                ],
                "evidence_record_ids": [
                    "record-san-rafael-boyd-tro-order-2023-08-16",
                    "record-san-rafael-boyd-preliminary-injunction-order-2023-10-19",
                    "doc-2024-08-08-boyd-dismissal-release",
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
        ],
        "program_candidates": [
            {
                "id": "program-san-rafael-sanctioned-camping",
                "name": "San Rafael sanctioned camping program",
                "program_type": "sanctioned_camping_program",
                "institution_id": "inst-city-of-san-rafael",
                "jurisdiction_place_id": "place-san-rafael",
                "status": "implemented",
                "record_ids": [
                    "record-san-rafael-sanctioned-camping-area-page",
                    "record-2024-08-19-sanctioned-camp-site-plan",
                    "record-2024-08-19-sanctioned-camp-code-of-conduct",
                    "record-2024-08-19-resolution-15336-text",
                ],
                "related_case_ids": [
                    "case-boyd-v-city-of-san-rafael",
                ],
                "related_decision_ids": [
                    "decision-2024-08-19-resolution-15336",
                    "decision-2024-08-19-ordinance-2040-introduction",
                ],
                "place_ids": [
                    "place-mahon-creek-path",
                ],
            }
        ],
        "case_candidates": [
            {
                "id": "case-boyd-v-city-of-san-rafael",
                "name": "Boyd v. City of San Rafael",
                "case_type": "civil_rights_camping_ordinance_challenge",
                "court_name": "U.S. District Court, Northern District of California",
                "court_institution_id": "inst-us-district-court-ndca",
                "docket_number": "23-cv-04085-EMC",
                "status": "dismissed",
                "filed_at": "2023-08-11",
                "closed_at": "2024-08-07",
                "record_ids": [
                    "record-san-rafael-boyd-tro-order-2023-08-16",
                    "record-san-rafael-boyd-preliminary-injunction-order-2023-10-19",
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                    "doc-2024-08-08-boyd-dismissal-release",
                    "doc-2024-08-19-item-5a-report",
                    "doc-2024-08-19-staff-report",
                    "doc-2024-06-28-grants-pass-statement",
                    "record-san-rafael-grants-pass-explainer-2024-09-02",
                    "record-san-rafael-sanctioned-camping-area-page",
                ],
                "issue_ids": [
                    "issue-homelessness",
                    "issue-encampments",
                    "issue-camping-ordinance",
                ],
                "place_ids": [
                    "place-san-rafael",
                    "place-mahon-creek-path",
                ],
                "related_decision_ids": [
                    "decision-2024-08-19-ordinance-2040-introduction",
                    "decision-2024-08-19-resolution-15336",
                ],
                "related_program_ids": [
                    "program-san-rafael-sanctioned-camping",
                ],
                "notes": [
                    "The first legal bundle now includes public filed-order copies for the TRO, preliminary injunction, and dismissal stages, plus the city's own official summaries of the amendment and implementation chain.",
                    "City records consistently say the operative Boyd injunction was grounded in ADA and Fourteenth Amendment state-created-danger theories, not the Eighth Amendment or Grants Pass directly.",
                ],
            }
        ],
        "proceeding_candidates": [
            {
                "id": "proceeding-boyd-complaint-filed-2023-08-11",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "proceeding_type": "complaint_filing",
                "occurred_at": "2023-08-11",
                "status": "filed",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
            {
                "id": "proceeding-boyd-tro-granted-2023-08-15",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "proceeding_type": "temporary_restraining_order",
                "occurred_at": "2023-08-15",
                "status": "granted",
                "judge_actor_id": "actor-trina-l-thompson",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-tro-order-2023-08-16",
                ],
            },
            {
                "id": "proceeding-boyd-preliminary-injunction-2023-10-19",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "proceeding_type": "preliminary_injunction_order",
                "occurred_at": "2023-10-19",
                "status": "granted_in_part",
                "judge_actor_id": "actor-edward-m-chen",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-preliminary-injunction-order-2023-10-19",
                ],
            },
            {
                "id": "proceeding-boyd-motion-to-dismiss-filed-2024-05-10",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "proceeding_type": "motion_to_dismiss_filing",
                "occurred_at": "2024-05-10",
                "status": "filed",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
            {
                "id": "proceeding-boyd-motion-hearing-2024-07-15",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "proceeding_type": "motion_hearing",
                "occurred_at": "2024-07-15",
                "judge_actor_id": "actor-edward-m-chen",
                "status": "heard",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
            {
                "id": "proceeding-boyd-dismissal-order-2024-08-07",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "proceeding_type": "dismissal_order",
                "occurred_at": "2024-08-07",
                "judge_actor_id": "actor-edward-m-chen",
                "status": "granted",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
        ],
        "case_participation_candidates": [
            {
                "id": "casepart-boyd-plaintiff-group",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "actor_id": "actor-shaleeta-boyd-et-al",
                "role": "plaintiff",
                "start_date": "2023-08-11",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
            {
                "id": "casepart-boyd-city-defendant",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "institution_id": "inst-city-of-san-rafael",
                "role": "defendant",
                "start_date": "2023-08-11",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
            },
        ],
        "methodology_findings": [
            {
                "id": "method-legal-precedent-01-court-origin-boundary",
                "summary": "The first legal bundle now includes three strong public filed-order copies for the TRO, preliminary injunction, and dismissal stages. The remaining provenance gap is no longer missing order text; it is that the TRO and preliminary injunction are held as public copied filings rather than court-hosted captures."
            },
            {
                "id": "method-legal-precedent-01-bounded-precedent-context",
                "summary": "Grants Pass remains context, not a full second case bundle here. The current Boyd slice uses San Rafael's June 28 statement and September 2 explainer only to preserve the city's own account that Boyd's operative injunction was not itself an Eighth Amendment / Grants Pass constraint."
            },
            {
                "id": "method-legal-precedent-01-program-crosswalk",
                "summary": "The bundle ties Boyd to the August 19, 2024 ordinance and resolution actions plus the sanctioned camping program because those are the first official city records that convert the legal constraint story into specific local decisions, contracts, and implementation steps."
            },
        ],
        "crosswalks": [
            {
                "id": "crosswalk-boyd-to-item-5a",
                "case_id": "case-boyd-v-city-of-san-rafael",
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
                    "doc-2024-08-19-item-5a-report",
                    "doc-2024-08-19-staff-report",
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
                "summary": "The August 19 package is the first official local decision chain that explicitly absorbs the Boyd dismissal, the Grants Pass posture, the amended ordinance, and the sanctioned-camping operational response into one council action."
            }
        ],
        "open_questions": [
            {
                "id": "OQ-030",
                "status": "watch",
                "summary": "The Boyd TRO and preliminary-injunction texts are now captured as public filed-order copies, but not yet from a direct court-hosted docket surface.",
                "why_it_matters": "The legal lane now has the substantive order text it needs for `Case` and `Proceeding` joins. The remaining question is provenance strength, not whether the operative order texts are missing.",
                "next_evidence": "If a stable public court-hosted docket or order path becomes available, replace the copied-file provenance with direct court captures while keeping the same semantic record IDs.",
            }
        ],
        "notes": [
            f"Boyd release extract artifact: {boyd_release['artifacts'][0]['artifact_path']}",
            f"Grants Pass statement extract artifact: {grants_pass_statement['artifacts'][0]['artifact_path']}",
            f"Grants Pass explainer extract artifact: {grants_pass_explainer['artifacts'][0]['artifact_path']}",
            f"August 19 staff report extract artifact: {staff_report['artifacts'][1]['artifact_path']}",
            "This bundle is normalized-only for now. It creates the first real legal-precedent bundle without widening graph-v1 import scope in the same step.",
        ],
    }


def main() -> None:
    write_json(
        BOYD_TRO_ORDER_EXTRACT,
        build_order_extract(
            source_id="san-rafael-boyd-tro-order",
            manifest_path=BOYD_TRO_ORDER_MANIFEST,
            text_path=BOYD_TRO_ORDER_TEXT,
            artifact_path="data/raw/san-rafael-boyd-tro-order/2026-04-12/order.pdf",
            title="Order Granting Plaintiffs' Motion for a Temporary Restraining Order",
            published_at="2023-08-16",
            page_count=16,
            notes=[
                "Public filed-order copy surfaced through the Civil Rights Litigation Clearinghouse document page for ECF 19.",
                "Strong enough for substantive TRO terms and procedural sequencing, but not a court-hosted artifact.",
            ],
            actor_hits=[
                "Boyd et al.",
                "City of San Rafael et al.",
                "Camp Integrity",
            ],
            issue_hits=[
                "homelessness",
                "encampments",
                "camping ordinance",
                "Eighth Amendment",
            ],
            legal_refs=[
                "Case No. 23-cv-04085-EMC",
                "Document 19",
                "temporary restraining order",
                "Mahon Creek Path",
            ],
            procedural_dates=[
                "2023-08-11 complaint filed",
                "2023-08-15 TRO hearing",
                "2023-08-16 TRO order entered",
            ],
        ),
    )
    write_json(
        BOYD_PI_ORDER_EXTRACT,
        build_order_extract(
            source_id="san-rafael-boyd-preliminary-injunction-order",
            manifest_path=BOYD_PI_ORDER_MANIFEST,
            text_path=BOYD_PI_ORDER_TEXT,
            artifact_path="data/raw/san-rafael-boyd-preliminary-injunction-order/2026-04-12/order.pdf",
            title="Order Granting in Part and Denying in Part Plaintiffs' Motion for Preliminary Injunction",
            published_at="2023-10-19",
            page_count=50,
            notes=[
                "Public filed-order copy surfaced through the Civil Rights Litigation Clearinghouse document page for ECF 98.",
                "Strong enough for substantive injunction terms and legal reasoning, but not a court-hosted artifact.",
            ],
            actor_hits=[
                "Boyd et al.",
                "City of San Rafael et al.",
                "Camp Integrity",
                "San Rafael Homeless Union",
            ],
            issue_hits=[
                "homelessness",
                "encampments",
                "camping ordinance",
                "Americans with Disabilities Act",
                "due process",
                "state-created-danger doctrine",
            ],
            legal_refs=[
                "Case No. 23-cv-04085-EMC",
                "Document 98",
                "preliminary injunction",
                "Martin v. City of Boise",
            ],
            procedural_dates=[
                "2023-09-06 preliminary injunction hearing",
                "2023-10-19 preliminary injunction order",
            ],
        ),
    )
    write_json(
        BOYD_DISMISSAL_ORDER_EXTRACT,
        build_order_extract(
            source_id="san-rafael-boyd-dismissal-order",
            manifest_path=BOYD_DISMISSAL_ORDER_MANIFEST,
            text_path=BOYD_DISMISSAL_ORDER_TEXT,
            artifact_path="data/raw/san-rafael-boyd-dismissal-order/2026-04-12/order.pdf",
            title="Order Granting Defendant's Motion to Dismiss",
            published_at="2024-08-07",
            page_count=9,
            notes=[
                "Direct court order PDF linked from the official San Rafael Boyd dismissal news release.",
                "This is the strongest court-origin Boyd record currently held in the repo.",
            ],
            actor_hits=[
                "Shaleeta Boyd, et al.",
                "City of San Rafael, et al.",
                "Camp Integrity",
                "San Rafael Homeless Union",
            ],
            issue_hits=[
                "homelessness",
                "encampments",
                "camping ordinance",
                "public property",
                "Americans with Disabilities Act",
                "state-created-danger doctrine",
            ],
            legal_refs=[
                "Case No. 23-cv-04085-EMC",
                "Chapter 19.50",
                "temporary restraining order",
                "preliminary injunction",
                "motion to dismiss",
            ],
            procedural_dates=[
                "2023-08-11 complaint filed",
                "2023-08-15 temporary restraining order granted",
                "2023-10-19 preliminary injunction granted in part",
                "2024-05-10 motion to dismiss filed",
                "2024-07-15 motion hearing",
                "2024-08-07 dismissal order",
            ],
        ),
    )
    write_json(OUTPUT_PATH, build_bundle())


if __name__ == "__main__":
    main()
