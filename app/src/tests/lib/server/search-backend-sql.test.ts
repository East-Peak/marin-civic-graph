import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(async () => {
    throw new Error("live Neo4j search path should not run in substrate mode");
  }),
}));

type NodeFixture = {
  id: string;
  type: string;
  searchLabel: string;
  props?: Record<string, unknown>;
};

function writeNode(db: Database.Database, node: NodeFixture) {
  const props = node.props ?? {};
  db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)").run(
    node.id,
    node.type,
    node.searchLabel,
    JSON.stringify(props),
  );
  const row = db.prepare("SELECT rowid FROM nodes WHERE id = ?").get(node.id) as {
    rowid: number;
  };
  db.prepare("INSERT INTO search_fts(rowid, search_label, search_terms) VALUES (?, ?, ?)").run(
    row.rowid,
    node.searchLabel,
    String(props.search_terms ?? ""),
  );
}

function writeFixtureDb(nodes: NodeFixture[]): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-search-sql-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE nodes (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      search_label TEXT NOT NULL,
      props TEXT NOT NULL CHECK (json_valid(props))
    );
    CREATE VIRTUAL TABLE search_fts
      USING fts5(
        search_label,
        search_terms,
        content='',
        tokenize='unicode61'
      );
  `);
  for (const node of nodes) writeNode(db, node);
  db.close();
  return dbPath;
}

const bucketNodes: NodeFixture[] = [
  {
    id: "record-shelter-exact",
    type: "Record",
    searchLabel: "Shelter record",
    props: {
      captured_at: "2026-06-30T10:00:00Z",
      search_terms: "shelter",
    },
  },
  {
    id: "person-shelter-mayor",
    type: "Person",
    searchLabel: "Shelter ranked entity",
    props: {
      jurisdiction_name: "San Rafael",
      search_key_fact: "Council member",
      search_last_activity: "2026-06-01",
      search_rank: 20,
      search_terms: "record-shelter-exact shelter rankbucket",
    },
  },
  {
    id: "org-shelter-partners",
    type: "Organization",
    searchLabel: "Shelter ranked entity",
    props: {
      jurisdiction_name: "Marin County",
      search_rank: 10,
      search_terms: "shelter rankbucket",
    },
  },
  {
    id: "record-shelter-new",
    type: "Record",
    searchLabel: "Shelter record",
    props: {
      captured_at: "2026-07-01T10:00:00Z",
      search_terms: "shelter",
    },
  },
  {
    id: "record-shelter-old",
    type: "Record",
    searchLabel: "Shelter record",
    props: {
      captured_at: "2026-01-01T10:00:00Z",
      search_terms: "shelter",
    },
  },
  {
    id: "project-or-token",
    type: "Project",
    searchLabel: "Standalone singleton project",
    props: {
      search_rank: 3,
      search_terms: "singleton",
    },
  },
  {
    id: "economicinterest-consulting-income",
    type: "EconomicInterest",
    searchLabel: "Consulting income",
    props: {
      jurisdiction_name: "San Rafael",
      search_key_fact: "Schedule C income",
      search_last_activity: "2025-04-01",
      search_rank: 42,
      search_terms: "consulting",
    },
  },
];

describe("runSearchSubstrate", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("builds the declared FTS query as lowercased quoted tokens joined with OR", async () => {
    const { buildFtsQuery } = await import("@/lib/server/search-backend-sql");

    expect(buildFtsQuery("  Shelter\tCAF\u00c9  ")).toBe('"shelter" OR "caf\u00e9"');
    expect(buildFtsQuery('Alpha "Beta" gamma-delta')).toBe(
      '"alpha" OR """beta""" OR "gamma-delta"',
    );
    expect(buildFtsQuery(" \n\t ")).toBeNull();
  });

  it("keeps an exact Record id first even when records are otherwise excluded", async () => {
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb(bucketNodes);
    const { runSearchSubstrate } = await import("@/lib/server/search-backend-sql");

    const payload = await runSearchSubstrate("record-shelter-exact", false);

    expect(payload.query).toBe("record-shelter-exact");
    expect(payload.results.map((result) => result.id)).toEqual([
      "record-shelter-exact",
      "person-shelter-mayor",
    ]);
    expect(payload.results[0].type).toBe("Record");
  });

  it("keeps entity and record buckets separate and orders records by captured_at", async () => {
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb(bucketNodes);
    const { runSearchSubstrate } = await import("@/lib/server/search-backend-sql");

    const withoutRecords = await runSearchSubstrate("shelter", false);
    const withRecords = await runSearchSubstrate("shelter", true);

    expect(withoutRecords.results.map((result) => result.type)).not.toContain("Record");
    expect(withRecords.results.map((result) => result.id)).toEqual([
      "person-shelter-mayor",
      "org-shelter-partners",
      "record-shelter-new",
      "record-shelter-exact",
      "record-shelter-old",
    ]);
  });

  it("uses OR semantics across terms instead of FTS5's default AND", async () => {
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb(bucketNodes);
    const { runSearchSubstrate } = await import("@/lib/server/search-backend-sql");

    const payload = await runSearchSubstrate("singleton nohit", false);

    expect(payload.results.map((result) => result.id)).toEqual(["project-or-token"]);
  });

  it("caps the assembled exact + bucketed result list at 50 total", async () => {
    const capNodes: NodeFixture[] = [
      {
        id: "person-capexact",
        type: "Person",
        searchLabel: "Cap exact",
        props: { search_rank: 100, search_terms: "person-capexact" },
      },
      ...Array.from({ length: 60 }, (_, index) => ({
        id: `person-cap-${String(index).padStart(2, "0")}`,
        type: "Person",
        searchLabel: "Cap entity",
        props: { search_rank: 0, search_terms: "person-capexact" },
      })),
    ];
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb(capNodes);
    const { runSearchSubstrate } = await import("@/lib/server/search-backend-sql");

    const payload = await runSearchSubstrate("person-capexact", true);

    expect(payload.results).toHaveLength(50);
    expect(payload.results[0].id).toBe("person-capexact");
    expect(new Set(payload.results.map((result) => result.id))).toHaveLength(50);
  });

  it("emits the SearchResult envelope from node props and substrate labels", async () => {
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb(bucketNodes);
    const { runSearchSubstrate } = await import("@/lib/server/search-backend-sql");

    const payload = await runSearchSubstrate("economicinterest-consulting-income", false);

    expect(payload.results[0]).toMatchObject({
      id: "economicinterest-consulting-income",
      type: "EconomicInterest",
      search_label: "Consulting income",
      route: "/economic-interest/consulting-income",
      key_fact: "Schedule C income",
      last_activity: "2025-04-01",
      jurisdiction: "San Rafael",
      rank: 42,
    });
  });

  it("handles empty and operator-heavy queries without widening or throwing", async () => {
    const garbageId = 'record-bad-"quote"-caf\u00e9-\u03a9';
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb([
      ...bucketNodes,
      {
        id: "   ",
        type: "Record",
        searchLabel: "Whitespace exact id",
        props: { captured_at: "2026-01-01T00:00:00Z", search_terms: "shelter" },
      },
      {
        id: garbageId,
        type: "Record",
        searchLabel: "Quoted unicode id",
        props: { captured_at: "2026-01-02T00:00:00Z", search_terms: "quote cafe" },
      },
    ]);
    const { runSearchSubstrate } = await import("@/lib/server/search-backend-sql");

    const emptyPayload = await runSearchSubstrate("   ", false);
    const garbagePayload = await runSearchSubstrate(garbageId, false);

    expect(emptyPayload.results.map((result) => result.id)).toEqual(["   "]);
    expect(garbagePayload.results[0].id).toBe(garbageId);
  });

  it("runSearch delegates to the SQL backend when SERVING_BACKEND=substrate", async () => {
    process.env.SUBSTRATE_DB_PATH = writeFixtureDb(bucketNodes);
    const { runSearch } = await import("@/lib/server/search-backend");

    const payload = await runSearch("singleton", false);

    expect(payload.results.map((result) => result.id)).toEqual(["project-or-token"]);
  });
});
