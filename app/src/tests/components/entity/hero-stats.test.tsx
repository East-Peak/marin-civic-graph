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
  it("renders money, decisions, counterparties, evidence for a Project (§7.1)", () => {
    render(
      <HeroStats
        entity={makeEntity({
          properties: {
            id: "project-merrydale",
            total_money: 15337953,
            decisions_count: 6,
            counterparties_count: 4,
            records_count: 20,
          },
        })}
      />,
    );
    expect(screen.getByText("$15,337,953")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("money")).toBeInTheDocument();
    expect(screen.getByText("decisions")).toBeInTheDocument();
    expect(screen.getByText("counterparties")).toBeInTheDocument();
    expect(screen.getByText("evidence")).toBeInTheDocument();
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
    // Four Project stats (money, decisions, counterparties, evidence), all missing.
    expect(dashes.length).toBe(4);
  });

  it("renders a Person's current seat, service window, filings strip (§7.1)", () => {
    render(
      <HeroStats
        entity={makeEntity({
          id: "person-kate-colin",
          type: "Person",
          label: "Kate Colin",
          properties: {
            id: "person-kate-colin",
            current_seat_display: "Mayor — San Rafael",
            current_seat_started_at: "2023-11-28",
            current_seat_ended_at: "2027-12-01",
            filings_count: 12,
          },
        })}
      />,
    );
    expect(screen.getByText("Mayor — San Rafael")).toBeInTheDocument();
    expect(screen.getByText("2023-11-28 – 2027-12-01")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    // Labels present.
    expect(screen.getByText("current seat")).toBeInTheDocument();
    expect(screen.getByText("service")).toBeInTheDocument();
    expect(screen.getByText("filings")).toBeInTheDocument();
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
    // money → em-dash; decisions, counterparties, evidence also em-dash = 4 total.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBe(4);
  });
});
