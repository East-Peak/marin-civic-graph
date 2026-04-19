import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HeroStats } from "@/components/entity/hero-stats";
import type { EntityPayload } from "@/lib/server/entity-loader";

function makeEntity(overrides: Partial<EntityPayload> = {}): EntityPayload {
  return {
    id: "project-merrydale",
    type: "Project",
    label: "350 Merrydale Interim Shelter",
    properties: { id: "project-merrydale" },
    neighbors: [],
    edges: [],
    neighbor_total: 0,
    focus_event_date: null,
    ...overrides,
  };
}

describe("HeroStats", () => {
  it("renders formatted money, decisions, and records for a Project", () => {
    render(
      <HeroStats
        entity={makeEntity({
          properties: {
            id: "project-merrydale",
            total_money: 15337953,
            decisions_count: 6,
            records_count: 20,
          },
        })}
      />,
    );
    expect(screen.getByText("$15,337,953")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("money")).toBeInTheDocument();
    expect(screen.getByText("decisions")).toBeInTheDocument();
    expect(screen.getByText("records")).toBeInTheDocument();
  });

  it("em-dashes values whose props are missing", () => {
    render(
      <HeroStats
        entity={makeEntity({
          properties: { id: "project-merrydale" },
        })}
      />,
    );
    const dashes = screen.getAllByText("—");
    // three Project stats, all missing
    expect(dashes.length).toBe(3);
  });

  it("renders a Person's current seat, filings, and votes strip", () => {
    render(
      <HeroStats
        entity={makeEntity({
          id: "person-kate-colin",
          type: "Person",
          label: "Kate Colin",
          properties: {
            id: "person-kate-colin",
            current_seat_display: "Mayor — San Rafael",
            filings_count: 12,
            votes_count: 94,
          },
        })}
      />,
    );
    expect(screen.getByText("Mayor — San Rafael")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("94")).toBeInTheDocument();
  });

  it("returns null for Tier 2 types (e.g. MoneyFlow)", () => {
    const { container } = render(
      <HeroStats
        entity={makeEntity({
          id: "moneyflow-x",
          type: "MoneyFlow",
          label: "$50k grant",
          properties: { id: "moneyflow-x" },
        })}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("handles zero money as em-dash (not $0)", () => {
    render(
      <HeroStats
        entity={makeEntity({
          properties: { id: "project-x", total_money: 0 },
        })}
      />,
    );
    // money value is em-dash, decisions and records also em-dash = 3 dashes
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBe(3);
  });
});
