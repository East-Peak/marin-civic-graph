#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

CANONICAL_SEEDS_PATH = ROOT / "data" / "normalized" / "canonical-seeds-san-rafael-01.json"
CAMPAIGN_FORM460_SCHEDULE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-form460-schedules-01" / "bundle-01.json"
)
CAMPAIGN_FINANCE_SAMPLE_PATH = (
    ROOT / "data" / "normalized" / "campaign-finance-sample-basket-01" / "bundle-01.json"
)
HOMELESSNESS_CORE_PATH = ROOT / "data" / "normalized" / "san-rafael-homelessness-01" / "bundle-01.json"

OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-actor-completeness-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

CASE_STUDY_ID = "san-rafael-actor-completeness-01"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"

FORM460_TARGET_IDS = {
    "actor-anedot",
    "actor-four-waters-media-inc",
    "actor-pmcohen-public-affairs",
    "actor-paul-jensen",
    "actor-bruce-burtch",
    "actor-caran-cuneo",
    "actor-diana-maier",
}
CAMPAIGN_FINANCE_TARGET_IDS = {
    "actor-se-owens-and-company",
}
HOMELESSNESS_TARGET_IDS = {
    "actor-other-junk-co",
    "actor-wehope",
}

HOMELESSNESS_EVIDENCE_OVERRIDES = {
    "actor-other-junk-co": [
        "record-2024-08-19-contract-other-junk-co",
        "doc-2024-08-19-item-5a-report",
    ],
    "actor-wehope": [
        "record-2024-08-19-contract-wehope",
        "doc-2024-08-19-item-5a-report",
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def build_money_flow_evidence_index(bundle: dict[str, Any]) -> dict[str, list[str]]:
    evidence_by_actor: dict[str, set[str]] = {}
    for flow in bundle.get("money_flow_candidates", []):
        target_id = flow.get("to_actor_id")
        if not target_id:
            continue
        evidence_by_actor.setdefault(target_id, set()).update(flow.get("evidence_record_ids", []))
    return {actor_id: sorted(record_ids) for actor_id, record_ids in evidence_by_actor.items()}


def clean_name(name: str) -> str:
    cleaned = (
        name.replace("®", "")
        .replace("©", "")
        .replace("❑", "")
        .replace("✓", "")
        .replace("�", "")
        .strip()
    )
    return " ".join(cleaned.split())


def main() -> None:
    canonical_seeds = load_json(CANONICAL_SEEDS_PATH)
    form460_schedule_bundle = load_json(CAMPAIGN_FORM460_SCHEDULE_PATH)
    campaign_finance_sample_bundle = load_json(CAMPAIGN_FINANCE_SAMPLE_PATH)
    homelessness_bundle = load_json(HOMELESSNESS_CORE_PATH)

    canonical_actor_ids = {row["id"] for row in canonical_seeds.get("actor_candidates", [])}
    schedule_evidence_by_actor = build_money_flow_evidence_index(form460_schedule_bundle)

    actor_candidates: list[dict[str, Any]] = []

    for actor in form460_schedule_bundle.get("actor_candidates", []):
        if actor["id"] in canonical_actor_ids or actor["id"] not in FORM460_TARGET_IDS:
            continue
        evidence_record_ids = sorted(
            set(actor.get("evidence_record_ids", [])) | set(schedule_evidence_by_actor.get(actor["id"], []))
        )
        actor_candidates.append(
            {
                "id": actor["id"],
                "name": clean_name(actor["name"]),
                "actor_type": actor["actor_type"],
                "status": "promoted_for_graph_completeness",
                "observed_labels": actor.get("observed_labels", []),
                "evidence_record_ids": evidence_record_ids,
                "promotion_basis": "recurring_form460_vendor_platform_or_donor",
            }
        )

    sample_evidence_by_actor = build_money_flow_evidence_index(campaign_finance_sample_bundle)
    for actor in campaign_finance_sample_bundle.get("actor_candidates", []):
        if actor["id"] in canonical_actor_ids or actor["id"] not in CAMPAIGN_FINANCE_TARGET_IDS:
            continue
        evidence_record_ids = schedule_evidence_by_actor.get(actor["id"]) or sample_evidence_by_actor.get(actor["id"], [])
        actor_candidates.append(
            {
                "id": actor["id"],
                "name": clean_name(actor["name"]),
                "actor_type": actor["actor_type"],
                "status": "promoted_for_graph_completeness",
                "observed_labels": [actor["name"]],
                "evidence_record_ids": evidence_record_ids,
                "promotion_basis": "campaign_finance_sample_vendor",
            }
        )

    for actor in homelessness_bundle.get("actor_seed_records", []):
        if actor["id"] in canonical_actor_ids or actor["id"] not in HOMELESSNESS_TARGET_IDS:
            continue
        actor_candidates.append(
            {
                "id": actor["id"],
                "name": clean_name(actor["name"]),
                "actor_type": actor["actor_type"],
                "status": "promoted_for_graph_completeness",
                "observed_labels": [actor["name"]],
                "evidence_record_ids": HOMELESSNESS_EVIDENCE_OVERRIDES.get(actor["id"], []),
                "promotion_basis": "official_contract_counterparty_seed",
            }
        )

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "Recurring city-side campaign vendor/platform actors and a small set of repeated clean donor names referenced by live Form 460 money-flow edges",
            "High-signal contract counterparties already referenced by the San Rafael homelessness decision chain",
            "Graph-v1 completeness supplement only; no broad OCR donor promotion and no new alias person nodes",
        ],
        "actor_candidates": sorted(actor_candidates, key=lambda row: row["id"]),
        "methodology_findings": [
            {
                "id": "method-actor-completeness-v1-selected-recurring-orgs",
                "summary": "This supplement only promotes explicit recurring organization/business/nonprofit actors plus a very small set of repeated clean donor names that already sit inside live graph-v1 money-flow or contract edges. It does not widen into one-off OCR donors or role-alias placeholders."
            }
        ],
        "open_questions": [
            {
                "id": "OQ-029",
                "status": "watch",
                "summary": "After the narrow supplement and actor-alias remap, the remaining actor misses should be judged one by one for suppression, canonical promotion, or future vendor/platform expansion."
            }
        ],
        "notes": [
            "Raw officeholder alias IDs such as actor-mayor-kate should resolve through the canonical seed layer, not by adding duplicate alias actor nodes.",
            "This bundle is intentionally explicit and small so graph-v1 gains completeness without importing OCR-tainted actor noise.",
        ],
    }

    write_json(OUTPUT_PATH, payload)


if __name__ == "__main__":
    main()
