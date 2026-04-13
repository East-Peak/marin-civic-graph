#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = ROOT / "registry" / "import-manifest.yaml"

NODE_TYPE_BY_PREFIX = {
    "actor-": "Actor",
    "agencyresponse-": "AgencyResponse",
    "agenda-item-": "AgendaItem",
    "case-": "Case",
    "casepart-": "CaseParticipation",
    "claim-": "Claim",
    "committee-": "Committee",
    "decision-": "Decision",
    "doc-": "Record",
    "eid-": "EconomicInterestDisclosure",
    "election-": "Election",
    "filing-": "Filing",
    "finding-": "Finding",
    "inst-": "Institution",
    "issue-": "Issue",
    "lead-": "Lead",
    "meeting-": "Meeting",
    "mention-": "Mention",
    "moneyflow-": "MoneyFlow",
    "oversightreport-": "OversightReport",
    "place-": "Place",
    "program-": "Program",
    "proceeding-": "Proceeding",
    "record-": "Record",
    "recommendation-": "Recommendation",
    "reliefrequest-": "ReliefRequest",
    "seat-": "Seat",
    "seatservice-": "SeatService",
    "validationcheck-": "ValidationCheck",
}

PROMOTION_RANK = {
    "review": 1,
    "candidate": 2,
    "promoted": 3,
    "canonical": 4,
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def read_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or DEFAULT_MANIFEST_PATH
    return load_json(manifest_path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def is_scalar_list(value: Any) -> bool:
    return isinstance(value, list) and all(is_scalar(item) for item in value)


def infer_node_type_from_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    for prefix, node_type in NODE_TYPE_BY_PREFIX.items():
        if value.startswith(prefix):
            return node_type
    return None


def derive_display_label(payload: dict[str, Any]) -> str:
    for key in ("name", "title", "summary", "role_label"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return payload["id"]


def sanitize_graph_properties(payload: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "id":
            continue
        if is_scalar(value):
            if value is not None:
                properties[key] = value
            continue
        if is_scalar_list(value) and value:
            properties[key] = value
    properties["payload_json"] = json.dumps(payload, sort_keys=True)
    return properties


def union_scalar_lists(left: list[Any], right: list[Any]) -> list[Any]:
    seen = set()
    merged: list[Any] = []
    for candidate in left + right:
        key = json.dumps(candidate, sort_keys=True) if isinstance(candidate, (dict, list)) else candidate
        if key in seen:
            continue
        seen.add(key)
        merged.append(candidate)
    return merged


def merge_property_maps(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    *,
    prefer_incoming: bool,
) -> tuple[dict[str, Any], list[str]]:
    merged = dict(existing)
    conflicts: list[str] = []
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
            continue
        current = merged[key]
        if current == value:
            continue
        if key == "payload_json":
            if prefer_incoming:
                merged[key] = value
            continue
        if key == "page" and isinstance(current, (int, float)) and isinstance(value, (int, float)):
            merged.pop("page", None)
            merged["pages"] = union_scalar_lists(merged.get("pages", []), [current, value])
            continue
        if key == "pages" and isinstance(current, list) and isinstance(value, list):
            merged[key] = union_scalar_lists(current, value)
            continue
        if isinstance(current, list) and isinstance(value, list):
            merged[key] = union_scalar_lists(current, value)
            continue
        if current in (None, "", []):
            merged[key] = value
            continue
        if value in (None, "", []):
            continue
        if prefer_incoming:
            merged[key] = value
        conflicts.append(key)
    return merged, conflicts


def cypher_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(cypher_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(f"{key}: {cypher_literal(val)}" for key, val in sorted(value.items()))
        return "{" + items + "}"
    raise TypeError(f"Unsupported Cypher literal: {type(value).__name__}")
