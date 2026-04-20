// app/src/tests/components/browse/browse-table.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import { BrowseTable } from "@/components/browse/browse-table";
import type { BrowseResult } from "@/lib/server/browse-queries";

function makeInitial(rows: BrowseResult["rows"], next_cursor: string | null = null): BrowseResult {
  return {
    rows,
    next_cursor,
    columns: [
      { key: "search_label", label: "Name" },
      { key: "current_seat_display", label: "Current seat" },
      { key: "jurisdiction_name", label: "Jurisdiction" },
    ],
  };
}

function personRow(overrides: Partial<BrowseResult["rows"][number]>): BrowseResult["rows"][number] {
  return {
    id: "person-a",
    type: "Person",
    search_label: "Alice",
    route: "/person/a",
    current_seat_display: "Mayor",
    jurisdiction_name: "Ross",
    ...overrides,
  };
}

describe("BrowseTable", () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("renders one header per column + an ID column", () => {
    render(
      <BrowseTable
        type="Person"
        initial={makeInitial([personRow({})])}
      />,
    );
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Current seat")).toBeInTheDocument();
    expect(screen.getByText("Jurisdiction")).toBeInTheDocument();
    expect(screen.getByText("ID")).toBeInTheDocument();
  });

  it("renders search_label as a Link to row.route", () => {
    render(
      <BrowseTable
        type="Person"
        initial={makeInitial([
          personRow({ id: "person-kate-colin", search_label: "Kate Colin", route: "/person/kate-colin" }),
        ])}
      />,
    );
    const link = screen.getByRole("link", { name: "Kate Colin" });
    expect(link.getAttribute("href")).toBe("/person/kate-colin");
  });

  it("renders ID column with the full canonical id", () => {
    render(
      <BrowseTable
        type="Person"
        initial={makeInitial([personRow({ id: "person-alice" })])}
      />,
    );
    expect(screen.getByText("person-alice")).toBeInTheDocument();
  });

  it("shows 'loaded' count and an (more available) suffix when cursor is non-null", () => {
    render(
      <BrowseTable
        type="Person"
        initial={makeInitial([personRow({})], "person-zz")}
      />,
    );
    expect(screen.getByText(/1 loaded/)).toBeInTheDocument();
    expect(screen.getByText(/more available/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();
  });

  it("Load more appends the next page and updates cursor", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        type: "Person",
        rows: [personRow({ id: "person-b", search_label: "Bob", route: "/person/b" })],
        next_cursor: null,
        columns: makeInitial([]).columns,
      }),
    });
    render(
      <BrowseTable
        type="Person"
        initial={makeInitial([personRow({ id: "person-a" })], "person-a")}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Bob" })).toBeInTheDocument(),
    );
    // First-page row still visible (accumulator), second-page row appended.
    expect(screen.getByText("Alice")).toBeInTheDocument();
    const callUrl = mockFetch.mock.calls[0][0] as string;
    expect(callUrl).toContain("/api/browse/person");
    expect(callUrl).toContain("cursor=person-a");
  });

  it("hides Load more once next_cursor is null", () => {
    render(
      <BrowseTable
        type="Person"
        initial={makeInitial([personRow({})], null)}
      />,
    );
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
  });

  it("renders an empty-state when there are no rows", () => {
    render(
      <BrowseTable
        type="Person"
        initial={makeInitial([], null)}
      />,
    );
    const table = screen.getByTestId("browse-table");
    expect(within(table).getByText(/No rows/i)).toBeInTheDocument();
  });

  it("uses urlSegmentForType to construct the fetch URL (camelCase -> kebab-case)", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ type: "MoneyFlow", rows: [], next_cursor: null, columns: [] }),
    });
    render(
      <BrowseTable
        type="MoneyFlow"
        initial={{
          rows: [
            {
              id: "moneyflow-x",
              type: "MoneyFlow",
              search_label: "X",
              route: "/money-flow/x",
              amount: 1000,
              flow_date: "2024-01-01",
            },
          ],
          next_cursor: "moneyflow-x",
          columns: [
            { key: "search_label", label: "Name" },
            { key: "amount", label: "Amount" },
            { key: "flow_date", label: "Date" },
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const callUrl = mockFetch.mock.calls[0][0] as string;
    expect(callUrl).toContain("/api/browse/money-flow");
  });
});
