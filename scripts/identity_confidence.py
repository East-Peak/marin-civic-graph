"""Derived identity-confidence projection.

IdentityConfidence records are rebuildable read-side signals over verdict-feed
rows, read-model attach cases, graph collision context, and the assertion ledger.
They are never ledger truth and never publish SAME_AS edges.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from string import hexdigits
from typing import Any, Iterable, Mapping

from enrich_casos_keys import scan_for_forbidden
from identity_ledger import is_publishing, source_snapshot_hash
from reconciliation_refs import anchor_id_of, anchor_ref_of, literal_key_of, vendor_id_of, vendor_ref_of
from reconciliation_registry import CONFIDENCE_BANDS
from verdict_feed import (
    EVIDENCE_FIELDS,
    EVIDENCE_SOURCES,
    EVIDENCE_SUPPORTS,
    PROVENANCE_FIELDS,
    validate_row as validate_feed_row,
)

SCHEMA_VERSION = "identity-confidence-v1"
BANDS = frozenset({"high", "medium", "low"})
STATUSES = frozenset({"active", "superseded_by_assertion", "retired_contradicted", "stale"})
RECORD_FIELDS = frozenset({
    "schema_version",
    "id",
    "subject_ref",
    "target_ref",
    "band",
    "signals",
    "provenance",
    "evidence",
    "source_row",
    "reason",
    "status",
    "superseded_by",
    "computed_at",
    "source_snapshot_hash",
})
SIGNAL_FIELDS = frozenset({"verdict", "confidence", "corroborating_dimensions", "name_signal"})
SOURCE_ROW_FIELDS = frozenset({"run", "gid"})


def pair_digest(subject_ref: str, target_ref: str) -> str:
    """The pair-stable 16-hex digest used by IdentityConfidence ids."""
    return hashlib.sha1(f"{subject_ref}|{target_ref}".encode("utf-8")).hexdigest()[:16]


def _record_id(subject_ref: str, target_ref: str) -> str:
    return f"conf-{pair_digest(subject_ref, target_ref)}"


def _reject_unknown_keys(section: str, obj: Mapping[str, Any], expected: frozenset[str]) -> None:
    missing = expected - set(obj)
    unknown = set(obj) - expected
    if missing or unknown:
        raise ValueError(
            f"identity confidence {section}: missing {sorted(missing)} "
            f"unknown {sorted(unknown)}"
        )


def _require_non_empty_string(obj: Mapping[str, Any], field: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"identity confidence {field} must be a non-empty string")
    return value


def _validate_provenance(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("identity confidence provenance must be an object")
    missing = {"model", "run"} - set(value)
    unknown = set(value) - PROVENANCE_FIELDS
    if missing or unknown:
        raise ValueError(
            f"identity confidence provenance missing {sorted(missing)} "
            f"unknown {sorted(unknown)}"
        )
    for field in ("model", "run"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise ValueError(f"identity confidence provenance.{field} must be a non-empty string")
    if "tranche" in value and (
        not isinstance(value["tranche"], str) or not value["tranche"]
    ):
        raise ValueError("identity confidence provenance.tranche must be a non-empty string")


def _validate_dimensions(value: Any, *, section: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"identity confidence {section} must be a list")
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"identity confidence {section}[{i}] must be a non-empty string")


def _validate_evidence(value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError("identity confidence evidence must be a list")
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"identity confidence evidence[{i}] must be an object")
        missing = EVIDENCE_FIELDS - set(item)
        unknown = set(item) - EVIDENCE_FIELDS
        if missing or unknown:
            raise ValueError(
                f"identity confidence evidence[{i}] missing {sorted(missing)} "
                f"unknown {sorted(unknown)}"
            )
        if item["source"] not in EVIDENCE_SOURCES:
            raise ValueError(
                f"identity confidence evidence[{i}].source must be one of "
                f"{sorted(EVIDENCE_SOURCES)}"
            )
        if item["supports"] not in EVIDENCE_SUPPORTS:
            raise ValueError(
                f"identity confidence evidence[{i}].supports must be one of "
                f"{sorted(EVIDENCE_SUPPORTS)}"
            )
        if not isinstance(item["url_or_record_id"], str) or not item["url_or_record_id"]:
            raise ValueError(
                f"identity confidence evidence[{i}].url_or_record_id must be a non-empty string"
            )


def _validate_signals(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("identity confidence signals must be an object")
    _reject_unknown_keys("signals", value, SIGNAL_FIELDS)
    if value["verdict"] != "same":
        raise ValueError("identity confidence signals.verdict must be 'same'")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("identity confidence signals.confidence must be numeric")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("identity confidence signals.confidence must be in [0, 1]")
    _validate_dimensions(value["corroborating_dimensions"], section="signals.corroborating_dimensions")
    name_signal = value["name_signal"]
    if name_signal is not None and (not isinstance(name_signal, str) or not name_signal):
        raise ValueError("identity confidence signals.name_signal must be a string or null")


def _validate_source_row(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("identity confidence source_row must be an object")
    unknown = set(value) - SOURCE_ROW_FIELDS
    if "run" not in value or unknown:
        raise ValueError(
            f"identity confidence source_row missing "
            f"{sorted({'run'} - set(value))} unknown {sorted(unknown)}"
        )
    if not isinstance(value["run"], str) or not value["run"]:
        raise ValueError("identity confidence source_row.run must be a non-empty string")
    if "gid" in value and isinstance(value["gid"], bool):
        raise ValueError("identity confidence source_row.gid must be a string or integer")
    if "gid" in value and not isinstance(value["gid"], (str, int)):
        raise ValueError("identity confidence source_row.gid must be a string or integer")


def _validate_sha1(value: str) -> None:
    if len(value) != 40 or any(c not in hexdigits for c in value):
        raise ValueError("identity confidence source_snapshot_hash must be a sha1 hex string")


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate one IdentityConfidence v1 record and return it unchanged."""
    if not isinstance(record, dict):
        raise ValueError("identity confidence record must be an object")
    _reject_unknown_keys("record", record, RECORD_FIELDS)
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"identity confidence schema_version must be {SCHEMA_VERSION!r}")
    subject_ref = _require_non_empty_string(record, "subject_ref")
    target_ref = _require_non_empty_string(record, "target_ref")
    expected_id = _record_id(subject_ref, target_ref)
    if record["id"] != expected_id:
        raise ValueError(f"identity confidence id must be {expected_id!r}")
    if record["band"] not in BANDS:
        raise ValueError(f"identity confidence band must be one of {sorted(BANDS)}")
    _validate_signals(record["signals"])
    _validate_provenance(record["provenance"])
    _validate_evidence(record["evidence"])
    _validate_source_row(record["source_row"])
    if not isinstance(record["reason"], str):
        raise ValueError("identity confidence reason must be a string")
    if record["status"] not in STATUSES:
        raise ValueError(f"identity confidence status must be one of {sorted(STATUSES)}")
    superseded_by = record["superseded_by"]
    if record["status"] == "superseded_by_assertion":
        if not isinstance(superseded_by, str) or not superseded_by.startswith("assertion-"):
            raise ValueError("identity confidence superseded_by must be an assertion id")
    elif superseded_by is not None:
        raise ValueError("identity confidence superseded_by must be null unless superseded")
    _require_non_empty_string(record, "computed_at")
    _validate_sha1(_require_non_empty_string(record, "source_snapshot_hash"))

    violations = scan_for_forbidden(record)
    if violations:
        raise ValueError(f"identity confidence record failed redaction gate: {violations}")
    return record


def band_of(
    row: dict[str, Any],
    *,
    candidate_count: int,
    needs_careful_review: bool,
    key_collision: bool,
) -> str | None:
    """Derive the v1 confidence band for one verdict row."""
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or candidate_count < 1:
        raise ValueError("candidate_count must be a positive integer")
    verdict = row.get("verdict")
    if verdict != "same":
        if verdict in {"unsure", "different"}:
            return None
        raise ValueError("verdict must be 'same', 'unsure', or 'different'")
    confidence = row.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be numeric")
    dimensions = row.get("dimensions", [])
    _validate_dimensions(dimensions, section="dimensions")

    thresholds = CONFIDENCE_BANDS["thresholds"]
    high_min_confidence = float(thresholds["high_min_confidence"])
    medium_min_confidence = float(thresholds["medium_min_confidence"])
    high_min_dimensions = int(thresholds["high_min_dimensions"])

    checks = (
        ("high_confidence", float(confidence) >= high_min_confidence),
        ("high_dimensions", len(dimensions) >= high_min_dimensions),
        ("single_candidate", candidate_count == 1),
        ("not_careful", needs_careful_review is not True),
    )
    if key_collision:
        return "low"
    if all(ok for _name, ok in checks):
        return "high"
    failures = [name for name, ok in checks if not ok]
    if float(confidence) >= medium_min_confidence and len(failures) == 1:
        return "medium"
    return "low"


def _case_row(case: Any) -> dict[str, Any]:
    if isinstance(case, dict):
        return case
    if hasattr(case, "candidate_joins"):
        from reconciliation_read_model import build_case_row

        return build_case_row(case)
    raise ValueError(f"unsupported read-model case shape: {type(case)!r}")


def _join(case: dict[str, Any]) -> dict[str, Any]:
    joins = case.get("candidate_joins")
    if not isinstance(joins, list) or len(joins) != 1:
        raise ValueError(
            f"case {case.get('case_id', '<unknown>')!r} must contain exactly one candidate_join"
        )
    return joins[0]


def _index_cases(
    read_model_cases: Iterable[Any],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, int]]:
    by_feed_pair: dict[tuple[str, str], dict[str, Any]] = {}
    candidate_counts: dict[str, int] = {}
    rows = [_case_row(case) for case in read_model_cases]
    for case in rows:
        if case.get("case_type") != "identity_key_attach":
            continue
        vendor_id = vendor_id_of(case)
        candidate_counts[vendor_id] = candidate_counts.get(vendor_id, 0) + 1
    for case in rows:
        if case.get("case_type") != "identity_key_attach":
            continue
        key = (vendor_id_of(case), literal_key_of(case))
        if key in by_feed_pair:
            raise ValueError(f"duplicate read-model case for vendor/key {key!r}")
        by_feed_pair[key] = case
    return by_feed_pair, candidate_counts


def _snapshot_ref(entity_ref: dict[str, Any]) -> dict[str, Any]:
    fields = entity_ref.get("public_fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("read-model entity_ref.public_fields must be an object")
    local_id = entity_ref.get("local_id")
    if not isinstance(local_id, str) or not local_id:
        raise ValueError("read-model entity_ref.local_id must be a non-empty string")
    display_label = entity_ref.get("display_label") or fields.get("display_label") or local_id
    if not isinstance(display_label, str) or not display_label:
        raise ValueError("read-model entity_ref.display_label must be a non-empty string")
    out: dict[str, Any] = {"id": local_id, "display_label": display_label}
    for key in ("ein", "uei", "sos_id", "committee_id"):
        if fields.get(key) is not None:
            out[key] = fields[key]
    if fields.get("registry_ein") is not None and "ein" not in out:
        out["ein"] = fields["registry_ein"]
    return out


def _name_signal(case: dict[str, Any]) -> str | None:
    signals = _join(case).get("signals", [])
    if not isinstance(signals, list):
        raise ValueError("read-model candidate_join.signals must be a list")
    for signal in signals:
        if not isinstance(signal, str):
            raise ValueError("read-model candidate_join.signals entries must be strings")
        if signal == "normalized_name_exact" or signal.startswith("name_") or signal.startswith("name_similarity"):
            return signal
    return signals[0] if signals else None


def _source_row(row: dict[str, Any]) -> dict[str, Any]:
    source_row: dict[str, Any] = {"run": row["provenance"]["run"]}
    if "gid" in row:
        source_row["gid"] = row["gid"]
    return source_row


def _live_publishing_assertion(
    ledger_assertions: Iterable[dict[str, Any]],
    *,
    subject_ref: str,
    target_ref: str,
) -> dict[str, Any] | None:
    matches = [
        assertion
        for assertion in ledger_assertions
        if assertion.get("subject_ref") == subject_ref
        and assertion.get("target_ref") == target_ref
        and assertion.get("superseded_by") is None
        and is_publishing(assertion)
    ]
    if len(matches) > 1:
        raise ValueError(f"multiple live publishing assertions for pair {subject_ref!r}|{target_ref!r}")
    return matches[0] if matches else None


def _context_for(context_by_vendor: Mapping[str, Any], vendor_id: str) -> dict[str, Any]:
    entry = context_by_vendor.get(vendor_id, {})
    if not isinstance(entry, dict):
        raise ValueError(f"context_by_vendor[{vendor_id!r}] must be an object")
    return entry


def build_confidence(
    feed_rows: Iterable[dict[str, Any]],
    read_model_cases: Iterable[Any],
    ledger_assertions: Iterable[dict[str, Any]],
    context_by_vendor: Mapping[str, Any],
    *,
    computed_at: str,
) -> list[dict[str, Any]]:
    """Build IdentityConfidence records from verdict feed rows."""
    if not isinstance(computed_at, str) or not computed_at:
        raise ValueError("computed_at must be caller-supplied as a non-empty string")
    case_by_feed_pair, candidate_counts = _index_cases(read_model_cases)
    ledger = list(ledger_assertions)
    context = dict(context_by_vendor or {})
    records: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for raw in feed_rows:
        row = validate_feed_row(dict(raw))
        if row["verdict"] != "same":
            continue
        feed_pair = (row["vendor_id"], str(row["proposed_key"]))
        case = case_by_feed_pair.get(feed_pair)
        if case is None:
            raise ValueError(f"no read-model case for verdict feed pair {feed_pair!r}")
        subject_ref = anchor_id_of(case)
        target_ref = vendor_id_of(case)
        pair = (subject_ref, target_ref)
        if pair in seen_pairs:
            raise ValueError(f"duplicate confidence pair {pair!r}")
        seen_pairs.add(pair)

        vendor_context = _context_for(context, target_ref)
        candidate_count = int(
            vendor_context.get("candidate_count", candidate_counts.get(target_ref, 0))
        )
        needs_careful_review = bool(case.get("review_flags", {}).get("needs_careful_review", False))
        key_collision = bool(vendor_context.get("key_collision", False))
        band = band_of(
            row,
            candidate_count=candidate_count,
            needs_careful_review=needs_careful_review,
            key_collision=key_collision,
        )
        if band is None:
            continue

        live_assertion = _live_publishing_assertion(
            ledger,
            subject_ref=subject_ref,
            target_ref=target_ref,
        )
        status = "superseded_by_assertion" if live_assertion is not None else "active"
        subject = _snapshot_ref(anchor_ref_of(case))
        target = _snapshot_ref(vendor_ref_of(case))
        record = {
            "schema_version": SCHEMA_VERSION,
            "id": _record_id(subject_ref, target_ref),
            "subject_ref": subject_ref,
            "target_ref": target_ref,
            "band": band,
            "signals": {
                "verdict": row["verdict"],
                "confidence": float(row["confidence"]),
                "corroborating_dimensions": list(row.get("dimensions", [])),
                "name_signal": _name_signal(case),
            },
            "provenance": dict(row["provenance"]),
            "evidence": [dict(item) for item in row.get("evidence", [])],
            "source_row": _source_row(row),
            "reason": row.get("reason", ""),
            "status": status,
            "superseded_by": live_assertion["id"] if live_assertion is not None else None,
            "computed_at": computed_at,
            "source_snapshot_hash": source_snapshot_hash(subject, target),
        }
        records.append(validate_record(record))
    return records


def write_confidence(records: Iterable[dict[str, Any]], path: str | Path) -> None:
    """Write deterministic sorted IdentityConfidence JSONL atomically."""
    path = Path(path)
    validated = [validate_record(dict(record)) for record in records]
    ids = [record["id"] for record in validated]
    duplicates = sorted({record_id for record_id in ids if ids.count(record_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate identity confidence ids: {duplicates}")
    rows = sorted(validated, key=lambda record: record["id"])
    body = "".join(json.dumps(record, sort_keys=True) + "\n" for record in rows)
    violations = scan_for_forbidden(body)
    if violations:
        raise ValueError(f"identity confidence JSONL failed redaction gate: {violations}")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
