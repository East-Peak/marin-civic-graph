#!/usr/bin/env python3

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

BOYD_ORDER_PDF = (
    ROOT / "data" / "raw" / "san-rafael-boyd-dismissal-order" / "2026-04-12" / "order.pdf"
)
BOYD_ORDER_MANIFEST = (
    ROOT / "data" / "raw" / "san-rafael-boyd-dismissal-order" / "2026-04-12" / "manifest.json"
)
BOYD_ORDER_TEXT = ROOT / "data" / "extracted" / "san-rafael-boyd-dismissal-order" / "order.txt"
BOYD_ORDER_EXTRACT = (
    ROOT / "data" / "extracted" / "san-rafael-boyd-dismissal-order" / "2026-04-12.json"
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


def build_boyd_order_extract() -> dict:
    manifest = load_json(BOYD_ORDER_MANIFEST)
    text = BOYD_ORDER_TEXT.read_text()
    word_count = len(text.split())

    return {
        "source_id": "san-rafael-boyd-dismissal-order",
        "capture_id": manifest["capture_id"],
        "capture_date": "2026-04-12",
        "entry_url": manifest["entry_url"],
        "fetch_strategy": manifest["fetch_strategy"],
        "generated_at": utc_now_iso(),
        "artifacts": [
            {
                "artifact_path": "data/raw/san-rafael-boyd-dismissal-order/2026-04-12/order.pdf",
                "content_type": "application/pdf",
                "artifact_type": "pdf",
                "title": "Order Granting Defendant's Motion to Dismiss",
                "published_at": "2024-08-07",
                "page_count": 9,
                "court_name": "U.S. District Court, Northern District of California",
                "docket_number": "23-cv-04085-EMC",
                "text_path": "data/extracted/san-rafael-boyd-dismissal-order/order.txt",
                "word_count": word_count,
            }
        ],
        "candidate_signals": {
            "actor_hits": [
                "Shaleeta Boyd, et al.",
                "City of San Rafael, et al.",
                "Camp Integrity",
                "San Rafael Homeless Union",
            ],
            "place_hits": [
                "San Rafael",
                "Mahon Creek Path",
            ],
            "issue_hits": [
                "homelessness",
                "encampments",
                "camping ordinance",
                "public property",
                "Americans with Disabilities Act",
                "state-created-danger doctrine",
            ],
            "legal_refs": [
                "Case No. 23-cv-04085-EMC",
                "Chapter 19.50",
                "temporary restraining order",
                "preliminary injunction",
                "motion to dismiss",
            ],
            "procedural_dates": [
                "2023-08-11 complaint filed",
                "2023-08-15 temporary restraining order granted",
                "2023-10-19 preliminary injunction granted in part",
                "2024-05-10 motion to dismiss filed",
                "2024-07-15 motion hearing",
                "2024-08-07 dismissal order",
            ],
        },
        "notes": [
            "Direct court order PDF linked from the official San Rafael Boyd dismissal news release.",
            "This is the strongest court-origin Boyd record currently held in the repo.",
        ],
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
            "one court-origin dismissal order plus official city-side legal response records",
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
                "id": "actor-edward-m-chen",
                "name": "Edward M. Chen",
                "roles": [
                    "judge",
                ],
                "evidence_record_ids": [
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
                    "The first legal bundle centers on the dismissal-side court order and the city's own official summaries of the injunction, amendment, and implementation chain.",
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
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                ],
                "notes": [
                    "Order text says Judge Thompson granted the TRO four days after the August 11 complaint filing.",
                ],
            },
            {
                "id": "proceeding-boyd-preliminary-injunction-2023-10-19",
                "case_id": "case-boyd-v-city-of-san-rafael",
                "proceeding_type": "preliminary_injunction_order",
                "occurred_at": "2023-10-19",
                "status": "granted_in_part",
                "evidence_record_ids": [
                    "record-san-rafael-boyd-dismissal-order-2024-08-07",
                    "doc-2024-08-19-item-5a-report",
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
                "summary": "The first legal bundle now includes one true court-origin Boyd record: the August 7, 2024 dismissal order PDF linked directly from the official San Rafael dismissal release. Earlier TRO and preliminary injunction stages are still modeled from later official summaries and the dismissal order's procedural history, not from separately captured court orders."
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
                "status": "open",
                "summary": "The repo still lacks the operative August 2023 TRO order and the October 19, 2023 preliminary injunction order as direct court-origin records.",
                "why_it_matters": "The current Boyd timeline is strong enough for case, proceeding, and decision joins, but the most important constraint-side orders are still represented through later city summaries and the dismissal order's procedural history instead of their original court texts.",
                "next_evidence": "Capture a clean public docket or direct order surface for Docket Nos. 19 and 98, then replace summary-backed proceeding detail with direct court-order records.",
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
    write_json(BOYD_ORDER_EXTRACT, build_boyd_order_extract())
    write_json(OUTPUT_PATH, build_bundle())


if __name__ == "__main__":
    main()
