# Open Marin Phase 0 — v2-Native Projection Consolidation: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-stage `build_graph_projection.py` (legacy `Actor`/`Institution`) → `migrate_graph_v2.py` (→ `Person`/`Organization`) pipeline with a single **v2-native projection** that emits the settled schema directly from a reproducible materialization manifest, proven equivalent to today's live graph and verified by a dedicated gate — so no two-headed schema can mislead future work.

**Architecture:** Three ordered milestones. **A** builds the safety harness (frozen live-graph baseline, the materialization manifest, the equivalence verifier) *before* any behavior changes. **B** builds the v2-native projector behaviorally pinned by golden fixtures captured from the current pipeline, plus a v2-ported query pack whose metrics must match the frozen v1 metrics. **C** retires the legacy path, adds a local-only refresh, reconciles schema + docs, and lands it. Correctness rests on golden-parity (the new projector must reproduce the current `migrate_graph_v2` output) and a baseline-diff equivalence gate (rebuild into a clean target, diff against a frozen export).

**Tech Stack:** Python 3.14 (`pytest`, `neo4j` driver 5.x), Neo4j AuraDB, existing repo scripts under `scripts/`, `canonical_type.py` as the typing source of truth.

**Governing spec:** `docs/specs/2026-06-07-open-marin-coi-ngo-swarm-design.md` §2.5, §8. **Reference behavior:** `scripts/migration_mapping.py` (the exact transforms to reproduce), `scripts/migrate_graph_v2.py`, `scripts/build_graph_projection.py`, `scripts/graph_projection_lib.py`, `scripts/load_neo4j_v2.py`.

---

## Conventions

- **TDD, always:** failing test → run it red → minimal code → run it green → commit. Never implementation before a red test.
- **Git discipline:** `git branch --show-current` must be `main` immediately before every commit; stage only listed paths (the tree has untracked ambient `data/` — **never `git add -A`**); author must be `stuart@eastpeak.cc`; commit messages end with the Co-Authored-By trailer.
- **Tests live at `tests/`** (the repo's existing Python test tree — verified; do NOT use `tests/`). **Fixtures at** `tests/fixtures/phase0/`.
- **Run tests from repo root:** `python -m pytest tests/<file> -v`; "full suite green" means `python -m pytest tests -v`.

---

## File Structure

| File | Responsibility | Milestone |
|------|----------------|-----------|
| `scripts/export_graph_baseline.py` | Connect to live Aura, assert host fingerprint + count floors, export canonical facts (nodes+rels) to JSONL + sha256 | A |
| `registry/v2-materialization-manifest.json` | Declares every input that materializes the graph's facts (bundles + direct-ingestor JSONL), each git-tracked, sha256, expected counts | A |
| `scripts/materialization_manifest.py` | Load + validate the manifest (hashes match, inputs git-tracked, counts present) | A |
| `scripts/graph_compare.py` | Pure comparator: diff two canonical-fact graph exports over ids/labels/node-props/rels/rel-props, with a FIXED volatile denylist | A |
| `scripts/verify_phase0_consolidation.py` | The acceptance gate: baseline diff + count floors + no-legacy-labels + ported query pack + smoke | A/B |
| `scripts/build_graph_v2.py` | The v2-native projector: manifest → `Person`/`Organization` graph-v2 JSONL directly | B |
| `scripts/graph_v2_transforms.py` | Pure transforms ported from `migration_mapping.py` (classification, rel renames, prop remaps, CaseParticipation→PARTY_TO) | B |
| `scripts/run_graph_query_pack.py` | (modify) port Q1–Q5 to v2 labels/edges; assert metrics equal frozen v1 metrics | B |
| `scripts/refresh_openmarin.py` | (modify) add `--local-only` to skip all external/egress stages | C |
| `registry/neo4j-schema.cypher` | (replace) match `canonical_type.py` + ValidationCheck carve-out | C |

---

## Milestone A — Safety harness (baseline, manifest, verifier)

Nothing in this milestone changes graph-building behavior. It builds the instruments that make B provable.

### Task A1: Frozen baseline exporter with live-graph preflight

**Files:**
- Create: `scripts/export_graph_baseline.py`
- Test: `tests/test_export_graph_baseline.py`

- [ ] **Step 1: Write the failing test** (pure helpers — no live DB)

```python
# tests/test_export_graph_baseline.py
import json, hashlib
from scripts.export_graph_baseline import (
    assert_live_graph_floors, canonical_node_record, canonical_rel_record, export_sha256,
)

def test_floors_reject_undersized_graph():
    # ~112K nodes expected; a 6K stale/local graph must be rejected
    import pytest
    with pytest.raises(ValueError, match="below floor"):
        assert_live_graph_floors(total_nodes=6000, total_rels=20000,
                                 per_label={"Person": 6000})

def test_floors_accept_live_sized_graph():
    assert_live_graph_floors(
        total_nodes=112000, total_rels=140000,
        per_label={"Person": 6000, "Organization": 1300, "MoneyFlow": 11000,
                   "Filing": 10000, "Project": 49000},
    )  # returns None, no raise

def test_canonical_node_record_is_stable_and_sorted():
    rec = canonical_node_record(
        {"id": "person-x", "labels": ["Person"], "props": {"b": 2, "a": 1}})
    assert list(rec["props"].keys()) == ["a", "b"]   # sorted for stable hashing
    assert rec["id"] == "person-x"

def test_export_sha256_is_deterministic():
    rows = [{"id": "a"}, {"id": "b"}]
    assert export_sha256(rows) == export_sha256(list(rows))
```

- [ ] **Step 2: Run red**

Run: `python -m pytest tests/test_export_graph_baseline.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the helpers + a `main()` that does the live preflight**

```python
# scripts/export_graph_baseline.py  (helpers shown; main() wires the driver)
from __future__ import annotations
import json, hashlib, os
from urllib.parse import urlparse

# Hard floors derived from the verified live graph (2026-06): ~112K nodes / ~140K rels.
FLOORS = {"total_nodes": 100_000, "total_rels": 120_000,
          "labels": {"Person": 5_000, "Organization": 1_000, "MoneyFlow": 9_000,
                     "Filing": 8_000, "Project": 40_000}}

def assert_live_graph_floors(total_nodes, total_rels, per_label):
    if total_nodes < FLOORS["total_nodes"]:
        raise ValueError(f"total_nodes {total_nodes} below floor {FLOORS['total_nodes']}")
    if total_rels < FLOORS["total_rels"]:
        raise ValueError(f"total_rels {total_rels} below floor {FLOORS['total_rels']}")
    for label, floor in FLOORS["labels"].items():
        if per_label.get(label, 0) < floor:
            raise ValueError(f"label {label} count {per_label.get(label,0)} below floor {floor}")

def canonical_node_record(node):
    return {"id": node["id"], "labels": sorted(node["labels"]),
            "props": dict(sorted(node["props"].items()))}

def canonical_rel_record(rel):
    return {"source": rel["source"], "target": rel["target"], "type": rel["type"],
            "props": dict(sorted(rel["props"].items()))}

def export_sha256(rows):
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()

def aura_host(uri: str) -> str:
    return urlparse(uri).hostname or ""
# main(): connect via app/.env.local env, record aura_host fingerprint, count nodes/rels
# + per-label, call assert_live_graph_floors, stream nodes+rels to data/baseline/<host>-<ts>.jsonl,
# write a sidecar .sha256 + a manifest {host, counts, sha256}. Refuse to overwrite an existing baseline.
```

- [ ] **Step 4: Run green** — `python -m pytest tests/test_export_graph_baseline.py -v` → PASS.
- [ ] **Step 5: Commit** — `git add scripts/export_graph_baseline.py tests/test_export_graph_baseline.py && git commit -m "feat(phase0): frozen baseline exporter with live-graph preflight floors"`

### Task A2: Materialization manifest + validator

> **PREREQUISITE BLOCKER (Stuart + Tammy decision):** A large share of the bundles that materialize the live ~112K graph are **untracked ambient `data/` work** today (`data/normalized/form700/*`, `marin-county-permits/*`, `marin-county-campaign-finance-*`, and most jurisdiction meeting bundles have 0 git-tracked files). The manifest's reproducibility guarantee requires its inputs to be **git-tracked**. Before A2 can produce a manifest that materializes the full graph, the canonical materialization source set must be **selected and committed** (coordinating with Tammy, since this is mid-batch ambient work — never `git add -A` it blindly). Until then, A2 must `BLOCKED: untracked materialization inputs` rather than build a partial manifest.

**Files:**
- Create: `registry/v2-materialization-manifest.json`, `scripts/materialization_manifest.py`
- Test: `tests/test_materialization_manifest.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_materialization_manifest.py
import pytest
from scripts.materialization_manifest import load_manifest, validate_manifest

def test_rejects_untracked_input(tmp_path, monkeypatch):
    m = {"inputs": [{"path": "data/x.jsonl", "sha256": "deadbeef", "kind": "direct",
                     "expected_nodes": 10, "expected_edges": 0}]}
    # stub: pretend git does NOT track data/x.jsonl
    monkeypatch.setattr("scripts.materialization_manifest.is_git_tracked", lambda p: False)
    with pytest.raises(ValueError, match="not git-tracked"):
        validate_manifest(m, repo_root=tmp_path, check_hashes=False)

def test_accepts_tracked_input_with_matching_hash(tmp_path, monkeypatch):
    f = tmp_path / "data" / "x.jsonl"; f.parent.mkdir(parents=True); f.write_text("{}\n")
    import hashlib; sha = hashlib.sha256(f.read_bytes()).hexdigest()
    m = {"inputs": [{"path": "data/x.jsonl", "sha256": sha, "kind": "bundle",
                     "expected_nodes": 1, "expected_edges": 0}]}
    monkeypatch.setattr("scripts.materialization_manifest.is_git_tracked", lambda p: True)
    validate_manifest(m, repo_root=tmp_path, check_hashes=True)  # no raise
```

- [ ] **Step 2: Run red.**
- [ ] **Step 3: Implement** `load_manifest` (read JSON), `is_git_tracked(path)` (`git ls-files --error-unmatch`), `validate_manifest` (every input git-tracked; if `check_hashes`, recompute sha256 and compare; require `expected_nodes`/`expected_edges` present). Seed `registry/v2-materialization-manifest.json` by enumerating the current `data/normalized/**/bundle*.json` + the settled direct-ingestor JSONL (Form 700) actually loaded today; compute hashes; fill expected counts from a dry projection.
- [ ] **Step 4: Run green.**
- [ ] **Step 5: Commit** — `feat(phase0): v2 materialization manifest + git-tracked input validator`

### Task A3: Pure graph comparator with fixed denylist + mutation tests

**Files:**
- Create: `scripts/graph_compare.py`
- Test: `tests/test_graph_compare.py`

- [ ] **Step 1: Failing test** (the mutation tests are the anti-false-completion guarantee)

```python
# tests/test_graph_compare.py
from scripts.graph_compare import compare_graphs, VOLATILE_PROPS

BASE_NODES = [{"id": "person-a", "labels": ["Person"], "props": {"name": "A", "ingested_at": "t1"}}]
BASE_RELS  = [{"source": "person-a", "target": "filing-1", "type": "FILED_BY", "props": {}}]

def test_identical_graphs_are_equivalent():
    r = compare_graphs(BASE_NODES, BASE_RELS, BASE_NODES, BASE_RELS)
    assert r.equivalent and not r.diffs

def test_volatile_prop_difference_is_ignored():
    other = [{"id": "person-a", "labels": ["Person"], "props": {"name": "A", "ingested_at": "t2"}}]
    assert compare_graphs(BASE_NODES, BASE_RELS, other, BASE_RELS).equivalent

def test_real_prop_mutation_fails():   # MUTATION TEST — must catch silent corruption
    other = [{"id": "person-a", "labels": ["Person"], "props": {"name": "B", "ingested_at": "t1"}}]
    assert not compare_graphs(BASE_NODES, BASE_RELS, other, BASE_RELS).equivalent

def test_missing_node_fails():
    assert not compare_graphs(BASE_NODES, BASE_RELS, [], BASE_RELS).equivalent

def test_rel_prop_mutation_fails():
    other = [{"source": "person-a", "target": "filing-1", "type": "FILED_BY", "props": {"role": "x"}}]
    assert not compare_graphs(BASE_NODES, BASE_RELS, BASE_NODES, other).equivalent

def test_denylist_is_small_and_fixed():
    assert VOLATILE_PROPS == frozenset({"ingested_at", "captured_at", "run_id", "_loaded_at"})
```

- [ ] **Step 2: Run red.**
- [ ] **Step 3: Implement** `VOLATILE_PROPS` (the small fixed denylist above — no per-run expansion), `compare_graphs(base_nodes, base_rels, new_nodes, new_rels)` returning a result with `equivalent: bool` and `diffs: list`. Strip `VOLATILE_PROPS` before comparing; key nodes by `id`, rels by `(source, type, target)` plus an index if repeated; report added/removed/changed. The function reports denied keys count so the gate can log them.
- [ ] **Step 4: Run green.**
- [ ] **Step 5: Commit** — `feat(phase0): pure graph comparator with fixed volatile denylist + mutation tests`

### Task A4: Verifier skeleton wiring (gate, no projector yet)

**Files:**
- Create: `scripts/verify_phase0_consolidation.py`
- Test: `tests/test_verify_phase0_consolidation.py`

- [ ] **Step 1: Failing test** — assert the gate fails when legacy labels are present and passes on a clean equivalent pair.

```python
# tests/test_verify_phase0_consolidation.py
from scripts.verify_phase0_consolidation import assert_no_legacy_labels
import pytest

def test_legacy_labels_rejected():
    with pytest.raises(AssertionError, match="legacy label"):
        assert_no_legacy_labels([{"id": "actor-x", "labels": ["Actor"], "props": {}}])

def test_settled_labels_ok():
    assert_no_legacy_labels([{"id": "person-x", "labels": ["Person"], "props": {}}])
```

- [ ] **Step 2: Run red.**
- [ ] **Step 3: Implement** `assert_no_legacy_labels` (reject `Actor`/`Institution`/`EconomicInterestDisclosure`/`CaseParticipation`) and a `main()` that: loads the frozen baseline, loads a rebuilt-graph export, runs `compare_graphs`, runs `assert_no_legacy_labels`, applies count floors, and (later) invokes the ported query pack — exits nonzero on any failure. The query-pack call is stubbed until B3.
- [ ] **Step 4: Run green.**
- [ ] **Step 5: Commit** — `feat(phase0): equivalence gate skeleton (no-legacy + baseline diff wiring)`

---

## Milestone B — v2-native projector + query-pack equivalence

### Task B1: Capture golden fixtures from the CURRENT pipeline

**Files:**
- Create: `tests/fixtures/phase0/golden-v2-nodes.jsonl`, `golden-v2-edges.jsonl`, `golden-input-bundles/` (a small but representative slice covering: a person Actor, an org-like Actor of each `actor_type`, an Institution (court + government), an EconomicInterestDisclosure, a CaseParticipation, and pass-through types)
- Test: `tests/test_golden_fixtures_present.py`

- [ ] **Step 1: Failing test** — assert the golden files exist and are non-empty and contain only settled labels.
- [ ] **Step 2: Run red.**
- [ ] **Step 3: Generate the goldens** by running the CURRENT pipeline on the fixture slice: `build_graph_projection.py` → `migrate_graph_v2.py`, copy the resulting `nodes.jsonl`/`edges.jsonl` into the fixture paths. These freeze today's behavior (incl. the `migration_mapping.py` rules: Actor→Person/Org by `actor_type`, Institution→Org, EID→Filing+`filing_type=form_700`, `REL_TYPE_MAP` renames, CaseParticipation→PARTY_TO).
- [ ] **Step 4: Run green.**
- [ ] **Step 5: Commit** — `test(phase0): freeze golden graph-v2 fixtures from current pipeline`

### Task B2: Port the transforms (pure), pinned by golden parity

**Files:**
- Create: `scripts/graph_v2_transforms.py`
- Test: `tests/test_graph_v2_transforms.py`

- [ ] **Step 1: Failing test** — assert the ported transforms reproduce `migration_mapping.py` on representative nodes/edges (import both; assert equality), e.g.:

```python
# tests/test_graph_v2_transforms.py
from scripts import migration_mapping as old
from scripts.graph_v2_transforms import classify_actor, rename_rel, cp_to_party_to

def test_actor_classification_matches_legacy():
    for atype, _ in old._ACTOR_ORG_LABELS.items():
        node = {"id": f"actor-x", "node_type": "Actor", "properties": {"actor_type": atype}}
        legacy = old.migrate_node(node)
        new_type, new_labels, new_id = classify_actor("actor-x", atype)
        assert (new_type, new_labels, new_id) == (legacy["node_type"], legacy["labels"], legacy["id"])

def test_person_default_for_unknown_actor_type():
    assert classify_actor("actor-y", "")[0] == "Person"

def test_rel_rename_matches_legacy_map():
    for old_rel, new_rel in old.REL_TYPE_MAP.items():
        assert rename_rel(old_rel) == new_rel
```

- [ ] **Step 2: Run red.**
- [ ] **Step 3: Implement** `graph_v2_transforms.py` by lifting the rules from `migration_mapping.py` into projection-time helpers: `classify_actor`, `classify_institution`, `eid_to_filing`, `rename_rel` (reuse `REL_TYPE_MAP`), `remap_props`, `cp_to_party_to`. Keep them pure. **Do not re-derive by hand where you can import the existing constants** (`_ORG_ACTOR_TYPES`, `_ACTOR_ORG_LABELS`, `REL_TYPE_MAP`).
- [ ] **Step 4: Run green.**
- [ ] **Step 5: Commit** — `feat(phase0): pure v2 transforms ported from migration_mapping, golden-pinned`

### Task B3: The v2-native projector

**Files:**
- Create: `scripts/build_graph_v2.py`
- Test: `tests/test_build_graph_v2.py`

- [ ] **Step 1: Failing test** — run `build_graph_v2` on the golden input bundles and assert output equals `golden-v2-nodes.jsonl` / `golden-v2-edges.jsonl` exactly (over canonical facts via `compare_graphs`).
- [ ] **Step 2: Run red.**
- [ ] **Step 3: Implement** `build_graph_v2.py`: read the materialization manifest, project each bundle's objects directly to settled-schema nodes/edges using `graph_v2_transforms` (no `Actor`/`Institution` ever emitted), fold in CaseParticipation→PARTY_TO, write `data/projected/graph-v2/{nodes,edges}.jsonl`. Reuse `build_graph_projection.py`'s object-walking structure but emit v2 types directly.
- [ ] **Step 4: Run green** (golden parity).
- [ ] **Step 5: Commit** — `feat(phase0): v2-native projector (manifest -> Person/Organization, golden-equivalent)`

### Task B4: Port the query pack to v2 with metric parity

**Files:**
- Modify: `scripts/run_graph_query_pack.py`
- Test: `tests/test_query_pack_v2_parity.py`

- [ ] **Step 1: Failing test** — freeze the current v1 query-pack metrics on the fixture slice (a committed `golden-querypack-metrics.json`), then assert the v2-ported pack produces identical metric values when run on the v2 projection of the same slice.
- [ ] **Step 2: Run red.**
- [ ] **Step 3: Implement** the port: update Q1–Q5 to v2 labels (`Person`/`Organization`) and `REL_TYPE_MAP` edge names, add a small ID/edge translation note, require an explicit `--projection-dir`, and assert no legacy labels appear in the projection it reads. Metrics must equal the frozen v1 metrics.
- [ ] **Step 4: Run green.**
- [ ] **Step 5: Commit** — `feat(phase0): port graph query pack to v2 with frozen-metric parity`

### Task B5: Full-graph equivalence run + wire the gate

**Files:**
- Modify: `scripts/verify_phase0_consolidation.py` (un-stub the query-pack call)
- Test: `tests/test_verify_phase0_consolidation.py` (extend)

- [ ] **Step 1:** Extend the verifier test to assert it invokes `compare_graphs` + the v2 query pack + floors and fails if any fails.
- [ ] **Step 2: Run red.**
- [ ] **Step 3:** Un-stub the query-pack call in `main()`. Document the operator run: export frozen baseline (A1) → `build_graph_v2` from manifest → load into a **scratch** Neo4j (`NEO4J_DATABASE=phase0scratch` or a local instance; **do not wipe live Aura unattended**) → export the scratch graph → `verify_phase0_consolidation`.
- [ ] **Step 4: Run green** (unit level). Operator runs the full live equivalence once and pastes output.
- [ ] **Step 5: Commit** — `feat(phase0): wire full equivalence gate (baseline diff + v2 query pack + floors)`

---

## Milestone C — Retirement, refresh, schema, docs, land

### Task C1: `refresh_openmarin.py --local-only`

**Files:** Modify: `scripts/refresh_openmarin.py` · Test: `tests/test_refresh_local_only.py`

- [ ] **Step 1: Failing test** — assert that with `--local-only`, the planned step list excludes the embedding/UMAP/cluster/`name_clusters`/`publish_constellation` stages and includes only local rebuild + search props + catalog + sync state.
- [ ] **Step 2: Run red.** **Step 3:** Add a `--local-only` flag that filters `PYTHON_STEPS` to the non-egress subset. **Step 4: Run green.** **Step 5: Commit** — `feat(phase0): refresh_openmarin --local-only (no external egress stages)`

### Task C2: Retire the legacy path (after goldens protect its semantics)

**Files:** Delete: `scripts/build_graph_projection.py`, `scripts/graph_projection_lib.py` (verify no non-v1 importers first), `scripts/migrate_graph_v2.py`, `scripts/migration_mapping.py`, and their tests · Test: `tests/test_no_legacy_pipeline_refs.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_no_legacy_pipeline_refs.py
import subprocess
def test_no_live_importers_of_legacy_pipeline():
    # git grep exits 1 on no-match: treat 1 as success, >1 as error
    r = subprocess.run(
        ["git", "grep", "-nE", r"build_graph_projection|graph_projection_lib|migrate_graph_v2|migration_mapping",
         "--", "scripts/", "app/"],
        capture_output=True, text=True)
    hits = [l for l in r.stdout.splitlines() if "test_no_legacy_pipeline_refs" not in l]
    assert hits == [], f"legacy pipeline still referenced:\n" + "\n".join(hits)
```

- [ ] **Step 2: Run red** (will list current importers). **Step 3:** Delete the four scripts + their tests; fix any remaining importer to use `build_graph_v2`. Confirm `graph_projection_lib.py` has no surviving non-v1 user before deleting. **Step 4: Run green.** **Step 5: Commit** — `refactor(phase0): retire legacy Actor/Institution projection + migration`

### Task C3: Reconcile schema with `canonical_type.py`

**Files:** Replace: `registry/neo4j-schema.cypher` · Test: `tests/test_schema_parity.py`

- [ ] **Step 1: Failing test** — parse `registry/neo4j-schema.cypher` constraint labels; assert the node-type set equals `canonical_type.ALL_TYPES` **plus** `{"ValidationCheck"}` (the documented QA carve-out) and the Organization subtype labels; assert no `Actor`/`Institution`/`EconomicInterestDisclosure`/`CaseParticipation`.
- [ ] **Step 2: Run red.** **Step 3:** Regenerate `neo4j-schema.cypher` from `canonical_type.ALL_TYPES` + subtypes + `ValidationCheck`. **Step 4: Run green.** **Step 5: Commit** — `fix(phase0): schema matches canonical_type (+ ValidationCheck carve-out)`

### Task C4: Update operational/recovery docs

**Files:** Modify: `README.md`, `docs/graph-query-pack.md`, `docs/internal/claude-collaboration-handoff.md`, `data/projected/README.md` (if present), `AGENTS.md`, `docs/internal/decision-log.md` · Test: `tests/test_docs_no_legacy_routing.py`

- [ ] **Step 1: Failing test** — grep these specific operational docs for "build_graph_projection"/"migrate_graph_v2"/"graph-v1" *as a current instruction* (allow a clearly-marked Historical section) and assert none route a fresh agent to the retired path.
- [ ] **Step 2: Run red.** **Step 3:** Update each doc to describe the v2-native rebuild (`build_graph_v2` from the manifest → `load_neo4j_v2` → `refresh_openmarin --local-only`); reconcile `AGENTS.md` branch policy + the single typing source (`canonical_type.py` + TS twin). **Step 4: Run green.** **Step 5: Commit** — `docs(phase0): route all recovery docs to the v2-native rebuild`

### Task C5: Final equivalence + land

- [ ] **Step 1:** Operator runs the full live flow: baseline export → `build_graph_v2` → scratch load → `verify_phase0_consolidation` (paste PASS). Then rebuild live Aura from the manifest and run `refresh_openmarin --local-only`.
- [ ] **Step 2:** Full suite green: `python -m pytest scripts/tests -v` (+ `cd app && npm run verify` if `app` touched).
- [ ] **Step 3:** Final git ledger: `git status --short --branch`, confirm only intended paths, `git log -1 --format="%an <%ae>"` == `stuart@eastpeak.cc`.
- [ ] **Step 4: Commit + push** — `feat(phase0): land v2-native projection consolidation` ; `git push origin main`.
- [ ] **Step 5:** Update `~/.openclaw/workspace/projects/marin-civic-graph.md` + decision log: Phase 0 complete; Phase 1 (COI schema) is next.

---

## Self-Review

- **Spec coverage:** §2.5 Phase 0 (v2-native projection, retire v1+migration, canonical_type sole source, materialization manifest, canonical-fact equivalence excluding derived state) → Tasks A1–C5. §8 Phase 0 tests (equivalence diff, verify green, no legacy importers) → A3/A4/B5/C2. ✓
- **Codex prompt-round findings folded in:** baseline live-Aura fingerprint + floors (A1); clean **scratch** target, no unattended Aura wipe (B5); git-tracked manifest inputs (A2); **fixed** comparator denylist + mutation tests (A3); query-pack **metric parity** (B4); golden parity preserving migration semantics before deletion (B1/B2/C2); `--local-only` refresh (C1); expanded docs retirement incl. handoff/AGENTS (C4); ValidationCheck carve-out (C3). ✓
- **Type consistency:** `compare_graphs` signature used identically in A3/A4/B3/B5; `classify_actor` returns `(node_type, labels, id)` consistently; `VOLATILE_PROPS` is the single fixed set. ✓
- **No placeholders:** every code/test step shows real code or an exact command. Larger implementation bodies (projector walk, schema regen) reference the specific existing module to lift from, pinned by golden/parity tests. ✓
