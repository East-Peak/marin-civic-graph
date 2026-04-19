import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CatalogList } from "@/components/home/catalog-list";

describe("CatalogList", () => {
  it("renders grouped types with counts", () => {
    render(
      <CatalogList
        counts={{
          Person: 2184,
          Organization: 1893,
          Meeting: 4500,
          AgendaItem: 0,
          Decision: 1453,
          Seat: 0,
          SeatService: 0,
          Election: 0,
          Candidacy: 0,
          Committee: 135,
          Filing: 1085,
          MoneyFlow: 11248,
          Program: 0,
          Project: 49133,
          Agreement: 0,
          Amendment: 0,
          Case: 477,
          Proceeding: 0,
          Place: 0,
          Issue: 0,
          Record: 38412,
        }}
      />,
    );
    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.getByText("2,184")).toBeInTheDocument();
    expect(screen.getByText("Money flows")).toBeInTheDocument();
    expect(screen.getByText("11,248")).toBeInTheDocument();
    // Records in its own section
    expect(screen.getByText("Source records")).toBeInTheDocument();
  });
});
