import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const APP = process.cwd();

function src(...segments: string[]): string {
  return readFileSync(path.join(APP, "operator-workbench-src", ...segments), "utf-8");
}

describe("operator workbench reconciliation overlay script", () => {
  it("calls reconciliation_overlay.py directly from the route and page", () => {
    const route = src("api", "reconcile", "cases", "route.ts");
    const page = src("reconcile", "page.tsx");

    expect(route).toContain('"reconciliation_overlay.py"');
    expect(page).toContain('"reconciliation_overlay.py"');
    expect(route).not.toContain('"reconcile_cases.py"');
    expect(page).not.toContain('"reconcile_cases.py"');
  });

  it("passes the optional identity confidence projection through the cases route and page", () => {
    const route = src("api", "reconcile", "cases", "route.ts");
    const page = src("reconcile", "page.tsx");

    expect(route).toContain("confidenceArgs()");
    expect(page).toContain("confidenceArgs()");
  });

  it("passes the committee candidate file through the decide route", () => {
    const route = src("api", "reconcile", "decide", "route.ts");
    expect(route).toContain('"--committee-candidates"');
    expect(route).toContain("DATA.committeeCandidates()");
  });
});
