import { execSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { afterAll, describe, expect, it } from "vitest";

const APP = process.cwd();
const SCRIPT = path.join(APP, "scripts", "copy-subgraphs.mjs");
const PUBLIC = path.join(APP, "public");

function runCopySubgraphs() {
  execSync(`node ${JSON.stringify(SCRIPT)}`, { cwd: APP, stdio: "pipe" });
}

function publicJsonFiles(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return publicJsonFiles(full);
    return entry.name.endsWith(".json") || entry.name.endsWith(".jsonl") ? [full] : [];
  });
}

describe("public build confidence exclusion", () => {
  afterAll(() => {
    rmSync(path.join(PUBLIC, "confidence.jsonl"), { force: true });
    rmSync(path.join(PUBLIC, "reconciliation-overlay.json"), { force: true });
    runCopySubgraphs();
  });

  it("removes stale confidence artifacts and confidence-bearing overlay output from public assets", () => {
    mkdirSync(path.join(PUBLIC, "subgraphs"), { recursive: true });
    writeFileSync(path.join(PUBLIC, "confidence.jsonl"), '{"id":"conf-deadbeef"}\n', "utf-8");
    writeFileSync(
      path.join(PUBLIC, "subgraphs", "stale-overlay.json"),
      '{"case_id":"c1","confidence":{"band":"high","status":"active"}}\n',
      "utf-8",
    );

    runCopySubgraphs();

    expect(existsSync(path.join(PUBLIC, "confidence.jsonl"))).toBe(false);
    expect(existsSync(path.join(PUBLIC, "subgraphs", "stale-overlay.json"))).toBe(false);
    for (const file of publicJsonFiles(PUBLIC)) {
      expect(readFileSync(file, "utf-8")).not.toContain('"confidence"');
      expect(readFileSync(file, "utf-8")).not.toContain('"conf-');
    }
  });
});
