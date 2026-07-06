"""Versioned reconciliation verdict feed.

The verdict feed is an audit-chain input, not an incidental JSONL convention:
duplicates are explicit, schema validation is fail-loud, and researcher free text
passes through the same redaction scanner as published reconciliation artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from enrich_casos_keys import scan_for_forbidden
from identity_key_registry import ANCHOR_PREFIXES

SCHEMA_VERSION = "verdict-feed-v1"
VERDICTS = frozenset({"same", "different", "unsure"})
VERIFICATION_FIELDS = frozenset({"verify_ok", "refuted", "ks_valid", "key_sighted"})
PROVENANCE_FIELDS = frozenset({"model", "run", "tranche"})
OPTIONAL_FIELDS = frozenset(
    {"verification", "reason", "source_proposed_key", "gid", "auto_candidate"}
)
REQUIRED_FIELDS = frozenset(
    {"schema_version", "vendor_id", "proposed_key", "verdict", "confidence", "provenance"}
)


class VerdictFeedConflictError(ValueError):
    """Raised when two rows assert different verdict data for the same pair."""


def _strip_anchor_prefix(value: Any) -> str:
    key = str(value)
    for prefix in ANCHOR_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix):]
    return key


def _require_string(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"verdict feed {field} must be a non-empty string")
    return value


def _validate_provenance(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("verdict feed provenance must be an object")
    missing = {"model", "run"} - set(value)
    unknown = set(value) - PROVENANCE_FIELDS
    if missing or unknown:
        raise ValueError(
            f"verdict feed provenance missing {sorted(missing)} unknown {sorted(unknown)}"
        )
    for field in ("model", "run"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise ValueError(f"verdict feed provenance.{field} must be a non-empty string")
    if "tranche" in value and (
        not isinstance(value["tranche"], str) or not value["tranche"]
    ):
        raise ValueError("verdict feed provenance.tranche must be a non-empty string")


def _validate_verification(value: Any) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("verdict feed verification must be a non-empty object")
    unknown = set(value) - VERIFICATION_FIELDS
    if unknown:
        raise ValueError(f"verdict feed verification unknown fields: {sorted(unknown)}")
    for field, field_value in value.items():
        if not isinstance(field_value, bool):
            raise ValueError(f"verdict feed verification.{field} must be a boolean")


def validate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Validate one v1 verdict row and return it unchanged."""
    if not isinstance(row, dict):
        raise ValueError("verdict feed row must be an object")
    missing = REQUIRED_FIELDS - set(row)
    unknown = set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS
    if missing or unknown:
        raise ValueError(
            f"verdict feed row missing {sorted(missing)} unknown {sorted(unknown)}"
        )
    if row.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"verdict feed schema_version must be {SCHEMA_VERSION!r}")
    _require_string(row, "vendor_id")
    proposed_key = _require_string(row, "proposed_key")
    if _strip_anchor_prefix(proposed_key) != proposed_key:
        raise ValueError("verdict feed proposed_key must be literal, not anchor-prefixed")
    verdict = row.get("verdict")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict feed verdict must be one of {sorted(VERDICTS)}")
    confidence = row.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("verdict feed confidence must be numeric")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("verdict feed confidence must be in [0, 1]")
    _validate_provenance(row.get("provenance"))
    if "verification" in row:
        _validate_verification(row["verification"])
    if "reason" in row and not isinstance(row["reason"], str):
        raise ValueError("verdict feed reason must be a string")
    if "source_proposed_key" in row and not isinstance(row["source_proposed_key"], str):
        raise ValueError("verdict feed source_proposed_key must be a string")
    if "auto_candidate" in row and not isinstance(row["auto_candidate"], bool):
        raise ValueError("verdict feed auto_candidate must be a boolean")

    violations = scan_for_forbidden(row)
    if violations:
        raise ValueError(f"verdict feed row failed redaction gate: {violations}")
    return row


def _clean_provenance(defaults: dict[str, Any] | None, row: dict[str, Any]) -> dict[str, str]:
    defaults = defaults or {}
    model = row.get("model") or defaults.get("model") or row.get("adjudicator") or row.get("researcher")
    run = (
        row.get("adjudicator_version")
        or defaults.get("run")
        or row.get("researched_at")
        or row.get("accessed_at")
        or row.get("researcher")
    )
    provenance = {
        "model": str(model or "legacy-verdict-feed"),
        "run": str(run or "legacy"),
    }
    tranche = row.get("tranche") or defaults.get("tranche")
    if tranche is not None:
        provenance["tranche"] = str(tranche)
    return provenance


def _verification_from_legacy(row: dict[str, Any]) -> dict[str, bool]:
    verification: dict[str, bool] = {}
    for field in ("verify_ok", "ks_valid", "key_sighted"):
        if isinstance(row.get(field), bool):
            verification[field] = row[field]
    refuted = row.get("refuted")
    if not isinstance(refuted, bool):
        verifier = row.get("verifier")
        if isinstance(verifier, dict):
            refuted = verifier.get("refuted")
    if isinstance(refuted, bool):
        verification["refuted"] = refuted
    return verification


def upgrade_legacy(
    row: dict[str, Any],
    *,
    provenance_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapt a legacy pilot/scale/tranche verdict row into verdict-feed-v1."""
    if row.get("schema_version") == SCHEMA_VERSION:
        return validate_row(dict(row))

    if "literal_key" in row and row.get("literal_key") not in (None, ""):
        proposed_key = str(row["literal_key"])
    else:
        proposed_key = _strip_anchor_prefix(row.get("proposed_key", ""))
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "vendor_id": str(row.get("vendor_id", "")),
        "proposed_key": proposed_key,
        "verdict": row.get("verdict"),
        "confidence": row.get("confidence"),
        "provenance": _clean_provenance(provenance_defaults, row),
    }

    verification = _verification_from_legacy(row)
    if verification:
        out["verification"] = verification
    for field in ("reason", "gid", "auto_candidate"):
        if field in row and row[field] is not None:
            out[field] = row[field]

    source_key = row.get("source_proposed_key", row.get("proposed_key"))
    if source_key is not None and str(source_key) != proposed_key:
        out["source_proposed_key"] = str(source_key)

    return validate_row(out)


def _coerce_row(
    row: dict[str, Any],
    *,
    provenance_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if row.get("schema_version") == SCHEMA_VERSION:
        return validate_row(dict(row))
    return upgrade_legacy(row, provenance_defaults=provenance_defaults)


def _canonical(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True)


def _conflict_fields(first: dict[str, Any], second: dict[str, Any]) -> list[str]:
    fields = []
    for field in ("confidence", "verdict", "verification"):
        if first.get(field) != second.get(field):
            fields.append(field)
    return sorted(fields)


def summarize_conflicts(
    rows: Iterable[dict[str, Any]],
    *,
    provenance_defaults: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return duplicate pair conflicts without applying last-write-wins."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for raw in rows:
        row = _coerce_row(raw, provenance_defaults=provenance_defaults)
        pair = (row["vendor_id"], row["proposed_key"])
        existing = seen.get(pair)
        if existing is None:
            seen[pair] = row
            continue
        if _canonical(existing) == _canonical(row):
            continue
        conflicts.append({
            "vendor_id": pair[0],
            "proposed_key": pair[1],
            "fields": _conflict_fields(existing, row),
            "first": existing,
            "second": row,
        })
    return conflicts


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_feed(
    paths: Iterable[str | Path] | str | Path,
    *,
    provenance_defaults: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Load verdict JSONL files, collapsing only byte-identical duplicate rows."""
    out: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(paths, (str, Path)):
        paths = [paths]
    for path in paths:
        defaults = {"model": "legacy-verdict-feed", "run": "legacy"}
        if provenance_defaults:
            defaults.update(provenance_defaults)
        for raw in _read_jsonl(path):
            row = _coerce_row(raw, provenance_defaults=defaults)
            pair = (row["vendor_id"], row["proposed_key"])
            existing = seen.get(pair)
            if existing is None:
                seen[pair] = row
                out.append(row)
                continue
            if _canonical(existing) == _canonical(row):
                continue
            raise VerdictFeedConflictError(
                "conflicting verdict feed duplicate for "
                f"vendor_id={pair[0]!r} proposed_key={pair[1]!r}: "
                f"first={_canonical(existing)} second={_canonical(row)}"
            )
    return out
