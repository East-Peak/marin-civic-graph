import path from "node:path";
import os from "node:os";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DATA, confidenceArgs } from "../../../operator-workbench-src/_lib/operator-python";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("operator python data paths", () => {
  it("uses the concrete FPPC committee candidate review artifact path", () => {
    vi.stubEnv("OPERATOR_REPO_ROOT", "/repo");
    expect(DATA.committeeCandidates()).toBe(
      path.join("/repo", "data", "review", "fppc-committee-review", "committee-candidates.jsonl"),
    );
  });

  it("uses the concrete identity confidence projection path", () => {
    vi.stubEnv("OPERATOR_REPO_ROOT", "/repo");
    expect(DATA.confidencePath()).toBe(path.join("/repo", "data", "identity", "confidence.jsonl"));
  });

  it("passes --confidence only when the operator confidence projection exists", () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "open-marin-confidence-test-"));
    vi.stubEnv("OPERATOR_REPO_ROOT", root);
    expect(confidenceArgs()).toEqual([]);

    mkdirSync(path.join(root, "data", "identity"), { recursive: true });
    writeFileSync(DATA.confidencePath(), "", "utf-8");

    expect(confidenceArgs()).toEqual(["--confidence", DATA.confidencePath()]);
  });
});
