import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TimelineRibbon } from "@/components/entity/timeline-ribbon";
import type { EntityPayload, Neighbor } from "@/lib/server/entity-loader";

function neighbor(overrides: Partial<Neighbor> & Pick<Neighbor, "id" | "type">): Neighbor {
  return {
    label: overrides.id,
    route: `/${overrides.type.toLowerCase()}/${overrides.id}`,
    ring: 1,
    role: "must-show",
    event_date: null,
    ...overrides,
  };
}

function makeEntity(overrides: Partial<EntityPayload> = {}): EntityPayload {
  return {
    id: "person-kate-colin",
    type: "Person",
    label: "Kate Colin",
    properties: { id: "person-kate-colin" },
    neighbors: [],
    edges: [],
    neighbor_total: 0,
    focus_event_date: null,
    ...overrides,
  };
}

describe("TimelineRibbon", () => {
  it("renders a diamond for each neighbor that carries a real event_date", () => {
    const entity = makeEntity({
      neighbors: [
        neighbor({
          id: "meeting-sr-2024-08-19",
          type: "Meeting",
          label: "SR City Council — 2024-08-19",
          route: "/meeting/sr-2024-08-19",
          event_date: "2024-08-19",
        }),
        neighbor({
          id: "decision-2024-09-16-resolution-15337",
          type: "Decision",
          label: "Resolution 15337",
          route: "/decision/2024-09-16-resolution-15337",
          event_date: "2024-09-16",
        }),
        neighbor({
          id: "filing-2025-01-04-kate-colin-form-803",
          type: "Filing",
          label: "Kate Colin — Form 803",
          route: "/filing/2025-01-04-kate-colin-form-803",
          event_date: "2025-01-04",
        }),
      ],
      neighbor_total: 3,
    });
    render(<TimelineRibbon entity={entity} />);

    const diamonds = screen.getAllByTestId("timeline-event");
    expect(diamonds).toHaveLength(3);
    const hrefs = diamonds.map((d) => d.getAttribute("href"));
    expect(hrefs).toContain("/meeting/sr-2024-08-19");
    expect(hrefs).toContain("/decision/2024-09-16-resolution-15337");
    expect(hrefs).toContain("/filing/2025-01-04-kate-colin-form-803");
  });

  it("renders at least one year tick label across a multi-year span", () => {
    const entity = makeEntity({
      neighbors: [
        neighbor({
          id: "meeting-a",
          type: "Meeting",
          label: "Meeting",
          route: "/meeting/a",
          event_date: "2022-01-10",
        }),
        neighbor({
          id: "meeting-b",
          type: "Meeting",
          label: "Meeting",
          route: "/meeting/b",
          event_date: "2025-06-20",
        }),
      ],
      neighbor_total: 2,
    });
    render(<TimelineRibbon entity={entity} />);
    const ticks = screen.getAllByTestId("timeline-year-tick");
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });

  it("renders an empty state when no neighbor carries an event_date", () => {
    const entity = makeEntity({
      neighbors: [
        neighbor({
          id: "org-san-rafael-city-council",
          type: "Organization",
          label: "San Rafael City Council",
          route: "/organization/san-rafael-city-council",
          event_date: null,
        }),
        neighbor({
          id: "seat-mayor-sr",
          type: "Seat",
          label: "Mayor — SR",
          route: "/seat/mayor-sr",
          ring: 2,
          event_date: null,
        }),
      ],
      neighbor_total: 2,
    });
    render(<TimelineRibbon entity={entity} />);
    expect(screen.getByTestId("timeline-ribbon-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("timeline-ribbon")).toBeNull();
  });

  it("does NOT fabricate dates from date-shaped substrings in neighbor ids", () => {
    // Fix 6 — the old regex fallback would mis-date this Person neighbor
    // because its id happens to contain a YYYY-MM-DD substring. The new
    // contract trusts event_date only; this Person should be skipped.
    const entity = makeEntity({
      neighbors: [
        neighbor({
          id: "person-2024-08-19-bogus",
          type: "Person",
          label: "Bogus",
          route: "/person/2024-08-19-bogus",
          event_date: null,
        }),
      ],
      neighbor_total: 1,
    });
    render(<TimelineRibbon entity={entity} />);
    // No event diamonds rendered → empty state shown.
    expect(screen.getByTestId("timeline-ribbon-empty")).toBeInTheDocument();
  });

  it("anchors the ribbon with the focus entity's own focus_event_date", () => {
    const entity = makeEntity({
      type: "Meeting",
      label: "SR City Council — 2024-08-19",
      focus_event_date: "2024-08-19",
      neighbors: [
        neighbor({
          id: "decision-15336",
          type: "Decision",
          label: "Resolution 15336",
          route: "/decision/15336",
          event_date: "2024-08-19",
        }),
      ],
      neighbor_total: 1,
    });
    render(<TimelineRibbon entity={entity} />);
    // One neighbor diamond (linked) plus one focus diamond (un-linked).
    expect(screen.getAllByTestId("timeline-event")).toHaveLength(1);
    expect(screen.getAllByTestId("timeline-event-focus")).toHaveLength(1);
  });
});
