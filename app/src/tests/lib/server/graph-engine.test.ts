import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
    JSON.stringify(node.props ?? {}),
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
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-graph-engine-"));
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
    { id: "person-alice", type: "Person", label: "Alice Council" },
    { id: "seatservice-alice-council", type: "SeatService", label: "Alice council service" },
    { id: "seat-council", type: "Seat", label: "Council seat" },
    { id: "org-city-council", type: "Organization", label: "City Council" },
    { id: "record-source", type: "Record", label: "Source record" },
    { id: "decision-recorded", type: "Decision", label: "Recorded decision" },
    { id: "org-alias", type: "Organization", label: "Alias organization" },
    { id: "org-total", type: "Organization", label: "Total focus" },
    { id: "person-total", type: "Person", label: "Total person" },
    { id: "decision-total", type: "Decision", label: "Total decision" },
    { id: "place-total", type: "Place", label: "Total place" },
    { id: "issue-total", type: "Issue", label: "Total issue" },
  ];
  for (let i = 1; i <= 9; i += 1) {
    nodes.push({
      id: `moneyflow-${i}`,
      type: "MoneyFlow",
      label: `Money flow ${i}`,
      props: { amount: i * 100, flow_date: `2024-01-0${i}` },
    });
  }
  for (const node of nodes) insertNode(db, node);

  const edges: EdgeFixture[] = [
    { source: "seatservice-alice-council", rel: "HELD_BY", target: "person-alice" },
    { source: "seatservice-alice-council", rel: "HELD_BY", target: "person-alice" },
    { source: "seatservice-alice-council", rel: "FOR_SEAT", target: "seat-council" },
    { source: "seat-council", rel: "AT_INSTITUTION", target: "org-city-council" },
    { source: "decision-recorded", rel: "EVIDENCED_BY", target: "record-source" },
    { source: "org-alias", rel: "SAME_AS", target: "org-city-council" },
    { source: "person-alice", rel: "IGNORED_REL", target: "org-alias" },
    { source: "org-total", rel: "MEMBER", target: "person-total" },
    { source: "person-total", rel: "PARTY_TO", target: "decision-total" },
    { source: "org-total", rel: "PRIMARY_PLACE", target: "place-total" },
    { source: "org-total", rel: "RELATES_TO_PROJECT", target: "issue-total" },
  ];
  for (let i = 1; i <= 9; i += 1) {
    edges.push({ source: `moneyflow-${i}`, rel: "FROM_SOURCE", target: "person-alice" });
  }
  for (const edge of edges) insertEdge(db, edge);

  db.close();
  return dbPath;
}

describe("graph-engine", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb();
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("loads node metadata, filtered adjacency edge classes, lazy props, and reuses one singleton", async () => {
    const { loadGraph } = await import("@/lib/server/graph-engine");

    const graph = loadGraph();
    expect(loadGraph()).toBe(graph);
    expect(graph.nodeMeta.get("person-alice")).toEqual({
      type: "Person",
      label: "Alice Council",
    });
    expect(graph.nodeMeta.has("moneyflow-1")).toBe(true);
    expect(graph.getNodeProps("moneyflow-9")).toMatchObject({ amount: 900 });

    const aliceEdges = graph.adjacency.get("person-alice") ?? [];
    expect(aliceEdges.some((edge) => edge.rel === "IGNORED_REL")).toBe(false);
    expect(
      graph.adjacency
        .get("decision-recorded")
        ?.find((edge) => edge.rel === "EVIDENCED_BY")?.edgeClass,
    ).toBe("universal");
    expect(
      graph.adjacency.get("org-alias")?.find((edge) => edge.rel === "SAME_AS")?.edgeClass,
    ).toBe("same_as");
  });

  it("executes the Person must-show SeatService -> Seat -> Organization path with ring numbers", async () => {
    const { loadGraph } = await import("@/lib/server/graph-engine");
    const graph = loadGraph();

    expect(graph.mustShowFor("Person", "person-alice")).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "seatservice-alice-council",
          ring: 1,
          relationship: "HELD_BY",
          role: "must-show",
        }),
        expect.objectContaining({
          id: "seat-council",
          ring: 2,
          relationship: "FOR_SEAT",
        }),
        expect.objectContaining({
          id: "org-city-council",
          type: "Organization",
          ring: 3,
          relationship: "AT_INSTITUTION",
        }),
      ]),
    );
  });

  it("phase2Fill applies MoneyFlow quota trimming, amount ranking, and aggregate cap", async () => {
    const { loadGraph } = await import("@/lib/server/graph-engine");
    const graph = loadGraph();
    const mustShowIds = graph.mustShowFor("Person", "person-alice").map((row) => row.id);

    const uncapped = graph.phase2Fill("person-alice", mustShowIds, 40);
    const moneyFlows = uncapped.filter((row) => row.type === "MoneyFlow");
    expect(moneyFlows.map((row) => row.id)).toEqual([
      "moneyflow-9",
      "moneyflow-8",
      "moneyflow-7",
      "moneyflow-6",
      "moneyflow-5",
      "moneyflow-4",
      "moneyflow-3",
      "moneyflow-2",
    ]);
    expect(moneyFlows.map((row) => row.rank_value)).toEqual([
      900, 800, 700, 600, 500, 400, 300, 200,
    ]);

    expect(graph.phase2Fill("person-alice", mustShowIds, 3).map((row) => row.id)).toEqual([
      "moneyflow-9",
      "moneyflow-8",
      "moneyflow-7",
    ]);
  });

  it("uses the Record EVIDENCED_BY waiver for Tier 2 neighborhoods", async () => {
    const { loadGraph } = await import("@/lib/server/graph-engine");
    const graph = loadGraph();

    expect(graph.tier2Neighborhood("record-source", "Record")).toEqual({
      neighbors: [
        expect.objectContaining({
          id: "decision-recorded",
          type: "Decision",
          ring: 1,
        }),
      ],
      edges: [
        {
          relationship: "EVIDENCED_BY",
          start_id: "decision-recorded",
          end_id: "record-source",
        },
      ],
    });
  });

  it("dedupes selected edges from adjacency and sorts by relationship/start/end", async () => {
    const { loadGraph } = await import("@/lib/server/graph-engine");
    const graph = loadGraph();

    expect(
      graph.edgesAmongSelected(
        ["person-alice", "seatservice-alice-council", "seat-council"],
        ["FOR_SEAT", "HELD_BY"],
      ),
    ).toEqual([
      {
        source: "seat-council",
        target: "seatservice-alice-council",
        relationship: "FOR_SEAT",
        start_id: "seatservice-alice-council",
        end_id: "seat-council",
      },
      {
        source: "person-alice",
        target: "seatservice-alice-council",
        relationship: "HELD_BY",
        start_id: "seatservice-alice-council",
        end_id: "person-alice",
      },
    ]);
  });

  it("counts neighbor totals with per-type waiver rules and Place/Issue exclusions", async () => {
    const { loadGraph } = await import("@/lib/server/graph-engine");
    const graph = loadGraph();

    expect(graph.neighborTotal("record-source", "Record")).toBe(1);
    expect(graph.neighborTotal("org-total", "Organization")).toBe(2);
  });
});
