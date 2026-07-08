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

function makeEvidenceDb(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-evidence-"));
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

  writeNode(db, "decision-target", "Decision", "Target", { title: "Target" });
  writeNode(db, "record-null-date", "Record", "Undated", {
    captured_at: null,
    has_public_source: true,
    preferred_display_artifact: "undated.pdf",
    preferred_public_url: "https://example.test/undated.pdf",
    record_type: "minutes",
  });
  writeNode(db, "record-2024-date", "Record", "Dated", {
    captured_at: "2024-02-01",
    has_public_source: false,
    preferred_display_artifact: "dated.pdf",
    preferred_public_url: null,
    record_type: "staff_report",
  });
  writeNode(db, "not-record", "Organization", "Not a record", {
    captured_at: null,
    record_type: "should_not_emit",
  });
  writeNode(db, "record-other-target", "Record", "Other", {
    captured_at: null,
    has_public_source: true,
    record_type: "other",
  });

  writeEdge(db, "decision-target", "EVIDENCED_BY", "record-2024-date");
  writeEdge(db, "decision-target", "EVIDENCED_BY", "record-null-date");
  writeEdge(db, "decision-target", "EVIDENCED_BY", "not-record");
  writeEdge(db, "other-target", "EVIDENCED_BY", "record-other-target");
  writeEdge(db, "record-other-target", "EVIDENCED_BY", "decision-target");
  db.close();
  return dbPath;
}

describe("loadEvidence substrate mode", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
    process.env.SUBSTRATE_DB_PATH = makeEvidenceDb();
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("loads target Evidence Records from SQLite with Cypher null-first DESC ordering", async () => {
    const { loadEvidence } = await import("@/lib/server/entity-evidence");

    await expect(loadEvidence("decision-target")).resolves.toEqual([
      {
        id: "record-null-date",
        record_type: "minutes",
        captured_at: null,
        preferred_public_url: "https://example.test/undated.pdf",
        preferred_display_artifact: "undated.pdf",
        has_public_source: true,
      },
      {
        id: "record-2024-date",
        record_type: "staff_report",
        captured_at: "2024-02-01",
        preferred_public_url: null,
        preferred_display_artifact: "dated.pdf",
        has_public_source: false,
      },
    ]);
  });
});
