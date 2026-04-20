// app/src/tests/components/search/search-results.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/server/search-backend", () => ({
  runSearch: vi.fn(),
  MAX_Q_LENGTH: 500,
  escapeLucene: (s: string) => s,
}));

import { runSearch, type SearchResult } from "@/lib/server/search-backend";
import { SearchResults, partitionResults } from "@/components/search/search-results";

const mockRunSearch = runSearch as unknown as ReturnType<typeof vi.fn>;

function entityResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    id: "person-kate-colin",
    type: "Person",
    search_label: "Kate Colin",
    route: "/person/kate-colin",
    key_fact: "Mayor, San Rafael",
    last_activity: "2024-03-01",
    jurisdiction: "San Rafael",
    rank: 96,
    ...overrides,
  };
}

function recordResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    id: "record-form-700-kate-colin-2024",
    type: "Record",
    search_label: "Form 700 · Kate Colin · 2024",
    route: "/record/form-700-kate-colin-2024",
    key_fact: "Form 700",
    last_activity: "2024-03-01",
    jurisdiction: null,
    rank: 40,
    ...overrides,
  };
}

async function renderAsync(node: Promise<React.ReactElement>) {
  const resolved = await node;
  return render(resolved);
}

describe("partitionResults", () => {
  it("separates entities from records; no exact if none match the query", () => {
    const { exact, entities, records } = partitionResults("kate", [
      entityResult(),
      recordResult(),
    ]);
    expect(exact).toBeNull();
    expect(entities).toHaveLength(1);
    expect(records).toHaveLength(1);
  });

  it("extracts the exact-id match out of the normal buckets", () => {
    const { exact, entities, records } = partitionResults(
      "record-form-700-kate-colin-2024",
      [
        entityResult(),
        recordResult(),
      ],
    );
    expect(exact?.id).toBe("record-form-700-kate-colin-2024");
    expect(entities).toHaveLength(1);
    expect(records).toHaveLength(0);
  });
});

describe("SearchResults", () => {
  beforeEach(() => {
    mockRunSearch.mockReset();
  });

  it("renders entity results without a records divider when none present", async () => {
    mockRunSearch.mockResolvedValueOnce({
      query: "kate",
      built_at: "2026-04-19T00:00:00Z",
      results: [entityResult()],
    });

    await renderAsync(
      SearchResults({ query: "kate", includeRecords: false }) as Promise<React.ReactElement>,
    );

    expect(screen.getByText("Kate Colin")).toBeInTheDocument();
    expect(screen.queryByTestId("records-divider")).not.toBeInTheDocument();
  });

  it("renders a records divider between entities and records when both present", async () => {
    mockRunSearch.mockResolvedValueOnce({
      query: "merrydale",
      built_at: "2026-04-19T00:00:00Z",
      results: [
        entityResult({
          id: "project-merrydale-shelter",
          type: "Project",
          search_label: "Merrydale Interim Shelter",
          route: "/project/merrydale-shelter",
        }),
        recordResult({
          id: "record-merrydale-env-review",
          search_label: "Merrydale Env Review",
          route: "/record/merrydale-env-review",
        }),
      ],
    });

    await renderAsync(
      SearchResults({ query: "merrydale", includeRecords: true }) as Promise<React.ReactElement>,
    );

    expect(screen.getByText("Merrydale Interim Shelter")).toBeInTheDocument();
    expect(screen.getByText("Merrydale Env Review")).toBeInTheDocument();
    expect(screen.getByTestId("records-divider")).toBeInTheDocument();
  });

  it("shows EXACT MATCH kicker above entities when the query hits an id directly", async () => {
    mockRunSearch.mockResolvedValueOnce({
      query: "record-form-700-kate-colin-2024",
      built_at: "2026-04-19T00:00:00Z",
      results: [
        recordResult(),
        entityResult(),
      ],
    });

    await renderAsync(
      SearchResults({
        query: "record-form-700-kate-colin-2024",
        includeRecords: false,
      }) as Promise<React.ReactElement>,
    );

    expect(screen.getByText("EXACT MATCH")).toBeInTheDocument();
    expect(screen.getByText("Form 700 · Kate Colin · 2024")).toBeInTheDocument();
    // The entity-bucket Kate Colin card still renders.
    expect(screen.getByText("Kate Colin")).toBeInTheDocument();
  });

  it("renders a no-matches state when results is empty", async () => {
    mockRunSearch.mockResolvedValueOnce({
      query: "xyzzy",
      built_at: "2026-04-19T00:00:00Z",
      results: [],
    });

    await renderAsync(
      SearchResults({ query: "xyzzy", includeRecords: false }) as Promise<React.ReactElement>,
    );

    expect(screen.getByText(/no matches/i)).toBeInTheDocument();
  });

  it("toggle link flips include_records between true and none", async () => {
    mockRunSearch.mockResolvedValueOnce({
      query: "kate",
      built_at: "2026-04-19T00:00:00Z",
      results: [entityResult()],
    });

    await renderAsync(
      SearchResults({ query: "kate", includeRecords: false }) as Promise<React.ReactElement>,
    );

    const toggle = screen.getByText(/include source records/i).closest("a");
    expect(toggle?.getAttribute("href")).toBe("/search?q=kate&include_records=true");
  });
});
