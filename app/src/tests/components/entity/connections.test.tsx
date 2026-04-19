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
        },
        {
          id: "meeting-sr-2024-09-16",
          type: "Meeting",
          label: "SR City Council — 2024-09-16",
          route: "/meeting/sr-2024-09-16",
          ring: 1,
          role: "must-show",
        },
        {
          id: "org-san-rafael-city-council",
          type: "Organization",
          label: "San Rafael City Council",
          route: "/organization/san-rafael-city-council",
          ring: 1,
          role: "must-show",
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
});
