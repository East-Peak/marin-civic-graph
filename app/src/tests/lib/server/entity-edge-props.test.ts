// CAST_VOTE's vote reaches the Person and Decision payloads in both serving modes, and nothing else on an edge does.
import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({ runQuery: vi.fn() }));

import { runQuery } from "@/lib/neo4j";

const mockRunQuery = runQuery as ReturnType<typeof vi.fn>;
const SENTINEL = "ledger_secret_code";
const LEAKS = [SENTINEL, "s3cret", "seat_id", "seat-fictional", "maybe-later"];

const PERSON = "person-avery-quill";
const DECISION = "decision-fictional-levee";

function expectNoLeaks(payload: unknown) {
  const serialized = JSON.stringify(payload);
  for (const leaked of LEAKS) expect(serialized).not.toContain(leaked);
}

type PayloadLike = { id: string; edges: Array<{ type: string; source: string; target: string; props?: unknown }> };

/** The focus's own CAST_VOTE edges as [start, end, props] (EntityEdge source/target are the edge's start/end). */
function focusVoteEdges(payload: PayloadLike) {
  return payload.edges
    .filter((edge) => edge.type === "CAST_VOTE" && (edge.source === payload.id || edge.target === payload.id))
    .map((edge) => [edge.source, edge.target, edge.props])
    .sort((a, b) => `${a[0]}${a[1]}`.localeCompare(`${b[0]}${b[1]}`));
}

// --- Substrate ---------------------------------------------------------------------------------------------------

function makeSubstrate({ withProps }: { withProps: boolean }): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-entity-edge-props-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, search_label TEXT NOT NULL,
      props TEXT NOT NULL CHECK (json_valid(props)));
    CREATE TABLE edges (source TEXT NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL
      ${withProps ? ", props TEXT CHECK (props IS NULL OR json_valid(props))" : ""});
    CREATE TABLE identity_links (source TEXT NOT NULL, target TEXT NOT NULL, assertion_id TEXT NOT NULL,
      basis TEXT, decided_at TEXT, reviewer TEXT, PRIMARY KEY (source, target, assertion_id));
    CREATE TABLE money_rollups (org_id TEXT PRIMARY KEY, flows_in_count INTEGER NOT NULL,
      money_in_total REAL NOT NULL, flows_out_count INTEGER NOT NULL, money_out_total REAL NOT NULL,
      top_counterparties TEXT NOT NULL, by_kind TEXT NOT NULL);
  `);
  const nodes: Array<[string, string, string, Record<string, unknown>]> = [
    [PERSON, "Person", "Avery Quill", {}],
    ["person-bo-tarn", "Person", "Bo Tarn", {}],
    [DECISION, "Decision", "Fictional levee", { decided_at: "2024-03-04" }],
    ["decision-fictional-ferry", "Decision", "Fictional ferry", { decided_at: "2024-04-05" }],
  ];
  for (const [id, type, label, props] of nodes) {
    db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)").run(
      id, type, label, JSON.stringify({ id, name: label, ...props }),
    );
  }
  const edges: Array<[string, string, string, Record<string, unknown> | null]> = [
    [PERSON, "CAST_VOTE", DECISION, { vote: "absent", seat_id: "seat-fictional", [SENTINEL]: "s3cret" }],
    [PERSON, "CAST_VOTE", "decision-fictional-ferry", { vote: "maybe-later" }],
    ["person-bo-tarn", "CAST_VOTE", DECISION, { vote: "no" }],
  ];
  for (const [source, rel, target, props] of edges) {
    if (withProps) {
      db.prepare("INSERT INTO edges(source, rel, target, props) VALUES (?, ?, ?, ?)").run(
        source, rel, target, props ? JSON.stringify(props) : null,
      );
    } else {
      db.prepare("INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)").run(source, rel, target);
    }
  }
  db.close();
  return dbPath;
}

describe("substrate payloads", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.SERVING_BACKEND;
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(async () => {
    (await import("@/lib/server/substrate")).closeSubstrateDb();
    delete process.env.SUBSTRATE_DB_PATH;
    vi.restoreAllMocks();
  });

  it("carries the vote onto the Person page's CAST_VOTE edges (the person is the start)", async () => {
    process.env.SUBSTRATE_DB_PATH = makeSubstrate({ withProps: true });
    const { loadEntity } = await import("@/lib/server/entity-loader");

    const payload = (await loadEntity("person", "avery-quill"))!;

    expect(focusVoteEdges(payload)).toEqual([
      [PERSON, "decision-fictional-ferry", undefined],
      [PERSON, DECISION, { vote: "absent" }],
    ]);
    expectNoLeaks(payload);
  });

  it("carries the vote onto the Decision page's CAST_VOTE edges (the decision is the end)", async () => {
    process.env.SUBSTRATE_DB_PATH = makeSubstrate({ withProps: true });
    const { loadEntity } = await import("@/lib/server/entity-loader");

    const payload = (await loadEntity("decision", "fictional-levee"))!;

    expect(focusVoteEdges(payload)).toEqual([
      [PERSON, DECISION, { vote: "absent" }],
      ["person-bo-tarn", DECISION, { vote: "no" }],
    ]);
    expectNoLeaks(payload);
  });

  it("serves an artifact without the props column: the same edges, none with props", async () => {
    process.env.SUBSTRATE_DB_PATH = makeSubstrate({ withProps: false });
    const { loadEntity } = await import("@/lib/server/entity-loader");

    const payload = (await loadEntity("decision", "fictional-levee"))!;

    expect(focusVoteEdges(payload)).toEqual([
      [PERSON, DECISION, undefined],
      ["person-bo-tarn", DECISION, undefined],
    ]);
    for (const edge of payload.edges) expect("props" in edge).toBe(false);
  });
});

// --- Live (Cypher-result fixtures) ---------------------------------------------------------------------------------

function record(data: Record<string, unknown>) {
  return { get: (key: string) => data[key] };
}

function liveEdgeRow(start: string, end: string, props?: unknown) {
  const [source, target] = start < end ? [start, end] : [end, start];
  return record({
    source,
    target,
    rel_type: "CAST_VOTE",
    start_id: start,
    end_id: end,
    ...(props === undefined ? {} : { props }),
  });
}

function installLive(edgeRows: unknown[]) {
  mockRunQuery.mockImplementation(async (cypher: string) => {
    if (cypher.includes("count(DISTINCT n) AS total")) return [record({ total: 2 })];
    if (cypher.includes("startNode(r).id AS start_id") && cypher.includes("$whitelist")) return edgeRows;
    if (cypher.includes("$id") && !cypher.includes("$focus_id")) {
      return [record({ n: { properties: { id: DECISION }, labels: ["Decision"] } })];
    }
    if (cypher.includes("CAST_VOTE")) {
      return [
        record({ id: PERSON, labels: ["Person"], label: "Avery Quill", ring: 1 }),
        record({ id: "person-bo-tarn", labels: ["Person"], label: "Bo Tarn", ring: 1 }),
      ];
    }
    return [];
  });
}

describe("live payloads", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "live";
    mockRunQuery.mockReset();
  });

  afterEach(() => {
    delete process.env.SERVING_BACKEND;
    vi.restoreAllMocks();
  });

  it("projects only allowlisted properties in the edges query, never properties(r)", async () => {
    installLive([]);
    const { loadEntity } = await import("@/lib/server/entity-loader");

    await loadEntity("decision", "fictional-levee");

    const edgesCypher = mockRunQuery.mock.calls
      .map((call) => String(call[0]))
      .find((cypher) => cypher.includes("$whitelist"));
    expect(edgesCypher).toContain("CASE type(r) WHEN 'CAST_VOTE' THEN {vote: r.vote} ELSE null END AS props");
    expect(edgesCypher).not.toContain("properties(");
  });

  it("sanitizes projected props: the vote survives, invalid values and unlisted keys drop and are counted", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    installLive([
      liveEdgeRow(PERSON, DECISION, { vote: "absent", [SENTINEL]: "s3cret", seat_id: "seat-fictional" }),
      liveEdgeRow("person-bo-tarn", DECISION, { vote: "maybe-later" }),
    ]);
    const { loadEntity } = await import("@/lib/server/entity-loader");

    const payload = (await loadEntity("decision", "fictional-levee"))!;

    expect(focusVoteEdges(payload)).toEqual([
      [PERSON, DECISION, { vote: "absent" }],
      ["person-bo-tarn", DECISION, undefined],
    ]);
    expect(payload.edges.filter((edge) => "props" in edge)).toHaveLength(1);
    expectNoLeaks(payload);
    const logged = JSON.stringify(warn.mock.calls);
    expect(logged).toContain("1 out-of-vocabulary");
    expect(logged).toContain("2 non-allowlisted");
    for (const leaked of LEAKS) expect(logged).not.toContain(leaked);
  });

  it("reads a result row without a props column (or a null one) as no properties", async () => {
    installLive([liveEdgeRow(PERSON, DECISION), liveEdgeRow("person-bo-tarn", DECISION, null)]);
    const { loadEntity } = await import("@/lib/server/entity-loader");

    const payload = (await loadEntity("decision", "fictional-levee"))!;

    expect(payload.edges).toHaveLength(2);
    for (const edge of payload.edges) expect("props" in edge).toBe(false);
  });
});
