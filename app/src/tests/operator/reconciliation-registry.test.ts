// R4 — the operator workbench reconciliation registry is codegen'd from
// registry/reconciliation.json, mirroring the node-types registry pattern.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  BENCH_DONE_STATUSES,
  BENCH_KNOWN_STATUSES,
  BENCH_REJECTED_STATUSES,
  KEY_FIELD_BY_SOURCE,
  LEDGER_ACTIONABILITY,
} from "../../../operator-workbench-src/_lib/reconciliation.generated";
import { KEY_FIELD } from "../../../operator-workbench-src/_lib/case-refs";
import { renderReconciliationRegistry } from "../../../scripts/codegen-reconciliation.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const REGISTRY_PATH = path.join(REPO_ROOT, "registry", "reconciliation.json");
const GENERATED_PATH = path.join(REPO_ROOT, "app", "operator-workbench-src", "_lib", "reconciliation.generated.ts");

const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf-8"));

describe("reconciliation registry codegen mirror", () => {
  it("the committed generated file is up to date", () => {
    const onDisk = readFileSync(GENERATED_PATH, "utf-8");
    expect(onDisk).toBe(renderReconciliationRegistry(registry));
  });

  it("exports ledger actionability from the registry", () => {
    expect(LEDGER_ACTIONABILITY).toEqual({
      none: "actionable",
      requeued: "needs_review",
      approved: "resolved",
      deterministic: "resolved",
      superseded: "resolved",
      rejected_current_evidence: "resolved",
      rejected_entity_distinct: "resolved",
    });
  });

  it("exports the bench bucket sets from the registry", () => {
    expect([...BENCH_REJECTED_STATUSES]).toEqual(["rejected_current_evidence", "rejected_entity_distinct"]);
    expect([...BENCH_DONE_STATUSES]).toEqual(["approved", "superseded", "deterministic", "unsure"]);
    expect([...BENCH_KNOWN_STATUSES]).toEqual([
      "none",
      "requeued",
      "approved",
      "superseded",
      "deterministic",
      "rejected_current_evidence",
      "rejected_entity_distinct",
    ]);
  });

  it("exports the key field map consumed by case refs", () => {
    expect(KEY_FIELD_BY_SOURCE).toEqual({
      ein: "registry_ein",
      sos_id: "sos_id",
      committee_id: "committee_id",
    });
    expect(KEY_FIELD).toEqual(KEY_FIELD_BY_SOURCE);
  });
});
