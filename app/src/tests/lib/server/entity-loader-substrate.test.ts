import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(async () => {
    throw new Error("live Neo4j path should not run in substrate loader tests");
  }),
}));

type NodeFixture = {
  id: string;
  type: string;
  label: string;
  props?: Record<string, unknown>;
};

type EdgeFixture = {
  source: string;
  rel: string;
  target: string;
};

function insertNode(db: Database.Database, node: NodeFixture) {
  db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)").run(
    node.id,
    node.type,
    node.label,
    JSON.stringify({
      id: node.id,
      search_label: node.label,
      name: node.label,
      ...(node.props ?? {}),
    }),
  );
}

function insertEdge(db: Database.Database, edge: EdgeFixture) {
  db.prepare("INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)").run(
    edge.source,
    edge.rel,
    edge.target,
  );
}

function makeFixtureDb(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-entity-loader-substrate-"));
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

  const nodes: NodeFixture[] = [
    {
      id: "person-alice",
      type: "Person",
      label: "Alice Council",
      props: { custom: "focus-prop" },
    },
    {
      id: "seatservice-alice-council",
      type: "SeatService",
      label: "Alice council service",
      props: { started_at: "2021-01-01" },
    },
    { id: "seat-council", type: "Seat", label: "Council seat" },
    { id: "org-city-council", type: "Organization", label: "City Council" },
    {
      id: "moneyflow-big",
      type: "MoneyFlow",
      label: "Large contribution",
      props: { amount: 900, flow_date: "2024-02-03" },
    },
    {
      id: "moneyflow-small",
      type: "MoneyFlow",
      label: "Small contribution",
      props: { amount: 100, flow_date: "2024-01-03" },
    },
    {
      id: "decision-phase",
      type: "Decision",
      label: "Phase decision",
      props: { decided_at: "2024-03-04" },
    },
    {
      id: "record-source",
      type: "Record",
      label: "Source record",
      props: { published_at: "2024-04-05" },
    },
    {
      id: "decision-recorded",
      type: "Decision",
      label: "Recorded decision",
      props: { decided_at: "2024-05-06" },
    },
    { id: "org-sunrise", type: "Organization", label: "Sunrise Org" },
    { id: "person-kate-colin", type: "Person", label: "Kate Colin" },
    { id: "person-cap", type: "Person", label: "Cap Person" },
  ];

  for (let i = 1; i <= 39; i += 1) {
    nodes.push({
      id: `seatservice-cap-${i.toString().padStart(2, "0")}`,
      type: "SeatService",
      label: `Cap service ${i}`,
    });
  }
  for (let i = 1; i <= 3; i += 1) {
    nodes.push({
      id: `moneyflow-cap-${i}`,
      type: "MoneyFlow",
      label: `Cap money ${i}`,
      props: { amount: i * 100, flow_date: `2024-06-0${i}` },
    });
  }
  for (const node of nodes) insertNode(db, node);

  const edges: EdgeFixture[] = [
    { source: "seatservice-alice-council", rel: "HELD_BY", target: "person-alice" },
    { source: "seatservice-alice-council", rel: "FOR_SEAT", target: "seat-council" },
    { source: "seat-council", rel: "AT_INSTITUTION", target: "org-city-council" },
    { source: "moneyflow-big", rel: "FROM_SOURCE", target: "person-alice" },
    { source: "moneyflow-small", rel: "FROM_SOURCE", target: "person-alice" },
    { source: "person-alice", rel: "CAST_VOTE", target: "decision-phase" },
    { source: "decision-recorded", rel: "EVIDENCED_BY", target: "record-source" },
  ];
  for (let i = 1; i <= 39; i += 1) {
    edges.push({
      source: `seatservice-cap-${i.toString().padStart(2, "0")}`,
      rel: "HELD_BY",
      target: "person-cap",
    });
  }
  for (let i = 1; i <= 3; i += 1) {
    edges.push({
      source: `moneyflow-cap-${i}`,
      rel: "FROM_SOURCE",
      target: "person-cap",
    });
  }
  for (const edge of edges) insertEdge(db, edge);

  db.close();
  return dbPath;
}

function edgeKey(edge: { source: string; target: string; type: string }) {
  return `${edge.type}:${[edge.source, edge.target].sort().join("<>")}`;
}

describe("loadEntitySubstrate", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb();
    delete process.env.SERVING_BACKEND;
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SUBSTRATE_DB_PATH;
    delete process.env.SERVING_BACKEND;
  });

  it("assembles a Tier 1 Person payload with must-show, phase-2, selected edges, rings, and event dates", async () => {
    const { loadEntitySubstrate } = await import("@/lib/server/entity-loader-substrate");

    const result = await loadEntitySubstrate("person", "alice");

    expect(result).toMatchObject({
      id: "person-alice",
      type: "Person",
      label: "Alice Council",
      properties: {
        id: "person-alice",
        custom: "focus-prop",
      },
      focus_event_date: null,
    });
    expect(result?.neighbors.map((neighbor) => neighbor.id)).toEqual([
      "seatservice-alice-council",
      "seat-council",
      "org-city-council",
      "moneyflow-big",
      "moneyflow-small",
      "decision-phase",
    ]);
    expect(result?.neighbors.map((neighbor) => [neighbor.id, neighbor.ring, neighbor.role])).toEqual([
      ["seatservice-alice-council", 1, "must-show"],
      ["seat-council", 2, "must-show"],
      ["org-city-council", 3, "must-show"],
      ["moneyflow-big", 1, "phase-2"],
      ["moneyflow-small", 1, "phase-2"],
      ["decision-phase", 1, "phase-2"],
    ]);
    expect(Object.fromEntries(result?.neighbors.map((n) => [n.id, n.event_date]) ?? [])).toEqual({
      "seatservice-alice-council": "2021-01-01",
      "seat-council": null,
      "org-city-council": null,
      "moneyflow-big": "2024-02-03",
      "moneyflow-small": "2024-01-03",
      "decision-phase": "2024-03-04",
    });
    expect(result?.neighbors.find((n) => n.id === "seatservice-alice-council")?.route).toBe(
      "/seat-service/alice-council",
    );
    expect(result?.neighbor_total).toBe(5);
    expect(new Set(result?.edges.map(edgeKey))).toEqual(
      new Set([
        "AT_INSTITUTION:org-city-council<>seat-council",
        "CAST_VOTE:decision-phase<>person-alice",
        "FOR_SEAT:seat-council<>seatservice-alice-council",
        "FROM_SOURCE:moneyflow-big<>person-alice",
        "FROM_SOURCE:moneyflow-small<>person-alice",
        "HELD_BY:person-alice<>seatservice-alice-council",
      ]),
    );
    expect(result?.edges.filter((edge) => edge.type === "FROM_SOURCE").map((edge) => edge.style)).toEqual([
      "money",
      "money",
    ]);
  });

  it("assembles a Tier 2 Record payload with waiver edges, totals, routes, and event dates", async () => {
    const { loadEntitySubstrate } = await import("@/lib/server/entity-loader-substrate");

    const result = await loadEntitySubstrate("record", "source");

    expect(result).toMatchObject({
      id: "record-source",
      type: "Record",
      label: "Source record",
      focus_event_date: "2024-04-05",
      neighbor_total: 1,
    });
    expect(result?.neighbors).toEqual([
      expect.objectContaining({
        id: "decision-recorded",
        type: "Decision",
        route: "/decision/recorded",
        ring: 1,
        role: "must-show",
        event_date: "2024-05-06",
      }),
    ]);
    expect(result?.edges).toEqual([
      {
        source: "decision-recorded",
        target: "record-source",
        type: "EVIDENCED_BY",
        style: "governance",
      },
    ]);
  });

  it("trims phase-2 fill at the 40-node cap while preserving all must-show rows first", async () => {
    const { loadEntitySubstrate } = await import("@/lib/server/entity-loader-substrate");

    const result = await loadEntitySubstrate("person", "cap");

    expect(result?.neighbors).toHaveLength(40);
    expect(result?.neighbors.slice(0, 39).every((neighbor) => neighbor.role === "must-show")).toBe(
      true,
    );
    expect(result?.neighbors.at(-1)).toMatchObject({
      id: "moneyflow-cap-3",
      role: "phase-2",
    });
    expect(result?.neighbors.some((neighbor) => neighbor.id === "moneyflow-cap-2")).toBe(false);
  });

  it("resolves organization short-prefix ids and legacy id aliases before returning payloads", async () => {
    const { loadEntitySubstrate } = await import("@/lib/server/entity-loader-substrate");

    await expect(loadEntitySubstrate("organization", "sunrise")).resolves.toMatchObject({
      id: "org-sunrise",
      type: "Organization",
      label: "Sunrise Org",
    });
    await expect(loadEntitySubstrate("actor", "kate-colin")).resolves.toMatchObject({
      id: "person-kate-colin",
      type: "Person",
      label: "Kate Colin",
    });
  });

  it("returns null for a missing entity", async () => {
    const { loadEntitySubstrate } = await import("@/lib/server/entity-loader-substrate");

    await expect(loadEntitySubstrate("person", "missing")).resolves.toBeNull();
  });

  it("loadEntity delegates to the substrate loader when SERVING_BACKEND=substrate", async () => {
    process.env.SERVING_BACKEND = "substrate";
    const { loadEntity } = await import("@/lib/server/entity-loader");

    await expect(loadEntity("record", "source")).resolves.toMatchObject({
      id: "record-source",
      type: "Record",
    });
  });
});
