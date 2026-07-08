import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeType } from "@/lib/type-display";

type NodeFixture = {
  id: string;
  type: NodeType;
  label?: string;
  props?: Record<string, unknown>;
};

type EdgeFixture = {
  source: string;
  rel: string;
  target: string;
};

function makeFixtureDb(nodes: NodeFixture[], edges: EdgeFixture[]): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-explorer-engine-"));
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

  const insertNode = db.prepare(
    "INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)",
  );
  for (const node of nodes) {
    insertNode.run(
      node.id,
      node.type,
      node.label ?? node.id,
      JSON.stringify(node.props ?? {}),
    );
  }

  const insertEdge = db.prepare("INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)");
  for (const edge of edges) {
    insertEdge.run(edge.source, edge.rel, edge.target);
  }

  db.close();
  return dbPath;
}

async function closeSubstrate() {
  const mod = await import("@/lib/server/substrate");
  mod.closeSubstrateDb();
}

const focus: NodeFixture = {
  id: "person-focus",
  type: "Person",
  label: "Focus Person",
};

describe("expandSubstrate", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
  });

  afterEach(async () => {
    await closeSubstrate();
    delete process.env.SUBSTRATE_DB_PATH;
    delete process.env.SERVING_BACKEND;
    vi.resetModules();
  });

  it("trims a type pool by quota using hop then SUB_SPECS ranking", async () => {
    const moneyFlows: NodeFixture[] = Array.from({ length: 5 }, (_, idx) => {
      const amount = (idx + 1) * 100;
      return {
        id: `moneyflow-${idx + 1}`,
        type: "MoneyFlow",
        props: { amount, flow_date: `2024-01-0${idx + 1}` },
      };
    });
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [focus, ...moneyFlows],
      moneyFlows.map((node) => ({
        source: node.id,
        rel: "FROM_SOURCE",
        target: focus.id,
      })),
    );

    const { expandSubstrate } = await import("@/lib/server/explorer-engine");
    const result = expandSubstrate({
      focusId: focus.id,
      hopLimit: 1,
      excludedNodeTypes: [],
      excludedEdgeTypes: [],
      alreadyLoadedIds: [],
      includeUniversals: false,
    });

    expect(result.cap).toBe(20);
    expect(result.nodes.map((node) => node.id)).toEqual([
      "moneyflow-5",
      "moneyflow-4",
      "moneyflow-3",
      "moneyflow-2",
    ]);
    expect(result.nodes.map((node) => node.event_date)).toEqual([
      "2024-01-05",
      "2024-01-04",
      "2024-01-03",
      "2024-01-02",
    ]);
    expect(result.edges).toHaveLength(4);
    expect(result.edges[0]).toMatchObject({ type: "FROM_SOURCE", style: "money" });
  });

  it("applies the aggregate cap after merging type quotas, dropping lower-priority pools", async () => {
    const highPriority: NodeFixture[] = [
      ...Array.from({ length: 4 }, (_, idx) => ({
        id: `moneyflow-${idx}`,
        type: "MoneyFlow" as const,
        props: { amount: 1000 - idx, flow_date: `2024-01-${10 + idx}` },
      })),
      ...Array.from({ length: 4 }, (_, idx) => ({
        id: `decision-${idx}`,
        type: "Decision" as const,
        props: { decided_at: `2024-02-${10 + idx}` },
      })),
      ...Array.from({ length: 2 }, (_, idx) => ({
        id: `case-${idx}`,
        type: "Case" as const,
        props: { filed_at: `2024-03-${10 + idx}` },
      })),
      ...Array.from({ length: 2 }, (_, idx) => ({
        id: `project-${idx}`,
        type: "Project" as const,
      })),
      ...Array.from({ length: 2 }, (_, idx) => ({
        id: `program-${idx}`,
        type: "Program" as const,
      })),
      ...Array.from({ length: 2 }, (_, idx) => ({
        id: `agreement-${idx}`,
        type: "Agreement" as const,
        props: { effective_date: `2024-04-${10 + idx}` },
      })),
      { id: "amendment-0", type: "Amendment", props: { effective_date: "2024-05-10" } },
      ...Array.from({ length: 3 }, (_, idx) => ({
        id: `filing-${idx}`,
        type: "Filing" as const,
        props: { signed_at: `2024-06-${10 + idx}` },
      })),
    ];
    const lowPriority: NodeFixture[] = [
      { id: "committee-low", type: "Committee" },
      { id: "issue-lowest", type: "Issue" },
    ];
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [focus, ...highPriority, ...lowPriority],
      [...highPriority, ...lowPriority].map((node) => ({
        source: focus.id,
        rel: "PARTY_TO",
        target: node.id,
      })),
    );

    const { expandSubstrate } = await import("@/lib/server/explorer-engine");
    const result = expandSubstrate({
      focusId: focus.id,
      hopLimit: 1,
      excludedNodeTypes: [],
      excludedEdgeTypes: [],
      alreadyLoadedIds: [],
      includeUniversals: false,
    });

    expect(result.nodes).toHaveLength(20);
    expect(result.nodes.map((node) => node.id)).not.toContain("committee-low");
    expect(result.nodes.map((node) => node.id)).not.toContain("issue-lowest");
  });

  it("honors excluded node types, excluded edge types, and already-loaded ids", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        focus,
        { id: "decision-excluded-type", type: "Decision", props: { decided_at: "2024-01-01" } },
        { id: "moneyflow-excluded-edge", type: "MoneyFlow", props: { amount: 500 } },
        { id: "person-loaded", type: "Person" },
        { id: "record-kept", type: "Record", props: { published_at: "2024-03-01" } },
      ],
      [
        { source: focus.id, rel: "AT_MEETING", target: "decision-excluded-type" },
        { source: "moneyflow-excluded-edge", rel: "FROM_SOURCE", target: focus.id },
        { source: focus.id, rel: "PARTY_TO", target: "person-loaded" },
        { source: "record-kept", rel: "EVIDENCED_BY", target: focus.id },
      ],
    );

    const { expandSubstrate } = await import("@/lib/server/explorer-engine");
    const result = expandSubstrate({
      focusId: focus.id,
      hopLimit: 1,
      excludedNodeTypes: ["Decision"],
      excludedEdgeTypes: ["FROM_SOURCE"],
      alreadyLoadedIds: ["person-loaded"],
      includeUniversals: true,
    });

    expect(result.nodes.map((node) => node.id)).toEqual(["record-kept"]);
    expect(result.edges.map((edge) => [edge.source, edge.target, edge.type])).toEqual([
      ["record-kept", focus.id, "EVIDENCED_BY"],
      [focus.id, "person-loaded", "PARTY_TO"],
    ]);
  });

  it("reports the minimum BFS path length as ring for hop-2 candidates", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        focus,
        { id: "person-hop1", type: "Person" },
        { id: "project-hop2", type: "Project" },
      ],
      [
        { source: focus.id, rel: "MEMBER", target: "person-hop1" },
        { source: "person-hop1", rel: "RELATES_TO_PROJECT", target: "project-hop2" },
      ],
    );

    const { expandSubstrate } = await import("@/lib/server/explorer-engine");
    const result = expandSubstrate({
      focusId: focus.id,
      hopLimit: 2,
      excludedNodeTypes: [],
      excludedEdgeTypes: [],
      alreadyLoadedIds: [],
      includeUniversals: false,
    });

    expect(result.nodes.find((node) => node.id === "person-hop1")?.ring).toBe(1);
    expect(result.nodes.find((node) => node.id === "project-hop2")?.ring).toBe(2);
  });

  it("coalesces Proceeding event_date from occurred_at then proceeding_date", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        focus,
        {
          id: "proceeding-occurred",
          type: "Proceeding",
          props: { occurred_at: "2024-08-01", proceeding_date: "2024-07-01" },
        },
        {
          id: "proceeding-legacy",
          type: "Proceeding",
          props: { proceeding_date: "2024-06-01" },
        },
      ],
      [
        { source: "proceeding-occurred", rel: "PART_OF_CASE", target: focus.id },
        { source: "proceeding-legacy", rel: "PART_OF_CASE", target: focus.id },
      ],
    );

    const { expandSubstrate } = await import("@/lib/server/explorer-engine");
    const result = expandSubstrate({
      focusId: focus.id,
      hopLimit: 1,
      excludedNodeTypes: [],
      excludedEdgeTypes: [],
      alreadyLoadedIds: [],
      includeUniversals: false,
    });

    expect(
      Object.fromEntries(result.nodes.map((node) => [node.id, node.event_date])),
    ).toEqual({
      "proceeding-legacy": "2024-06-01",
      "proceeding-occurred": "2024-08-01",
    });
  });

  it("uses universal edges only when includeUniversals is true", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [focus, { id: "record-universal", type: "Record", props: { published_at: "2024-01-01" } }],
      [{ source: "record-universal", rel: "EVIDENCED_BY", target: focus.id }],
    );

    const { expandSubstrate } = await import("@/lib/server/explorer-engine");
    const baseParams = {
      focusId: focus.id,
      hopLimit: 1 as const,
      excludedNodeTypes: [],
      excludedEdgeTypes: [],
      alreadyLoadedIds: [],
    };

    expect(expandSubstrate({ ...baseParams, includeUniversals: false }).nodes).toEqual([]);
    expect(expandSubstrate({ ...baseParams, includeUniversals: true }).nodes).toEqual([
      expect.objectContaining({ id: "record-universal" }),
    ]);
  });

  it("preserves the outer rank_value DESC quirk for id-ranked types", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        focus,
        { id: "project-a", type: "Project" },
        { id: "project-z", type: "Project" },
      ],
      [
        { source: focus.id, rel: "RELATES_TO_PROJECT", target: "project-a" },
        { source: focus.id, rel: "RELATES_TO_PROJECT", target: "project-z" },
      ],
    );

    const { expandSubstrate } = await import("@/lib/server/explorer-engine");
    const result = expandSubstrate({
      focusId: focus.id,
      hopLimit: 1,
      excludedNodeTypes: [],
      excludedEdgeTypes: [],
      alreadyLoadedIds: [],
      includeUniversals: false,
    });

    expect(result.nodes.map((node) => node.id)).toEqual(["project-z", "project-a"]);
  });
});

describe("GET /api/expand in substrate mode", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
  });

  afterEach(async () => {
    await closeSubstrate();
    delete process.env.SUBSTRATE_DB_PATH;
    delete process.env.SERVING_BACKEND;
    vi.resetModules();
    vi.doUnmock("@/lib/neo4j");
  });

  it("serves the same envelope from expandSubstrate without calling the live Neo4j path", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        focus,
        { id: "decision-substrate", type: "Decision", props: { decided_at: "2024-09-01" } },
      ],
      [{ source: focus.id, rel: "AT_MEETING", target: "decision-substrate" }],
    );
    vi.doMock("@/lib/neo4j", () => ({
      runQuery: vi.fn(() => {
        throw new Error("live Neo4j path should not run in substrate mode");
      }),
    }));

    const { GET } = await import("@/app/api/expand/route");
    const res = await GET(
      new Request(`http://localhost/api/expand?focus=${focus.id}&hop=1`),
    );
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body).toMatchObject({
      nodes: [
        {
          id: "decision-substrate",
          type: "Decision",
          label: "decision-substrate",
          route: "/decision/substrate",
          ring: 1,
          event_date: "2024-09-01",
        },
      ],
      new_count: 1,
      cap: 20,
    });
    expect(body.edges).toEqual([
      {
        source: focus.id,
        target: "decision-substrate",
        type: "AT_MEETING",
        style: "governance",
      },
    ]);
  });
});
