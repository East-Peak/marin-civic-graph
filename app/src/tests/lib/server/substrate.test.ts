import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function makeDbPath(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-substrate-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)");
  db.close();
  return dbPath;
}

describe("substrate server module", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("defaults to the live backend unless SERVING_BACKEND=substrate", async () => {
    const mod = await import("@/lib/server/substrate");
    expect(mod.servingBackend()).toBe("live");

    process.env.SERVING_BACKEND = "substrate";
    expect(mod.servingBackend()).toBe("substrate");

    process.env.SERVING_BACKEND = "SUBSTRATE";
    expect(mod.servingBackend()).toBe("live");
  });

  it("opens SUBSTRATE_DB_PATH as a read-only singleton", async () => {
    const dbPath = makeDbPath();
    process.env.SUBSTRATE_DB_PATH = dbPath;

    const { getSubstrateDb } = await import("@/lib/server/substrate");
    const first = getSubstrateDb();
    const second = getSubstrateDb();

    expect(second).toBe(first);
    expect(() =>
      first.prepare("INSERT INTO meta(key, value) VALUES ('write', 'blocked')").run(),
    ).toThrow(/readonly|read-only|attempt to write/i);
  });

  it("requires the substrate file to exist", async () => {
    process.env.SUBSTRATE_DB_PATH = path.join(
      tmpdir(),
      `missing-substrate-${Date.now()}.sqlite`,
    );

    const { getSubstrateDb } = await import("@/lib/server/substrate");
    expect(() => getSubstrateDb()).toThrow(/cannot open|no such file|exist|unable to open/i);
  });
});
