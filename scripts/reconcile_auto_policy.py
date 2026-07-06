"""§9a auto-approve policy helper.

Pure JSON tooling for the first research-fleet auto-approve batch:

* normalize scale verdict keys into the literal key shape the read model consumes;
* compute a deterministic preview eligibility snapshot from current inputs.

This module does not write the identity ledger. Apply remains a separate operator
step through ``reconcile_decide`` after preview/go-no-go and drift recheck.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from enrich_casos_keys import scan_for_forbidden
from identity_key_registry import ANCHOR_PREFIXES
import reconcile_decide
from reconciliation_refs import anchor_id_of, literal_key_of, vendor_id_of


# Reviewer identity per the SIGNED policy document (data/review/research-adjudicated/
# auto-approve-policy.md) — the 12 applied assertions carry this exact string; do not change.
RESEARCH_POLICY_REVIEWER = "research-fleet-v1/policy-stuart-2026-07-01"
# Distinct policy-version stamp (F8c): policy_version must never default to the reviewer.
AUTO_APPROVE_POLICY_VERSION = "auto-approve-policy-2026-07-01"


def _stable_hash(obj: Any) -> str:
    body = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, obj: Any) -> None:
    violations = scan_for_forbidden(obj)
    if violations:
        raise ValueError(f"redaction gate failed for {path}: {violations}")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    violations = scan_for_forbidden(rows)
    if violations:
        raise ValueError(f"redaction gate failed for {path}: {violations}")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def literal_proposed_key(row: dict[str, Any]) -> str:
    proposed = str(row.get("proposed_key", ""))
    for prefix in ANCHOR_PREFIXES:
        if proposed.startswith(prefix):
            return proposed[len(prefix):]
    return proposed


def normalized_verdict_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    literal = literal_proposed_key(row)
    if out.get("proposed_key") != literal and "source_proposed_key" not in out:
        out["source_proposed_key"] = out.get("proposed_key")
    out["proposed_key"] = literal
    return out


def normalized_verdict_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalized_verdict_row(r) for r in rows]


def _load_second_research(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("results", []))


def _join(case: dict[str, Any]) -> dict[str, Any]:
    return case["candidate_joins"][0]


def _vendor_id(case: dict[str, Any]) -> str:
    return vendor_id_of(case)


def _anchor_id(case: dict[str, Any]) -> str:
    return anchor_id_of(case)


def _case_literal_key(case: dict[str, Any]) -> str:
    return literal_key_of(case)


def _pair_from_second(row: dict[str, Any]) -> tuple[str, str]:
    literal = row.get("literal_key") or literal_proposed_key(row)
    return str(row.get("vendor_id")), str(literal)


def _evidence_urls(row: dict[str, Any]) -> list[str]:
    urls = []
    for ev in row.get("evidence", []):
        url = ev.get("url")
        if url and url not in urls:
            urls.append(url)
    return urls


def _is_true(value: Any) -> bool:
    return value is True


def _is_false(value: Any) -> bool:
    return value is False


def _candidate_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in cases:
        vendor = _vendor_id(c)
        counts[vendor] = counts.get(vendor, 0) + 1
    return counts


def _index_cases(cases: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for c in cases:
        indexed.setdefault((_vendor_id(c), _case_literal_key(c)), c)
    return indexed


def _index_cases_by_id(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(c["case_id"]): c for c in cases}


def _sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    gid = row.get("gid")
    return (int(gid) if isinstance(gid, int) else 10**9, str(row.get("vendor_id", "")), str(row.get("literal_key", "")))


def build_preview(
    *,
    verdict_rows: list[dict[str, Any]],
    second_research_rows: list[dict[str, Any]],
    read_model_cases: list[dict[str, Any]],
    context_by_vendor: dict[str, dict[str, Any]],
    policy_hash: str,
) -> dict[str, Any]:
    verdicts = normalized_verdict_rows(verdict_rows)
    second_by_pair = {_pair_from_second(r): r for r in second_research_rows}
    cases_by_pair = _index_cases(read_model_cases)
    counts = _candidate_counts(read_model_cases)

    eligible: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []

    for row in sorted((r for r in verdicts if r.get("auto_candidate") is True), key=_sort_key):
        vendor_id = str(row.get("vendor_id"))
        literal_key = literal_proposed_key(row)
        pair = (vendor_id, literal_key)
        second = second_by_pair.get(pair)
        case = cases_by_pair.get(pair)
        ctx = context_by_vendor.get(vendor_id)
        reasons: list[str] = []

        if row.get("verdict") != "same":
            reasons.append("verdict_not_same")
        if float(row.get("confidence", 0.0)) < 0.9:
            reasons.append("confidence_below_0_9")
        if not _is_true(row.get("key_sighted")):
            reasons.append("key_not_sighted")
        if not _is_true(row.get("verify_ok")):
            reasons.append("verifier_not_ok")
        if row.get("refuted") is True:
            reasons.append("verifier_refuted")
        if not _is_true(row.get("ks_valid")):
            reasons.append("key_sighting_invalid")

        if second is None:
            reasons.append("missing_second_research")
        else:
            second_researcher = second.get("second_researcher", {})
            skeptic = second.get("skeptic", {})
            if second_researcher.get("verdict") != "same":
                reasons.append("second_research_not_same")
            if not _is_true(second_researcher.get("key_sighted_valid")):
                reasons.append("second_key_sighting_invalid")
            if not _is_true(skeptic.get("concurrence")):
                reasons.append("codex_not_concurred")
            if skeptic.get("refuted") is True:
                reasons.append("codex_refuted")

        if case is None:
            reasons.append("case_missing")
        else:
            if case.get("current_ledger_status") != "none":
                reasons.append("ledger_status_not_none")
            if counts.get(vendor_id, 0) != 1:
                reasons.append("not_single_candidate")
            if case.get("review_flags", {}).get("needs_careful_review") is True:
                reasons.append("needs_careful_review")

        if ctx is None:
            reasons.append("missing_collision_context")
        elif ctx.get("key_collision") is True:
            reasons.append("live_collision")

        base = {
            "gid": row.get("gid"),
            "vendor_id": vendor_id,
            "literal_key": literal_key,
            "source_proposed_key": row.get("source_proposed_key", row.get("proposed_key")),
        }
        if reasons:
            ineligible.append({**base, "reasons": reasons})
            continue

        assert case is not None and ctx is not None and second is not None
        join = _join(case)
        eligible.append({
            **base,
            "case_id": case["case_id"],
            "anchor_id": _anchor_id(case),
            "confidence": float(row.get("confidence", 0.0)),
            "display_label": ctx.get("display_label") or join["left_ref"].get("display_label"),
            "money_total": float(ctx.get("money_total", 0.0)),
            "flow_count": int(ctx.get("flow_count", 0)),
            "departments": sorted(ctx.get("departments", [])),
            "evidence_urls": _evidence_urls(second),
        })

    eligible.sort(key=_sort_key)
    ineligible.sort(key=_sort_key)
    snapshot = {
        "policy_hash": policy_hash,
        "considered_count": len(eligible) + len(ineligible),
        "eligible": eligible,
        "ineligible": ineligible,
    }
    return {
        **snapshot,
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible),
        "eligible_case_ids": [e["case_id"] for e in eligible],
        "money_total": sum(e["money_total"] for e in eligible),
        "eligibility_snapshot_hash": _stable_hash(snapshot),
    }


def _build_preview_from_paths(
    *,
    verdicts: str | Path,
    second_research: str | Path,
    read_model: str | Path,
    context: str | Path,
    policy_hash: str,
) -> dict[str, Any]:
    return build_preview(
        verdict_rows=_load_jsonl(verdicts),
        second_research_rows=_load_second_research(second_research),
        read_model_cases=_load_jsonl(read_model),
        context_by_vendor=_load_json(context),
        policy_hash=policy_hash,
    )


def _candidate_path_arg_name(source: str) -> str:
    return {"ein": "ein_candidates", "sos_id": "sos_candidates"}.get(source, source)


def _raw_candidate_pairs(path: str | Path) -> set[tuple[str, str]]:
    return {
        (str(r.get("subject_ref")), str(r.get("candidate_ref")))
        for r in _load_jsonl(path)
    }


def _live_ledger_pairs(path: str | Path) -> set[tuple[str, str]]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return set()
    return {
        (str(r.get("subject_ref")), str(r.get("target_ref")))
        for r in _load_jsonl(ledger_path)
        if r.get("superseded_by") is None
    }


def _preflight_apply_inputs(
    *,
    eligible: list[dict[str, Any]],
    cases_by_id: dict[str, dict[str, Any]],
    candidate_paths: dict[str, str | Path],
    ledger: str | Path,
) -> None:
    raw_pairs_by_source: dict[str, set[tuple[str, str]]] = {}
    live_pairs = _live_ledger_pairs(ledger)
    for row in eligible:
        case_id = str(row["case_id"])
        case = cases_by_id.get(case_id)
        if case is None:
            raise ValueError(f"preview case missing from read model: {case_id}")
        join = _join(case)
        source = join["left_ref"]["source_id"]
        candidate_path = candidate_paths.get(source)
        if candidate_path is None:
            raise ValueError(f"missing --{_candidate_path_arg_name(source).replace('_', '-')} for {case_id}")
        raw_pairs = raw_pairs_by_source.setdefault(source, _raw_candidate_pairs(candidate_path))
        pair = (_anchor_id(case), _vendor_id(case))
        if pair not in raw_pairs:
            raise ValueError(f"raw candidate missing for {case_id}: {pair[0]} | {pair[1]}")
        if pair in live_pairs:
            raise ValueError(f"ledger drift before apply for {case_id}: live assertion already exists")


def apply_batch(
    *,
    verdicts: str | Path,
    second_research: str | Path,
    read_model: str | Path,
    context: str | Path,
    preview: str | Path,
    policy_hash: str,
    candidate_paths: dict[str, str | Path],
    ledger: str | Path,
    attach_dir: str | Path,
    reviewer: str,
    decided_at: str,
    now: str | None = None,
    policy_version: str = AUTO_APPROVE_POLICY_VERSION,
) -> dict[str, Any]:
    approved_preview = _load_json(preview)
    recomputed = _build_preview_from_paths(
        verdicts=verdicts,
        second_research=second_research,
        read_model=read_model,
        context=context,
        policy_hash=policy_hash,
    )
    if approved_preview.get("policy_hash") != policy_hash:
        raise ValueError("policy hash drift between approved preview and apply inputs")
    expected_hash = approved_preview.get("eligibility_snapshot_hash")
    actual_hash = recomputed["eligibility_snapshot_hash"]
    if actual_hash != expected_hash:
        raise ValueError(f"snapshot drift before apply: expected {expected_hash}, got {actual_hash}")

    cases_by_id = _index_cases_by_id(_load_jsonl(read_model))
    _preflight_apply_inputs(
        eligible=recomputed["eligible"],
        cases_by_id=cases_by_id,
        candidate_paths=candidate_paths,
        ledger=ledger,
    )

    results = []
    for case_id in recomputed["eligible_case_ids"]:
        out = reconcile_decide.decide(
            case_id,
            "approve",
            reviewer=reviewer,
            decided_at=decided_at,
            read_model_path=read_model,
            candidate_paths=candidate_paths,
            ledger_path=ledger,
            attach_dir=attach_dir,
            now=now,
            policy_version=policy_version,
            policy_hash=policy_hash,
            eligibility_snapshot_hash=actual_hash,
        )
        results.append({
            "case_id": case_id,
            "result": out["result"],
            "assertion_id": out["assertion"]["id"] if out.get("assertion") else None,
        })

    return {
        "applied_count": len(results),
        "eligibility_snapshot_hash": actual_hash,
        "policy_hash": policy_hash,
        "results": results,
    }


def _cmd_normalize(args: argparse.Namespace) -> int:
    _write_jsonl(args.out, normalized_verdict_rows(_load_jsonl(args.verdicts)))
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    preview = _build_preview_from_paths(
        verdicts=args.verdicts,
        second_research=args.second_research,
        read_model=args.read_model,
        context=args.context,
        policy_hash=args.policy_hash,
    )
    _write_json(args.out, preview)
    print(json.dumps({
        "eligible_count": preview["eligible_count"],
        "money_total": preview["money_total"],
        "eligibility_snapshot_hash": preview["eligibility_snapshot_hash"],
    }, sort_keys=True))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    candidate_paths: dict[str, str] = {}
    if args.ein_candidates:
        candidate_paths["ein"] = args.ein_candidates
    if args.sos_candidates:
        candidate_paths["sos_id"] = args.sos_candidates
    result = apply_batch(
        verdicts=args.verdicts,
        second_research=args.second_research,
        read_model=args.read_model,
        context=args.context,
        preview=args.preview,
        policy_hash=args.policy_hash,
        candidate_paths=candidate_paths,
        ledger=args.ledger,
        attach_dir=args.attach_dir,
        reviewer=args.reviewer,
        decided_at=args.decided_at,
        now=args.now,
        policy_version=args.policy_version,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research-fleet §9a auto-approve helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    norm = sub.add_parser("normalize-verdicts", help="Normalize verdict proposed_key values for read-model ingestion.")
    norm.add_argument("--verdicts", required=True)
    norm.add_argument("--out", required=True)
    norm.set_defaults(func=_cmd_normalize)

    prev = sub.add_parser("preview", help="Build a deterministic §9a eligibility preview snapshot.")
    prev.add_argument("--verdicts", required=True)
    prev.add_argument("--second-research", required=True)
    prev.add_argument("--read-model", required=True)
    prev.add_argument("--context", required=True)
    prev.add_argument("--policy-hash", required=True)
    prev.add_argument("--out", required=True)
    prev.set_defaults(func=_cmd_preview)

    apply = sub.add_parser("apply", help="Apply a previewed §9a batch via reconcile_decide after drift checks.")
    apply.add_argument("--verdicts", required=True)
    apply.add_argument("--second-research", required=True)
    apply.add_argument("--read-model", required=True)
    apply.add_argument("--context", required=True)
    apply.add_argument("--preview", required=True)
    apply.add_argument("--policy-hash", required=True)
    apply.add_argument("--ein-candidates", default=None)
    apply.add_argument("--sos-candidates", default=None)
    apply.add_argument("--ledger", required=True)
    apply.add_argument("--attach-dir", required=True)
    apply.add_argument("--reviewer", default=RESEARCH_POLICY_REVIEWER)
    apply.add_argument("--policy-version", default=AUTO_APPROVE_POLICY_VERSION)
    apply.add_argument("--decided-at", required=True)
    apply.add_argument("--now", default=None)
    apply.set_defaults(func=_cmd_apply)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
