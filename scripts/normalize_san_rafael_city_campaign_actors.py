#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

DISCOVERY_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "san-rafael-city-campaign-discovery-01" / "bundle-01.json"
)
IE_BUNDLE_PATH = ROOT / "data" / "normalized" / "san-rafael-city-campaign-ie-01" / "bundle-01.json"
CANONICAL_SEEDS_PATH = ROOT / "data" / "normalized" / "canonical-seeds-san-rafael-01.json"

OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-city-campaign-actors-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

CASE_STUDY_ID = "san-rafael-city-campaign-actors-01"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    discovery_bundle = load_json(DISCOVERY_BUNDLE_PATH)
    ie_bundle = load_json(IE_BUNDLE_PATH)
    canonical_seeds = load_json(CANONICAL_SEEDS_PATH)

    canonical_actor_ids = {row["id"] for row in canonical_seeds.get("actor_candidates", [])}

    actor_candidates: list[dict[str, Any]] = []

    for actor in discovery_bundle.get("actor_candidates", []):
        if actor["id"] in canonical_actor_ids:
            continue
        if actor.get("resolution_status") != "discovery_candidate":
            continue
        actor_candidates.append(
            {
                "id": actor["id"],
                "name": actor["name"],
                "actor_type": actor["actor_type"],
                "status": "promoted_from_discovery",
                "evidence_record_ids": actor["evidence_record_ids"],
                "promotion_basis": "page_backed_candidate_actor",
            }
        )

    for committee in ie_bundle.get("committee_candidates", []):
        actor_id = committee["actor_candidate_id"]
        if actor_id in canonical_actor_ids:
            continue
        actor_candidates.append(
            {
                "id": actor_id,
                "name": committee["name"],
                "actor_type": "political_committee",
                "status": "promoted_from_ie_title_layer",
                "evidence_record_ids": committee["evidence_record_ids"],
                "promotion_basis": "outside_spending_committee_title_layer",
                "source_committee_id": committee["id"],
            }
        )

    deduped: dict[str, dict[str, Any]] = {}
    for actor in actor_candidates:
        existing = deduped.get(actor["id"])
        if existing is None:
            deduped[actor["id"]] = actor
            continue
        existing["evidence_record_ids"] = sorted(
            set(existing.get("evidence_record_ids", [])) | set(actor.get("evidence_record_ids", []))
        )
        if "promotion_basis" in existing and "promotion_basis" in actor and existing["promotion_basis"] != actor["promotion_basis"]:
            existing["promotion_basis"] = f"{existing['promotion_basis']}; {actor['promotion_basis']}"

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "Strong page-backed San Rafael city-side campaign actors from the discovery layer that are not already canonical seeds",
            "Strong title-backed outside-spending committee actors from the San Rafael IE bundle that are not already canonical seeds",
            "Actor completeness only; no OCR-only vendor/payee names are promoted in this supplement",
        ],
        "actor_candidates": sorted(deduped.values(), key=lambda row: row["id"]),
        "methodology_findings": [
            {
                "id": "method-campaign-actors-strong-sources-only",
                "summary": "This supplement only promotes actors whose names are already stable in page-backed discovery records or IE title-layer records. OCR-only actor candidates remain out of graph-v1."
            }
        ],
        "open_questions": [
            {
                "id": "OQ-029",
                "status": "watch",
                "summary": "Graph-v1 still excludes OCR-only campaign actors such as vendor/payee labels until a stronger identity source or explicit OCR-promotion rule exists."
            }
        ],
        "notes": [
            "This bundle intentionally excludes actors already present in canonical-seeds-san-rafael-01.",
            "This bundle intentionally excludes OCR-only campaign actor candidates from the Form 460 schedule layer.",
        ],
    }

    write_json(OUTPUT_PATH, payload)


if __name__ == "__main__":
    main()
