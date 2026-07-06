"""Reconciliation adapters — normalize PRECOMPUTED candidate artifacts into the
generic `CandidateJoin` shape (EntityRef ↔ EntityRef + `signal_strength`).

Goal 1 of the civic reconciliation toolkit (Tranche 1; spec §5.6/§5.9).

For Goal 1 the adapters read the lanes' already-computed candidate outputs (EIN,
county sos_id, FPPC committee) and expose them through a uniform interface —
`emit_refs()`, `emit_candidates(existing_refs)`, `coverage_report()`,
`redaction_policy()`. They do NOT rerun the raw source scans (CA-SOS streaming, BMF
parsing, FPPC gating stay in their byte-identical lanes). Each candidate shape differs
(EIN: `signal_strength` + flat `registry_*`; county sos: `confidence` + nested
`sos_ref`; FPPC: `confidence` + `committee_id`) — normalization collapses them to one
shape where `confidence` is mapped to `signal_strength` and every join carries
`EntityRef`s drawn from the adapter's declared public fields.
"""
from __future__ import annotations

from typing import Any, Iterable

from reconciliation_cases import CandidateJoin, EntityRef


class ReconciliationAdapter:
    """Base adapter: normalizes a list of precomputed candidate dicts. Subclasses set
    ``source_id`` and the right-endpoint (registry-anchor) public-field projection +
    ``redaction_policy``."""

    source_id: str = "generic"

    def __init__(self, raw_candidates: Iterable[dict[str, Any]]):
        self._raw = list(raw_candidates)

    # --- subclass hooks -----------------------------------------------------
    def _right_public_fields(self, raw: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _right_display(self, raw: dict[str, Any]) -> str:
        return raw["subject_ref"]

    def _review_flags(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Per-source review flags surfaced for bulk-gating. Base = none."""
        return {}

    @classmethod
    def matches_source(
        cls,
        raw: dict[str, Any],
        *,
        public_key_field: str,
        anchor_prefix: str,
    ) -> bool:
        """Whether this adapter can consume ``raw`` under the registry source spec."""
        return public_key_field in raw or str(raw.get("subject_ref", "")).startswith(anchor_prefix)

    def redaction_policy(self) -> dict[str, Any]:
        raise NotImplementedError

    # --- interface ----------------------------------------------------------
    def emit_candidates(self, existing_refs: Iterable[Any] = ()) -> list[CandidateJoin]:
        """Normalize the precomputed candidates. ``existing_refs`` is part of the
        resolver-style interface but unused when normalizing precomputed artifacts."""
        return [self._normalize(raw) for raw in self._raw]

    def emit_refs(self) -> list[EntityRef]:
        refs: list[EntityRef] = []
        for raw in self._raw:
            j = self._normalize(raw)
            refs.extend((j.left_ref, j.right_ref))
        return refs

    def coverage_report(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "candidates": len(self._raw)}

    # --- normalization ------------------------------------------------------
    def _normalize(self, raw: dict[str, Any]) -> CandidateJoin:
        strength = raw.get("signal_strength", raw.get("confidence"))
        if strength is None:
            raise ValueError(
                f"candidate {raw.get('subject_ref')!r} has neither signal_strength nor confidence"
            )
        display = raw.get("display_label", raw["candidate_ref"])
        left = EntityRef(
            source_id=self.source_id,
            local_id=raw["candidate_ref"],
            display_label=display,
            public_fields={"display_label": display},
            provenance={"adapter": self.source_id, "vendor_ref": raw.get("vendor_ref", raw["candidate_ref"])},
        )
        right = EntityRef(
            source_id=self.source_id,
            local_id=raw["subject_ref"],
            display_label=self._right_display(raw),
            public_fields=self._right_public_fields(raw),
            provenance={"adapter": self.source_id, "anchor_ref": raw["subject_ref"]},
        )
        return CandidateJoin(
            candidate_id=f"{raw['subject_ref']}|{raw['candidate_ref']}",
            left_ref=left,
            right_ref=right,
            signals=list(raw.get("signals", [])),
            signal_strength=float(strength),
            review_flags=self._review_flags(raw),
        )


class EinAdapter(ReconciliationAdapter):
    source_id = "ein"
    _PUBLIC = ("registry_ein", "registry_city", "registry_state", "registry_irs_subsection_class")

    def _right_public_fields(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {k: raw[k] for k in self._PUBLIC if k in raw}

    def redaction_policy(self) -> dict[str, Any]:
        return {
            "public_fields": ["display_label", *self._PUBLIC],
            "forbidden_fields": [],
            "pii_class": "none",
        }


class SosAdapter(ReconciliationAdapter):
    source_id = "sos_id"
    # the 7 publishable CA-SOS entity-level fields (mirrors publishable_casos_fields)
    _PUBLISHABLE = (
        "sos_id", "display_label", "entity_type", "entity_status",
        "formation_date", "principal_city", "principal_state",
    )

    def _right_public_fields(self, raw: dict[str, Any]) -> dict[str, Any]:
        sos = raw.get("sos_ref", {})
        return {k: sos[k] for k in self._PUBLISHABLE if k in sos}

    @classmethod
    def matches_source(
        cls,
        raw: dict[str, Any],
        *,
        public_key_field: str,
        anchor_prefix: str,
    ) -> bool:
        return super().matches_source(
            raw,
            public_key_field=public_key_field,
            anchor_prefix=anchor_prefix,
        ) or "sos_ref" in raw

    def _right_display(self, raw: dict[str, Any]) -> str:
        return raw.get("sos_ref", {}).get("display_label", raw["subject_ref"])

    def _review_flags(self, raw: dict[str, Any]) -> dict[str, Any]:
        # CA-SOS carries needs_careful_review; absent ⇒ True (fail-safe: bulk-ineligible).
        return {"needs_careful_review": bool(raw.get("needs_careful_review", True))}

    def redaction_policy(self) -> dict[str, Any]:
        return {
            "public_fields": list(self._PUBLISHABLE),
            "forbidden_fields": [
                "registered_agent", "agent_name", "agent_address",
                "principal_address", "mailing_address", "officer_name",
            ],
            "pii_class": "ca_sos_officers_addresses",
        }


class CommitteeAdapter(ReconciliationAdapter):
    source_id = "committee_id"
    _PUBLIC = ("committee_id", "display_label")

    def _right_public_fields(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {k: raw[k] for k in self._PUBLIC if k in raw}

    def redaction_policy(self) -> dict[str, Any]:
        return {"public_fields": list(self._PUBLIC), "forbidden_fields": [], "pii_class": "none"}
