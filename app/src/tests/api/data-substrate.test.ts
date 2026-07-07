import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function writeNode(
  db: Database.Database,
  id: string,
  type: string,
  searchLabel: string,
  props: Record<string, unknown>,
) {
  db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)").run(
    id,
    type,
    searchLabel,
    JSON.stringify(props),
  );
}

function writeEdge(db: Database.Database, source: string, rel: string, target: string) {
  db.prepare("INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)").run(
    source,
    rel,
    target,
  );
}

function writeFixtureDb(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-data-route-"));
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
    CREATE TABLE meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);
  db.prepare("INSERT INTO meta(key, value) VALUES ('as_of_date', '2026-07-07')").run();
  writeNode(db, "person-alice", "Person", "Alice Council", { name: "Alice Council" });
  writeNode(db, "seatservice-alice", "SeatService", "Alice service", {
    ended_at: null,
    jurisdiction_id: "place-san-rafael",
    seat_id: "seat-san-rafael-council",
  });
  writeNode(db, "filing-alice-700", "Filing", "Alice Form 700", {
    filing_type: "form_700",
    signed_at: "2024-03-20",
  });
  writeEdge(db, "person-alice", "HELD_BY", "seatservice-alice");
  writeEdge(db, "filing-alice-700", "FILED_BY", "person-alice");
  db.close();
  return dbPath;
}

describe("GET /api/data/[query] in substrate mode", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb();
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("uses the SQL backend and adds as_of_date for current-officeholders coverage", async () => {
    const { GET } = await import("@/app/api/data/[query]/route");

    const res = await GET(
      new Request(
        "http://localhost/api/data/current-officeholders-form-coverage?jurisdiction_id=place-san-rafael",
      ),
      { params: Promise.resolve({ query: "current-officeholders-form-coverage" }) },
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.slug).toBe("current-officeholders-form-coverage");
    expect(body.as_of_date).toBe("2026-07-07");
    expect(body.columns.map((column: { key: string }) => column.key)).toEqual([
      "person_name",
      "seat_display",
      "form_700_count",
      "form_803_count",
      "id",
    ]);
    expect(body.rows).toEqual([
      {
        person_name: "Alice Council",
        seat_display: "seat-san-rafael-council",
        form_700_count: 1,
        form_803_count: 0,
        id: "person-alice",
      },
    ]);
  });
});
