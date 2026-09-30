import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EntityPayload } from "@/lib/server/entity-loader";

vi.mock("@/lib/neo4j", () => ({ runQuery: vi.fn() }));
vi.mock("@/lib/server/homepage-data", () => ({
  loadStatus: vi.fn(async () => ({
    connected: true,
    node_count: 1,
    edge_count: 1,
    jurisdiction_count: 1,
    ingest_at: null,
    subgraphs_built_at: null,
  })),
}));
vi.mock("@/lib/server/entity-evidence", () => ({ loadEvidence: vi.fn(async () => []) }));
vi.mock("@/components/layout/status-bar", () => ({ StatusBar: () => null }));
vi.mock("@/components/layout/nav-header", () => ({ NavHeader: () => null }));
vi.mock("@/components/entity/hero-title", () => ({ HeroTitle: () => null }));
vi.mock("@/components/entity/hero-stats", () => ({ HeroStats: () => null }));
vi.mock("@/components/entity/radial-hero", () => ({ RadialHero: () => null }));
vi.mock("@/components/entity/facts-panel", () => ({ FactsPanel: () => null }));
vi.mock("@/components/entity/connections", () => ({ Connections: () => null }));
vi.mock("@/components/entity/timeline-ribbon", () => ({ TimelineRibbon: () => null }));
vi.mock("@/components/entity/editorial-callout", () => ({ EditorialCallout: () => null }));
vi.mock("@/components/entity/evidence-drawer", () => ({ EvidenceDrawer: () => null }));
vi.mock("@/components/shortcuts/recent-entity-tracker", () => ({ RecentEntityTracker: () => null }));
vi.mock("@/components/contributions/committee-top-contributors", () => ({
  CommitteeTopContributors: (props: { committeeId: string; committeePath: string; after: string | null }) => (
    <div data-testid="top-contributors">{JSON.stringify(props)}</div>
  ),
}));

import { EntityPage } from "@/components/entity/entity-page";

function entity(id: string, type: EntityPayload["type"]): EntityPayload {
  return {
    id,
    type,
    properties: { id },
    label: id,
    neighbors: [],
    edges: [],
    neighbor_total: 0,
    focus_event_date: null,
  } as EntityPayload;
}

describe("EntityPage top contributors", () => {
  it("adds the ranking to a committee page, passing its path and cursor", async () => {
    render(await EntityPage({ entity: entity("committee-alpha", "Committee"), contributorsAfter: "5:person-x" }));
    expect(JSON.parse(screen.getByTestId("top-contributors").textContent!)).toEqual({
      committeeId: "committee-alpha",
      committeePath: "/committee/alpha",
      after: "5:person-x",
    });
  });

  it.each(["Person", "Organization", "MoneyFlow"] as const)("leaves a %s page without it", async (type) => {
    render(await EntityPage({ entity: entity(`x-${type}`, type) }));
    expect(screen.queryByTestId("top-contributors")).toBeNull();
  });
});
