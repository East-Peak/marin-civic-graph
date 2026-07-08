import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

vi.mock("@/lib/server/data-queries-dispatch", () => ({
  executeDataQuery: vi.fn(),
}));

vi.mock("@/lib/server/homepage-data", () => ({
  loadStatus: vi.fn(),
}));

vi.mock("@/components/layout/status-bar", () => ({
  StatusBar: () => <div data-testid="status-bar" />,
}));

vi.mock("@/components/layout/nav-header", () => ({
  NavHeader: () => <div data-testid="nav-header" />,
}));

vi.mock("@/components/data/data-query-nav", () => ({
  DataQueryNav: () => <div data-testid="data-query-nav" />,
}));

vi.mock("@/components/data/data-filters", () => ({
  DataFilters: () => <div data-testid="data-filters" />,
}));

vi.mock("@/components/data/data-table", () => ({
  DataTable: ({ rows }: { rows: Record<string, unknown>[] }) => (
    <div data-testid="data-table">{JSON.stringify(rows)}</div>
  ),
}));

import { runQuery } from "@/lib/neo4j";
import { executeDataQuery } from "@/lib/server/data-queries-dispatch";
import { loadStatus } from "@/lib/server/homepage-data";
import DataQueryPage from "@/app/data/[query]/page";

const executeDataQueryMock = executeDataQuery as unknown as ReturnType<typeof vi.fn>;
const loadStatusMock = loadStatus as unknown as ReturnType<typeof vi.fn>;
const runQueryMock = runQuery as unknown as ReturnType<typeof vi.fn>;

describe("/data/[query] page", () => {
  beforeEach(() => {
    executeDataQueryMock.mockReset();
    loadStatusMock.mockReset();
    runQueryMock.mockReset();
    loadStatusMock.mockResolvedValue({
      connected: true,
      node_count: 1,
      edge_count: 2,
      jurisdiction_count: 3,
      ingest_at: null,
      subgraphs_built_at: null,
    });
  });

  it("runs query rows through the shared server dispatch instead of live Cypher", async () => {
    executeDataQueryMock.mockResolvedValue({
      rows: [
        {
          person_name: "Alice Council",
          seat_display: "Council",
          form_700_count: 1,
          form_803_count: 0,
          id: "person-alice",
        },
      ],
    });

    const element = await DataQueryPage({
      params: Promise.resolve({ query: "current-officeholders-form-coverage" }),
      searchParams: Promise.resolve({ jurisdiction_id: "place-san-rafael" }),
    });
    render(element);

    expect(executeDataQueryMock).toHaveBeenCalledTimes(1);
    expect(executeDataQueryMock.mock.calls[0][0].slug).toBe(
      "current-officeholders-form-coverage",
    );
    expect(executeDataQueryMock.mock.calls[0][1]).toEqual({
      jurisdiction_id: "place-san-rafael",
    });
    expect(runQueryMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("data-table").textContent).toContain("Alice Council");
  });
});
