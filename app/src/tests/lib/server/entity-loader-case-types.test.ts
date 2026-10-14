import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// A worked case (docs/schema-v1.md "Worked-Case Modelling") adds only existing node types, linked by existing
// relationships, and no money. This proves the substrate loader serves each of them on its existing entity page
// and that a case link onto a committee leaves the committee's money untouched. Fictional values throughout.

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(async () => {
    throw new Error("live Neo4j path should not run in substrate loader tests");
  }),
}));

const KIND = "campaign_contribution";

const CASE_NODES: [string, string, string, Record<string, unknown>][] = [
  ["election-2030-sample-measure-q", "Election", "Sample County Measure Q (2030)", { title: "Sample County Measure Q (2030)", election_type: "county_measure" }],
  ["decision-sample-board-1-item-6", "Decision", "Sample fund — board item 6", { title: "Establish the sample fund", vote_summary: "AYES: ALL", agenda_item_number: "6" }],
  ["program-sample-resident-fund", "Program", "Sample Resident Fund", { program_type: "resident_empowerment_fund", status: "active" }],
  ["agreement-sample-fund-2030", "Agreement", "Sample fund agreement (2030)", { title: "Sample fund agreement", agreement_type: "fund_agreement", parties: "Sample County; Example Fund" }],
  ["filing-990-001234567-2029", "Filing", "Form 990 — Example Fund — TY 2029", { filing_type: "form_990", period_end: "2030-06-30" }],
  ["record-sample-form-460", "Record", "Form 460 — Sample Committee", { record_type: "form_460", has_public_source: true }],
];

function makeDb(withCase: boolean): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-case-types-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, search_label TEXT NOT NULL,
                        props TEXT NOT NULL CHECK (json_valid(props)));
    CREATE TABLE edges (source TEXT NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL);
    CREATE TABLE identity_links (source TEXT NOT NULL, target TEXT NOT NULL, assertion_id TEXT NOT NULL,
                                 basis TEXT, decided_at TEXT, reviewer TEXT, PRIMARY KEY (source, target, assertion_id));
    CREATE TABLE money_rollups (org_id TEXT PRIMARY KEY, flows_in_count INTEGER NOT NULL, money_in_total REAL NOT NULL,
                                flows_out_count INTEGER NOT NULL, money_out_total REAL NOT NULL,
                                top_counterparties TEXT NOT NULL CHECK (json_valid(top_counterparties)),
                                by_kind TEXT NOT NULL CHECK (json_valid(by_kind)));
  `);
  const node = db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)");
  const edge = db.prepare("INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)");
  node.run("committee-netfile-7", "Committee", "Sample Committee - Yes on Q", JSON.stringify({ name: "Sample Committee - Yes on Q" }));
  node.run("org-example-fund", "Organization", "Example Fund", JSON.stringify({ name: "Example Fund" }));
  node.run("moneyflow-7-a1", "MoneyFlow", "contribution", JSON.stringify({ amount: 250, flow_type: "contribution" }));
  edge.run("org-example-fund", "FROM_SOURCE", "moneyflow-7-a1");
  edge.run("moneyflow-7-a1", "TO_TARGET", "committee-netfile-7");
  db.prepare("INSERT INTO money_rollups VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    "org-example-fund", 0, 0, 1, 250, JSON.stringify([]),
    JSON.stringify([{ kind: KIND, in_count: 0, in_total: 0, out_count: 1, out_total: 250 }]));
  if (withCase) {
    for (const [id, type, label, props] of CASE_NODES) {
      node.run(id, type, label, JSON.stringify({ name: label, ...props }));
    }
    edge.run("committee-netfile-7", "PRIMARY_FOR_ELECTION", "election-2030-sample-measure-q");
    edge.run("program-sample-resident-fund", "RELATES_TO_DECISION", "decision-sample-board-1-item-6");
    edge.run("decision-sample-board-1-item-6", "RELATES_TO_AGREEMENT", "agreement-sample-fund-2030");
    edge.run("agreement-sample-fund-2030", "COUNTERPARTY_ACTOR", "org-example-fund");
    edge.run("filing-990-001234567-2029", "FILED_BY_ORG", "org-example-fund");
    edge.run("election-2030-sample-measure-q", "EVIDENCED_BY", "record-sample-form-460");
  }
  db.close();
  return dbPath;
}

async function load(dbPath: string, id: string) {
  vi.resetModules();
  process.env.SUBSTRATE_DB_PATH = dbPath;
  const { loadEntitySubstrateById } = await import("@/lib/server/entity-loader-substrate");
  const payload = await loadEntitySubstrateById(id);
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  return payload;
}

describe("worked-case node types on existing entity pages", () => {
  let base: string;
  let withCase: string;
  beforeEach(() => {
    base = makeDb(false);
    withCase = makeDb(true);
  });
  afterEach(() => {
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it.each(CASE_NODES.map(([id, type]) => [type, id]))("serves the %s %s", async (type, id) => {
    const payload = await load(withCase, id);
    expect(payload?.id).toBe(id);
    expect(payload?.type).toBe(type);
    expect(await load(base, id)).toBeNull();
  });

  it("links the committee to its election without moving any money", async () => {
    const before = await load(base, "committee-netfile-7");
    const after = await load(withCase, "committee-netfile-7");
    const ids = (p: typeof after) => (p?.neighbors ?? []).map((n) => n.id);
    expect(ids(after)).toContain("election-2030-sample-measure-q");
    expect(ids(before)).not.toContain("election-2030-sample-measure-q");
    const fundBefore = await load(base, "org-example-fund");
    const fundAfter = await load(withCase, "org-example-fund");
    expect(fundBefore?.money_rollup?.money_out_total).toBe(250);
    expect(fundBefore?.money_rollup?.by_kind).toEqual([{ kind: KIND, in_count: 0, in_total: 0, out_count: 1, out_total: 250 }]);
    expect(fundAfter?.money_rollup).toEqual(fundBefore?.money_rollup);
  });
});
