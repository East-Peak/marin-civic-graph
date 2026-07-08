// app/src/tests/lib/server/about-data.test.ts
import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { loadJurisdictions } from "@/lib/server/about-data";

const mockRunQuery = runQuery as unknown as ReturnType<typeof vi.fn>;

function fakeRecord(row: Record<string, unknown>) {
  return { get: (k: string) => row[k] };
}

function makeJurisdictionDb(
  rows: Array<{ id: string; type: string; props: Record<string, unknown> }>,
) {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-about-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE nodes (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      search_label TEXT NOT NULL,
      props TEXT NOT NULL CHECK (json_valid(props))
    );
    CREATE TABLE edges (
      source TEXT NOT NULL,
      rel TEXT NOT NULL,
      target TEXT NOT NULL
    );
  `);
  for (const row of rows) {
    db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)").run(
      row.id,
      row.type,
      String(row.props.name ?? row.id),
      JSON.stringify(row.props),
    );
  }
  db.close();
  return dbPath;
}

describe("loadJurisdictions", () => {
  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
    mockRunQuery.mockReset();
  });

  it("returns { ok: true, jurisdictions } with name+type rows in query order", async () => {
    mockRunQuery.mockResolvedValueOnce([
      fakeRecord({ name: "Belvedere", type: "city" }),
      fakeRecord({ name: "Fairfax", type: "town" }),
      fakeRecord({ name: "Marin County", type: "county" }),
    ]);
    const result = await loadJurisdictions();
    expect(result).toEqual({
      ok: true,
      jurisdictions: [
        { name: "Belvedere", type: "city" },
        { name: "Fairfax", type: "town" },
        { name: "Marin County", type: "county" },
      ],
    });
  });

  it("filters to Place nodes via shared JURISDICTION_PLACE_TYPES param", async () => {
    mockRunQuery.mockResolvedValueOnce([]);
    await loadJurisdictions();
    const [cypher, params] = mockRunQuery.mock.calls[0];
    expect(cypher).toContain(":Place");
    expect(cypher).toContain("place_type IN $place_types");
    expect(cypher).toContain("ORDER BY p.name ASC");
    // Single source of truth — must agree with /about list predicate.
    expect(params).toEqual({
      place_types: ["city", "town", "county"],
    });
  });

  it("returns { ok: true, jurisdictions: [] } on a legitimately-empty result", async () => {
    mockRunQuery.mockResolvedValueOnce([]);
    const result = await loadJurisdictions();
    expect(result).toEqual({ ok: true, jurisdictions: [] });
  });

  it("returns substrate jurisdictions from Place nodes ordered by name", async () => {
    process.env.SERVING_BACKEND = "substrate";
    process.env.SUBSTRATE_DB_PATH = makeJurisdictionDb([
      { id: "place-z", type: "Place", props: { name: "Z City", place_type: "city" } },
      {
        id: "place-marin",
        type: "Place",
        props: { name: "Marin County", place_type: "county" },
      },
      {
        id: "org-not-place",
        type: "Organization",
        props: { name: "Not Place", place_type: "city" },
      },
      {
        id: "place-region",
        type: "Place",
        props: { name: "Bay Area", place_type: "region" },
      },
      { id: "place-a", type: "Place", props: { name: "A Town", place_type: "town" } },
    ]);

    const result = await loadJurisdictions();

    expect(result).toEqual({
      ok: true,
      jurisdictions: [
        { name: "A Town", type: "town" },
        { name: "Marin County", type: "county" },
        { name: "Z City", type: "city" },
      ],
    });
    expect(mockRunQuery).not.toHaveBeenCalled();
  });

  it("returns { ok: true, jurisdictions: [] } for an empty substrate jurisdiction set", async () => {
    process.env.SERVING_BACKEND = "substrate";
    process.env.SUBSTRATE_DB_PATH = makeJurisdictionDb([
      {
        id: "place-region",
        type: "Place",
        props: { name: "Bay Area", place_type: "region" },
      },
    ]);

    await expect(loadJurisdictions()).resolves.toEqual({ ok: true, jurisdictions: [] });
    expect(mockRunQuery).not.toHaveBeenCalled();
  });

  it("returns { ok: false } on loader error — distinguishes empty from broken", async () => {
    mockRunQuery.mockRejectedValueOnce(new Error("boom"));
    const result = await loadJurisdictions();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe("unknown");
    }
  });

  it("coerces missing type to empty string", async () => {
    mockRunQuery.mockResolvedValueOnce([fakeRecord({ name: "Ross", type: null })]);
    const result = await loadJurisdictions();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.jurisdictions[0]).toEqual({ name: "Ross", type: "" });
    }
  });
});
