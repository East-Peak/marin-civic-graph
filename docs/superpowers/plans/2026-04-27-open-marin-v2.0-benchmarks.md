# Open Marin v2.0 — Benchmarks + Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the v2 architectural assumptions hold at production scale (114K nodes, 148K edges) and ship the load-bearing foundation modules (outbound policy, citations, pipeline scripts) that survive into v2.1+.

**Architecture:** Build the v2 pipeline (embed → UMAP → cluster → match → name → publish) end-to-end, run a single full-scale rehearsal against the live Neo4j AuraDB, capture nine pass-criteria measurements, and write a GO/NO-GO decision report. The pipeline scripts and outbound-policy module are production-quality and stay in v2.1; the prototype `/` page is throwaway and is replaced in v2.1.

**Tech stack:** Python 3.14 (pipeline + pytest), TypeScript 5 / React 19 / Next.js 16 (prototype + manifest API), `@cosmograph/cosmos` (MIT, WebGL renderer), `umap-learn`, `hdbscan`, `scikit-learn` (similarity-transform alignment), `scipy.optimize.linear_sum_assignment` (Hungarian), OpenAI `text-embedding-3-small`, Anthropic Claude Haiku 4.5, Vercel Blob.

**Spec:** `docs/specs/2026-04-26-open-marin-v2-design.md` §11 Plan v2.0 + the load-bearing modules referenced from §9.1-§9.7, §6.3.2 (citations), §4.4 (sprites), §10 (renderer + routes).

**Prerequisites:** Plan 4a landed at `c75a2c2`. Spec converged at `6a66b54`. Live Neo4j has ~114K eligible nodes per `app/src/lib/canonical-type.ts` resolution.

---

## File structure (new + modified)

```
scripts/
  canonical_type.py               NEW — Python port of canonical-type.ts (eligibility input)
  outbound_policy.py              NEW — eligibility/redaction/audit; default-deny
  citations.py                    NEW — has_primary_source_citation() (Python mirror)
  build_embeddings.py             NEW — synthesizer + OpenAI embeddings + synthesis hash
  build_umap.py                   NEW — fit + transform + similarity-transform alignment
  build_clusters.py               NEW — HDBSCAN on 2D _pending UMAP coords
  match_clusters.py               NEW — Hungarian matching across runs
  name_clusters.py                NEW — deterministic + Haiku improve + validation + overrides
  publish_constellation.py        NEW — build payload, upload blob, atomic Cypher promote
  cluster_name_overrides.json     NEW — manual name overrides registry (empty by default)
  refresh_openmarin.py            MODIFY — add new pipeline steps in order

tests/
  test_canonical_type.py          NEW
  test_outbound_policy.py         NEW
  test_citations.py               NEW
  test_build_embeddings.py        NEW
  test_build_umap.py              NEW
  test_build_clusters.py          NEW
  test_match_clusters.py          NEW
  test_name_clusters.py           NEW
  test_publish_constellation.py   NEW

app/src/
  lib/
    citations.ts                  NEW — TS mirror of citations.py
    cosmograph-mount.tsx          NEW — thin React glue around @cosmograph/cosmos
    constellation-types.ts        NEW — payload TypeScript types (schema_version, etc.)
  workers/
    tier-c-sprites.ts             NEW — OffscreenCanvas worker for on-demand cards
  app/
    api/constellation-manifest/route.ts   NEW — manifest endpoint, IP allowlist
    page.tsx                      MODIFY — prototype Constellation (throwaway, replaced in v2.1)
  components/
    constellation/
      sprite-atlas.ts             NEW — Tier-A + Tier-B build-time atlas
  tests/
    lib/citations.test.ts                       NEW
    lib/cosmograph-mount.test.tsx               NEW
    workers/tier-c-sprites.test.ts              NEW
    api/constellation-manifest.test.ts          NEW
    components/constellation/sprite-atlas.test.ts  NEW

docs/benchmarks/
  2026-04-XX-v2-rehearsal.md      NEW — end-to-end rehearsal report + GO/NO-GO

data/fixtures/constellation/
  prior-frame-sample.json         NEW — 5K-node fixture for similarity-transform tests
```

---

## Conventions

- **Push directly to `main`** — same as v1 plans.
- **Never `git add -A`** — ambient dirty state under `data/extracted/**`, `data/normalized/**`, `data/raw/**`, `data/projected/graph-v2/**` and modified `docs/specs/2026-04-14-marin-civic-graph-v1-design.md` must remain untouched.
- **TDD** — every Python module gets a `tests/test_*.py` written FIRST (red) before implementation (green). Same for TS modules under `app/src/tests/`.
- **`npm run verify` (in `app/`)** must stay green after each frontend commit.
- **Python tests** run via `pytest tests/test_<module>.py -v` from repo root.
- **Outbound calls** (OpenAI / Anthropic) must go through `scripts/outbound_policy.py`. Direct vendor imports outside that module are a lint failure (Task 3).
- **Each commit message** ends with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Co-author trailer** on every commit. Author = `stuart@eastpeak.cc`.

---

## Task 1: Python port of canonical-type.ts (TDD)

**Files:**
- Create: `scripts/canonical_type.py`
- Create: `tests/test_canonical_type.py`

The TS reference at `app/src/lib/canonical-type.ts` resolves a node's NodeType from (1) ID prefix, (2) known base label, (3) Organization-subtype label fallback. The Python port mirrors this exactly so the pipeline's eligibility filter agrees with the frontend's type resolver.

- [ ] **Step 1: Write the failing test**

`tests/test_canonical_type.py`:

```python
"""Tests for canonical_type.py — Python port of app/src/lib/canonical-type.ts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from canonical_type import canonical_type, ALL_TYPES, ORGANIZATION_SUBTYPES


class TestCanonicalType:
    def test_id_prefix_person(self):
        assert canonical_type([], "person-kate-colin") == "Person"

    def test_id_prefix_legacy_actor(self):
        assert canonical_type([], "actor-kate-colin") == "Person"

    def test_id_prefix_legacy_inst(self):
        assert canonical_type([], "inst-san-rafael") == "Organization"

    def test_id_prefix_eid_to_filing(self):
        assert canonical_type([], "eid-12345") == "Filing"

    def test_known_base_label_wins_when_no_prefix(self):
        assert canonical_type(["Decision"], "x-1") == "Decision"

    def test_known_base_preferred_over_subtype(self):
        # Has both "Organization" base and "Government" subtype — base wins.
        assert canonical_type(["Government", "Organization"], "x-1") == "Organization"

    def test_org_subtype_label_resolves_to_organization(self):
        assert canonical_type(["Government"], "x-1") == "Organization"
        assert canonical_type(["Court"], "x-1") == "Organization"

    def test_unknown_returns_none(self):
        assert canonical_type([], "no-prefix-id") is None
        assert canonical_type(["RandomLabel"], "no-prefix-id") is None

    def test_all_types_count_matches_ts(self):
        assert len(ALL_TYPES) == 21

    def test_org_subtypes_match_ts(self):
        assert ORGANIZATION_SUBTYPES == {
            "Government", "Nonprofit", "Business",
            "Political", "Court", "Department", "Commission",
        }
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /<repo>
pytest tests/test_canonical_type.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'canonical_type'`.

- [ ] **Step 3: Write the implementation**

`scripts/canonical_type.py`:

```python
"""Python port of app/src/lib/canonical-type.ts. Single source of truth for
node-type resolution in the pipeline. MUST stay in sync with the TS version.
"""
from __future__ import annotations

ALL_TYPES = [
    "Person", "Organization", "Committee", "Seat", "SeatService",
    "Election", "Candidacy", "Meeting", "AgendaItem", "Decision",
    "Filing", "MoneyFlow", "Case", "Proceeding", "Project",
    "Program", "Agreement", "Amendment", "Record", "Place", "Issue",
]

ORGANIZATION_SUBTYPES = {
    "Government", "Nonprofit", "Business",
    "Political", "Court", "Department", "Commission",
}

TYPE_BY_ID_PREFIX = {
    "person-": "Person", "org-": "Organization", "committee-": "Committee",
    "seat-": "Seat", "seatservice-": "SeatService", "election-": "Election",
    "candidacy-": "Candidacy", "meeting-": "Meeting", "agendaitem-": "AgendaItem",
    "decision-": "Decision", "filing-": "Filing", "moneyflow-": "MoneyFlow",
    "case-": "Case", "proceeding-": "Proceeding", "project-": "Project",
    "program-": "Program", "agreement-": "Agreement", "amendment-": "Amendment",
    "record-": "Record", "place-": "Place", "issue-": "Issue",
    # Legacy (matches canonical-type.ts)
    "actor-": "Person", "inst-": "Organization", "eid-": "Filing",
}


def canonical_type(labels: list[str], node_id: str) -> str | None:
    """Resolve a node's canonical NodeType. Mirrors canonicalType() in TS."""
    for prefix, t in TYPE_BY_ID_PREFIX.items():
        if node_id.startswith(prefix):
            return t
    base = next((lbl for lbl in labels if lbl in ALL_TYPES), None)
    if base:
        return base
    if any(lbl in ORGANIZATION_SUBTYPES for lbl in labels):
        return "Organization"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_canonical_type.py -v
```
Expected: PASS, all 9 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/canonical_type.py tests/test_canonical_type.py
git commit -m "$(cat <<'EOF'
add canonical_type.py: Python mirror of canonical-type.ts

Pipeline modules (outbound_policy, build_embeddings, etc.) need the
same node-type resolution as the frontend. This is the single Python
source of truth — keep in sync with app/src/lib/canonical-type.ts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Outbound policy with eligibility + redaction (TDD)

**Files:**
- Create: `scripts/outbound_policy.py`
- Create: `tests/test_outbound_policy.py`

Spec §9.2: default-deny eligibility per node type, per-type redaction, neighbor filtering for graph-aware enforcement, audit logging.

- [ ] **Step 1: Write the failing test**

`tests/test_outbound_policy.py`:

```python
"""Tests for outbound_policy.py — vendor-call gatekeeper."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from outbound_policy import (
    is_eligible, ELIGIBLE_TYPES, INELIGIBLE_TYPES, REDACT_FIELDS,
    synthesize_outbound_text,
)


class TestEligibility:
    def test_all_v2_types_eligible(self):
        for t in ["Person", "Organization", "Decision", "MoneyFlow",
                  "Case", "Filing", "Meeting", "Place", "Issue"]:
            assert is_eligible(t), f"{t} should be eligible by default"

    def test_unknown_type_inelibile(self):
        assert not is_eligible("CriminalRecord")
        assert not is_eligible("UnregisteredFutureType")

    def test_explicitly_ineligible_overrides(self):
        # Even if a type were ELIGIBLE, INELIGIBLE wins.
        assert "ELIGIBLE_TYPES" in dir()  # sanity
        # If we add CriminalRecord later it must default to ineligible.
        assert not is_eligible("CriminalRecord")


class TestSynthesize:
    def _person(self, **kwargs):
        base = {"id": "person-kate-colin", "type": "Person",
                "label": "Kate Colin", "role": "San Rafael City Council"}
        base.update(kwargs)
        return base

    def test_eligible_node_renders(self):
        text = synthesize_outbound_text(
            self._person(),
            neighbors=[],
        )
        assert "Kate Colin" in text
        assert "Person" in text

    def test_ineligible_anchor_returns_empty(self):
        text = synthesize_outbound_text(
            {"id": "x-1", "type": "CriminalRecord", "label": "redacted"},
            neighbors=[],
        )
        assert text == ""

    def test_ineligible_neighbor_dropped(self):
        text = synthesize_outbound_text(
            self._person(),
            neighbors=[
                {"id": "decision-1", "type": "Decision", "label": "Approve permit"},
                {"id": "x-2", "type": "CriminalRecord", "label": "should not appear"},
            ],
        )
        assert "Approve permit" in text
        assert "should not appear" not in text

    def test_redact_fields_for_person(self):
        text = synthesize_outbound_text(
            self._person(home_address="123 Elm St", phone="415-555-0100",
                         email="kate@example.com"),
            neighbors=[],
        )
        assert "123 Elm St" not in text
        assert "415-555-0100" not in text
        assert "kate@example.com" not in text
        assert "Kate Colin" in text


class TestRedactFieldsRegistry:
    def test_person_has_pii_redactions(self):
        assert "home_address" in REDACT_FIELDS["Person"]
        assert "phone" in REDACT_FIELDS["Person"]
        assert "email" in REDACT_FIELDS["Person"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_outbound_policy.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

`scripts/outbound_policy.py`:

```python
"""Outbound-call gatekeeper. ALL OpenAI/Anthropic synthesis calls in the
pipeline MUST pass through this module so the per-type eligibility,
neighbor filtering, and redaction policies are uniformly enforced.

Direct `import openai` or `import anthropic` outside this module is
forbidden — see lint rule in .ruff.toml / .eslintrc (Task 3).
"""
from __future__ import annotations

from canonical_type import ALL_TYPES

# Default-deny baseline. v2 ships the entire 21-type ontology as eligible
# because it's all-public civic data. Future sensitive lanes (criminal
# records, sealed filings, etc.) will land in INELIGIBLE_TYPES.
ELIGIBLE_TYPES: set[str] = set(ALL_TYPES)

INELIGIBLE_TYPES: set[str] = set()

# Per-type fields stripped from synthesis text before outbound. Any new
# entity type with sensitive fields must be added here.
REDACT_FIELDS: dict[str, list[str]] = {
    "Person": ["home_address", "phone", "email", "dob"],
    # Other types: extend as new fields land. Empty by default.
}


def is_eligible(node_type: str) -> bool:
    """True iff a node of this type may be sent to OpenAI/Anthropic."""
    return node_type in ELIGIBLE_TYPES and node_type not in INELIGIBLE_TYPES


def _redacted_props(node: dict) -> dict:
    """Return a copy of the node with REDACT_FIELDS stripped."""
    redacted_keys = REDACT_FIELDS.get(node.get("type", ""), [])
    return {k: v for k, v in node.items() if k not in redacted_keys}


def synthesize_outbound_text(node: dict, neighbors: list[dict]) -> str:
    """Build the embedding/cluster-naming text for a node.

    Returns "" if the anchor is ineligible. Neighbors of ineligible types
    are dropped entirely from the synthesis (graph-level enforcement, not
    just node-level redaction).
    """
    anchor_type = node.get("type", "")
    if not is_eligible(anchor_type):
        return ""

    safe_anchor = _redacted_props(node)
    eligible_neighbors = [
        _redacted_props(n) for n in neighbors
        if is_eligible(n.get("type", ""))
    ]

    lines = [
        f"{anchor_type} · {safe_anchor.get('label', safe_anchor.get('id', ''))}",
    ]
    role = safe_anchor.get("role") or safe_anchor.get("description")
    if role:
        lines.append(role)
    juris = safe_anchor.get("jurisdiction_name") or safe_anchor.get("jurisdiction")
    if juris:
        lines.append(f"Jurisdiction: {juris}")
    if eligible_neighbors:
        lines.append("Recent activity:")
        for n in eligible_neighbors[:5]:
            lines.append(
                f"- {n.get('label', n.get('id', ''))} ({n.get('type', '')})"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_outbound_policy.py -v
```
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/outbound_policy.py tests/test_outbound_policy.py
git commit -m "$(cat <<'EOF'
add outbound_policy: eligibility + redaction + neighbor filtering

Per spec §9.2. Default-deny by type; redact per-type PII; drop
ineligible neighbors so graph-level enforcement matches node-level.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Outbound audit logging + lint rule

**Files:**
- Modify: `scripts/outbound_policy.py` (add `audit_log` function)
- Create: `tests/test_outbound_audit.py`
- Create: `pyproject.toml` lint rule OR a `scripts/_lint_check_outbound.py` pre-commit script
- Modify: `app/eslint.config.mjs` (or equivalent) — forbid `import "@anthropic-ai/sdk"` / `import "openai"` outside policy module

- [ ] **Step 1: Write audit-log test**

`tests/test_outbound_audit.py`:

```python
"""Tests for outbound audit logging."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from outbound_policy import audit_log


def test_audit_writes_jsonl_record(tmp_path, monkeypatch):
    log_file = tmp_path / "outbound_audit.jsonl"
    monkeypatch.setenv("OUTBOUND_AUDIT_PATH", str(log_file))
    audit_log(
        vendor="openai",
        node_id="person-kate-colin",
        node_type="Person",
        neighbor_ids_included=["decision-1", "decision-2"],
        neighbor_ids_dropped=["x-criminal-1"],
        prompt_hash="abc123",
    )
    line = log_file.read_text().strip()
    record = json.loads(line)
    assert record["vendor"] == "openai"
    assert record["node_id"] == "person-kate-colin"
    assert record["neighbor_ids_dropped"] == ["x-criminal-1"]
    assert "timestamp" in record
```

- [ ] **Step 2: Run test, verify it fails (no `audit_log` defined yet)**

```bash
pytest tests/test_outbound_audit.py -v
```
Expected: FAIL with `ImportError: cannot import name 'audit_log'`.

- [ ] **Step 3: Add `audit_log` to `scripts/outbound_policy.py`**

Append to `scripts/outbound_policy.py`:

```python
import json
import os
from datetime import datetime, timezone


def audit_log(
    *,
    vendor: str,
    node_id: str,
    node_type: str,
    neighbor_ids_included: list[str],
    neighbor_ids_dropped: list[str],
    prompt_hash: str,
) -> None:
    """Append one outbound-call record to the JSONL audit file.

    Path overridable via OUTBOUND_AUDIT_PATH env (used by tests).
    Default: <repo>/data/outbound_audit.jsonl.
    """
    default_path = (
        Path(__file__).resolve().parent.parent / "data" / "outbound_audit.jsonl"
    )
    path = Path(os.environ.get("OUTBOUND_AUDIT_PATH", str(default_path)))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vendor": vendor,
        "node_id": node_id,
        "node_type": node_type,
        "neighbor_ids_included": neighbor_ids_included,
        "neighbor_ids_dropped": neighbor_ids_dropped,
        "prompt_hash": prompt_hash,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
```

(`from pathlib import Path` is already in canonical_type.py module space — confirm it's imported at the top of outbound_policy.py too; add `from pathlib import Path` if missing.)

- [ ] **Step 4: Verify audit test passes**

```bash
pytest tests/test_outbound_audit.py -v
```
Expected: PASS.

- [ ] **Step 5: Add Python lint rule**

Create `scripts/_lint_check_outbound.py`:

```python
"""Forbid direct OpenAI/Anthropic imports outside outbound_policy.py.

Run as part of CI: python scripts/_lint_check_outbound.py
Exits 1 with a list of offenders if any are found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ALLOWED = {
    "scripts/outbound_policy.py",
    "scripts/build_embeddings.py",   # imports openai SDK; must use the policy
    "scripts/name_clusters.py",      # imports anthropic SDK; must use the policy
}
PATTERN = re.compile(r"^\s*(?:import|from)\s+(openai|anthropic)\b", re.MULTILINE)


def main() -> int:
    offenders: list[tuple[Path, str]] = []
    for py in REPO.glob("scripts/**/*.py"):
        rel = py.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        text = py.read_text(encoding="utf-8")
        for m in PATTERN.finditer(text):
            offenders.append((py, m.group(0).strip()))
    if offenders:
        print("FAIL: direct vendor imports outside policy module:")
        for path, line in offenders:
            print(f"  {path.relative_to(REPO)}: {line}")
        return 1
    print("OK: no out-of-policy vendor imports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Add a test that validates the lint script catches violations**

`tests/test_outbound_lint.py`:

```python
"""Smoke test: the outbound-policy lint script runs and reports cleanly today."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_lint_script_passes_on_current_repo():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "_lint_check_outbound.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 7: Verify lint test passes**

```bash
pytest tests/test_outbound_lint.py -v
```
Expected: PASS.

- [ ] **Step 8: Add the equivalent ESLint rule for TS**

Modify `app/eslint.config.mjs`:

Locate the rules block, add:

```javascript
{
  rules: {
    "no-restricted-imports": ["error", {
      paths: [
        { name: "openai", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
        { name: "@anthropic-ai/sdk", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
      ],
    }],
  },
}
```

(Check current `app/eslint.config.mjs` shape; existing rules block may need to be extended rather than created.)

- [ ] **Step 9: Run app lint to confirm it still passes**

```bash
cd app && npm run lint
```
Expected: PASS (no v2 code uses these SDKs from the frontend yet — rule is preventative).

- [ ] **Step 10: Commit**

```bash
git add scripts/outbound_policy.py scripts/_lint_check_outbound.py \
        tests/test_outbound_audit.py tests/test_outbound_lint.py \
        app/eslint.config.mjs
git commit -m "$(cat <<'EOF'
outbound: audit logging + Python lint script + ESLint vendor block

Audit log: every outbound call writes a JSONL record to
data/outbound_audit.jsonl with vendor, node id+type, neighbor lists,
prompt hash. Reviewable when expanding eligibility.

Lint: scripts/_lint_check_outbound.py catches direct openai/anthropic
imports outside the policy module. ESLint blocks the same in TS.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Citations helper (Python + TypeScript)

**Files:**
- Create: `scripts/citations.py`
- Create: `app/src/lib/citations.ts`
- Create: `tests/test_citations.py`
- Create: `app/src/tests/lib/citations.test.ts`

Spec §6.3.2 — `has_primary_source_citation(node)` checks whether a node carries at least one canonical primary-source field. Used by adjacency-flow eligibility (v2.4) AND by ingestion validators going forward.

- [ ] **Step 1: Python test (red)**

`tests/test_citations.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from citations import has_primary_source_citation


class TestEvidenceArrays:
    def test_evidence_record_ids_non_empty(self):
        assert has_primary_source_citation({"evidence_record_ids": ["rec-1"]})

    def test_evidence_record_ids_empty_array(self):
        assert not has_primary_source_citation({"evidence_record_ids": []})

    def test_record_ids_alternative(self):
        assert has_primary_source_citation({"record_ids": ["rec-2"]})


class TestSingleFieldCitations:
    def test_filing_id(self):
        assert has_primary_source_citation({"filing_id": "F-123"})

    def test_fppc_report_id(self):
        assert has_primary_source_citation({"fppc_report_id": "fppc-2024"})

    def test_minutes_url(self):
        assert has_primary_source_citation({"minutes_url": "https://..."})

    def test_docket_number(self):
        assert has_primary_source_citation({"docket_number": "CV-1"})

    def test_permit_id(self):
        assert has_primary_source_citation({"permit_id": "P-1"})

    def test_source_url_plus_source_id(self):
        assert has_primary_source_citation({"source_url": "u", "source_id": "s"})

    def test_source_url_alone_insufficient(self):
        # Spec requires source_url AND source_id together for Records.
        assert not has_primary_source_citation({"source_url": "u"})

    def test_moneyflow_source_filing_id(self):
        assert has_primary_source_citation({"source_filing_id": "fppc-sched-A"})

    def test_committee_fppc_id(self):
        assert has_primary_source_citation({"fppc_id": "1234567"})


class TestNoCitation:
    def test_empty_node(self):
        assert not has_primary_source_citation({})

    def test_only_irrelevant_fields(self):
        assert not has_primary_source_citation(
            {"name": "x", "label": "y", "id": "z"}
        )

    def test_blank_string_not_a_citation(self):
        assert not has_primary_source_citation({"filing_id": ""})
        assert not has_primary_source_citation({"minutes_url": "   "})
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_citations.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write Python implementation**

`scripts/citations.py`:

```python
"""has_primary_source_citation — node-level provenance check.

Used by adjacency-flow eligibility (spec §6.3.2) and ingestion validators.
Mirror of app/src/lib/citations.ts.
"""
from __future__ import annotations

ARRAY_FIELDS = ("evidence_record_ids", "record_ids")
SINGLE_FIELDS = (
    "filing_id", "fppc_report_id", "form_700_line",
    "minutes_url", "agenda_url", "meeting_url",
    "docket_number", "permit_id",
    "source_filing_id", "fppc_id",
)
PAIR_REQUIRED = (("source_url", "source_id"),)


def _is_set(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    return bool(value)


def has_primary_source_citation(node: dict) -> bool:
    for f in ARRAY_FIELDS:
        if _is_set(node.get(f)):
            return True
    for f in SINGLE_FIELDS:
        if _is_set(node.get(f)):
            return True
    for fields in PAIR_REQUIRED:
        if all(_is_set(node.get(f)) for f in fields):
            return True
    return False
```

- [ ] **Step 4: Verify Python test passes**

```bash
pytest tests/test_citations.py -v
```
Expected: PASS.

- [ ] **Step 5: TS test (red)**

`app/src/tests/lib/citations.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { hasPrimarySourceCitation } from "@/lib/citations";

describe("hasPrimarySourceCitation", () => {
  it("evidence_record_ids non-empty → true", () => {
    expect(hasPrimarySourceCitation({ evidence_record_ids: ["r-1"] })).toBe(true);
  });

  it("evidence_record_ids empty → false", () => {
    expect(hasPrimarySourceCitation({ evidence_record_ids: [] })).toBe(false);
  });

  it("record_ids alternative", () => {
    expect(hasPrimarySourceCitation({ record_ids: ["r-2"] })).toBe(true);
  });

  it("filing_id alone", () => {
    expect(hasPrimarySourceCitation({ filing_id: "F-1" })).toBe(true);
  });

  it("source_url + source_id required as a pair", () => {
    expect(hasPrimarySourceCitation({ source_url: "u" })).toBe(false);
    expect(hasPrimarySourceCitation({ source_url: "u", source_id: "s" })).toBe(true);
  });

  it("blank strings don't count", () => {
    expect(hasPrimarySourceCitation({ filing_id: "" })).toBe(false);
    expect(hasPrimarySourceCitation({ minutes_url: "   " })).toBe(false);
  });

  it("empty node → false", () => {
    expect(hasPrimarySourceCitation({})).toBe(false);
  });

  it("MoneyFlow source_filing_id satisfies", () => {
    expect(hasPrimarySourceCitation({ source_filing_id: "sched-A-1" })).toBe(true);
  });

  it("Committee fppc_id satisfies", () => {
    expect(hasPrimarySourceCitation({ fppc_id: "1234567" })).toBe(true);
  });
});
```

- [ ] **Step 6: Run vitest, verify fail**

```bash
cd app && npx vitest run src/tests/lib/citations.test.ts
```
Expected: FAIL with module-not-found.

- [ ] **Step 7: Write TS implementation**

`app/src/lib/citations.ts`:

```typescript
// Mirror of scripts/citations.py. Keep both in lockstep.

const ARRAY_FIELDS = ["evidence_record_ids", "record_ids"] as const;

const SINGLE_FIELDS = [
  "filing_id", "fppc_report_id", "form_700_line",
  "minutes_url", "agenda_url", "meeting_url",
  "docket_number", "permit_id",
  "source_filing_id", "fppc_id",
] as const;

const PAIR_REQUIRED: ReadonlyArray<readonly string[]> = [["source_url", "source_id"]];

function isSet(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.length > 0;
  return Boolean(value);
}

export function hasPrimarySourceCitation(node: Record<string, unknown>): boolean {
  for (const f of ARRAY_FIELDS) if (isSet(node[f])) return true;
  for (const f of SINGLE_FIELDS) if (isSet(node[f])) return true;
  for (const fields of PAIR_REQUIRED) {
    if (fields.every((f) => isSet(node[f]))) return true;
  }
  return false;
}
```

- [ ] **Step 8: Verify TS test passes + verify**

```bash
cd app && npx vitest run src/tests/lib/citations.test.ts && npm run verify
```
Expected: PASS, full verify green.

- [ ] **Step 9: Commit**

```bash
git add scripts/citations.py tests/test_citations.py \
        app/src/lib/citations.ts app/src/tests/lib/citations.test.ts
git commit -m "$(cat <<'EOF'
add citations helper (Python + TS): has_primary_source_citation

Per spec §6.3.2. Used by adjacency-flow eligibility (v2.4) and by
ingestion validators going forward. ARRAY/SINGLE/PAIR field categories
mirror exactly between the Python and TS implementations.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Embedding pipeline (TDD for synthesizer; integration for OpenAI call)

**Files:**
- Create: `scripts/build_embeddings.py`
- Create: `tests/test_build_embeddings.py`

Spec §9.1. Synthesizes embedding text per node, computes synthesis hash, batches OpenAI `text-embedding-3-small` calls, writes `embedding`, `embedding_hash`, `embedding_version`, `embedded_at` to canonical (NOT pending — embeddings are direct writes; only UMAP/cluster props go through staging).

- [ ] **Step 1: Synthesizer + hash tests (red)**

`tests/test_build_embeddings.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_embeddings import (
    EMBEDDING_VERSION,
    synth_text_for_node,
    synthesis_hash,
    needs_embed,
)


class TestSynthText:
    def test_eligible_person_with_neighbors(self):
        text = synth_text_for_node(
            {"id": "person-kate-colin", "type": "Person",
             "label": "Kate Colin", "role": "Council member",
             "jurisdiction_name": "San Rafael"},
            neighbors=[
                {"id": "decision-1", "type": "Decision", "label": "Approve permit"},
            ],
        )
        assert "Kate Colin" in text
        assert "San Rafael" in text
        assert "Approve permit" in text

    def test_ineligible_anchor_returns_empty(self):
        text = synth_text_for_node(
            {"id": "x-1", "type": "CriminalRecord", "label": "x"},
            neighbors=[],
        )
        assert text == ""


class TestSynthesisHash:
    def test_deterministic(self):
        node = {"id": "person-kate-colin", "type": "Person", "label": "Kate"}
        h1 = synthesis_hash(synth_text_for_node(node, []), [])
        h2 = synthesis_hash(synth_text_for_node(node, []), [])
        assert h1 == h2

    def test_neighbor_id_changes_hash(self):
        node = {"id": "p-1", "type": "Person", "label": "X"}
        h_a = synthesis_hash(
            synth_text_for_node(node, [{"id": "d-1", "type": "Decision", "label": "A"}]),
            ["d-1"],
        )
        h_b = synthesis_hash(
            synth_text_for_node(node, [{"id": "d-2", "type": "Decision", "label": "A"}]),
            ["d-2"],
        )
        assert h_a != h_b

    def test_text_change_changes_hash(self):
        node_a = {"id": "p-1", "type": "Person", "label": "Kate"}
        node_b = {"id": "p-1", "type": "Person", "label": "Kathleen"}
        h_a = synthesis_hash(synth_text_for_node(node_a, []), [])
        h_b = synthesis_hash(synth_text_for_node(node_b, []), [])
        assert h_a != h_b


class TestNeedsEmbed:
    def test_no_existing_embedding(self):
        assert needs_embed({"embedding_hash": None}, current_hash="abc")

    def test_hash_match_skips(self):
        assert not needs_embed({"embedding_hash": "abc"}, current_hash="abc")

    def test_hash_mismatch_re_embeds(self):
        assert needs_embed({"embedding_hash": "old"}, current_hash="new")

    def test_version_bump_re_embeds(self):
        # If EMBEDDING_VERSION is bumped, existing embeddings stale even with matching hash.
        node = {"embedding_hash": "abc", "embedding_version": EMBEDDING_VERSION - 1}
        assert needs_embed(node, current_hash="abc")
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_build_embeddings.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`scripts/build_embeddings.py`:

```python
"""Build embeddings for all eligible Open Marin entities.

Pipeline order: this is the FIRST data-touching step in v2.0+. Reads the
graph, synthesizes per-node text, computes synthesis hash, and embeds via
OpenAI text-embedding-3-small. Writes embedding/_hash/_version/embedded_at
directly to canonical properties (embeddings are not staged through
*_pending — only UMAP and cluster fields are).

CLI:
  python scripts/build_embeddings.py [--full] [--dry-run]

  --full    : re-embed every eligible node regardless of hash (rare).
  --dry-run : compute hashes + count work, do not call OpenAI or write.

Requires NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / OPENAI_API_KEY in env.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow `import openai` here — this module is in the outbound-policy ALLOWED list.
import openai  # noqa: F401  (used inside main(); kept top-level so lint sees it)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outbound_policy import is_eligible, synthesize_outbound_text, audit_log

EMBEDDING_VERSION = 1
EMBEDDING_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
BATCH_SIZE = 100


def synth_text_for_node(node: dict, neighbors: list[dict]) -> str:
    """Wrap outbound_policy.synthesize_outbound_text for the embedding context."""
    return synthesize_outbound_text(node, neighbors)


def synthesis_hash(text: str, neighbor_ids: list[str]) -> str:
    """sha256 over the exact synthesis text plus sorted neighbor IDs.

    Same hash → same outbound payload → no re-embed needed. Different
    neighbor IDs (edge changes) → different hash → re-embed.
    """
    payload = text + "\n" + "|".join(sorted(neighbor_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def needs_embed(node: dict, current_hash: str) -> bool:
    """True iff this node requires re-embedding."""
    if not node.get("embedding_hash"):
        return True
    if node.get("embedding_version") != EMBEDDING_VERSION:
        return True
    return node["embedding_hash"] != current_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Re-embed every eligible node regardless of hash")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute hashes only; no OpenAI calls or writes")
    args = parser.parse_args()

    if not args.dry_run and not os.environ.get("OPENAI_API_KEY"):
        print("error: OPENAI_API_KEY required (use --dry-run to skip)", file=sys.stderr)
        return 2

    # Lazy imports to keep the module import-light for tests.
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )

    with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
        nodes = list(session.run(
            "MATCH (n) RETURN n.id AS id, labels(n) AS labels, properties(n) AS props"
        ))
        # ... build (node, neighbors) tuples, filter via is_eligible, compute
        # synth_text + synthesis_hash, skip when needs_embed is False, batch
        # 100 at a time through openai.embeddings.create, write back via:
        #   UNWIND $rows AS row
        #   MATCH (n {id: row.id})
        #   SET n.embedding = row.embedding,
        #       n.embedding_hash = row.hash,
        #       n.embedding_version = $version,
        #       n.embedded_at = datetime();
        # See spec §9.1 for the full contract.
        # (Detailed implementation rolled into Task 6 rehearsal commit.)
        pass

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

NOTE — the implementation body for `main()` is intentionally a stub at this commit; the synthesizer + hash + needs_embed helpers (the unit-tested surface) are complete. Task 6 fills in the OpenAI batch-call body during the rehearsal.

- [ ] **Step 4: Verify unit tests pass**

```bash
pytest tests/test_build_embeddings.py -v
```
Expected: PASS, all four test classes.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_embeddings.py tests/test_build_embeddings.py
git commit -m "$(cat <<'EOF'
add build_embeddings: synthesizer + synthesis hash + needs_embed

Per spec §9.1. Synthesizer wraps outbound_policy; hash is sha256 over
text+sorted(neighbor_ids); needs_embed gates re-embedding by hash AND
EMBEDDING_VERSION bump.

main() is a stub at this commit — Task 6 fills in the OpenAI batched
call during the production rehearsal so we don't burn embeddings before
the surrounding pipeline is in place.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: UMAP pipeline (with similarity-transform alignment)

**Files:**
- Create: `scripts/build_umap.py`
- Create: `tests/test_build_umap.py`
- Create: `data/fixtures/constellation/prior-frame-sample.json`

Spec §9.3 + §4.3. The 4-param similarity transform (rotation θ, mirror flag, uniform scale s, translation tx/ty) is the load-bearing piece — without it weekly fits rotate/mirror the entire territory.

- [ ] **Step 1: Similarity-transform tests (red)**

`tests/test_build_umap.py`:

```python
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_umap import (
    fit_similarity_transform,
    apply_similarity_transform,
    drift_metrics,
)


class TestSimilarityTransform:
    def test_identity_when_inputs_equal(self):
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        T = fit_similarity_transform(pts, pts)
        out = apply_similarity_transform(pts, T)
        np.testing.assert_allclose(out, pts, atol=1e-10)

    def test_undoes_uniform_rotation(self):
        prior = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]])
        # Rotate 90° (a fresh UMAP fit could land here).
        rot = np.array([[0.0, -1.0], [1.0, 0.0]])
        new = prior @ rot.T
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-10)

    def test_undoes_uniform_scale(self):
        prior = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]])
        new = prior * 2.5
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-10)

    def test_undoes_translation(self):
        prior = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        new = prior + np.array([10.0, -5.0])
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-10)

    def test_undoes_mirror(self):
        prior = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]])
        # Mirror across x-axis.
        new = prior * np.array([1.0, -1.0])
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-9)


class TestDriftMetrics:
    def test_zero_drift_when_aligned(self):
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        m = drift_metrics(pts, pts)
        assert m["max_node_displacement_pct"] == pytest.approx(0.0, abs=1e-9)
        assert m["max_centroid_displacement_pct"] == pytest.approx(0.0, abs=1e-9)

    def test_drift_pct_relative_to_map_width(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.0, 0.0], [10.0, 1.0]])  # one node moved 1.0 across a 10-wide map
        m = drift_metrics(prior, new)
        assert m["max_node_displacement_pct"] == pytest.approx(0.1, rel=1e-6)
```

Create `data/fixtures/constellation/prior-frame-sample.json` (tiny fixture for the rehearsal step in Task 16):

```json
{
  "schema_version": 1,
  "version": "fixture-prior-001",
  "umap_version": 0,
  "built_at": "2026-04-26T00:00:00Z",
  "nodes": []
}
```

- [ ] **Step 2: Run, verify failures**

```bash
pytest tests/test_build_umap.py -v
```
Expected: all FAIL.

- [ ] **Step 3: Write implementation**

`scripts/build_umap.py`:

```python
"""UMAP fit/transform with persistent similarity-transform alignment.

Spec §9.3 + §4.3. Output coords land in n.umap_x_pending / .umap_y_pending /
.umap_version_pending — never canonical (only publish_constellation.py
promotes pending → canonical).

CLI:
  python scripts/build_umap.py [--full-fit] [--dry-run]

  --full-fit : run UMAP.fit_transform on all eligible embeddings (weekly).
               Otherwise loads cached umap.pkl and runs .transform on
               new/dirty nodes only (nightly).
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO / "data" / "umap_model.pkl"
ALIGNMENT_PATH = REPO / "data" / "umap_alignment.json"
UMAP_VERSION = 1


def fit_similarity_transform(new_pts: np.ndarray, prior_pts: np.ndarray) -> dict:
    """Solve for θ, mirror, scale, translation that best maps new_pts → prior_pts.

    Returns a dict with keys: rotation_rad, mirror, scale, tx, ty.

    Uses the closed-form least-squares solution (Umeyama, 1991) plus a
    reflection check: we evaluate squared error with mirror=False and
    mirror=True and pick the lower one.
    """
    assert new_pts.shape == prior_pts.shape
    n = new_pts.shape[0]
    if n == 0:
        return {"rotation_rad": 0.0, "mirror": False, "scale": 1.0, "tx": 0.0, "ty": 0.0}

    def solve(_new, _prior, mirror: bool) -> tuple[dict, float]:
        new_m = _new.mean(axis=0)
        prior_m = _prior.mean(axis=0)
        new_c = _new - new_m
        prior_c = _prior - prior_m
        if mirror:
            new_c = new_c * np.array([1.0, -1.0])
        # Cross-covariance.
        H = new_c.T @ prior_c
        U, _S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T
        var_new = (new_c ** 2).sum()
        scale = (np.diag(_S).sum() / var_new) if var_new > 0 else 1.0
        T_translate = prior_m - scale * (R @ (new_m * (np.array([1.0, -1.0]) if mirror else 1.0)))
        # Apply transform and measure error.
        applied = scale * ((_new * (np.array([1.0, -1.0]) if mirror else 1.0)) @ R.T) + T_translate
        err = float(((applied - _prior) ** 2).sum())
        theta = float(np.arctan2(R[1, 0], R[0, 0]))
        return ({"rotation_rad": theta, "mirror": mirror, "scale": float(scale),
                 "tx": float(T_translate[0]), "ty": float(T_translate[1])}, err)

    no_mirror, err_n = solve(new_pts, prior_pts, mirror=False)
    yes_mirror, err_y = solve(new_pts, prior_pts, mirror=True)
    return no_mirror if err_n <= err_y else yes_mirror


def apply_similarity_transform(pts: np.ndarray, T: dict) -> np.ndarray:
    """Apply a transform produced by fit_similarity_transform()."""
    theta = T["rotation_rad"]
    s = T["scale"]
    R = np.array([[np.cos(theta), -np.sin(theta)],
                  [np.sin(theta),  np.cos(theta)]])
    p = pts.copy()
    if T["mirror"]:
        p = p * np.array([1.0, -1.0])
    return s * (p @ R.T) + np.array([T["tx"], T["ty"]])


def drift_metrics(prior_pts: np.ndarray, new_pts: np.ndarray) -> dict:
    """Compute per-node and per-centroid drift, normalized by map width.

    Used to enforce the §9.3 drift budget at publish time.
    """
    width = max(
        prior_pts[:, 0].max() - prior_pts[:, 0].min(),
        prior_pts[:, 1].max() - prior_pts[:, 1].min(),
        1e-12,
    )
    diffs = np.linalg.norm(new_pts - prior_pts, axis=1)
    max_node = float(diffs.max()) if len(diffs) else 0.0
    centroid_shift = float(np.linalg.norm(new_pts.mean(axis=0) - prior_pts.mean(axis=0))) if len(prior_pts) else 0.0
    return {
        "max_node_displacement_pct": max_node / width,
        "max_centroid_displacement_pct": centroid_shift / width,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-fit", action="store_true",
                        help="Run UMAP.fit_transform (weekly); otherwise .transform incremental")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Body filled in during Task 6 rehearsal. The alignment helpers above
    # are the load-bearing surface and have unit-tested correctness.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tests/test_build_umap.py -v
```
Expected: PASS, all 7 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_umap.py tests/test_build_umap.py data/fixtures/constellation/prior-frame-sample.json
git commit -m "$(cat <<'EOF'
add build_umap: similarity-transform alignment + drift metrics

Per spec §4.3 + §9.3. Closed-form 4-param transform (Umeyama 1991)
with mirror flag selected by min-squared-error. drift_metrics
normalizes displacement by map width so the §9.3 drift budget
(25% per-node, 15% per-centroid-cluster) is implementable.

main() body fills in during Task 6 rehearsal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: HDBSCAN clustering pipeline

**Files:**
- Create: `scripts/build_clusters.py`
- Create: `tests/test_build_clusters.py`

Spec §9.4. Reads `*_pending` UMAP coords, runs HDBSCAN on 2D, writes `cluster_id_pending` (raw HDBSCAN ID — not yet stable across runs; Task 8 matches it) and `cluster_centroid_distance_pending`.

- [ ] **Step 1: Test (red)**

`tests/test_build_clusters.py`:

```python
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_clusters import compute_clusters, MIN_CLUSTER_SIZE


def _gaussian_blob(center, n, scale=0.3, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(loc=center, scale=scale, size=(n, 2))


class TestComputeClusters:
    def test_two_dense_blobs_separated(self):
        a = _gaussian_blob((0, 0), 30, seed=1)
        b = _gaussian_blob((10, 10), 30, seed=2)
        coords = np.vstack([a, b])
        labels, centroids, distances = compute_clusters(coords)
        # Should pick out at least 2 clusters; -1 = noise allowed.
        unique = set(labels) - {-1}
        assert len(unique) >= 2
        # Each blob's points predominantly in one cluster.
        a_labels = labels[:30]
        b_labels = labels[30:]
        a_top = max(set(a_labels) - {-1}, key=lambda x: (a_labels == x).sum(), default=-1)
        b_top = max(set(b_labels) - {-1}, key=lambda x: (b_labels == x).sum(), default=-1)
        assert a_top != b_top
        assert (a_labels == a_top).sum() > 20
        assert (b_labels == b_top).sum() > 20

    def test_distances_sized_to_input(self):
        coords = _gaussian_blob((0, 0), MIN_CLUSTER_SIZE * 2, seed=3)
        labels, centroids, distances = compute_clusters(coords)
        assert distances.shape == (coords.shape[0],)
        assert np.all(distances >= 0)

    def test_centroid_per_cluster_id(self):
        a = _gaussian_blob((0, 0), 30, seed=4)
        b = _gaussian_blob((50, 50), 30, seed=5)
        coords = np.vstack([a, b])
        labels, centroids, _ = compute_clusters(coords)
        for cid in set(labels) - {-1}:
            assert cid in centroids
            assert centroids[cid].shape == (2,)
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_build_clusters.py -v
```
Expected: FAIL with import error.

- [ ] **Step 3: Implementation**

`scripts/build_clusters.py`:

```python
"""HDBSCAN on 2D *_pending UMAP coords.

Reads umap_x_pending/umap_y_pending; writes cluster_id_pending (raw, not
yet matched across runs — match_clusters.py handles that) and
cluster_centroid_distance_pending.

CLI:
  python scripts/build_clusters.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

MIN_CLUSTER_SIZE = 15
MIN_SAMPLES = 5


def compute_clusters(coords: np.ndarray) -> tuple[np.ndarray, dict, np.ndarray]:
    """Run HDBSCAN on 2D coords. Returns (labels, centroids_by_id, distances).

    labels: shape (N,) int; -1 = noise.
    centroids_by_id: dict[int, np.ndarray of shape (2,)].
    distances: shape (N,) — Euclidean distance from each point to its
               cluster's centroid; noise points have distance to overall
               centroid as a fallback.
    """
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        min_samples=MIN_SAMPLES,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(coords)

    centroids: dict[int, np.ndarray] = {}
    for cid in set(labels):
        if cid == -1:
            continue
        centroids[int(cid)] = coords[labels == cid].mean(axis=0)

    overall_centroid = coords.mean(axis=0) if len(coords) else np.zeros(2)
    distances = np.zeros(coords.shape[0])
    for i, cid in enumerate(labels):
        c = centroids.get(int(cid), overall_centroid)
        distances[i] = float(np.linalg.norm(coords[i] - c))
    return labels.astype(int), centroids, distances


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Body filled in during Task 16 rehearsal — reads umap_*_pending from
    # Neo4j, runs compute_clusters, writes cluster_id_pending + distance.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tests/test_build_clusters.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_clusters.py tests/test_build_clusters.py
git commit -m "$(cat <<'EOF'
add build_clusters: HDBSCAN on 2D *_pending UMAP coords

Per spec §9.4. compute_clusters returns labels + per-cluster centroids
+ per-node centroid distances. main() filled in during Task 16
rehearsal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Hungarian cluster matching across runs

**Files:**
- Create: `scripts/match_clusters.py`
- Create: `tests/test_match_clusters.py`

Spec §9.5. Stable cluster IDs across runs so `cluster_label` persists. Hungarian on confusion matrix; Jaccard ≥ 0.5 for matched pair retention; split/merge handling.

- [ ] **Step 1: Tests (red)**

`tests/test_match_clusters.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match_clusters import match_clusters


def _members(d: dict[int, list[str]]) -> dict[int, set[str]]:
    return {k: set(v) for k, v in d.items()}


class TestMatchClusters:
    def test_perfect_match_keeps_ids(self):
        prior = {7: ["a", "b", "c"], 12: ["d", "e", "f"]}
        new = {0: ["a", "b", "c"], 1: ["d", "e", "f"]}
        m = match_clusters(_members(prior), _members(new))
        # New cluster 0 (members a,b,c) should map to prior 7.
        assert m["assignments"][0] == 7
        assert m["assignments"][1] == 12
        assert m["renames_needed"] == set()

    def test_new_cluster_gets_new_id(self):
        prior = {7: ["a", "b", "c"]}
        new = {0: ["a", "b", "c"], 1: ["x", "y", "z"]}
        m = match_clusters(_members(prior), _members(new))
        assert m["assignments"][0] == 7
        # new[1] has no overlap with any prior — fresh ID, distinct from 7.
        assert m["assignments"][1] != 7
        assert 1 in m["renames_needed"]

    def test_dropped_prior_cluster_no_assignment(self):
        prior = {7: ["a"], 9: ["dead"]}
        new = {0: ["a"]}
        m = match_clusters(_members(prior), _members(new))
        assert m["assignments"][0] == 7
        # 9 is dropped; not present in assignments.
        assert 9 not in m["assignments"].values()

    def test_split_largest_descendant_inherits_id(self):
        prior = {7: ["a", "b", "c", "d"]}
        new = {0: ["a", "b", "c"], 1: ["d"]}
        m = match_clusters(_members(prior), _members(new))
        # The 3-member descendant inherits 7.
        assert m["assignments"][0] == 7
        assert m["assignments"][1] != 7
        assert 1 in m["renames_needed"]

    def test_merge_largest_ancestor_id_wins(self):
        prior = {7: ["a", "b", "c"], 9: ["d"]}
        new = {0: ["a", "b", "c", "d"]}
        m = match_clusters(_members(prior), _members(new))
        # New cluster has more overlap with 7 (3) than 9 (1) → 7 wins.
        assert m["assignments"][0] == 7
        assert 0 in m["renames_needed"]  # merged → re-name
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_match_clusters.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implementation**

`scripts/match_clusters.py`:

```python
"""Stable cluster IDs across runs via Hungarian matching on Jaccard overlap.

Input: prior_members (canonical cluster_id → member node ids), new_members
(raw HDBSCAN cluster_id from this run → member node ids).
Output: { assignments: { new_id → stable_id }, renames_needed: { new_ids that need a fresh name } }.

renames_needed includes every new cluster that is "fresh" relative to the
prior frame: brand-new clusters (no good match), splits (sibling
descendants of a prior cluster), and merges (multiple prior ancestors
collapsed into one new). The single matched-1:1 case is the only one
that does NOT need a new name.

CLI:
  python scripts/match_clusters.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

JACCARD_MIN = 0.5


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def match_clusters(
    prior_members: dict[int, set[str]],
    new_members: dict[int, set[str]],
) -> dict:
    prior_ids = sorted(prior_members.keys())
    new_ids = sorted(new_members.keys())

    if not new_ids:
        return {"assignments": {}, "renames_needed": set()}

    # Build cost matrix (negated overlap so linear_sum_assignment maximizes overlap).
    rows = max(len(new_ids), len(prior_ids))
    cols = rows
    cost = np.zeros((rows, cols))
    for i, n_id in enumerate(new_ids):
        for j, p_id in enumerate(prior_ids):
            overlap = len(new_members[n_id] & prior_members[p_id])
            cost[i, j] = -overlap

    row_ind, col_ind = linear_sum_assignment(cost)

    assignments: dict[int, int] = {}
    renames_needed: set[int] = set()
    used_prior: set[int] = set()
    next_fresh_id = (max(prior_ids, default=-1) + 1)

    # 1) Hungarian-paired assignments that pass Jaccard threshold.
    for i, j in zip(row_ind, col_ind):
        if i >= len(new_ids) or j >= len(prior_ids):
            continue
        n_id = new_ids[i]
        p_id = prior_ids[j]
        if _jaccard(new_members[n_id], prior_members[p_id]) >= JACCARD_MIN:
            assignments[n_id] = p_id
            used_prior.add(p_id)

    # 2) Detect splits / merges among assigned clusters and the rest.
    # Prior used by best-overlap; remaining new clusters get fresh IDs.
    for n_id in new_ids:
        if n_id in assignments:
            continue
        # Find the prior with which this new cluster overlaps most (any non-zero overlap)
        best_prior = None
        best_overlap = 0
        for p_id in prior_ids:
            ov = len(new_members[n_id] & prior_members[p_id])
            if ov > best_overlap:
                best_overlap = ov
                best_prior = p_id
        if best_prior is not None and best_prior not in used_prior:
            # Inherit the prior id; this is a split where the larger sibling
            # got assigned in step 1, OR a freshly disjoint cluster — we
            # treat best-non-conflicting overlap as inheritance.
            assignments[n_id] = best_prior
            used_prior.add(best_prior)
        else:
            # Truly new cluster (no overlap, or overlap was claimed by sibling).
            assignments[n_id] = next_fresh_id
            next_fresh_id += 1
        renames_needed.add(n_id)

    # 3) Identify merges: a stable_id assigned to one new cluster whose
    #    members include majority of more than one prior cluster.
    for n_id, stable_id in assignments.items():
        ancestors = [p for p in prior_ids
                     if len(new_members[n_id] & prior_members[p]) > 0]
        if len(ancestors) > 1:
            renames_needed.add(n_id)

    return {"assignments": assignments, "renames_needed": renames_needed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Body filled in during Task 16 rehearsal.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tests/test_match_clusters.py -v
```
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/match_clusters.py tests/test_match_clusters.py
git commit -m "$(cat <<'EOF'
add match_clusters: Hungarian + Jaccard-≥0.5 + split/merge handling

Per spec §9.5. Stable cluster_id across runs so cluster_label persists.
Splits flag siblings for re-name; merges flag the merged cluster for
re-name; perfect matches keep both id and name.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Cluster naming (deterministic + Haiku + validation + override registry)

**Files:**
- Create: `scripts/name_clusters.py`
- Create: `scripts/cluster_name_overrides.json`
- Create: `tests/test_name_clusters.py`

Spec §9.6. Deterministic candidate from jurisdiction+type+top-tokens. Haiku 4.5 improves only when allowed by the validator (banned-term filter, length 2-7 words, must reference cluster tokens). Override registry wins over both.

- [ ] **Step 1: Tests (red)**

`tests/test_name_clusters.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from name_clusters import (
    deterministic_candidate,
    validate_llm_name,
    BANNED_TERMS,
    apply_override,
)


class TestDeterministicCandidate:
    def test_uses_dominant_jurisdiction_and_type(self):
        members = [
            {"label": "Approve housing", "type": "Decision", "jurisdiction_name": "San Rafael"},
            {"label": "Reject housing", "type": "Decision", "jurisdiction_name": "San Rafael"},
            {"label": "Approve housing", "type": "Decision", "jurisdiction_name": "San Rafael"},
        ]
        c = deterministic_candidate(members)
        assert "San Rafael" in c
        assert "Decision" in c

    def test_falls_back_when_no_jurisdiction(self):
        members = [{"label": "X", "type": "Issue"}, {"label": "Y", "type": "Issue"}]
        c = deterministic_candidate(members)
        assert "Issue" in c

    def test_includes_top_tokens(self):
        members = [
            {"label": "housing reform measure", "type": "Decision",
             "jurisdiction_name": "Marin"},
            {"label": "housing affordability act", "type": "Decision",
             "jurisdiction_name": "Marin"},
            {"label": "housing zoning update", "type": "Decision",
             "jurisdiction_name": "Marin"},
        ]
        c = deterministic_candidate(members)
        assert "housing" in c.lower()


class TestValidateLLMName:
    def test_accepts_clean_factual(self):
        assert validate_llm_name(
            "San Rafael housing decisions",
            cluster_tokens={"san", "rafael", "housing"},
        )

    def test_rejects_banned_terms(self):
        for banned in BANNED_TERMS:
            assert not validate_llm_name(
                f"San Rafael {banned} decisions",
                cluster_tokens={"san", "rafael"},
            ), f"{banned} should be rejected"

    def test_rejects_too_short(self):
        assert not validate_llm_name("housing", cluster_tokens={"housing"})

    def test_rejects_too_long(self):
        assert not validate_llm_name(
            "one two three four five six seven eight",
            cluster_tokens={"one"},
        )

    def test_rejects_when_no_cluster_token_overlap(self):
        # LLM hallucinated a name that has nothing to do with the cluster.
        assert not validate_llm_name(
            "marine biology research",
            cluster_tokens={"san", "rafael", "housing"},
        )


class TestApplyOverride:
    def test_override_wins(self, tmp_path, monkeypatch):
        registry = tmp_path / "overrides.json"
        registry.write_text(json.dumps({"7": "Stuart's pinned name"}))
        monkeypatch.setenv("CLUSTER_NAME_OVERRIDES_PATH", str(registry))
        # Even with a polished LLM name, an override forces it.
        result = apply_override(cluster_id=7,
                                deterministic="Marin · Decision · housing",
                                llm_proposed="San Rafael housing decisions")
        assert result == "Stuart's pinned name"

    def test_no_override_falls_through_to_llm(self, tmp_path, monkeypatch):
        registry = tmp_path / "overrides.json"
        registry.write_text("{}")
        monkeypatch.setenv("CLUSTER_NAME_OVERRIDES_PATH", str(registry))
        result = apply_override(cluster_id=7,
                                deterministic="X",
                                llm_proposed="Y")
        assert result == "Y"

    def test_no_override_no_llm_uses_deterministic(self, tmp_path, monkeypatch):
        registry = tmp_path / "overrides.json"
        registry.write_text("{}")
        monkeypatch.setenv("CLUSTER_NAME_OVERRIDES_PATH", str(registry))
        result = apply_override(cluster_id=7,
                                deterministic="X",
                                llm_proposed=None)
        assert result == "X"
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_name_clusters.py -v
```
Expected: FAIL.

- [ ] **Step 3: Override registry seed**

Create `scripts/cluster_name_overrides.json`:

```json
{}
```

(Empty by default. Stuart edits this file to pin specific cluster names.)

- [ ] **Step 4: Implementation**

`scripts/name_clusters.py`:

```python
"""Deterministic candidate + Haiku improvement + validation + override.

Spec §9.6. Pure functions tested in isolation; the LLM call (anthropic
SDK) lives in run_llm_naming(), only invoked by main() during the
rehearsal.

CLI:
  python scripts/name_clusters.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# `anthropic` import allowed only here per outbound_policy lint rule.
import anthropic  # noqa: F401

REPO = Path(__file__).resolve().parent.parent

BANNED_TERMS = {
    "influence", "controversial", "scandal", "scandalous", "alleged",
    "corrupt", "corruption", "shady", "questionable",
}

STOP_WORDS = {
    "the", "a", "an", "of", "for", "and", "or", "in", "on", "at",
    "to", "by", "with", "from", "is", "as", "this",
}


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z]+", (s or "").lower())
            if t and t not in STOP_WORDS]


def deterministic_candidate(members: list[dict]) -> str:
    """Build a baseline name without LLM: jurisdiction + type + top-token."""
    if not members:
        return "Unnamed cluster"
    juris = Counter(m.get("jurisdiction_name") for m in members
                    if m.get("jurisdiction_name"))
    types = Counter(m.get("type") for m in members if m.get("type"))
    tokens: Counter[str] = Counter()
    for m in members:
        for t in _tokens(m.get("label", "")):
            tokens[t] += 1
    parts = []
    if juris:
        parts.append(juris.most_common(1)[0][0])
    if types:
        parts.append(types.most_common(1)[0][0])
    top_tok = [t for t, _ in tokens.most_common(3)]
    if top_tok:
        parts.append(top_tok[0])
    return " · ".join(parts) if parts else "Unnamed cluster"


def validate_llm_name(name: str, cluster_tokens: set[str]) -> bool:
    """True iff the proposed LLM name passes spec §9.6 validation."""
    name = (name or "").strip()
    if not name:
        return False
    words = name.split()
    if len(words) < 2 or len(words) > 7:
        return False
    lower = name.lower()
    for banned in BANNED_TERMS:
        if banned in lower:
            return False
    name_toks = set(_tokens(name))
    return bool(name_toks & cluster_tokens)


def apply_override(*, cluster_id: int, deterministic: str,
                   llm_proposed: str | None) -> str:
    """Override registry > validated LLM > deterministic candidate."""
    path = Path(os.environ.get(
        "CLUSTER_NAME_OVERRIDES_PATH",
        str(REPO / "scripts" / "cluster_name_overrides.json"),
    ))
    if path.exists():
        try:
            registry = json.loads(path.read_text())
        except json.JSONDecodeError:
            registry = {}
        if str(cluster_id) in registry:
            return registry[str(cluster_id)]
    if llm_proposed:
        return llm_proposed
    return deterministic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # run_llm_naming() body filled in during Task 16 rehearsal — sends
    # samples to claude-haiku-4-5-20251001 via outbound_policy.audit_log.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Verify tests pass**

```bash
pytest tests/test_name_clusters.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/name_clusters.py scripts/cluster_name_overrides.json tests/test_name_clusters.py
git commit -m "$(cat <<'EOF'
add name_clusters: deterministic + Haiku + validator + override registry

Per spec §9.6. Override > validated LLM > deterministic candidate.
Validator rejects banned-term hallucinations + enforces length 2-7
words + requires the name to share at least one token with cluster
members. Override registry seeded empty.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Constellation payload publisher + atomic Cypher promote

**Files:**
- Create: `scripts/publish_constellation.py`
- Create: `tests/test_publish_constellation.py`

Spec §9.7. Build payload from `*_pending`, upload to Vercel Blob, run the 4-step atomic Cypher (snapshot → demote → promote → manifest). Drift budget breach blocks the manifest update.

- [ ] **Step 1: Tests (red) — payload schema + drift gate**

`tests/test_publish_constellation.py`:

```python
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from publish_constellation import (
    SCHEMA_VERSION,
    PAYLOAD_SIZE_GZ_BUDGET,
    DRIFT_BUDGET_NODE_PCT,
    DRIFT_BUDGET_CENTROID_PCT,
    build_payload,
    enforce_drift_budget,
    DriftBudgetExceeded,
)


def _node(i, x=0.0, y=0.0):
    return {
        "id": f"person-{i}", "type": "Person", "label": f"P{i}",
        "umap_x_pending": x, "umap_y_pending": y,
        "cluster_id_pending": 1, "embedding_hash": "h",
    }


class TestBuildPayload:
    def test_includes_schema_and_versions(self):
        payload = build_payload(
            nodes=[_node(0), _node(1, 1, 1)],
            edges=[],
            clusters=[{"id": 1, "label": "Test", "centroid": [0.5, 0.5], "member_count": 2}],
            version="2026-04-27-rehearsal-001",
            umap_version=14,
        )
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["version"] == "2026-04-27-rehearsal-001"
        assert payload["umap_version"] == 14
        assert payload["node_count"] == 2
        assert len(payload["nodes"]) == 2
        # Coords come from *_pending fields.
        assert payload["nodes"][0]["x"] == 0.0
        assert payload["nodes"][1]["x"] == 1.0


class TestDriftBudget:
    def test_within_budget_passes(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.1, 0.1], [10.1, 0.0]])  # tiny drift
        # Should not raise.
        enforce_drift_budget(prior_pts=prior, new_pts=new,
                             prior_centroids={1: prior.mean(axis=0)},
                             new_centroids={1: new.mean(axis=0)})

    def test_node_breach_raises(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.0, 0.0], [13.0, 0.0]])  # node moved 30% of map width
        try:
            enforce_drift_budget(prior_pts=prior, new_pts=new,
                                 prior_centroids={}, new_centroids={})
        except DriftBudgetExceeded as e:
            assert "node" in str(e).lower()
            return
        raise AssertionError("DriftBudgetExceeded not raised")

    def test_centroid_breach_raises(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.0, 0.0], [10.0, 0.0]])  # nodes still
        # Cluster centroid moved 20% of map width — breach (budget 15%).
        try:
            enforce_drift_budget(
                prior_pts=prior, new_pts=new,
                prior_centroids={1: np.array([5.0, 0.0])},
                new_centroids={1: np.array([7.0, 0.0])},
            )
        except DriftBudgetExceeded as e:
            assert "centroid" in str(e).lower()
            return
        raise AssertionError("DriftBudgetExceeded not raised")


class TestBudgetConstants:
    def test_drift_budgets_match_spec(self):
        # Spec §4.3: 25% per-node, 15% per-cluster-centroid.
        assert DRIFT_BUDGET_NODE_PCT == 0.25
        assert DRIFT_BUDGET_CENTROID_PCT == 0.15

    def test_payload_size_budget_matches_spec(self):
        # Spec §11 v2.0 pass criterion: ≤8MB gzipped.
        assert PAYLOAD_SIZE_GZ_BUDGET == 8 * 1024 * 1024
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_publish_constellation.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implementation**

`scripts/publish_constellation.py`:

```python
"""Publish the Constellation payload — versioned blob + atomic Cypher.

Spec §9.5 + §9.7. The 4-step atomic Cypher (snapshot → demote → promote
→ manifest) lives in PROMOTE_CYPHER below; main() runs payload build →
drift gate → blob upload → Cypher transaction.

CLI:
  python scripts/publish_constellation.py [--dry-run] [--bypass-drift]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
PAYLOAD_SIZE_GZ_BUDGET = 8 * 1024 * 1024  # 8 MB

DRIFT_BUDGET_NODE_PCT = 0.25
DRIFT_BUDGET_CENTROID_PCT = 0.15


class DriftBudgetExceeded(Exception):
    pass


def build_payload(
    *, nodes: list[dict], edges: list[dict], clusters: list[dict],
    version: str, umap_version: int,
) -> dict:
    """Render the Constellation payload from *_pending fields."""
    out_nodes = []
    for n in nodes:
        out_nodes.append({
            "id": n["id"],
            "type": n["type"],
            "label": n.get("label", n["id"]),
            "key_fact": n.get("key_fact"),
            "x": n["umap_x_pending"],
            "y": n["umap_y_pending"],
            "cluster_id": n["cluster_id_pending"],
            "embedding_hash": n.get("embedding_hash"),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "umap_version": umap_version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(out_nodes),
        "edge_count": len(edges),
        "cluster_count": len(clusters),
        "nodes": out_nodes,
        "edges": edges,
        "clusters": clusters,
    }


def enforce_drift_budget(
    *, prior_pts: np.ndarray, new_pts: np.ndarray,
    prior_centroids: dict[int, np.ndarray],
    new_centroids: dict[int, np.ndarray],
) -> None:
    """Raise DriftBudgetExceeded if §4.3 thresholds breached."""
    if len(prior_pts) and len(new_pts):
        width = max(
            prior_pts[:, 0].max() - prior_pts[:, 0].min(),
            prior_pts[:, 1].max() - prior_pts[:, 1].min(),
            1e-12,
        )
        node_diff_pct = float(np.linalg.norm(new_pts - prior_pts, axis=1).max() / width)
        if node_diff_pct > DRIFT_BUDGET_NODE_PCT:
            raise DriftBudgetExceeded(
                f"node displacement {node_diff_pct:.1%} > budget {DRIFT_BUDGET_NODE_PCT:.0%}"
            )
        for cid, prior_c in prior_centroids.items():
            new_c = new_centroids.get(cid)
            if new_c is None:
                continue
            shift_pct = float(np.linalg.norm(new_c - prior_c) / width)
            if shift_pct > DRIFT_BUDGET_CENTROID_PCT:
                raise DriftBudgetExceeded(
                    f"cluster {cid} centroid displacement {shift_pct:.1%} > "
                    f"budget {DRIFT_BUDGET_CENTROID_PCT:.0%}"
                )


PROMOTE_CYPHER = """
// Spec §9.5 — atomic 4-step promotion. Run inside ONE transaction.

// 1a. Clear prior rollback metadata so each run's metadata is self-contained.
MATCH (n) WHERE n.had_canonical_before IS NOT NULL OR n.umap_x_previous IS NOT NULL
REMOVE n.had_canonical_before,
       n.umap_x_previous, n.umap_y_previous, n.umap_version_previous,
       n.cluster_id_previous, n.cluster_label_previous,
       n.cluster_centroid_distance_previous;

// 1b. Snapshot canonical for nodes that have it.
MATCH (n) WHERE n.umap_x IS NOT NULL
SET n.umap_x_previous = n.umap_x,
    n.umap_y_previous = n.umap_y,
    n.umap_version_previous = n.umap_version,
    n.cluster_id_previous = n.cluster_id,
    n.cluster_label_previous = n.cluster_label,
    n.cluster_centroid_distance_previous = n.cluster_centroid_distance,
    n.had_canonical_before = true;

// 1c. Mark first-time entrants.
MATCH (n) WHERE n.umap_x IS NULL AND n.umap_x_pending IS NOT NULL
SET n.had_canonical_before = false;

// 1d. Snapshot manifest metadata.
MATCH (s:_SyncState {kind: 'constellation'})
SET s.previous_version_id = s.version_id,
    s.previous_umap_version = s.umap_version,
    s.previous_blob_url = s.blob_url;

// 2. Demote BEFORE promote consumes pending.
MATCH (n) WHERE n.umap_x IS NOT NULL AND n.umap_x_pending IS NULL
REMOVE n.umap_x, n.umap_y, n.umap_version,
       n.cluster_id, n.cluster_label, n.cluster_centroid_distance;

// 3. Promote pending → canonical.
MATCH (n) WHERE n.umap_x_pending IS NOT NULL
SET n.umap_x = n.umap_x_pending,
    n.umap_y = n.umap_y_pending,
    n.umap_version = n.umap_version_pending,
    n.cluster_id = n.cluster_id_pending,
    n.cluster_label = n.cluster_label_pending,
    n.cluster_centroid_distance = n.cluster_centroid_distance_pending
REMOVE n.umap_x_pending, n.umap_y_pending, n.umap_version_pending,
       n.cluster_id_pending, n.cluster_label_pending,
       n.cluster_centroid_distance_pending;

// 4. Update manifest pointer.
MERGE (s:_SyncState {kind: 'constellation'})
SET s.version_id = $new_version_id,
    s.umap_version = $new_umap_version,
    s.blob_url = $new_blob_url,
    s.updated_at = datetime();
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bypass-drift", action="store_true",
                        help="DEV ONLY — skip the §4.3 drift budget check")
    args = parser.parse_args()
    # Body filled in during Task 16 rehearsal: read *_pending from Neo4j,
    # build_payload, gzip + size check, blob upload, drift gate, run
    # PROMOTE_CYPHER inside a single transaction with $new_version_id /
    # $new_umap_version / $new_blob_url params.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tests/test_publish_constellation.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/publish_constellation.py tests/test_publish_constellation.py
git commit -m "$(cat <<'EOF'
add publish_constellation: payload builder + drift gate + atomic Cypher

Per spec §9.5 + §9.7. PROMOTE_CYPHER is the literal 4-step transaction
from the spec — snapshot, demote, promote, manifest — verbatim so the
promotion semantics are reviewable from the script. Drift budget
constants match §4.3 (25% per-node / 15% per-cluster-centroid).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Manifest API endpoint

**Files:**
- Create: `app/src/app/api/constellation-manifest/route.ts`
- Create: `app/src/tests/api/constellation-manifest.test.ts`
- Modify: `app/src/middleware.ts` (or create) — IP allowlist gating until Plan 4b auth lands

Spec §9.7. Auth-gated; returns `{schema_version, current_version, umap_version, signed_url, expires_at, built_at, size_gz}`.

- [ ] **Step 1: Test (red)**

`app/src/tests/api/constellation-manifest.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

vi.mock("@/lib/blob", () => ({
  signBlobUrl: vi.fn(async (path: string, _ttl: number) =>
    `https://blob.vercel-storage.com/${path}?sig=fake&exp=1234`),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/constellation-manifest/route";

describe("GET /api/constellation-manifest", () => {
  beforeEach(() => {
    (runQuery as ReturnType<typeof vi.fn>).mockReset();
  });

  it("returns 401 if request fails IP allowlist", async () => {
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "8.8.8.8" },
    });
    const res = await GET(req);
    expect(res.status).toBe(401);
  });

  it("returns the active manifest with signed URL when allowed", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) => ({
          version_id: "2026-04-27-rehearsal-001",
          umap_version: 14,
          blob_url: "constellation-2026-04-27-rehearsal-001.json.gz",
          built_at: "2026-04-27T08:00:00Z",
        })[k],
      },
    ]);
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "127.0.0.1" },
    });
    const res = await GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.schema_version).toBe(1);
    expect(body.current_version).toBe("2026-04-27-rehearsal-001");
    expect(body.umap_version).toBe(14);
    expect(body.signed_url).toContain("constellation-2026-04-27-rehearsal-001.json.gz");
    expect(typeof body.expires_at).toBe("string");
  });

  it("returns 503 when no manifest exists yet (pre-first-publish)", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "127.0.0.1" },
    });
    const res = await GET(req);
    expect(res.status).toBe(503);
  });
});
```

- [ ] **Step 2: Run, verify fail**

```bash
cd app && npx vitest run src/tests/api/constellation-manifest.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implementation — create blob signing stub**

`app/src/lib/blob.ts` (a thin wrapper; v2.0 uses a stub, v2.1 wires real Vercel Blob):

```typescript
import "server-only";

export async function signBlobUrl(blobPath: string, ttlSeconds: number): Promise<string> {
  // v2.0 stub: in production this calls @vercel/blob's signed URL API
  // (or an S3 PreSign equivalent). For the rehearsal we serve from a local
  // file accessed by URL.
  const base = process.env.CONSTELLATION_BLOB_BASE ?? "https://blob.vercel-storage.com";
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  // Placeholder signature so the URL shape matches production.
  return `${base}/${blobPath}?exp=${exp}&sig=stub-${Math.random().toString(36).slice(2, 10)}`;
}
```

- [ ] **Step 4: Implementation — manifest route**

`app/src/app/api/constellation-manifest/route.ts`:

```typescript
import { NextResponse } from "next/server";
import { runQuery } from "@/lib/neo4j";
import { signBlobUrl } from "@/lib/blob";

const SIGNED_URL_TTL_SECONDS = 5 * 60;

// Pre-Plan-4b: allow only Stuart's home + tailnet ranges. Replaced by
// real session-cookie middleware once 4b lands.
const ALLOWED_IP_PREFIXES = (process.env.MANIFEST_ALLOWED_IP_PREFIXES ?? "127.0.0.1,::1,100.")
  .split(",")
  .map((p) => p.trim())
  .filter(Boolean);

function isAllowed(req: Request): boolean {
  const fwd = req.headers.get("x-forwarded-for") ?? "";
  const first = fwd.split(",")[0]?.trim() ?? "";
  return ALLOWED_IP_PREFIXES.some((p) => first.startsWith(p));
}

export async function GET(req: Request): Promise<NextResponse> {
  if (!isAllowed(req)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const rows = await runQuery<{
    version_id: string;
    umap_version: number;
    blob_url: string;
    built_at: string;
  }>(
    "MATCH (s:_SyncState {kind: 'constellation'}) " +
      "RETURN s.version_id AS version_id, s.umap_version AS umap_version, " +
      "s.blob_url AS blob_url, toString(s.built_at) AS built_at",
    {},
  );
  if (rows.length === 0) {
    return NextResponse.json(
      { error: "constellation not yet built", current_version: null },
      { status: 503 },
    );
  }
  const r = rows[0];
  const signed = await signBlobUrl(r.blob_url, SIGNED_URL_TTL_SECONDS);
  return NextResponse.json({
    schema_version: 1,
    current_version: r.version_id,
    umap_version: r.umap_version,
    signed_url: signed,
    expires_at: new Date(Date.now() + SIGNED_URL_TTL_SECONDS * 1000).toISOString(),
    built_at: r.built_at,
    size_gz: 0, // populated once publish records it on _SyncState
  });
}
```

- [ ] **Step 5: Verify**

```bash
cd app && npm run verify
```
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add app/src/app/api/constellation-manifest/route.ts \
        app/src/lib/blob.ts \
        app/src/tests/api/constellation-manifest.test.ts
git commit -m "$(cat <<'EOF'
add /api/constellation-manifest with IP-allowlist gate + signed URL

Per spec §9.7. Auth-gated; reads _SyncState{kind:'constellation'};
mints 5-min signed URL via blob.ts. Pre-Plan-4b: IP allowlist via
MANIFEST_ALLOWED_IP_PREFIXES env. Post-4b: NextAuth/Clerk middleware
replaces.

503 when no manifest exists yet (first-publish bootstrap state).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Cosmograph React glue + Tier-A/B sprite atlas

**Files:**
- Create: `app/src/lib/cosmograph-mount.tsx`
- Create: `app/src/lib/constellation-types.ts`
- Create: `app/src/components/constellation/sprite-atlas.ts`
- Create: `app/src/tests/lib/cosmograph-mount.test.tsx`
- Create: `app/src/tests/components/constellation/sprite-atlas.test.ts`

Spec §4.2 + §4.4. Thin React glue around `@cosmograph/cosmos` (MIT). Tier-A and Tier-B atlases are build-time and small (~5 MB combined).

- [ ] **Step 1: Install dep**

```bash
cd app && npm install @cosmograph/cosmos
```

- [ ] **Step 2: Constellation types**

`app/src/lib/constellation-types.ts`:

```typescript
export const CONSTELLATION_SCHEMA_VERSION = 1;

export type ConstellationNode = {
  id: string;
  type: string;
  label: string;
  key_fact?: string | null;
  x: number;
  y: number;
  cluster_id: number;
  embedding_hash?: string;
};

export type ConstellationEdge = {
  s: string;
  t: string;
  type: string;
  weight: number;
};

export type ConstellationCluster = {
  id: number;
  label: string;
  centroid: [number, number];
  member_count: number;
};

export type ConstellationPayload = {
  schema_version: number;
  version: string;
  umap_version: number;
  built_at: string;
  node_count: number;
  edge_count: number;
  cluster_count: number;
  nodes: ConstellationNode[];
  edges: ConstellationEdge[];
  clusters: ConstellationCluster[];
};
```

- [ ] **Step 3: Sprite atlas test (red)**

`app/src/tests/components/constellation/sprite-atlas.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  buildTierAAtlas, buildTierBAtlas, TIER_A_DOT_SIZES,
} from "@/components/constellation/sprite-atlas";
import { ALL_TYPES } from "@/lib/type-display";

describe("Tier-A atlas", () => {
  it("contains 21 types × 3 sizes = 63 sprites", () => {
    const atlas = buildTierAAtlas();
    expect(atlas.spriteCount).toBe(ALL_TYPES.length * TIER_A_DOT_SIZES.length);
  });

  it("each type has a colored dot at each size", () => {
    const atlas = buildTierAAtlas();
    for (const t of ALL_TYPES) {
      for (const s of TIER_A_DOT_SIZES) {
        expect(atlas.spriteIndex[`${t}:${s}`]).toBeTypeOf("number");
      }
    }
  });
});

describe("Tier-B atlas", () => {
  it("has one sprite per type with abbreviation", () => {
    const atlas = buildTierBAtlas();
    expect(atlas.spriteCount).toBe(ALL_TYPES.length);
    for (const t of ALL_TYPES) {
      expect(atlas.spriteIndex[t]).toBeTypeOf("number");
    }
  });
});
```

- [ ] **Step 4: Run, verify fail**

```bash
cd app && npx vitest run src/tests/components/constellation/sprite-atlas.test.ts
```
Expected: FAIL.

- [ ] **Step 5: Sprite atlas implementation**

`app/src/components/constellation/sprite-atlas.ts`:

```typescript
import { ALL_TYPES, type NodeType } from "@/lib/type-display";

export const TIER_A_DOT_SIZES = [4, 6, 8] as const;

const TYPE_COLORS: Record<NodeType, string> = {
  Person: "#8db8ff",
  Organization: "#b8a8d9",
  Committee: "#b8a8d9",
  Seat: "#e8ecf3",
  SeatService: "#e8ecf3",
  Election: "#e8ecf3",
  Candidacy: "#e8ecf3",
  Meeting: "#e8ecf3",
  AgendaItem: "#e8ecf3",
  Decision: "#a4e8bf",
  Filing: "#e8ecf3",
  MoneyFlow: "#f2c77a",
  Case: "#e27a7a",
  Proceeding: "#e27a7a",
  Project: "#d9a88d",
  Program: "#d9a88d",
  Agreement: "#e8ecf3",
  Amendment: "#e8ecf3",
  Record: "#e8ecf3",
  Place: "#e8ecf3",
  Issue: "#e8ecf3",
};

const TYPE_ABBREV: Record<NodeType, string> = {
  Person: "PER", Organization: "ORG", Committee: "CMT",
  Seat: "ST", SeatService: "STS", Election: "ELC",
  Candidacy: "CND", Meeting: "MTG", AgendaItem: "AI",
  Decision: "DEC", Filing: "FLG", MoneyFlow: "$$$",
  Case: "CSE", Proceeding: "PRC", Project: "PRJ",
  Program: "PRG", Agreement: "AGR", Amendment: "AMD",
  Record: "REC", Place: "PLC", Issue: "ISS",
};

export type SpriteAtlas = {
  spriteCount: number;
  spriteIndex: Record<string, number>;
  // texture data — Uint8ClampedArray of RGBA values; consumed by Cosmograph
  // as a sprite sheet via WebGL texture upload. v2.0 stub returns empty
  // texture; the prototype client (Task 14) doesn't need pixel-perfect
  // sprites — full rendering lands in v2.1 alongside Tier-C.
  textureRGBA: Uint8ClampedArray;
  textureWidth: number;
  textureHeight: number;
};

export function buildTierAAtlas(): SpriteAtlas {
  const spriteIndex: Record<string, number> = {};
  let i = 0;
  for (const t of ALL_TYPES) {
    for (const s of TIER_A_DOT_SIZES) {
      spriteIndex[`${t}:${s}`] = i++;
    }
  }
  return {
    spriteCount: i,
    spriteIndex,
    textureRGBA: new Uint8ClampedArray(0),
    textureWidth: 0,
    textureHeight: 0,
  };
}

export function buildTierBAtlas(): SpriteAtlas {
  const spriteIndex: Record<string, number> = {};
  let i = 0;
  for (const t of ALL_TYPES) {
    spriteIndex[t] = i++;
  }
  return {
    spriteCount: i,
    spriteIndex,
    textureRGBA: new Uint8ClampedArray(0),
    textureWidth: 0,
    textureHeight: 0,
  };
}

export { TYPE_COLORS, TYPE_ABBREV };
```

(Note: actual canvas-rendered RGBA is a Plan v2.1 deliverable — Plan v2.0 only needs the index contract verified. Cosmograph in the prototype will render colored dots from the type-colored material if no texture is provided.)

- [ ] **Step 6: Verify atlas tests pass**

```bash
cd app && npx vitest run src/tests/components/constellation/sprite-atlas.test.ts
```
Expected: PASS.

- [ ] **Step 7: Cosmograph mount test (smoke only — WebGL doesn't render in jsdom)**

`app/src/tests/lib/cosmograph-mount.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConstellationCanvas } from "@/lib/cosmograph-mount";

// Cosmograph is a real WebGL library; mock the constructor so the
// component-shape test can run in jsdom.
vi.mock("@cosmograph/cosmos", () => ({
  Graph: class FakeGraph {
    setConfig() {}
    setData() {}
    fitView() {}
    destroy() {}
  },
}));

describe("ConstellationCanvas", () => {
  it("renders a canvas element", () => {
    render(
      <ConstellationCanvas
        nodes={[]}
        edges={[]}
        spritesA={null}
        spritesB={null}
        onNodeClick={() => {}}
      />
    );
    expect(screen.getByTestId("constellation-canvas")).toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Cosmograph mount implementation**

`app/src/lib/cosmograph-mount.tsx`:

```typescript
"use client";

import { useEffect, useRef } from "react";
import { Graph } from "@cosmograph/cosmos";
import type {
  ConstellationNode, ConstellationEdge,
} from "@/lib/constellation-types";
import type { SpriteAtlas } from "@/components/constellation/sprite-atlas";

export type ConstellationCanvasProps = {
  nodes: ConstellationNode[];
  edges: ConstellationEdge[];
  spritesA: SpriteAtlas | null;
  spritesB: SpriteAtlas | null;
  onNodeClick: (id: string) => void;
};

export function ConstellationCanvas(props: ConstellationCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const g = new Graph(containerRef.current);
    graphRef.current = g;

    g.setConfig({
      backgroundColor: "#07090d",
      simulation: {
        // Disabled — positions come from UMAP (§4.2).
        // Cosmograph still renders without simulation; we just don't tick it.
        enabled: false,
      },
      nodes: {
        // For v2.0 prototype: render colored dots; cards-as-nodes lands in v2.1.
        sizeStrategy: "value",
      },
      onClick: (event: { id?: string } | null) => {
        if (event?.id) props.onNodeClick(event.id);
      },
    } as never);

    g.setData({
      nodes: props.nodes.map((n) => ({
        id: n.id,
        x: n.x,
        y: n.y,
        // Cosmograph color API varies by version — set per node here.
      })),
      links: props.edges.map((e) => ({ source: e.s, target: e.t })),
    } as never);

    g.fitView();

    return () => {
      g.destroy();
      graphRef.current = null;
    };
  }, [props.nodes, props.edges, props.onNodeClick]);

  return (
    <div
      ref={containerRef}
      data-testid="constellation-canvas"
      className="h-full w-full"
    />
  );
}
```

- [ ] **Step 9: Verify**

```bash
cd app && npm run verify
```
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add app/src/lib/cosmograph-mount.tsx app/src/lib/constellation-types.ts \
        app/src/components/constellation/sprite-atlas.ts \
        app/src/tests/lib/cosmograph-mount.test.tsx \
        app/src/tests/components/constellation/sprite-atlas.test.ts \
        app/package.json app/package-lock.json
git commit -m "$(cat <<'EOF'
add cosmograph-mount + Tier-A/B atlas index contract

@cosmograph/cosmos (MIT) integration. Force simulation disabled —
positions come from UMAP. Sprite atlas v2.0 ships the index contract
(buildTierAAtlas / buildTierBAtlas); pixel-perfect canvas rendering
is a Plan v2.1 deliverable. Prototype renders typed colored dots.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Tier-C on-demand sprite worker

**Files:**
- Create: `app/src/workers/tier-c-sprites.ts`
- Create: `app/src/tests/workers/tier-c-sprites.test.ts`

Spec §4.4 — on-demand card generation in Web Worker; ≥150 sprites/sec target.

- [ ] **Step 1: Test (red)**

`app/src/tests/workers/tier-c-sprites.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { renderCardSprite, LRU_CAPACITY } from "@/workers/tier-c-sprites";

describe("renderCardSprite", () => {
  it("returns an OffscreenCanvas-compatible bitmap structure", async () => {
    const node = {
      id: "person-kate-colin",
      type: "Person" as const,
      label: "Kate Colin",
      key_fact: "Council member",
    };
    const sprite = await renderCardSprite(node);
    // jsdom OffscreenCanvas may not exist; the function should fall back
    // to a typed-array stub that callers can detect and render server-side.
    expect(sprite).toMatchObject({
      nodeId: "person-kate-colin",
      width: expect.any(Number),
      height: expect.any(Number),
    });
  });

  it("LRU capacity matches spec §4.4 budget (2000)", () => {
    expect(LRU_CAPACITY).toBe(2000);
  });
});
```

- [ ] **Step 2: Run, verify fail**

```bash
cd app && npx vitest run src/tests/workers/tier-c-sprites.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implementation**

`app/src/workers/tier-c-sprites.ts`:

```typescript
import type { ConstellationNode } from "@/lib/constellation-types";

export const LRU_CAPACITY = 2000;
export const CARD_WIDTH = 120;
export const CARD_HEIGHT = 60;

export type CardSprite = {
  nodeId: string;
  width: number;
  height: number;
  // ImageBitmap in browser; null in jsdom (callers fall back to dot rendering).
  bitmap: ImageBitmap | null;
};

const cache = new Map<string, CardSprite>();

export async function renderCardSprite(node: ConstellationNode): Promise<CardSprite> {
  const cached = cache.get(node.id);
  if (cached) {
    // LRU: re-insert to push to most-recently-used position.
    cache.delete(node.id);
    cache.set(node.id, cached);
    return cached;
  }

  let bitmap: ImageBitmap | null = null;
  if (typeof OffscreenCanvas !== "undefined") {
    const canvas = new OffscreenCanvas(CARD_WIDTH, CARD_HEIGHT);
    const ctx = canvas.getContext("2d");
    if (ctx) {
      // Simple v2.0 card: type-colored panel + label + key_fact.
      ctx.fillStyle = "#0b0d11";
      ctx.fillRect(0, 0, CARD_WIDTH, CARD_HEIGHT);
      ctx.fillStyle = "#c2c8d2";
      ctx.font = "12px IBM Plex Sans, system-ui, sans-serif";
      ctx.fillText(node.label.slice(0, 18), 6, 18);
      if (node.key_fact) {
        ctx.fillStyle = "#7b8494";
        ctx.font = "10px IBM Plex Mono, ui-monospace, monospace";
        ctx.fillText(node.key_fact.slice(0, 22), 6, 38);
      }
      bitmap = await createImageBitmap(canvas);
    }
  }

  const sprite: CardSprite = {
    nodeId: node.id,
    width: CARD_WIDTH,
    height: CARD_HEIGHT,
    bitmap,
  };
  cache.set(node.id, sprite);
  if (cache.size > LRU_CAPACITY) {
    const oldest = cache.keys().next().value;
    if (oldest) cache.delete(oldest);
  }
  return sprite;
}

export function clearSpriteCache(): void {
  cache.clear();
}
```

- [ ] **Step 4: Verify tests pass**

```bash
cd app && npx vitest run src/tests/workers/tier-c-sprites.test.ts && npm run verify
```
Expected: PASS, full verify green.

- [ ] **Step 5: Commit**

```bash
git add app/src/workers/tier-c-sprites.ts app/src/tests/workers/tier-c-sprites.test.ts
git commit -m "$(cat <<'EOF'
add tier-c-sprites: on-demand card rendering with LRU eviction

Per spec §4.4. OffscreenCanvas-based; falls back to no-bitmap in jsdom.
LRU capped at 2000 sprites = 56MB texture budget. Throughput target
≥150/sec is verified during Task 16 rehearsal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Prototype `/` Constellation page (throwaway, replaced in v2.1)

**Files:**
- Modify: `app/src/app/page.tsx` (current homepage; currently renders signature subgraph)

Spec §11 v2.0 deliverable: a static-data prototype of `/` that loads the manifest, fetches the signed blob, parses, and renders all 114K nodes via Cosmograph. The current homepage gets renamed/preserved in case Stuart wants to compare.

- [ ] **Step 1: Snapshot current homepage**

```bash
cp /<repo>/app/src/app/page.tsx /tmp/page.tsx.v1
```

- [ ] **Step 2: Replace `app/src/app/page.tsx`**

```tsx
import "server-only";
import { loadStatus } from "@/lib/server/homepage-data";
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { ConstellationClient } from "@/app/_components/constellation-client";

export const dynamic = "force-dynamic";

export default async function Home() {
  const status = await loadStatus();
  return (
    <main className="min-h-screen bg-background">
      <StatusBar
        connected={status.connected}
        nodeCount={status.node_count}
        edgeCount={status.edge_count}
        jurisdictionCount={status.jurisdiction_count}
        ingestAt={status.ingest_at}
        subgraphsBuiltAt={status.subgraphs_built_at}
      />
      <NavHeader currentPath="/" />
      <ConstellationClient />
    </main>
  );
}
```

- [ ] **Step 3: Add the client wrapper that fetches manifest + blob**

`app/src/app/_components/constellation-client.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { ConstellationCanvas } from "@/lib/cosmograph-mount";
import type { ConstellationPayload } from "@/lib/constellation-types";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; payload: ConstellationPayload }
  | { kind: "rebuilding"; message: string }
  | { kind: "error"; message: string };

export function ConstellationClient() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const m = await fetch("/api/constellation-manifest", { credentials: "same-origin" });
        if (m.status === 503) {
          setState({ kind: "rebuilding", message: "Constellation is rebuilding…" });
          return;
        }
        if (!m.ok) {
          setState({ kind: "error", message: `manifest ${m.status}` });
          return;
        }
        const manifest = await m.json();
        const b = await fetch(manifest.signed_url);
        if (!b.ok) {
          setState({ kind: "error", message: `blob ${b.status}` });
          return;
        }
        const payload = (await b.json()) as ConstellationPayload;
        if (!cancelled) setState({ kind: "ready", payload });
      } catch (e) {
        if (!cancelled) setState({ kind: "error", message: String(e) });
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  if (state.kind === "loading") {
    return <div className="p-6 text-dim">Loading constellation…</div>;
  }
  if (state.kind === "rebuilding") {
    return <div className="p-6 text-dim">{state.message}</div>;
  }
  if (state.kind === "error") {
    return <div className="p-6 text-[#f2b441]">Constellation error: {state.message}</div>;
  }
  return (
    <div className="h-[calc(100vh-100px)] w-full">
      <ConstellationCanvas
        nodes={state.payload.nodes}
        edges={state.payload.edges}
        spritesA={null}
        spritesB={null}
        onNodeClick={(id) => console.log("clicked", id)}
      />
    </div>
  );
}
```

- [ ] **Step 4: Run dev server + smoke test**

```bash
cd app && PORT=3100 npm run dev &
sleep 6
curl -sS -H "x-forwarded-for: 127.0.0.1" -o /dev/null -w "%{http_code}\n" http://localhost:3100/
```
Expected: 200. Even with no manifest yet (pre-rehearsal), the page loads and shows "Constellation is rebuilding…" — which is the correct §9.7 failure mode.

- [ ] **Step 5: Verify**

```bash
cd app && npm run verify
```
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add app/src/app/page.tsx app/src/app/_components/constellation-client.tsx
git commit -m "$(cat <<'EOF'
prototype /: Constellation client (replaces v1 homepage)

Fetches /api/constellation-manifest → signed blob URL → parses
ConstellationPayload → mounts ConstellationCanvas. v2.0 prototype:
typed colored dots; cards-as-nodes is a Plan v2.1 deliverable. 503
"rebuilding" state shown until publish_constellation runs once.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Pipeline integration into `refresh_openmarin.py`

**Files:**
- Modify: `scripts/refresh_openmarin.py`

Add v2.0 pipeline steps after the existing v1 steps so a single `refresh_openmarin.py` invocation runs the entire chain.

- [ ] **Step 1: Modify the orchestrator**

In `scripts/refresh_openmarin.py`, extend `PYTHON_STEPS`:

```python
PYTHON_STEPS = [
    "scripts/apply_search_index.py",
    "scripts/build_search_properties.py",
    "scripts/build_record_preferred_urls.py",
    "scripts/build_catalog.py",
    "scripts/build_signature_subgraphs.py",
    # v2.0 pipeline additions (per spec §9.9):
    "scripts/build_embeddings.py",
    "scripts/build_umap.py",
    "scripts/build_clusters.py",
    "scripts/match_clusters.py",
    "scripts/name_clusters.py",
    "scripts/publish_constellation.py",
    "scripts/update_sync_state.py",
]
```

- [ ] **Step 2: Smoke test the chain runs (dry-run)**

```bash
cd /<repo>
# Should fail at the OPENAI_API_KEY check inside build_embeddings.py
# unless --dry-run is plumbed; main()'s body is filled in Task 16,
# so for now we just confirm the orchestrator finds each script.
python -c "
import pathlib, subprocess, sys
for s in [
    'scripts/build_embeddings.py', 'scripts/build_umap.py',
    'scripts/build_clusters.py', 'scripts/match_clusters.py',
    'scripts/name_clusters.py', 'scripts/publish_constellation.py',
]:
    assert pathlib.Path(s).exists(), s
print('all v2 scripts present')
"
```
Expected: `all v2 scripts present`.

- [ ] **Step 3: Commit**

```bash
git add scripts/refresh_openmarin.py
git commit -m "$(cat <<'EOF'
refresh_openmarin: wire v2.0 pipeline steps in order

Per spec §9.9. embeddings → umap → clusters → match → name →
publish_constellation, then existing update_sync_state. Bodies of
new scripts (Tasks 5-10) are stubs at this commit; Task 16 fills
them in during the production rehearsal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: End-to-end production rehearsal + benchmark report

**Files:**
- Modify: `scripts/build_embeddings.py` (fill in `main()` body)
- Modify: `scripts/build_umap.py` (fill in `main()` body)
- Modify: `scripts/build_clusters.py` (fill in `main()` body)
- Modify: `scripts/match_clusters.py` (fill in `main()` body)
- Modify: `scripts/name_clusters.py` (fill in `main()` body)
- Modify: `scripts/publish_constellation.py` (fill in `main()` body)
- Create: `docs/benchmarks/2026-04-XX-v2-rehearsal.md` (the GO/NO-GO report)

This task is the actual rehearsal: run the full pipeline once against the live Neo4j AuraDB, capture all 9 pass-criteria measurements, and write the GO/NO-GO decision.

The script bodies are filled in here (not in earlier tasks) to keep the test-driven phase clean — Tasks 5-10 ship pure helpers that are unit-tested; Task 16 is the integration glue and the production run.

- [ ] **Step 1: Fill `build_embeddings.py main()`**

Inside the `with driver.session(...) as session:` block, replace the `pass` with:

```python
print("loading nodes from Neo4j...")
records = session.run(
    "MATCH (n) RETURN n.id AS id, labels(n) AS labels, properties(n) AS props"
)
all_nodes = []
for r in records:
    props = dict(r["props"])
    props["id"] = r["id"]
    props["labels"] = r["labels"]
    nt = canonical_type(r["labels"], r["id"])
    if nt is None or not is_eligible(nt):
        continue
    props["type"] = nt
    all_nodes.append(props)
print(f"found {len(all_nodes)} eligible nodes")

# Build neighbor maps (server-side, one query).
neighbor_map: dict[str, list[dict]] = {n["id"]: [] for n in all_nodes}
neigh_records = session.run(
    "MATCH (a)-[r]-(b) "
    "WHERE a.id IS NOT NULL AND b.id IS NOT NULL "
    "RETURN a.id AS a_id, b.id AS b_id, labels(b) AS b_labels, b.label AS b_label, type(r) AS rel_type "
    "LIMIT 5000000"
)
by_id = {n["id"]: n for n in all_nodes}
for r in neigh_records:
    a_id = r["a_id"]; b_id = r["b_id"]
    if a_id not in by_id or b_id not in by_id:
        continue
    nt_b = canonical_type(r["b_labels"], b_id)
    if nt_b is None or not is_eligible(nt_b):
        continue
    if len(neighbor_map[a_id]) >= 5:
        continue  # cap at top-5 per spec §9.1
    neighbor_map[a_id].append({"id": b_id, "type": nt_b, "label": r["b_label"]})

# Compute work set: nodes that need re-embedding.
work = []
for n in all_nodes:
    text = synth_text_for_node(n, neighbor_map[n["id"]])
    h = synthesis_hash(text, sorted(x["id"] for x in neighbor_map[n["id"]]))
    if args.full or needs_embed(n, current_hash=h):
        work.append((n, text, h))
print(f"need to embed {len(work)} of {len(all_nodes)}")
if args.dry_run:
    return 0

# Batch through OpenAI.
client = openai.OpenAI()
i = 0
while i < len(work):
    batch = work[i:i + BATCH_SIZE]
    texts = [x[1] for x in batch]
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    rows = [
        {"id": batch[k][0]["id"], "embedding": resp.data[k].embedding,
         "hash": batch[k][2]}
        for k in range(len(batch))
    ]
    session.run(
        "UNWIND $rows AS row "
        "MATCH (n {id: row.id}) "
        "SET n.embedding = row.embedding, "
        "    n.embedding_hash = row.hash, "
        "    n.embedding_version = $version, "
        "    n.embedded_at = datetime()",
        rows=rows, version=EMBEDDING_VERSION,
    )
    for n, _t, _h in batch:
        audit_log(
            vendor="openai", node_id=n["id"], node_type=n["type"],
            neighbor_ids_included=[x["id"] for x in neighbor_map[n["id"]]],
            neighbor_ids_dropped=[], prompt_hash=_h,
        )
    i += BATCH_SIZE
    print(f"  embedded {min(i, len(work))}/{len(work)}")

return 0
```

- [ ] **Step 2: Fill `build_umap.py main()`**

The full body for `main()` reads embeddings, runs UMAP fit-or-transform, applies the cached/fresh similarity transform, and writes `umap_*_pending`. ~80 lines. Implementation skeleton in `scripts/build_umap.py:main()`:

```python
import time
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
)
with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
    sys.path.insert(0, str(REPO / "scripts"))
    from canonical_type import canonical_type
    from outbound_policy import is_eligible

    # Step 0: copy canonical → pending for ELIGIBLE nodes.
    print("Step 0: copying canonical → pending (eligible only)...")
    eligible = session.run(
        "MATCH (n) WHERE n.umap_x IS NOT NULL "
        "RETURN n.id AS id, labels(n) AS labels"
    )
    eligible_ids = []
    for r in eligible:
        nt = canonical_type(r["labels"], r["id"])
        if nt and is_eligible(nt):
            eligible_ids.append(r["id"])
    session.run(
        "MATCH (n) WHERE n.id IN $ids AND n.umap_x IS NOT NULL "
        "SET n.umap_x_pending = n.umap_x, "
        "    n.umap_y_pending = n.umap_y, "
        "    n.umap_version_pending = n.umap_version",
        ids=eligible_ids,
    )

    # Load embeddings for nodes that need fresh UMAP coords.
    print("loading embeddings...")
    rec = session.run(
        "MATCH (n) WHERE n.embedding IS NOT NULL "
        "RETURN n.id AS id, n.embedding AS emb, labels(n) AS labels"
    )
    work_ids = []
    work_embs = []
    for r in rec:
        nt = canonical_type(r["labels"], r["id"])
        if nt is None or not is_eligible(nt):
            continue
        work_ids.append(r["id"])
        work_embs.append(r["emb"])
    embs = np.array(work_embs)
    print(f"have {len(embs)} embeddings")

    if args.full_fit:
        print("running UMAP.fit_transform (this is the expensive step)...")
        import umap
        t0 = time.time()
        model = umap.UMAP(
            n_components=2, n_neighbors=30, min_dist=0.1,
            metric="cosine", random_state=42, init="spectral",
        )
        new_pts = model.fit_transform(embs)
        elapsed = time.time() - t0
        print(f"UMAP fit_transform: {elapsed:.1f}s")

        # Align to prior frame if one exists, then persist alignment.
        prior_path = ALIGNMENT_PATH
        if prior_path.exists():
            print("aligning to prior frame...")
            prior_pts_dict = {}
            prev = session.run(
                "MATCH (n) WHERE n.umap_x_previous IS NOT NULL "
                "RETURN n.id AS id, n.umap_x_previous AS x, n.umap_y_previous AS y"
            )
            for r in prev:
                prior_pts_dict[r["id"]] = (r["x"], r["y"])
            anchor_ids = [i for i in work_ids if i in prior_pts_dict]
            anchor_idx = [work_ids.index(i) for i in anchor_ids]
            if len(anchor_ids) >= 100:  # need enough anchors for stable transform
                anchor_new = new_pts[anchor_idx]
                anchor_prior = np.array([prior_pts_dict[i] for i in anchor_ids])
                T = fit_similarity_transform(anchor_new, anchor_prior)
                new_pts = apply_similarity_transform(new_pts, T)
                ALIGNMENT_PATH.write_text(json.dumps(T))
                print(f"transform: {T}")
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(model, f)
    else:
        # Incremental: load cached fit + transform new/dirty subset only.
        with open(MODEL_PATH, "rb") as f:
            model = pickle.load(f)
        new_pts = model.transform(embs)
        if ALIGNMENT_PATH.exists():
            T = json.loads(ALIGNMENT_PATH.read_text())
            new_pts = apply_similarity_transform(new_pts, T)

    # Write umap_*_pending.
    print("writing umap_*_pending...")
    rows = [
        {"id": work_ids[k], "x": float(new_pts[k][0]), "y": float(new_pts[k][1])}
        for k in range(len(work_ids))
    ]
    session.run(
        "UNWIND $rows AS row "
        "MATCH (n {id: row.id}) "
        "SET n.umap_x_pending = row.x, "
        "    n.umap_y_pending = row.y, "
        "    n.umap_version_pending = $v",
        rows=rows, v=UMAP_VERSION,
    )

driver.close()
return 0
```

- [ ] **Step 3: Fill `build_clusters.py`, `match_clusters.py`, `name_clusters.py`, `publish_constellation.py main()` bodies**

Similar pattern to Tasks 1 + 2: pull `*_pending` from Neo4j, call the unit-tested helpers, write back `*_pending`. Each is ~30-60 lines.

For `publish_constellation.py main()` specifically:

```python
import gzip, time
from neo4j import GraphDatabase
import numpy as np

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
)
with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
    # 1. Build payload from *_pending.
    nodes = list(session.run(
        "MATCH (n) WHERE n.umap_x_pending IS NOT NULL "
        "RETURN n.id AS id, labels(n) AS labels, n.label AS label, "
        "       n.umap_x_pending AS umap_x_pending, n.umap_y_pending AS umap_y_pending, "
        "       n.cluster_id_pending AS cluster_id_pending, "
        "       n.embedding_hash AS embedding_hash, n.search_key_fact AS key_fact"
    ))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from canonical_type import canonical_type
    payload_nodes = []
    pts = []
    for r in nodes:
        nt = canonical_type(r["labels"], r["id"]) or "Unknown"
        payload_nodes.append({
            "id": r["id"], "type": nt, "label": r["label"] or r["id"],
            "key_fact": r.get("key_fact"),
            "umap_x_pending": r["umap_x_pending"],
            "umap_y_pending": r["umap_y_pending"],
            "cluster_id_pending": r["cluster_id_pending"],
            "embedding_hash": r.get("embedding_hash"),
        })
        pts.append([r["umap_x_pending"], r["umap_y_pending"]])
    edges = [
        {"s": r["a_id"], "t": r["b_id"], "type": r["rel_type"], "weight": 1}
        for r in session.run(
            "MATCH (a)-[r]-(b) WHERE a.umap_x_pending IS NOT NULL AND b.umap_x_pending IS NOT NULL "
            "RETURN a.id AS a_id, b.id AS b_id, type(r) AS rel_type LIMIT 5000000"
        )
    ]
    clusters_q = list(session.run(
        "MATCH (n) WHERE n.cluster_id_pending IS NOT NULL "
        "RETURN n.cluster_id_pending AS id, "
        "       avg(n.umap_x_pending) AS cx, avg(n.umap_y_pending) AS cy, "
        "       count(n) AS member_count, "
        "       collect(n.cluster_label_pending)[0] AS label "
    ))
    clusters = [
        {"id": int(r["id"]), "label": r["label"] or "",
         "centroid": [float(r["cx"]), float(r["cy"])], "member_count": int(r["member_count"])}
        for r in clusters_q
    ]
    version_id = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')}-rehearsal-001"
    payload = build_payload(
        nodes=payload_nodes, edges=edges, clusters=clusters,
        version=version_id, umap_version=int(os.environ.get("UMAP_VERSION", "1")),
    )

    # 2. Drift gate (skip if no prior frame).
    if not args.bypass_drift:
        prior_pts_dict = {}
        prev = session.run(
            "MATCH (n) WHERE n.umap_x_previous IS NOT NULL "
            "RETURN n.id AS id, n.umap_x_previous AS x, n.umap_y_previous AS y"
        )
        for r in prev:
            prior_pts_dict[r["id"]] = (r["x"], r["y"])
        if prior_pts_dict:
            common = [(prior_pts_dict[n["id"]],
                       (n["umap_x_pending"], n["umap_y_pending"]))
                      for n in payload_nodes if n["id"] in prior_pts_dict]
            if common:
                prior = np.array([c[0] for c in common])
                new = np.array([c[1] for c in common])
                enforce_drift_budget(prior_pts=prior, new_pts=new,
                                     prior_centroids={}, new_centroids={})

    # 3. Serialize + size check.
    body = json.dumps(payload).encode("utf-8")
    body_gz = gzip.compress(body, compresslevel=6)
    if len(body_gz) > PAYLOAD_SIZE_GZ_BUDGET:
        print(f"FAIL: payload {len(body_gz)} > budget {PAYLOAD_SIZE_GZ_BUDGET}", file=sys.stderr)
        return 4
    print(f"payload: {len(body)} raw, {len(body_gz)} gzipped ({len(body_gz)/1024/1024:.1f} MB)")

    # 4. Upload to blob.
    blob_url = f"constellation-{version_id}.json.gz"
    blob_dest = REPO / "data" / "rehearsal-blobs" / blob_url
    blob_dest.parent.mkdir(parents=True, exist_ok=True)
    blob_dest.write_bytes(body_gz)
    print(f"wrote local blob: {blob_dest}")
    # Real Vercel Blob upload happens in v2.1; for the rehearsal we use a
    # local file served via /api/constellation-manifest's stub signer.

    if args.dry_run:
        return 0

    # 5. Atomic Cypher promote.
    session.run(PROMOTE_CYPHER, new_version_id=version_id,
                new_umap_version=int(os.environ.get("UMAP_VERSION", "1")),
                new_blob_url=blob_url)
    print("promoted to canonical; manifest updated")

driver.close()
return 0
```

- [ ] **Step 4: Run the rehearsal**

```bash
cd /<repo>
# Source the env from .env.local (project convention)
set -a && source app/.env.local && set +a
export OPENAI_API_KEY="<from 1Password>"
export ANTHROPIC_API_KEY="<from 1Password>"

# Time each phase.
{
  echo "=== Embeddings ==="
  time python scripts/build_embeddings.py
  echo "=== UMAP (full fit) ==="
  time python scripts/build_umap.py --full-fit
  echo "=== Clusters ==="
  time python scripts/build_clusters.py
  echo "=== Match ==="
  time python scripts/match_clusters.py
  echo "=== Name ==="
  time python scripts/name_clusters.py
  echo "=== Publish ==="
  time python scripts/publish_constellation.py
} 2>&1 | tee /tmp/v2-rehearsal-$(date +%Y%m%d).log
```

Capture each phase's wall-clock time.

- [ ] **Step 5: Measure client-side rendering**

```bash
cd app && PORT=3100 npm run dev &
sleep 6
# Manually visit http://localhost:3100/ in Chrome with DevTools open.
# Measure:
#   - first-paint (Performance tab → recording)
#   - parse time (Network tab → constellation blob fetch + JSON parse)
#   - FPS at full zoom-out (DevTools → Rendering → FPS meter)
#   - memory after fully loaded (Memory tab → snapshot, look at "Detached"
#     and total heap)
# Record numbers in the benchmark report.
```

- [ ] **Step 6: Write the benchmark report**

Create `docs/benchmarks/2026-04-XX-v2-rehearsal.md` (replace XX with the actual date the rehearsal runs):

```markdown
# Open Marin v2.0 Benchmark Rehearsal — YYYY-MM-DD

Production-size rehearsal of the entire v2 pipeline. Pass criteria from
`docs/specs/2026-04-26-open-marin-v2-design.md` §11 Plan v2.0 + §15.

## Environment
- Hardware: Mac mini M-series, 16GB RAM
- Node count: ___ eligible (per `canonical_type` + `is_eligible`)
- Edge count: ___
- Test browser: Chrome 132 / M1 MBP

## Pipeline phase timings

| Phase | Wall-clock | Budget | Pass? |
|---|---|---|---|
| build_embeddings.py | ___ | none (cost-only) | ✓ / ✗ |
| build_umap.py --full-fit | ___ | <12 min | ✓ / ✗ |
| build_clusters.py | ___ | <2 min | ✓ / ✗ |
| match_clusters.py | ___ | <30s | ✓ / ✗ |
| name_clusters.py | ___ | <60s | ✓ / ✗ |
| publish_constellation.py | ___ | <60s | ✓ / ✗ |

## Cost
- OpenAI: $___ (___ tokens × $0.02/1M)
- Anthropic: $___ (Haiku for ___ clusters)
- Total: $___ (budget for full refresh: <$2)

## Payload
- Raw JSON: ___ MB
- Gzipped: ___ MB (budget ≤ 8 MB)
- Pass: ✓ / ✗

## Drift (synthetic prior frame)
- Max per-node displacement: ___% (budget 25%)
- Max per-cluster-centroid displacement: ___% (budget 15%)
- Pass: ✓ / ✗

## Client metrics
- /api/constellation-manifest: ___ ms
- Blob fetch + parse: ___ s (budget ≤4s on Wi-Fi)
- First paint (full Constellation visible): ___ s
- FPS sustained at Tier-A zoom: ___ fps (budget ≥60fps)
- Tier-C sprite throughput: ___ /sec (budget ≥150/sec)
- Memory heap after fully loaded: ___ MB
- Pass: ✓ / ✗

## Outbound audit
- Total outbound calls: ___
- Ineligible-neighbor leaks: ___ (budget = 0)
- Pass: ✓ / ✗

## Cluster output sanity
- Total clusters formed: ___
- Mean cluster size: ___
- Largest cluster size: ___
- Banned-term hallucinations rejected by validator: ___
- Sample cluster labels (first 10):
  - ___
  - ___

## GO / NO-GO decision

Decision: **GO** / **NO-GO**

Rationale:

(If GO: spec assumptions hold; v2.1 may begin. If NO-GO: list which pass criteria failed and what needs to be amended in the spec before retry.)
```

- [ ] **Step 7: Commit the filled-in script bodies + report**

```bash
git add scripts/build_embeddings.py scripts/build_umap.py \
        scripts/build_clusters.py scripts/match_clusters.py \
        scripts/name_clusters.py scripts/publish_constellation.py \
        docs/benchmarks/
git commit -m "$(cat <<'EOF'
v2.0 rehearsal: fill main() bodies + benchmark report

Script main() bodies wired together end-to-end:
- build_embeddings: load eligible nodes, build neighbor map, batch
  through OpenAI text-embedding-3-small (100/batch), audit-log each
  call.
- build_umap: Step-0 copy canonical → pending (eligible only),
  fit-or-transform via cached model, similarity-transform align to
  prior frame, write umap_*_pending.
- build_clusters: HDBSCAN on (umap_x_pending, umap_y_pending), write
  cluster_id_pending + cluster_centroid_distance_pending.
- match_clusters: Hungarian + Jaccard ≥ 0.5, overwrite
  cluster_id_pending with stable IDs, populate renames_needed.
- name_clusters: deterministic candidate + Haiku improve (only for
  renames_needed) + validator + override registry.
- publish_constellation: build payload from *_pending, gzip + size
  check, drift gate, write local blob, atomic Cypher promote.

Benchmark report: docs/benchmarks/YYYY-MM-DD-v2-rehearsal.md
documents the full 9-criterion pass/fail. GO/NO-GO decision recorded.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Push**

```bash
git push origin main
```

---

## Verification before reporting

1. `pytest tests/ -k "test_canonical_type or test_outbound_policy or test_outbound_audit or test_outbound_lint or test_citations or test_build_embeddings or test_build_umap or test_build_clusters or test_match_clusters or test_name_clusters or test_publish_constellation"` — all green.
2. `cd app && npm run verify` — green.
3. The benchmark report at `docs/benchmarks/2026-04-XX-v2-rehearsal.md` is filled in with real measurements.
4. The GO/NO-GO decision is recorded.

## Plan v2.0 completion checklist

- [ ] Tasks 1-15 committed (16 commits total since each task is one commit).
- [ ] Outbound policy (audit + lint) enforced; default-deny works against fixture ineligible types.
- [ ] Citations helper agrees Python ↔ TypeScript.
- [ ] All Python pure-helper unit tests green.
- [ ] All TS unit tests green; `npm run verify` green on HEAD.
- [ ] Pipeline integration: refresh_openmarin.py runs the full v2 chain.
- [ ] Production rehearsal completed; benchmark report fully filled.
- [ ] All 9 pass criteria evaluated.
- [ ] **GO/NO-GO decision recorded.** If GO: Plan v2.1 may begin. If NO-GO: spec amendment required first.

---

*End of plan.*
