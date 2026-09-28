// /about's per-type counts must come from the same baked snapshot as the
// status bar, not the April graph-v1 copy in public/, and a missing catalog
// must read as unavailable rather than a fabricated "built today".
import { mkdtempSync, writeFileSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function substrateDir(withCatalog: boolean) {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-catalog-"));
  writeFileSync(path.join(dir, "public-substrate.sqlite"), "");
  if (withCatalog) {
    writeFileSync(
      path.join(dir, "catalog.json"),
      JSON.stringify({ as_of_date: "2026-07-07", built_at: "2026-07-07", counts: { Organization: 3548 } }),
    );
  }
  return path.join(dir, "public-substrate.sqlite");
}

describe("loadCatalog in substrate mode", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.SERVING_BACKEND;
  });
  afterEach(() => {
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("reads catalog.json baked next to the substrate", async () => {
    process.env.SUBSTRATE_DB_PATH = substrateDir(true);
    const { loadCatalog } = await import("@/lib/server/homepage-data");
    expect(await loadCatalog()).toMatchObject({
      built_at: "2026-07-07",
      counts: { Organization: 3548 },
    });
  });

  it("reports an unavailable catalog instead of fabricating a build date", async () => {
    process.env.SUBSTRATE_DB_PATH = substrateDir(false);
    const { loadCatalog } = await import("@/lib/server/homepage-data");
    expect(await loadCatalog()).toEqual({ built_at: null, counts: {} });
  });
});
