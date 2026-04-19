import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FactsPanel } from "@/components/entity/facts-panel";
import type { EntityPayload } from "@/lib/server/entity-loader";

function makeEntity(overrides: Partial<EntityPayload>): EntityPayload {
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

describe("FactsPanel", () => {
  it("renders all non-null rows with their values", () => {
    render(
      <FactsPanel
        entity={makeEntity({
          properties: {
            id: "person-kate-colin",
            name: "Kate Colin",
            current_seat_display: "Mayor — San Rafael",
            jurisdiction_name: "San Rafael",
          },
        })}
      />,
    );
    expect(screen.getByText("Kate Colin")).toBeInTheDocument();
    expect(screen.getByText("Mayor — San Rafael")).toBeInTheDocument();
    expect(screen.getByText("San Rafael")).toBeInTheDocument();
    expect(screen.getByText("person-kate-colin")).toBeInTheDocument();
  });

  it("renders em-dash for null values", () => {
    render(
      <FactsPanel
        entity={makeEntity({
          properties: { id: "person-kate-colin", name: "Kate Colin" },
        })}
      />,
    );
    // Three null fields (current seat, jurisdiction, aliases) all render as —
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(3);
  });

  it("renders the ID row with select-all affordance", () => {
    render(
      <FactsPanel
        entity={makeEntity({
          properties: { id: "person-kate-colin" },
        })}
      />,
    );
    const idCell = screen.getByText("person-kate-colin");
    expect(idCell.className).toContain("select-all");
  });
});
