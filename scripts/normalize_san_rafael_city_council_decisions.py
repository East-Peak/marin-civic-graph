#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MINUTES_EXTRACT_DIR = ROOT / "data" / "extracted" / "san-rafael-city-council-minutes"
COUNCIL_BACKBONE_PATH = ROOT / "data" / "normalized" / "san-rafael-city-council-backbone-01" / "bundle-01.json"
CANONICAL_SEEDS_PATH = ROOT / "data" / "normalized" / "canonical-seeds-san-rafael-01.json"
CAMPAIGN_ACTORS_PATH = ROOT / "data" / "normalized" / "san-rafael-city-campaign-actors-01" / "bundle-01.json"
HOMELESSNESS_PATH = ROOT / "data" / "normalized" / "san-rafael-homelessness-01" / "bundle-01.json"
ELECTION_RECORDS_PATH = ROOT / "data" / "normalized" / "san-rafael-election-records-01" / "bundle-01.json"
OUTPUT_DIR = ROOT / "data" / "normalized" / "san-rafael-city-council-decisions-01"
OUTPUT_PATH = OUTPUT_DIR / "bundle-01.json"

CASE_STUDY_ID = "san-rafael-city-council-decisions-01"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"

HISTORICAL_ACTOR_RECORDS = [
    {
        "id": "record-san-rafael-november-8-2011-election-page",
        "record_class": "meeting_record",
        "record_type": "election_page",
        "source_id": "san-rafael-november-8-2011-election",
        "artifact_path": "data/raw/san-rafael-november-8-2011-election/2026-04-11/source.html",
        "source_url": "https://www.cityofsanrafael.org/november-8-2011-election/",
        "title": "November 8, 2011 Election - San Rafael",
        "capture_status": "captured_html",
    },
    {
        "id": "record-san-rafael-november-3-2015-election-page",
        "record_class": "meeting_record",
        "record_type": "election_page",
        "source_id": "san-rafael-november-3-2015-election",
        "artifact_path": "data/raw/san-rafael-november-3-2015-election/2026-04-11/source.html",
        "source_url": "https://www.cityofsanrafael.org/november-3-2015-election/",
        "title": "November 3, 2015 Election - San Rafael",
        "capture_status": "captured_html",
    },
]

HISTORICAL_ACTOR_SPECS = [
    {
        "id": "actor-gary-phillips",
        "name": "Gary O. Phillips",
        "actor_type": "person",
        "status": "promoted_from_official_election_and_minutes_records",
        "observed_labels": ["Gary O. Phillips", "Gary Phillips", "Mayor Phillips", "Phillips"],
        "evidence_record_ids": [
            "record-san-rafael-november-8-2011-election-page",
            "record-san-rafael-november-3-2015-election-page",
        ],
        "promotion_basis": "official_election_page_plus_minutes_vote_resolution",
    },
    {
        "id": "actor-andrew-mccullough",
        "name": "Andrew McCullough",
        "actor_type": "person",
        "status": "promoted_from_official_election_and_minutes_records",
        "observed_labels": [
            "Andrew McCullough",
            "Andrew Cuyugan McCullough",
            "Vice Mayor McCullough",
            "McCullough",
        ],
        "evidence_record_ids": [
            "record-san-rafael-november-8-2011-election-page",
            "record-san-rafael-november-3-2015-election-page",
        ],
        "promotion_basis": "official_election_page_plus_minutes_vote_resolution",
    },
]

EXCLUDED_MEETING_IDS = {
    "meeting-2024-08-19-san-rafael-city-council",
}

MANUAL_COUNCIL_ALIASES = {
    "kate": "actor-kate-colin",
    "colin": "actor-kate-colin",
    "gamblin": "actor-john-gamblin",
    "bushey": "actor-maribeth-bushey",
    "kertz": "actor-rachel-kertz",
    "lloren gulati": "actor-maika-llorens-gulati",
    "llorens gulati": "actor-maika-llorens-gulati",
    "hill": "actor-eli-hill",
    "phillips": "actor-gary-phillips",
    "mccullough": "actor-andrew-mccullough",
    "vice mayor mccullough": "actor-andrew-mccullough",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latest_json(directory: Path) -> Path:
    candidates = sorted(directory.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No JSON files found in {directory}")
    return candidates[-1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def clean_label(value: str) -> str:
    value = value.lower().strip()
    value = value.replace("-", " ")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = value.replace("mayor pro tem", "")
    value = value.replace("vice mayor", "")
    value = value.replace("councilmember", "")
    value = value.replace("mayor", "")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return " ".join(value.split())


def classify_outcome(outcome_text: str, resolution_numbers: list[str]) -> tuple[str, str]:
    outcome = outcome_text.lower()
    if "introduced the ordinance" in outcome:
        return "ordinance_introduction", "introduced"
    if "adopted resolution" in outcome or resolution_numbers:
        return "resolution_adoption", "adopted"
    if "approved minutes" in outcome or "approved as submitted" in outcome:
        return "minutes_approval", "approved"
    if "approved staff recommendation" in outcome:
        return "staff_recommendation_approval", "approved"
    if "accepted report" in outcome:
        return "report_acceptance", "accepted"
    if outcome.startswith("received"):
        return "direction_or_receipt", "received"
    if outcome.startswith("removed"):
        return "agenda_removal", "removed"
    if outcome.startswith("continued"):
        return "continuance", "continued"
    if outcome.startswith("appointed"):
        return "appointment", "appointed"
    if outcome.startswith("approved"):
        return "approval", "approved"
    if outcome.startswith("accepted"):
        return "acceptance", "accepted"
    return "decision", "recorded"


def classify_section_decision(title: str, motion_text: str) -> tuple[str, str]:
    title_lower = title.lower()
    motion_lower = motion_text.lower()
    if "consent" in title_lower or "consent calendar" in motion_lower:
        return "consent_calendar_approval", "approved"
    return "motion_approval", "approved"


def build_actor_lookup() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    canonical = load_json(CANONICAL_SEEDS_PATH)
    campaign_actors = load_json(CAMPAIGN_ACTORS_PATH)

    alias_to_actor: dict[str, str] = {}
    seat_service_by_actor: dict[str, dict[str, str]] = {}

    for actor in canonical["actor_candidates"]:
        labels = [actor["name"], *actor.get("observed_labels", []), *actor.get("aliases", [])]
        for label in labels:
            cleaned = clean_label(label)
            if cleaned:
                alias_to_actor[cleaned] = actor["id"]

    for actor in campaign_actors["actor_candidates"]:
        labels = [actor["name"], *actor.get("observed_labels", []), *actor.get("aliases", [])]
        for label in labels:
            cleaned = clean_label(label)
            if cleaned:
                alias_to_actor.setdefault(cleaned, actor["id"])

    for actor in HISTORICAL_ACTOR_SPECS:
        for label in [actor["name"], *actor.get("observed_labels", [])]:
            cleaned = clean_label(label)
            if cleaned:
                alias_to_actor[cleaned] = actor["id"]

    for alias, actor_id in MANUAL_COUNCIL_ALIASES.items():
        alias_to_actor[alias] = actor_id

    for seat_service in canonical["seat_service_candidates"]:
        ended_at = seat_service.get("ended_at")
        if ended_at:
            continue
        seat_service_by_actor[seat_service["actor_id"]] = {
            "seat_id": seat_service["seat_id"],
            "seat_service_id": seat_service["id"],
            "started_at": seat_service.get("started_at") or "",
        }

    return alias_to_actor, seat_service_by_actor


def load_excluded_meeting_ids() -> set[str]:
    excluded = set(EXCLUDED_MEETING_IDS)
    homelessness = load_json(HOMELESSNESS_PATH)
    excluded.update(candidate["id"] for candidate in homelessness.get("meeting_candidates", []))
    elections = load_json(ELECTION_RECORDS_PATH)
    for decision in elections.get("decision_candidates", []):
        meeting_id = decision.get("meeting_id")
        if meeting_id:
            excluded.add(meeting_id)
    return excluded


def build_minutes_record_ref(entry: dict[str, Any]) -> dict[str, Any]:
    meeting_kind = entry["meeting_kind"]
    title_suffix = f" ({meeting_kind.replace('_', ' ').title()})" if meeting_kind != "regular" else ""
    return {
        "id": entry["minutes_record_id"],
        "record_class": "meeting_record",
        "record_type": "minutes_pdf",
        "source_id": "san-rafael-city-council-minutes",
        "artifact_path": entry["pdf_artifact_path"],
        "meeting_id": entry["meeting_id"],
        "source_url": entry["minutes_url"],
        "title": f"San Rafael City Council minutes - {entry['meeting_date']}{title_suffix}",
        "capture_status": "captured_pdf_and_extracted_text",
        "text_artifact_path": entry["text_artifact_path"],
        "page_count": entry["page_count"],
        "line_count": entry["line_count"],
    }


def build_vote_rows(
    vote_summary: dict[str, list[str]],
    *,
    meeting_date: str,
    alias_to_actor: dict[str, str],
    seat_service_by_actor: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    votes: list[dict[str, Any]] = []
    unresolved: dict[str, list[str]] = {"aye": [], "no": [], "absent": [], "abstain": []}

    bucket_map = {
        "ayes": "aye",
        "noes": "no",
        "absent": "absent",
        "abstain": "abstain",
    }

    for raw_bucket, bucket_vote in bucket_map.items():
        for label in vote_summary.get(raw_bucket, []):
            actor_id = alias_to_actor.get(clean_label(label))
            if not actor_id:
                unresolved[bucket_vote].append(label)
                continue
            vote_row: dict[str, Any] = {
                "actor_id": actor_id,
                "vote": bucket_vote,
                "raw_label": label,
            }
            seat_service = seat_service_by_actor.get(actor_id)
            if seat_service and meeting_date >= seat_service["started_at"]:
                vote_row["seat_id"] = seat_service["seat_id"]
                vote_row["seat_service_id"] = seat_service["seat_service_id"]
            votes.append(vote_row)

    return votes, unresolved


def decision_title_from_item(item: dict[str, Any], outcome_text: str) -> str:
    if outcome_text:
        return outcome_text
    return item["title"]


def build_minutes_decision_id(meeting_id: str, item_key: str, suffix: str) -> str:
    return f"decision-{meeting_id.removeprefix('meeting-')}-{item_key}-{suffix}"


def main() -> None:
    minutes_extract_path = latest_json(MINUTES_EXTRACT_DIR)
    minutes_payload = load_json(minutes_extract_path)
    council_backbone = load_json(COUNCIL_BACKBONE_PATH)
    alias_to_actor, seat_service_by_actor = build_actor_lookup()
    excluded_meeting_ids = load_excluded_meeting_ids()

    meeting_ids = {meeting["id"] for meeting in council_backbone["meeting_candidates"]}
    if not meeting_ids:
        raise RuntimeError("Council backbone bundle does not contain meeting candidates")

    record_refs = [*HISTORICAL_ACTOR_RECORDS]
    actor_candidates: list[dict[str, Any]] = []
    agenda_item_candidates: list[dict[str, Any]] = []
    decision_candidates: list[dict[str, Any]] = []

    # Only promote the historical actors if they are actually used by resolved votes in this slice.
    used_historical_actor_ids: set[str] = set()
    skipped_meeting_count = 0
    unresolved_vote_name_counts: dict[str, int] = {}

    for entry in minutes_payload["minutes_records"]:
        if entry["meeting_id"] not in meeting_ids:
            continue
        record_refs.append(build_minutes_record_ref(entry))

        if entry["meeting_id"] in excluded_meeting_ids:
            skipped_meeting_count += 1
            continue

        section_blocks = [item for item in entry["agenda_items"] if item["block_type"] == "section"]
        section_block_by_key = {item["item_key"]: item for item in section_blocks}
        item_by_key = {item["item_key"]: item for item in entry["agenda_items"]}

        # Some recent minutes place the consent-calendar motion and roll call after the all-caps
        # heading but before the numbered "2. Consent Calendar Items" line. In those cases the
        # motion lands on the prior section during parsing and needs to be reassigned.
        for index, section_item in enumerate(section_blocks[:-1]):
            next_section = section_blocks[index + 1]
            if (
                section_item.get("motion")
                and any((section_item.get("vote_summary") or {}).values())
                and "consent calendar" in next_section["title"].lower()
                and not next_section.get("motion")
            ):
                next_section["motion"] = section_item["motion"]
                next_section["vote_summary"] = section_item["vote_summary"]
                section_item["motion"] = None
                section_item["vote_summary"] = {"ayes": [], "noes": [], "absent": [], "abstain": []}

        section_decision_ids: dict[str, str] = {}
        borrowed_vote_item_keys: set[str] = set()

        for item in entry["agenda_items"]:
            agenda_item_id = f"agenda-item-{entry['meeting_id'].removeprefix('meeting-')}-{item['item_key']}"
            agenda_item_candidates.append(
                {
                    "id": agenda_item_id,
                    "meeting_id": entry["meeting_id"],
                    "item_number": item["item_number"],
                    "section_number": item["section_number"],
                    "item_letter": item["item_letter"],
                    "title": item["title"],
                    "status": "parsed_from_minutes",
                    "heading": item.get("heading"),
                    "parent_item_key": item.get("parent_item_key"),
                    "evidence": [{"document_id": entry["minutes_record_id"]}],
                }
            )

            motion = item.get("motion")
            vote_summary = dict(item.get("vote_summary") or {})
            outcome_lines = item.get("outcome_lines") or []
            resolution_numbers = item.get("resolution_numbers") or []

            if (
                item["block_type"] == "section"
                and motion
                and not any(vote_summary.values())
                and "consent calendar" in item["title"].lower()
            ):
                vote_sources = [
                    item_by_key[subitem_key]
                    for subitem_key in item.get("subitem_keys", [])
                    if any((item_by_key[subitem_key].get("vote_summary") or {}).values())
                    and not item_by_key[subitem_key].get("motion")
                ]
                if vote_sources:
                    vote_summary = dict(vote_sources[-1]["vote_summary"])
                    borrowed_vote_item_keys.update(source["item_key"] for source in vote_sources)

            # Section-level decisions capture block votes like consent-calendar approval.
            if (
                item["block_type"] == "section"
                and motion
                and any(vote_summary.values())
            ):
                decision_type, status = classify_section_decision(item["title"], motion["motion_text"])
                votes, unresolved = build_vote_rows(
                    vote_summary,
                    meeting_date=entry["meeting_date"],
                    alias_to_actor=alias_to_actor,
                    seat_service_by_actor=seat_service_by_actor,
                )
                for vote in votes:
                    if vote["actor_id"] in {"actor-gary-phillips", "actor-andrew-mccullough"}:
                        used_historical_actor_ids.add(vote["actor_id"])
                for bucket, labels in unresolved.items():
                    unresolved_vote_name_counts[bucket] = unresolved_vote_name_counts.get(bucket, 0) + len(labels)

                decision_id = build_minutes_decision_id(
                    entry["meeting_id"],
                    item["item_key"],
                    slugify(decision_type),
                )
                section_decision_ids[item["item_key"]] = decision_id
                decision_candidates.append(
                    {
                        "id": decision_id,
                        "title": (
                            f"Approve {item['title']}"
                            if motion["motion_text"].lower() in {"approve the", "approve the."}
                            else motion["motion_text"]
                        ),
                        "decision_type": decision_type,
                        "status": status,
                        "institution_id": "inst-san-rafael-city-council",
                        "meeting_id": entry["meeting_id"],
                        "agenda_item_id": agenda_item_id,
                        "effective_date": entry["meeting_date"],
                        "motion_text": motion["motion_text"],
                        "moved_by_name": motion["moved_by_raw"],
                        "seconded_by_name": motion["seconded_by_raw"],
                        "resolution_numbers": resolution_numbers,
                        "votes": votes,
                        "unresolved_vote_names": unresolved,
                        "evidence": [{"document_id": entry["minutes_record_id"]}],
                    }
                )

            if item["block_type"] != "subitem":
                continue

            outcome_text = outcome_lines[-1] if outcome_lines else ""
            if not outcome_text and not resolution_numbers and not motion:
                continue

            if outcome_text and outcome_text.lower().startswith("removed from agenda"):
                # Keep removal only at the section-vote layer when possible; avoid cluttering the citywide
                # decision timeline with staff-pulled items.
                continue

            decision_type, status = (
                classify_outcome(outcome_text, resolution_numbers)
                if outcome_text or resolution_numbers
                else classify_section_decision(item["title"], motion["motion_text"])
            )

            subitem_votes: list[dict[str, Any]] = []
            unresolved: dict[str, list[str]] = {"aye": [], "no": [], "absent": [], "abstain": []}
            if item["item_key"] not in borrowed_vote_item_keys and motion and any(vote_summary.values()):
                subitem_votes, unresolved = build_vote_rows(
                    vote_summary,
                    meeting_date=entry["meeting_date"],
                    alias_to_actor=alias_to_actor,
                    seat_service_by_actor=seat_service_by_actor,
                )
                for vote in subitem_votes:
                    if vote["actor_id"] in {"actor-gary-phillips", "actor-andrew-mccullough"}:
                        used_historical_actor_ids.add(vote["actor_id"])
                for bucket, labels in unresolved.items():
                    unresolved_vote_name_counts[bucket] = unresolved_vote_name_counts.get(bucket, 0) + len(labels)

            suffix_parts = [slugify(decision_type)]
            if resolution_numbers:
                suffix_parts.append("-".join(resolution_numbers))
            elif outcome_text:
                suffix_parts.append(slugify(outcome_text[:80]))
            decision_id = build_minutes_decision_id(
                entry["meeting_id"],
                item["item_key"],
                "-".join(part for part in suffix_parts if part),
            )

            decision_payload = {
                "id": decision_id,
                "title": decision_title_from_item(item, outcome_text),
                "decision_type": decision_type,
                "status": status,
                "institution_id": "inst-san-rafael-city-council",
                "meeting_id": entry["meeting_id"],
                "agenda_item_id": agenda_item_id,
                "effective_date": entry["meeting_date"],
                "resolution_numbers": resolution_numbers,
                "outcome_text": outcome_text or None,
                "evidence": [{"document_id": entry["minutes_record_id"]}],
            }
            if motion:
                decision_payload["motion_text"] = motion["motion_text"]
                decision_payload["moved_by_name"] = motion["moved_by_raw"]
                decision_payload["seconded_by_name"] = motion["seconded_by_raw"]
            if subitem_votes:
                decision_payload["votes"] = subitem_votes
                decision_payload["unresolved_vote_names"] = unresolved
            elif item.get("parent_item_key") in section_decision_ids:
                decision_payload["related_decision_id"] = section_decision_ids[item["parent_item_key"]]

            decision_candidates.append(decision_payload)

    for actor in HISTORICAL_ACTOR_SPECS:
        if actor["id"] in used_historical_actor_ids:
            actor_candidates.append(actor)

    payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": utc_now_iso(),
        "scope": [
            "San Rafael City Council 2019+ minutes-backed agenda-item and decision layer",
            "Conservative citywide decision extraction from captured minutes PDFs before packet-level deep parsing",
            "Section-level consent votes plus subitem outcomes, without inventing standalone roll calls for each consent subitem",
        ],
        "record_refs": record_refs,
        "actor_candidates": actor_candidates,
        "agenda_item_candidates": agenda_item_candidates,
        "decision_candidates": decision_candidates,
        "methodology_findings": [
            {
                "id": "method-council-decisions-minutes-first",
                "summary": "This bundle promotes agenda items and decisions from captured meeting minutes PDFs across the San Rafael council archive. It does not attempt full packet parsing or citywide record-splitting at this stage."
            },
            {
                "id": "method-council-decisions-consent-block-votes-are-section-level",
                "summary": "When minutes record one roll call for a consent-calendar block, the vote is attached to a section-level consent decision. Subitem outcomes remain as separate decisions linked back to that consent vote instead of receiving fabricated per-subitem roll calls."
            },
            {
                "id": "method-council-decisions-skips-meetings-already-covered-by-deeper-bundles",
                "summary": "Generic minutes-derived agenda items and decisions are not promoted for meetings already covered by deeper San Rafael bundles, including the August 19, 2024 homelessness package and the page-backed election-record meetings."
            },
        ],
        "open_questions": [
            {
                "id": "OQ-033",
                "status": "narrowed",
                "summary": "The citywide San Rafael council breadth slice now has a real minutes-backed agenda-item and decision layer, but vote precision still depends on minutes quality. Packet- and staff-report-level extraction is still needed for exact item boundaries, especially for complex multi-resolution consent items.",
            }
        ],
        "notes": [
            f"Minutes extract source: {minutes_extract_path.relative_to(ROOT)}",
            f"Skipped generic agenda/decision promotion for {skipped_meeting_count} meetings already covered by deeper bundles.",
            "Historical actor supplementation is intentionally narrow and only covers older officeholders needed to resolve recurring council vote labels in the 2019+ minutes corpus.",
        ],
        "summary": {
            "minutes_record_count": sum(
                1 for record in record_refs if record.get("source_id") == "san-rafael-city-council-minutes"
            ),
            "actor_candidate_count": len(actor_candidates),
            "agenda_item_count": len(agenda_item_candidates),
            "decision_count": len(decision_candidates),
            "decisions_with_votes": sum(1 for decision in decision_candidates if decision.get("votes")),
            "decisions_with_related_decision": sum(
                1 for decision in decision_candidates if decision.get("related_decision_id")
            ),
            "skipped_meeting_count": skipped_meeting_count,
            "unresolved_vote_name_counts": unresolved_vote_name_counts,
        },
    }

    write_json(OUTPUT_PATH, payload)


if __name__ == "__main__":
    main()
