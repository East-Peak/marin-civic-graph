"""Byte-pinned reconciliation parity fixtures for the R1 accessor refactor.

These fixtures deliberately pin the exact bytes emitted by the current read-model
and auto-policy preview paths before any accessor rewiring. Later R1 changes may
move the pair/key convention behind helpers, but they must not change these bytes.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconcile_auto_policy as auto_policy  # noqa: E402
import reconciliation_read_model as read_model  # noqa: E402
import verdict_feed  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recon_byte_fixtures"
POLICY_HASH = "h-recon-r1a-fixture-policy"

READ_MODEL_SHA256 = "4ab5cd32cd21c89dce145e7dc93ffc284b6de785c30f1590da6f9cac0779b6ac"
AUTO_PREVIEW_SHA256 = "29d85e64b6ce9a88a4a0daeb65bc71a0121301e128acdb2a5f09728eff1443d0"


def _load_jsonl(name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_model_bytes() -> bytes:
    cases = read_model.build_attach_read_model(
        _load_jsonl("mixed-candidates.jsonl"),
        verdict_rows=_load_jsonl("read-model-verdicts.jsonl"),
    )
    return "".join(read_model.emit_jsonl(cases)).encode("utf-8")


def _read_model_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _read_model_bytes().decode("utf-8").splitlines()]


def _auto_preview_bytes() -> bytes:
    preview = auto_policy.build_preview(
        verdict_rows=_load_jsonl("auto-policy-verdicts.jsonl"),
        second_research_rows=_load_json("auto-policy-second-research.json")["results"],
        read_model_cases=_read_model_rows(),
        context_by_vendor=_load_json("auto-policy-context.json"),
        policy_hash=POLICY_HASH,
    )
    return (json.dumps(preview, indent=2, sort_keys=True) + "\n").encode("utf-8")


def test_read_model_byte_fixture_hash_is_pinned():
    actual = _read_model_bytes()
    assert _sha256(actual) == READ_MODEL_SHA256
    assert actual == (FIXTURES / "expected-read-model.jsonl").read_bytes()


def test_auto_policy_preview_byte_fixture_hash_is_pinned():
    actual = _auto_preview_bytes()
    assert _sha256(actual) == AUTO_PREVIEW_SHA256
    assert actual == (FIXTURES / "expected-auto-policy-preview.json").read_bytes()


def test_read_model_bytes_unchanged_with_v1_verdict_feed_rows():
    v1_verdicts = [
        verdict_feed.upgrade_legacy(
            row,
            provenance_defaults={"model": "byte-fixture", "run": "read-model"},
        )
        for row in _load_jsonl("read-model-verdicts.jsonl")
    ]
    cases = read_model.build_attach_read_model(
        _load_jsonl("mixed-candidates.jsonl"),
        verdict_rows=v1_verdicts,
    )
    actual = "".join(read_model.emit_jsonl(cases)).encode("utf-8")

    assert _sha256(actual) == READ_MODEL_SHA256
    assert actual == (FIXTURES / "expected-read-model.jsonl").read_bytes()


def test_auto_policy_preview_bytes_unchanged_with_v1_verdict_feed_rows():
    v1_verdicts = [
        verdict_feed.upgrade_legacy(
            row,
            provenance_defaults={"model": "byte-fixture", "run": "auto-policy"},
        )
        for row in _load_jsonl("auto-policy-verdicts.jsonl")
    ]
    preview = auto_policy.build_preview(
        verdict_rows=v1_verdicts,
        second_research_rows=_load_json("auto-policy-second-research.json")["results"],
        read_model_cases=_read_model_rows(),
        context_by_vendor=_load_json("auto-policy-context.json"),
        policy_hash=POLICY_HASH,
    )
    actual = (json.dumps(preview, indent=2, sort_keys=True) + "\n").encode("utf-8")

    assert _sha256(actual) == AUTO_PREVIEW_SHA256
    assert actual == (FIXTURES / "expected-auto-policy-preview.json").read_bytes()
