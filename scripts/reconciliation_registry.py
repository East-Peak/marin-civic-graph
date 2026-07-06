"""Reconciliation registry loader.

`registry/reconciliation.json` is the single source for ledger status
actionability, operator-bench status buckets, and public key-source fields.
Validation is intentionally fail-loud, mirroring scripts/canonical_type.py:
missing or unknown structural keys reject instead of defaulting.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import identity_key_registry

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "registry" / "reconciliation.json"
)

EXPECTED_LEDGER_STATUSES: tuple[str, ...] = (
    "none",
    "requeued",
    "approved",
    "deterministic",
    "superseded",
    "rejected_current_evidence",
    "rejected_entity_distinct",
)
EXPECTED_ACTIONABILITY = frozenset({"actionable", "needs_review", "resolved"})
EXPECTED_TOP_LEVEL = frozenset(
    {"$comment", "ledger_statuses", "bench_display_buckets", "key_sources"}
)
EXPECTED_STATUS_KEYS = frozenset({"actionability"})
EXPECTED_BUCKET_KEYS = frozenset({"rejected", "done", "known_statuses"})
EXPECTED_KEY_SOURCE_KEYS = frozenset(
    {"source_id", "public_key_field", "anchor_prefix"}
)
EXPECTED_KEY_SOURCES = frozenset({"ein", "sos_id", "committee_id"})
EXPECTED_PUBLIC_KEY_FIELDS = {
    "ein": "registry_ein",
    "sos_id": "sos_id",
    "committee_id": "committee_id",
}
SESSION_ONLY_STATUSES = frozenset({"unsure"})


def _reject_unknown_keys(section: str, obj: dict[str, Any], expected: frozenset[str]) -> None:
    missing = expected - set(obj)
    unknown = set(obj) - expected
    if missing or unknown:
        raise ValueError(
            f"reconciliation registry {section}: missing {sorted(missing)} "
            f"unknown {sorted(unknown)}"
        )


def _validate_ledger_statuses(statuses: Any) -> None:
    if not isinstance(statuses, dict):
        raise ValueError("reconciliation registry ledger_statuses must be an object")
    if tuple(statuses) != EXPECTED_LEDGER_STATUSES:
        raise ValueError(
            "reconciliation registry ledger_statuses must be exactly "
            f"{list(EXPECTED_LEDGER_STATUSES)}, got {list(statuses)}"
        )
    for status, spec in statuses.items():
        if not isinstance(spec, dict):
            raise ValueError(f"ledger_statuses[{status!r}] must be an object")
        _reject_unknown_keys(f"ledger_statuses[{status!r}]", spec, EXPECTED_STATUS_KEYS)
        if spec["actionability"] not in EXPECTED_ACTIONABILITY:
            raise ValueError(
                f"ledger_statuses[{status!r}].actionability unknown: "
                f"{spec['actionability']!r}"
            )


def _validate_buckets(buckets: Any, ledger_statuses: dict[str, Any]) -> None:
    if not isinstance(buckets, dict):
        raise ValueError("reconciliation registry bench_display_buckets must be an object")
    _reject_unknown_keys("bench_display_buckets", buckets, EXPECTED_BUCKET_KEYS)
    known = tuple(buckets["known_statuses"])
    if set(known) != set(ledger_statuses) or len(known) != len(set(known)):
        raise ValueError(
            "bench_display_buckets.known_statuses membership must match ledger_statuses "
            f"exactly, got {buckets['known_statuses']!r}"
        )
    allowed_bucket_statuses = set(known) | set(SESSION_ONLY_STATUSES)
    for bucket_name in ("rejected", "done"):
        values = buckets[bucket_name]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"bench_display_buckets[{bucket_name!r}] must be a string list")
        duplicates = sorted({v for v in values if values.count(v) > 1})
        if duplicates:
            raise ValueError(
                f"bench_display_buckets[{bucket_name!r}] duplicate statuses: {duplicates}"
            )
        unknown = sorted(set(values) - allowed_bucket_statuses)
        if unknown:
            raise ValueError(
                f"bench_display_buckets[{bucket_name!r}] unknown statuses: {unknown}"
            )


def _identity_self_sources() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for entry in identity_key_registry.REGISTRY:
        if (
            entry.key_type in EXPECTED_KEY_SOURCES
            and entry.key_semantics == "self"
            and entry.dedup_eligibility
        ):
            out[entry.key_type] = {
                "source_id": entry.key_type,
                "anchor_prefix": entry.anchor_prefix,
            }
    return out


def _validate_key_sources(key_sources: Any) -> None:
    if not isinstance(key_sources, dict):
        raise ValueError("reconciliation registry key_sources must be an object")
    if set(key_sources) != EXPECTED_KEY_SOURCES:
        raise ValueError(
            f"reconciliation registry key_sources must be exactly "
            f"{sorted(EXPECTED_KEY_SOURCES)}, got {sorted(key_sources)}"
        )
    identity_sources = _identity_self_sources()
    for source, spec in key_sources.items():
        if not isinstance(spec, dict):
            raise ValueError(f"key_sources[{source!r}] must be an object")
        _reject_unknown_keys(f"key_sources[{source!r}]", spec, EXPECTED_KEY_SOURCE_KEYS)
        for key, value in spec.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"key_sources[{source!r}][{key!r}] must be a non-empty string")
        if spec["source_id"] != source:
            raise ValueError(
                f"key_sources[{source!r}].source_id must equal {source!r}, "
                f"got {spec['source_id']!r}"
            )
        if spec["public_key_field"] != EXPECTED_PUBLIC_KEY_FIELDS[source]:
            raise ValueError(
                f"key_sources[{source!r}].public_key_field drift: "
                f"{spec['public_key_field']!r} vs {EXPECTED_PUBLIC_KEY_FIELDS[source]!r}"
            )
        expected_identity = identity_sources.get(source)
        actual_identity = {
            "source_id": spec["source_id"],
            "anchor_prefix": spec["anchor_prefix"],
        }
        if actual_identity != expected_identity:
            raise ValueError(
                f"key_sources[{source!r}] drift from identity_key_registry: "
                f"{actual_identity!r} vs {expected_identity!r}"
            )


def load_registry(path: Path | str | None = None) -> dict[str, Any]:
    """Load and validate registry/reconciliation.json."""
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    with registry_path.open(encoding="utf-8") as f:
        registry = json.load(f)

    if not isinstance(registry, dict):
        raise ValueError("reconciliation registry must be an object")
    _reject_unknown_keys("top level", registry, EXPECTED_TOP_LEVEL)
    _validate_ledger_statuses(registry["ledger_statuses"])
    _validate_buckets(registry["bench_display_buckets"], registry["ledger_statuses"])
    _validate_key_sources(registry["key_sources"])
    return registry


_REGISTRY = load_registry()

LEDGER_ACTIONABILITY: dict[str, str] = {
    status: spec["actionability"]
    for status, spec in _REGISTRY["ledger_statuses"].items()
}
BENCH_BUCKETS: dict[str, tuple[str, ...]] = {
    key: tuple(values)
    for key, values in _REGISTRY["bench_display_buckets"].items()
}
KEY_SOURCES: dict[str, dict[str, str]] = {
    key: dict(values)
    for key, values in _REGISTRY["key_sources"].items()
}
KEY_FIELD_BY_SOURCE: dict[str, str] = {
    spec["source_id"]: spec["public_key_field"]
    for spec in KEY_SOURCES.values()
}
ANCHOR_PREFIX_BY_SOURCE: dict[str, str] = {
    spec["source_id"]: spec["anchor_prefix"]
    for spec in KEY_SOURCES.values()
}
