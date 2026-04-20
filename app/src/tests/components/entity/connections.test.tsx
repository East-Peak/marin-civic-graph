import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Connections } from "@/components/entity/connections";
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
    focus_event_date: null,
    ...overrides,
  };
}

describe("Connections", () => {
  it("groups neighbors by rel type (heading per rel)", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-sr-2024-08-19",
          type: "Meeting",
          label: "SR City Council — 2024-08-19",
          route: "/meeting/sr-2024-08-19",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
        {
          id: "meeting-sr-2024-09-16",
          type: "Meeting",
          label: "SR City Council — 2024-09-16",
          route: "/meeting/sr-2024-09-16",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
        {
          id: "org-san-rafael-city-council",
          type: "Organization",
          label: "San Rafael City Council",
          route: "/organization/san-rafael-city-council",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
      ],
      edges: [
        {
          source: "person-kate-colin",
          target: "meeting-sr-2024-08-19",
          type: "ATTENDED",
          style: "governance",
        },
        {
          source: "person-kate-colin",
          target: "meeting-sr-2024-09-16",
          type: "ATTENDED",
          style: "governance",
        },
        {
          source: "person-kate-colin",
          target: "org-san-rafael-city-council",
          type: "MEMBER_OF",
          style: "governance",
        },
      ],
      neighbor_total: 3,
    });

    render(<Connections entity={entity} />);
    const groups = screen.getAllByTestId("connection-group");
    expect(groups).toHaveLength(2);
    const headings = screen
      .getAllByTestId("connection-group-heading")
      .map((h) => h.textContent ?? "");
    expect(headings.some((h) => h.includes("attended"))).toBe(true);
    expect(headings.some((h) => h.includes("member of"))).toBe(true);
  });

  it("renders neighbor cards with clickable links", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-x",
          type: "Meeting",
          label: "Meeting X",
          route: "/meeting/x",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
      ],
      edges: [
        {
          source: "person-kate-colin",
          target: "meeting-x",
          type: "ATTENDED",
          style: "governance",
        },
      ],
      neighbor_total: 1,
    });
    render(<Connections entity={entity} />);
    const link = screen.getByRole("link", { name: /Meeting X/i });
    expect(link.getAttribute("href")).toBe("/meeting/x");
  });

  it("shows overflow footer when neighbor_total exceeds rendered neighbors", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-x",
          type: "Meeting",
          label: "Meeting X",
          route: "/meeting/x",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
      ],
      edges: [
        {
          source: "person-kate-colin",
          target: "meeting-x",
          type: "ATTENDED",
          style: "governance",
        },
      ],
      neighbor_total: 42,
    });
    render(<Connections entity={entity} />);
    const overflow = screen.getByTestId("connections-overflow");
    expect(overflow.textContent).toContain("41");
    expect(overflow.getAttribute("href")).toContain("/graph?focus=person-kate-colin");
  });

  it("returns null when there are no neighbors", () => {
    const { container } = render(<Connections entity={makeEntity()} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders groups + cards in deterministic order regardless of edge input order (round 3 fix)", () => {
    // Shuffled neighbor + edge input should still render: groups sorted alpha
    // by rel type (RELATED last), cards sorted by neighbor.id within each group.
    const entity = makeEntity({
      neighbors: [
        { id: "meeting-z", type: "Meeting", label: "Z", route: "/meeting/z", ring: 1, role: "must-show", event_date: null },
        { id: "meeting-a", type: "Meeting", label: "A", route: "/meeting/a", ring: 1, role: "must-show", event_date: null },
        { id: "org-z", type: "Organization", label: "Org Z", route: "/organization/z", ring: 1, role: "must-show", event_date: null },
        { id: "case-m", type: "Case", label: "Case M", route: "/case/m", ring: 1, role: "must-show", event_date: null },
      ],
      edges: [
        // Deliberately shuffled — MEMBER_OF first, then ZANDERS, then ATTENDED
        { source: "person-kate-colin", target: "org-z", type: "MEMBER_OF", style: "governance" },
        { source: "person-kate-colin", target: "case-m", type: "ZANDERS", style: "governance" },
        { source: "person-kate-colin", target: "meeting-z", type: "ATTENDED", style: "governance" },
        { source: "person-kate-colin", target: "meeting-a", type: "ATTENDED", style: "governance" },
      ],
      neighbor_total: 4,
    });

    render(<Connections entity={entity} />);
    const headings = screen
      .getAllByTestId("connection-group-heading")
      .map((h) => (h.textContent ?? "").split(/\d/)[0].trim());
    // Alphabetical: attended, member of, zanders
    expect(headings).toEqual(["attended", "member of", "zanders"]);

    // Cards within the ATTENDED group must be sorted by id ascending.
    const cards = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    const meetingAIdx = cards.indexOf("/meeting/a");
    const meetingZIdx = cards.indexOf("/meeting/z");
    expect(meetingAIdx).toBeGreaterThan(-1);
    expect(meetingZIdx).toBeGreaterThan(-1);
    expect(meetingAIdx).toBeLessThan(meetingZIdx);
  });

  it("orphan neighbors land in a RELATED group at the end", () => {
    const entity = makeEntity({
      neighbors: [
        { id: "person-alpha", type: "Person", label: "Alpha", route: "/person/alpha", ring: 1, role: "must-show", event_date: null },
        { id: "meeting-x", type: "Meeting", label: "Meeting X", route: "/meeting/x", ring: 1, role: "must-show", event_date: null },
      ],
      // Only meeting-x has an edge; person-alpha is orphaned → RELATED group
      edges: [
        { source: "person-kate-colin", target: "meeting-x", type: "ATTENDED", style: "governance" },
      ],
      neighbor_total: 2,
    });

    render(<Connections entity={entity} />);
    const headings = screen
      .getAllByTestId("connection-group-heading")
      .map((h) => (h.textContent ?? "").split(/\d/)[0].trim());
    // RELATED always last
    expect(headings[headings.length - 1]).toBe("related");
  });
});
