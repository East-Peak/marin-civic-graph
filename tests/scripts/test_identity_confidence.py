"""C1b identity-confidence projection tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import identity_confidence as ic  # noqa: E402
from identity_ledger import make_assertion, source_snapshot_hash  # noqa: E402


COMPUTED_AT = "2026-07-06T12:00:00Z"


def _case(
    vendor: str = "org-marincontract-recipient-alpha",
    key: str = "0123456",
    *,
    anchor: str | None = None,
    signals: list[str] | None = None,
    careful: bool = False,
) -> dict:
    anchor_id = anchor or f"org-casos-{key}"
    return {
        "schema_version": "recon-read-model-v2",
        "case_id": f"attach|{anchor_id}|{vendor}",
        "case_type": "identity_key_attach",
        "candidate_joins": [
            {
                "candidate_id": f"{anchor_id}|{vendor}",
                "left_ref": {
                    "source_id": "sos_id",
                    "local_id": vendor,
                    "display_label": "County Vendor Alpha",
                    "public_fields": {"display_label": "County Vendor Alpha"},
                    "provenance": {"adapter": "sos_id", "vendor_ref": vendor},
                },
                "right_ref": {
                    "source_id": "sos_id",
                    "local_id": anchor_id,
                    "display_label": "Alpha Services LLC",
                    "public_fields": {
                        "display_label": "Alpha Services LLC",
                        "sos_id": key,
                        "entity_status": "Active",
                    },
                    "provenance": {"adapter": "sos_id", "anchor_ref": anchor_id},
                },
                "signals": signals if signals is not None else ["normalized_name_exact"],
                "signal_strength": 0.9,
            }
        ],
        "current_ledger_status": "none",
        "ledger_assertion_refs": [],
        "review_flags": {"needs_careful_review": careful},
    }


def _feed(
    vendor: str = "org-marincontract-recipient-alpha",
    key: str = "0123456",
    *,
    verdict: str = "same",
    confidence: float = 0.86,
    dimensions: list[str] | None = None,
    evidence: list[dict] | None = None,
    provenance: dict | None = None,
    reason: str = "same org based on public records",
    gid: int = 1487,
) -> dict:
    return {
        "schema_version": "verdict-feed-v1",
        "vendor_id": vendor,
        "proposed_key": key,
        "verdict": verdict,
        "confidence": confidence,
        "dimensions": dimensions
        if dimensions is not None
        else ["service_domain", "county_payment_context"],
        "evidence": evidence
        if evidence is not None
        else [
            {
                "source": "county_open_data",
                "supports": "same",
                "url_or_record_id": "record-county-contract-alpha",
            }
        ],
        "provenance": provenance or {"model": "research-fleet", "run": "run-a"},
        "reason": reason,
        "gid": gid,
    }


@pytest.mark.parametrize(
    ("row", "candidate_count", "careful", "collision", "expected"),
    [
        (_feed(confidence=0.80), 1, False, False, "high"),
        (_feed(verdict="unsure"), 1, False, False, None),
        (_feed(verdict="different"), 1, False, False, None),
        (_feed(confidence=0.99), 1, False, True, "low"),
        (_feed(confidence=0.70), 1, False, False, "medium"),
        (_feed(dimensions=["service_domain"]), 1, False, False, "medium"),
        (_feed(), 2, False, False, "medium"),
        (_feed(), 1, True, False, "medium"),
        (_feed(confidence=0.64), 1, False, False, "low"),
        (_feed(confidence=0.70, dimensions=[]), 2, False, False, "low"),
    ],
)
def test_band_of_table_covers_spec_branches(row, candidate_count, careful, collision, expected):
    assert ic.band_of(
        row,
        candidate_count=candidate_count,
        needs_careful_review=careful,
        key_collision=collision,
    ) == expected


def test_band_of_reads_thresholds_from_registry(monkeypatch):
    monkeypatch.setitem(ic.CONFIDENCE_BANDS["thresholds"], "high_min_confidence", 0.90)

    assert ic.band_of(
        _feed(confidence=0.86),
        candidate_count=1,
        needs_careful_review=False,
        key_collision=False,
    ) == "medium"


def test_pair_stable_id_and_snapshot_are_idempotent_across_provenance_changes():
    case = _case()
    first = ic.build_confidence(
        [_feed(provenance={"model": "research-fleet", "run": "run-a"})],
        [case],
        [],
        {},
        computed_at=COMPUTED_AT,
    )[0]
    second = ic.build_confidence(
        [_feed(provenance={"model": "research-fleet", "run": "run-b"})],
        [case],
        [],
        {},
        computed_at=COMPUTED_AT,
    )[0]

    assert first["id"] == second["id"] == "conf-" + ic.pair_digest(
        "org-casos-0123456",
        "org-marincontract-recipient-alpha",
    )
    assert first["provenance"] != second["provenance"]
    assert first["source_snapshot_hash"] == source_snapshot_hash(
        {"id": "org-casos-0123456", "display_label": "Alpha Services LLC", "sos_id": "0123456"},
        {"id": "org-marincontract-recipient-alpha", "display_label": "County Vendor Alpha"},
    )
    assert first["source_row"] == {"run": "run-a", "gid": 1487}


def test_build_masks_live_publishing_assertion_for_pair():
    case = _case()
    assertion = make_assertion(
        subject_ref="org-casos-0123456",
        target_ref="org-marincontract-recipient-alpha",
        status="approved",
        basis="operator_approved_sos_id",
        subject={"id": "org-casos-0123456", "display_label": "Alpha Services LLC", "sos_id": "0123456"},
        target={"id": "org-marincontract-recipient-alpha", "display_label": "County Vendor Alpha"},
        reviewer="stuart@eastpeak.cc",
        decided_at="2026-07-06T11:00:00Z",
        policy_version="v1",
    )

    record = ic.build_confidence(
        [_feed()],
        [case],
        [assertion],
        {},
        computed_at=COMPUTED_AT,
    )[0]

    assert record["status"] == "superseded_by_assertion"
    assert record["superseded_by"] == assertion["id"]


@pytest.mark.parametrize(
    ("bad_row", "match"),
    [
        (_feed(reason="REDACT_ME_STREET"), "redaction"),
        (_feed(evidence=["bare researcher free text"]), "evidence"),
    ],
)
def test_build_refuses_poisoned_reason_and_unstructured_evidence(bad_row, match):
    with pytest.raises(ValueError, match=match):
        ic.build_confidence([bad_row], [_case()], [], {}, computed_at=COMPUTED_AT)


def test_validate_record_refuses_bare_string_evidence():
    record = ic.build_confidence([_feed()], [_case()], [], {}, computed_at=COMPUTED_AT)[0]
    record["evidence"] = ["bare string"]

    with pytest.raises(ValueError, match="evidence"):
        ic.validate_record(record)


def test_write_confidence_is_sorted_atomic_and_byte_deterministic(tmp_path):
    rows = [
        _feed("org-marincontract-recipient-beta", "2222222", gid=2),
        _feed("org-marincontract-recipient-alpha", "1111111", gid=1),
    ]
    cases = [
        _case("org-marincontract-recipient-alpha", "1111111"),
        _case("org-marincontract-recipient-beta", "2222222"),
    ]

    first = ic.build_confidence(rows, cases, [], {}, computed_at=COMPUTED_AT)
    second = ic.build_confidence(list(reversed(rows)), list(reversed(cases)), [], {}, computed_at=COMPUTED_AT)
    p1 = tmp_path / "confidence-a.jsonl"
    p2 = tmp_path / "confidence-b.jsonl"

    ic.write_confidence(first, p1)
    ic.write_confidence(list(reversed(second)), p2)

    assert p1.read_bytes() == p2.read_bytes()
    written_ids = [json.loads(line)["id"] for line in p1.read_text(encoding="utf-8").splitlines()]
    assert written_ids == sorted(written_ids)
