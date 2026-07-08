import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type NodeFixture = {
  id: string;
  type: string;
  label?: string;
  props?: Record<string, unknown>;
};

type EdgeFixture = {
  source: string;
  rel: string;
  target: string;
};

function makeFixtureDb(nodes: NodeFixture[], edges: EdgeFixture[]): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-path-finder-substrate-"));
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

async function findPathSubstrate(
  fromId: string,
  toId: string,
  options?: { loose?: boolean; maxHops?: number },
) {
  const mod = await import("@/lib/server/path-finder-substrate");
  return mod.findPathSubstrate(fromId, toId, options);
}

describe("findPathSubstrate", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
  });

  afterEach(async () => {
    await closeSubstrate();
    delete process.env.SUBSTRATE_DB_PATH;
    delete process.env.SERVING_BACKEND;
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("chooses the minimum-weight path even when a shorter-hop path is heavier", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        { id: "person-a", type: "Person", label: "Person A" },
        {
          id: "decision-heavy",
          type: "Decision",
          label: "Heavy direct decision",
          props: { decided_at: "2024-04-01" },
        },
        {
          id: "decision-target",
          type: "Decision",
          label: "Target decision",
          props: { meeting_date: "2024-05-01", decided_at: "2024-05-02" },
        },
      ],
      [
        { source: "person-a", rel: "AT_MEETING", target: "decision-target" },
        { source: "person-a", rel: "CAST_VOTE", target: "decision-heavy" },
        { source: "decision-heavy", rel: "DECIDED_BY", target: "decision-target" },
      ],
    );

    const result = await findPathSubstrate("person-a", "decision-target");

    expect(result.found).toBe(true);
    if (result.found) {
      expect(result.path.weight).toBe(2);
      expect(result.loose_match).toBe(false);
      expect(result.path.nodes.map((node) => node.id)).toEqual([
        "person-a",
        "decision-heavy",
        "decision-target",
      ]);
      expect(result.path.nodes.map((node) => node.event_date)).toEqual([
        null,
        "2024-04-01",
        "2024-05-01",
      ]);
    }
  });

  it("rejects loose-only edges in strict mode and admits them under loose mode", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        { id: "person-a", type: "Person" },
        { id: "decision-b", type: "Decision" },
      ],
      [{ source: "person-a", rel: "EVIDENCED_BY", target: "decision-b" }],
    );

    await expect(findPathSubstrate("person-a", "decision-b", { loose: false })).resolves.toEqual({
      found: false,
    });

    const loose = await findPathSubstrate("person-a", "decision-b", { loose: true });
    expect(loose.found).toBe(true);
    if (loose.found) {
      expect(loose.loose_match).toBe(true);
      expect(loose.path.weight).toBe(10);
      expect(loose.path.edges[0]).toMatchObject({
        source: "person-a",
        target: "decision-b",
        type: "EVIDENCED_BY",
        weight: 10,
      });
    }
  });

  it("blocks excluded intermediate node types in strict mode and penalizes them under loose mode", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        { id: "person-a", type: "Person" },
        { id: "record-mid", type: "Record", props: { published_at: "2024-01-15" } },
        { id: "decision-b", type: "Decision" },
      ],
      [
        { source: "person-a", rel: "CAST_VOTE", target: "record-mid" },
        { source: "record-mid", rel: "DECIDED_BY", target: "decision-b" },
      ],
    );

    await expect(findPathSubstrate("person-a", "decision-b")).resolves.toEqual({
      found: false,
    });

    const loose = await findPathSubstrate("person-a", "decision-b", { loose: true });
    expect(loose.found).toBe(true);
    if (loose.found) {
      expect(loose.loose_match).toBe(true);
      expect(loose.path.weight).toBe(12);
      expect(loose.path.nodes[1]).toMatchObject({
        id: "record-mid",
        type: "Record",
        event_date: "2024-01-15",
      });
    }
  });

  it("returns found:false for unconnected and missing endpoints", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [
        { id: "person-a", type: "Person" },
        { id: "decision-b", type: "Decision" },
        { id: "person-c", type: "Person" },
      ],
      [{ source: "person-a", rel: "CAST_VOTE", target: "person-c" }],
    );

    await expect(findPathSubstrate("person-a", "decision-b")).resolves.toEqual({
      found: false,
    });
    await expect(findPathSubstrate("person-a", "missing-node")).resolves.toEqual({
      found: false,
    });
  });

  it("returns found:false for self paths", async () => {
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      [{ id: "person-a", type: "Person" }],
      [],
    );

    await expect(findPathSubstrate("person-a", "person-a")).resolves.toEqual({
      found: false,
    });
  });

  it("defaults to maxHops=4 and honors a larger explicit hop budget", async () => {
    const nodeIds = ["n0", "n1", "n2", "n3", "n4", "n5"];
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(
      nodeIds.map((id, idx) => ({
        id,
        type: idx === 0 ? "Person" : "Decision",
      })),
      nodeIds.slice(0, -1).map((source, idx) => ({
        source,
        rel: "CAST_VOTE",
        target: nodeIds[idx + 1],
      })),
    );

    await expect(findPathSubstrate("n0", "n5")).resolves.toEqual({ found: false });
    const result = await findPathSubstrate("n0", "n5", { maxHops: 5 });
    expect(result.found).toBe(true);
    if (result.found) expect(result.path.weight).toBe(5);
  });

  it("logs and stops when simple-path enumeration hits the safety cap", async () => {
    const layerA = Array.from({ length: 28 }, (_, idx) => `a-${idx.toString().padStart(2, "0")}`);
    const layerB = Array.from({ length: 28 }, (_, idx) => `b-${idx.toString().padStart(2, "0")}`);
    const layerC = Array.from({ length: 28 }, (_, idx) => `c-${idx.toString().padStart(2, "0")}`);
    const nodes: NodeFixture[] = [
      { id: "source", type: "Person" },
      { id: "target", type: "Decision" },
      ...layerA.map((id) => ({ id, type: "Decision" })),
      ...layerB.map((id) => ({ id, type: "Decision" })),
      ...layerC.map((id) => ({ id, type: "Decision" })),
    ];
    const edges: EdgeFixture[] = [
      ...layerA.map((id) => ({ source: "source", rel: "CAST_VOTE", target: id })),
      ...layerA.flatMap((a) =>
        layerB.map((b) => ({ source: a, rel: "CAST_VOTE", target: b })),
      ),
      ...layerB.flatMap((b) =>
        layerC.map((c) => ({ source: b, rel: "CAST_VOTE", target: c })),
      ),
      ...layerC.map((id) => ({ source: id, rel: "CAST_VOTE", target: "target" })),
    ];
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb(nodes, edges);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const result = await findPathSubstrate("source", "target", { maxHops: 4 });

    expect(result.found).toBe(true);
    if (result.found) expect(result.path.weight).toBe(4);
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("path enumeration cap hit for source -> target; scored 20000 paths"),
    );
  });
});
