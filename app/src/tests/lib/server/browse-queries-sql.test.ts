import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type BrowseRowFixture = {
  id: string;
  type: string;
  search_label: string;
  col1_key?: string | null;
  col1_value?: unknown;
  col2_key?: string | null;
  col2_value?: unknown;
};

function insertBrowseRow(db: Database.Database, row: BrowseRowFixture) {
  db.prepare(
    `
      INSERT INTO browse_rows(
        id,
        type,
        search_label,
        label_lower,
        col1_key,
        col1_value,
        col2_key,
        col2_value
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
  ).run(
    row.id,
    row.type,
    row.search_label,
    row.search_label.toLowerCase(),
    row.col1_key ?? null,
    row.col1_value == null ? null : JSON.stringify(row.col1_value),
    row.col2_key ?? null,
    row.col2_value == null ? null : JSON.stringify(row.col2_value),
  );
}

function makeFixtureDb(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-browse-sql-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE browse_rows (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      search_label TEXT NOT NULL,
      label_lower TEXT NOT NULL,
      col1_key TEXT,
      col1_value TEXT,
      col2_key TEXT,
      col2_value TEXT
    );
    CREATE INDEX idx_browse_rows_type_id
      ON browse_rows(type, id);
    CREATE INDEX idx_browse_rows_label_lower
      ON browse_rows(label_lower);
  `);

  [
    {
      id: "person-alpha",
      type: "Person",
      search_label: "Alpha Mayor",
      col1_key: "current_seat_display",
      col1_value: "Mayor",
      col2_key: "jurisdiction_name",
      col2_value: "San Rafael",
    },
    {
      id: "person-beta",
      type: "Person",
      search_label: "Beta Council",
      col1_key: "current_seat_display",
      col1_value: "Councilmember",
      col2_key: "jurisdiction_name",
      col2_value: "Mill Valley",
    },
    {
      id: "person-gamma",
      type: "Person",
      search_label: "Gamma Resident",
      col1_key: "current_seat_display",
      col1_value: null,
      col2_key: "jurisdiction_name",
      col2_value: "Ross",
    },
    {
      id: "moneyflow-campaign-1250",
      type: "MoneyFlow",
      search_label: "$1,250 Campaign Contribution",
      col1_key: "amount",
      col1_value: 1250.75,
      col2_key: "flow_date",
      col2_value: "2024-03-10",
    },
  ].forEach((row) => insertBrowseRow(db, row));

  for (let i = 0; i < 205; i += 1) {
    insertBrowseRow(db, {
      id: `decision-${String(i).padStart(3, "0")}`,
      type: "Decision",
      search_label: `Decision ${i}`,
      col1_key: "decided_at",
      col1_value: "2024-01-01",
      col2_key: "institution_name",
      col2_value: "San Rafael City Council",
    });
  }

  db.close();
  return dbPath;
}

async function runSubstrateBrowse(
  opts: Parameters<
    typeof import("@/lib/server/browse-queries-sql").runBrowseQuerySubstrate
  >[0],
) {
  const { runBrowseQuerySubstrate } = await import("@/lib/server/browse-queries-sql");
  return runBrowseQuerySubstrate(opts);
}

describe("runBrowseQuerySubstrate", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb();
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("paginates by id ASC and resumes after the cursor", async () => {
    const first = await runSubstrateBrowse({ type: "Person", limit: 2 });
    expect(first.rows.map((row) => row.id)).toEqual(["person-alpha", "person-beta"]);
    expect(first.next_cursor).toBe("person-beta");

    const second = await runSubstrateBrowse({
      type: "Person",
      cursor: first.next_cursor ?? undefined,
      limit: 2,
    });
    expect(second.rows.map((row) => row.id)).toEqual(["person-gamma"]);
    expect(second.next_cursor).toBeNull();
  });

  it("filters q as a case-insensitive substring over label_lower", async () => {
    const result = await runSubstrateBrowse({
      type: "Person",
      search: "COUNCIL",
      limit: 10,
    });

    expect(result.rows.map((row) => row.id)).toEqual(["person-beta"]);
  });

  it("parses JSON-stringified column values so numeric props stay numeric", async () => {
    const result = await runSubstrateBrowse({ type: "MoneyFlow", limit: 10 });

    expect(result.rows).toEqual([
      expect.objectContaining({
        id: "moneyflow-campaign-1250",
        type: "MoneyFlow",
        search_label: "$1,250 Campaign Contribution",
        route: "/money-flow/campaign-1250",
        amount: 1250.75,
        flow_date: "2024-03-10",
      }),
    ]);
    expect(typeof result.rows[0].amount).toBe("number");
  });

  it("returns an empty page and the normal per-type columns when no rows match the type", async () => {
    const result = await runSubstrateBrowse({ type: "Organization", limit: 10 });

    expect(result.rows).toEqual([]);
    expect(result.next_cursor).toBeNull();
    expect(result.columns[0]).toEqual({ key: "search_label", label: "Name" });
  });

  it("clamps over-large limits to MAX_LIMIT", async () => {
    const result = await runSubstrateBrowse({ type: "Decision", limit: 10_000 });

    expect(result.rows).toHaveLength(200);
    expect(result.rows.at(-1)?.id).toBe("decision-199");
    expect(result.next_cursor).toBe("decision-199");
  });

  it("dispatches runBrowseQuery to the substrate reader when SERVING_BACKEND=substrate", async () => {
    const { runBrowseQuery } = await import("@/lib/server/browse-queries");

    const result = await runBrowseQuery({ type: "MoneyFlow", limit: 10 });

    expect(result.rows[0].amount).toBe(1250.75);
  });
});
