"""reconcile_decide.py — assemble a read-model case + an operator decision into a
``reconcile_writer.apply_decision`` call (Tranche 2, Slice 4). For approves it loads the
RAW candidate from the lane file so the ledger assertion keeps its ``evidence_record_ids``
(the read-model case doesn't carry them). Used by the workbench's POST /api/reconcile/decide
via subprocess. ATTACH-ONLY, no DB; the writer handles atomicity/idempotency/supersede.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from enrich_county_vendor_eins import build_ein_attach
from enrich_county_vendor_sos import build_sos_attach
from reconcile_writer import apply_decision
from reconciliation_cases import OperatorAction
from reconciliation_refs import anchor_id_of, vendor_id_of, vendor_ref_of


def _node(anchor_id: str, display: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"id": anchor_id, "node_type": "Organization", "labels": ["Organization"],
            "display_label": display, "properties": props}


def _ein_anchor(raw: dict[str, Any], vendor_ref: dict[str, Any]) -> dict[str, Any]:
    anchor = raw["subject_ref"]
    ein = raw.get("ein") or anchor.rsplit("-", 1)[-1]
    return _node(anchor, vendor_ref.get("display_label", anchor), {"source": "irs_bmf", "registry_ein": ein})


def _sos_anchor(raw: dict[str, Any], vendor_ref: dict[str, Any]) -> dict[str, Any]:
    anchor, sos = raw["subject_ref"], raw["sos_ref"]
    return _node(anchor, sos.get("display_label", anchor), {"source": "ca_sos", "sos_id": sos["sos_id"]})


# lane → (attach builder, anchor-node builder). Mirrors build_*_attach's subject so the
# materialized graph node matches the assertion the writer stamps.
_LANES: dict[str, dict[str, Callable]] = {
    "ein": {"builder": build_ein_attach, "anchor": _ein_anchor},
    "sos_id": {"builder": build_sos_attach, "anchor": _sos_anchor},
}


def _load_case(read_model_path: str | Path, case_id: str) -> dict[str, Any]:
    for line in Path(read_model_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c.get("case_id") == case_id:
            return c
    raise ValueError(f"case_id not found in read model: {case_id}")


def _load_raw_candidate(path: str | Path, subject_ref: str, candidate_ref: str) -> dict[str, Any]:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("subject_ref") == subject_ref and r.get("candidate_ref") == candidate_ref:
            return r
    raise ValueError(f"raw candidate not found: {subject_ref} | {candidate_ref}")


def decide(
    case_id: str,
    action_name: str,
    *,
    reviewer: str,
    decided_at: str,
    rejection_kind: str | None = None,
    read_model_path: str | Path,
    candidate_paths: dict[str, str | Path],
    ledger_path: str | Path,
    attach_dir: str | Path,
    now: str | None = None,
    policy_version: str | None = None,
    policy_hash: str | None = None,
    eligibility_snapshot_hash: str | None = None,
) -> dict[str, Any]:
    """Resolve a case + decision and persist it via the writer. Approve reads the raw
    candidate (evidence preserved) and materializes the SAME_AS node+edge handoff;
    reject/unsure write only the ledger row (or nothing)."""
    case = _load_case(read_model_path, case_id)
    join = case["candidate_joins"][0]
    vendor_read_ref = vendor_ref_of(case)
    source = vendor_read_ref["source_id"]
    if source not in _LANES:
        if source == "committee_id":
            raise ValueError(
                "unsupported source for decide: 'committee_id' is a committee Lane 3/R3 row; "
                "committee approvals are intentionally non-actionable until R3 wires the FPPC candidate path"
            )
        raise ValueError(f"unsupported source for decide: {source!r}")
    subject_ref = anchor_id_of(case)
    candidate_ref = vendor_id_of(case)
    action = OperatorAction(
        case_id=case_id, case_type=case["case_type"], action=action_name,
        reviewer=reviewer, decided_at=decided_at, key_type=source, rejection_kind=rejection_kind,
    )

    if action_name == "approve":
        cand_path = candidate_paths.get(source)
        if cand_path is None:
            raise ValueError(f"no candidate file provided for source {source!r}")
        raw = _load_raw_candidate(cand_path, subject_ref, candidate_ref)
        vendor_ref = {"id": candidate_ref, "display_label": vendor_read_ref["display_label"]}
        lane = _LANES[source]
        return apply_decision(
            action, candidate=raw, vendor_ref=vendor_ref, attach_builder=lane["builder"],
            anchor_node=lane["anchor"](raw, vendor_ref),
            ledger_path=ledger_path, attach_dir=attach_dir, now=now,
            **({} if policy_version is None else {"policy_version": policy_version}),
            policy_hash=policy_hash,
            eligibility_snapshot_hash=eligibility_snapshot_hash,
        )

    # reject / unsure — no raw candidate / no handoff
    return apply_decision(
        action, subject={"id": subject_ref}, target={"id": candidate_ref},
        ledger_path=ledger_path, attach_dir=attach_dir, now=now,
        **({} if policy_version is None else {"policy_version": policy_version}),
        policy_hash=policy_hash,
        eligibility_snapshot_hash=eligibility_snapshot_hash,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Persist one operator reconcile decision.")
    p.add_argument("--case-id", required=True)
    p.add_argument("--action", required=True, choices=["approve", "reject", "unsure"])
    p.add_argument("--reviewer", required=True)
    p.add_argument("--decided-at", required=True)
    p.add_argument("--rejection-kind", default=None)
    p.add_argument("--read-model", required=True)
    p.add_argument("--ein-candidates", default=None)
    p.add_argument("--sos-candidates", default=None)
    p.add_argument("--ledger", required=True)
    p.add_argument("--attach-dir", required=True)
    p.add_argument("--now", default=None)
    p.add_argument("--policy-version", default=None)
    p.add_argument("--policy-hash", default=None)
    p.add_argument("--eligibility-snapshot-hash", default=None)
    a = p.parse_args(argv)

    candidate_paths: dict[str, str] = {}
    if a.ein_candidates:
        candidate_paths["ein"] = a.ein_candidates
    if a.sos_candidates:
        candidate_paths["sos_id"] = a.sos_candidates

    result = decide(
        a.case_id, a.action, reviewer=a.reviewer, decided_at=a.decided_at,
        rejection_kind=a.rejection_kind, read_model_path=a.read_model,
        candidate_paths=candidate_paths, ledger_path=a.ledger, attach_dir=a.attach_dir, now=a.now,
        policy_version=a.policy_version, policy_hash=a.policy_hash,
        eligibility_snapshot_hash=a.eligibility_snapshot_hash,
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
