// Fast regression for copy-operator-workbench.mjs fail-closed behavior. The full
// guarantee (a real public `next build` carries no operator routes) is the separate
// `npm run check:operator-exclusion` build test; this pins the mount/unmount + deploy-guard
// logic and that the generated group is never tracked in git.
import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { afterAll, describe, expect, it } from "vitest";

const APP = process.cwd(); // vitest runs from app/
const SCRIPT = path.join(APP, "scripts", "copy-operator-workbench.mjs");
const DEST = path.join(APP, "src", "app", "(operator-workbench)");

function runCopy(operator: boolean, extraEnv: Record<string, string> = {}) {
  // Clear deploy signals by default so mount tests work regardless of where they run.
  execSync(`node ${JSON.stringify(SCRIPT)}`, {
    cwd: APP,
    stdio: "pipe",
    env: { ...process.env, CI: "", VERCEL: "", VERCEL_ENV: "", OPERATOR_WORKBENCH: operator ? "1" : "", ...extraEnv },
  });
}

describe("operator workbench mount is fail-closed", () => {
  afterAll(() => runCopy(false)); // leave the repo in the public (excluded) state

  it("mounts the operator routes only when OPERATOR_WORKBENCH=1", () => {
    runCopy(true);
    expect(existsSync(path.join(DEST, "reconcile", "page.tsx"))).toBe(true);
    expect(existsSync(path.join(DEST, "api", "reconcile", "decide", "route.ts"))).toBe(true);
  });

  it("removes a stale mount on a public copy (fail-closed)", () => {
    runCopy(true); // simulate a prior dev:operator leaving a copy
    expect(existsSync(DEST)).toBe(true);
    runCopy(false); // public predev/prebuild
    expect(existsSync(DEST)).toBe(false);
  });

  it("REFUSES to mount on a deploy/CI build even if the flag leaks", () => {
    expect(() => runCopy(true, { CI: "1" })).toThrow(); // nonzero exit
    expect(existsSync(DEST)).toBe(false);
  });

  it("never tracks the generated route group in git", () => {
    const tracked = execSync("git ls-files 'src/app/(operator-workbench)'", { cwd: APP }).toString().trim();
    expect(tracked).toBe("");
  });
});
