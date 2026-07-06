import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DATA } from "../../../operator-workbench-src/_lib/operator-python";

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
});
