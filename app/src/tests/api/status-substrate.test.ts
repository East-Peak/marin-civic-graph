import { mkdtempSync, writeFileSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function writeStatusFixture() {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-status-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  writeFileSync(dbPath, "");
  writeFileSync(
    path.join(dir, "status_manifest.json"),
    JSON.stringify({
      as_of_date: "2026-07-07",
      bake_version: "test",
      node_count: 5,
      edge_count: 4,
      jurisdiction_count: 1,
      per_type_counts: { Decision: 1 },
    }),
  );
  return dbPath;
}

describe("GET /api/status in substrate mode", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
    process.env.SUBSTRATE_DB_PATH = writeStatusFixture();
  });

  afterEach(() => {
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("returns connected=true with counts from status_manifest.json next to the db", async () => {
    const { GET } = await import("@/app/api/status/route");

    const res = await GET();
    const body = await res.json();

    expect(body).toMatchObject({
      connected: true,
      node_count: 5,
      edge_count: 4,
      jurisdiction_count: 1,
      ingest_at: "2026-07-07",
    });
  });
});
