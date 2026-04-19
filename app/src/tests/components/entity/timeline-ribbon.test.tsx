import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TimelineRibbon } from "@/components/entity/timeline-ribbon";
import type { EntityPayload } from "@/lib/server/entity-loader";

function makeEntity(overrides: Partial<EntityPayload> = {}): EntityPayload {
  return {
    id: "person-kate-colin",
    type: "Person",
    label: "Kate Colin",
    properties: { id: "person-kate-colin" },
    neighbors: [],
    edges: [],
    neighbor_total: 0,
    ...overrides,
  };
}

describe("TimelineRibbon", () => {
  it("renders a diamond for each dated neighbor (via id-embedded date)", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-sr-2024-08-19",
          type: "Meeting",
          label: "SR City Council — 2024-08-19",
          route: "/meeting/sr-2024-08-19",
          ring: 1,
          role: "must-show",
        },
        {
          id: "decision-2024-09-16-resolution-15337",
          type: "Decision",
          label: "Resolution 15337",
          route: "/decision/2024-09-16-resolution-15337",
          ring: 1,
          role: "must-show",
        },
        {
          id: "filing-2025-01-04-kate-colin-form-803",
          type: "Filing",
          label: "Kate Colin — Form 803",
          route: "/filing/2025-01-04-kate-colin-form-803",
          ring: 1,
          role: "must-show",
        },
      ],
      neighbor_total: 3,
    });
    render(<TimelineRibbon entity={entity} />);

    const diamonds = screen.getAllByTestId("timeline-event");
    expect(diamonds).toHaveLength(3);
    // Each one should be an <a> with an href into the neighbor route.
    const hrefs = diamonds.map((d) => d.getAttribute("href"));
    expect(hrefs).toContain("/meeting/sr-2024-08-19");
    expect(hrefs).toContain("/decision/2024-09-16-resolution-15337");
    expect(hrefs).toContain("/filing/2025-01-04-kate-colin-form-803");
  });

  it("renders at least one year tick label across a multi-year span", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-2022-01-10",
          type: "Meeting",
          label: "Meeting",
          route: "/meeting/2022-01-10",
          ring: 1,
          role: "must-show",
        },
        {
          id: "meeting-2025-06-20",
          type: "Meeting",
          label: "Meeting",
          route: "/meeting/2025-06-20",
          ring: 1,
          role: "must-show",
        },
      ],
      neighbor_total: 2,
    });
    render(<TimelineRibbon entity={entity} />);
    const ticks = screen.getAllByTestId("timeline-year-tick");
    // Spans at least 2022–2025, expect at least 3 year ticks visible.
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });

  it("renders an empty state when no neighbors have dated events", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "org-san-rafael-city-council",
          type: "Organization",
          label: "San Rafael City Council",
          route: "/organization/san-rafael-city-council",
          ring: 1,
          role: "must-show",
        },
        {
          id: "seat-mayor-sr",
          type: "Seat",
          label: "Mayor — SR",
          route: "/seat/mayor-sr",
          ring: 2,
          role: "must-show",
        },
      ],
      neighbor_total: 2,
    });
    render(<TimelineRibbon entity={entity} />);
    expect(screen.getByTestId("timeline-ribbon-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("timeline-ribbon")).toBeNull();
  });

  it("skips neighbors of durable types even when ids contain date-like suffixes", () => {
    const entity = makeEntity({
      neighbors: [
        // Person id has no date — should be skipped.
        {
          id: "person-kate-colin",
          type: "Person",
          label: "Kate",
          route: "/person/kate",
          ring: 1,
          role: "must-show",
        },
        // Dated event to anchor the ribbon.
        {
          id: "meeting-sr-2024-08-19",
          type: "Meeting",
          label: "Meeting",
          route: "/meeting/sr-2024-08-19",
          ring: 1,
          role: "must-show",
        },
      ],
      neighbor_total: 2,
    });
    render(<TimelineRibbon entity={entity} />);
    const diamonds = screen.getAllByTestId("timeline-event");
    expect(diamonds).toHaveLength(1);
  });
});
