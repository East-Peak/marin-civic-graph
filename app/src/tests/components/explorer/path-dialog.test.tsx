import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PathDialog } from "@/components/explorer/path-dialog";

const originalFetch = globalThis.fetch;

function mockFetch(handler: (url: string) => { ok: boolean; json: unknown; status?: number }) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const r = handler(url);
    return {
      ok: r.ok,
      status: r.status ?? 200,
      json: async () => r.json,
    } as Response;
  }) as unknown as typeof fetch;
}

describe("PathDialog", () => {
  beforeEach(() => {
    // Reset fetch between tests.
    globalThis.fetch = originalFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("does not render when open=false", () => {
    render(
      <PathDialog
        open={false}
        onClose={() => {}}
        onHighlightPath={() => {}}
      />,
    );
    expect(screen.queryByTestId("path-dialog")).toBeNull();
  });

  it("renders two search inputs and a loose checkbox when open", () => {
    render(
      <PathDialog
        open={true}
        onClose={() => {}}
        onHighlightPath={() => {}}
      />,
    );
    expect(screen.getByLabelText(/source/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/target/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/loose/i)).toBeInTheDocument();
  });

  it("shows path-found result with node chain and highlight button", async () => {
    mockFetch((url) => {
      if (url.startsWith("/api/path")) {
        return {
          ok: true,
          json: {
            found: true,
            loose_match: false,
            path: {
              nodes: [
                { id: "person-kate-colin", type: "Person", label: "Kate Colin" },
                { id: "meeting-x", type: "Meeting", label: "Meeting X" },
                { id: "project-merrydale", type: "Project", label: "Merrydale" },
              ],
              edges: [
                { source: "person-kate-colin", target: "meeting-x", type: "ATTENDED", weight: 5 },
                { source: "meeting-x", target: "project-merrydale", type: "ABOUT_PROJECT", weight: 4 },
              ],
              weight: 9,
            },
          },
        };
      }
      return { ok: false, json: { error: "nope" }, status: 404 };
    });

    render(
      <PathDialog
        open={true}
        onClose={() => {}}
        onHighlightPath={() => {}}
      />,
    );
    const from = screen.getByLabelText(/source/i) as HTMLInputElement;
    const to = screen.getByLabelText(/target/i) as HTMLInputElement;
    fireEvent.change(from, { target: { value: "person-kate-colin" } });
    fireEvent.change(to, { target: { value: "project-merrydale" } });
    fireEvent.click(screen.getByRole("button", { name: /find path/i }));

    await waitFor(() => {
      expect(screen.getByTestId("path-result")).toBeInTheDocument();
    });
    expect(screen.getByTestId("path-result").textContent).toContain("Kate Colin");
    expect(screen.getByTestId("path-result").textContent).toContain("Meeting X");
    expect(screen.getByTestId("path-result").textContent).toContain("Merrydale");
    expect(screen.getByRole("button", { name: /highlight on canvas/i })).toBeInTheDocument();
  });

  it("shows loose-match tag when result.loose_match is true", async () => {
    mockFetch(() => ({
      ok: true,
      json: {
        found: true,
        loose_match: true,
        path: {
          nodes: [
            { id: "a", type: "Person", label: "A" },
            { id: "b", type: "Person", label: "B" },
          ],
          edges: [{ source: "a", target: "b", type: "CAST_VOTE", weight: 1 }],
          weight: 1,
        },
      },
    }));

    render(
      <PathDialog
        open={true}
        onClose={() => {}}
        onHighlightPath={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText(/source/i), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText(/target/i), { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: /find path/i }));

    await waitFor(() => {
      expect(screen.getByText(/PATH VIA LOOSE MATCH/i)).toBeInTheDocument();
    });
  });

  it("shows no-path message when server returns found=false", async () => {
    mockFetch(() => ({ ok: true, json: { found: false } }));

    render(
      <PathDialog
        open={true}
        onClose={() => {}}
        onHighlightPath={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText(/source/i), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText(/target/i), { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: /find path/i }));

    await waitFor(() => {
      expect(screen.getByTestId("path-no-result")).toBeInTheDocument();
    });
  });

  it("invokes onHighlightPath when the user clicks highlight", async () => {
    mockFetch(() => ({
      ok: true,
      json: {
        found: true,
        loose_match: false,
        path: {
          nodes: [
            { id: "a", type: "Person", label: "A" },
            { id: "b", type: "Person", label: "B" },
          ],
          edges: [{ source: "a", target: "b", type: "CAST_VOTE", weight: 1 }],
          weight: 1,
        },
      },
    }));
    const onHighlightPath = vi.fn();
    render(
      <PathDialog
        open={true}
        onClose={() => {}}
        onHighlightPath={onHighlightPath}
      />,
    );
    fireEvent.change(screen.getByLabelText(/source/i), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText(/target/i), { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: /find path/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /highlight on canvas/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /highlight on canvas/i }));
    expect(onHighlightPath).toHaveBeenCalledWith({
      nodeIds: ["a", "b"],
      edgeKeys: expect.any(Array),
      // Fix 2: full node + edge payload is emitted so the parent can inject
      // any unloaded path hops before applying the highlight.
      nodes: [
        { id: "a", type: "Person", label: "A" },
        { id: "b", type: "Person", label: "B" },
      ],
      edges: [
        { source: "a", target: "b", type: "CAST_VOTE", weight: 1 },
      ],
    });
  });

  // -------------------------------------------------------------------------
  // Fix 14: "try loose" retry uses the fresh loose state, not stale state
  // -------------------------------------------------------------------------

  it("fix 14: 'try loose' fetches with loose=true on the retry (no stale state)", async () => {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push(url);
      return {
        ok: true,
        status: 200,
        // First response (strict): no path. Second response (loose retry):
        // still no path — the test asserts the URL, not the outcome.
        json: async () => ({ found: false }),
      } as Response;
    }) as unknown as typeof fetch;

    render(
      <PathDialog open={true} onClose={() => {}} onHighlightPath={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText(/source/i), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText(/target/i), { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: /find path/i }));

    // Wait for the no-result render, then click "try loose".
    await waitFor(() => {
      expect(screen.getByTestId("path-no-result")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /try loose/i }));

    await waitFor(() => {
      // The retry must have fired a second fetch with loose=true in the URL.
      expect(calls.some((u) => u.includes("loose=true"))).toBe(true);
    });
    // Assert on the /api/path calls ONLY — they carry `loose=`. The debounced
    // /api/search autocomplete calls (which can leak across tests under heavy
    // parallel load — a pending timer from a prior test firing into this shared
    // `calls` array) don't, so filtering by `loose=` keeps this deterministic
    // instead of trusting `calls.at(-1)`. Test-isolation only.
    // Pre-fix 14 the retry URL still had loose=false because setLoose(true)
    // hadn't been committed to state by the time onSubmit read it.
    const pathCalls = calls.filter((u) => u.includes("loose="));
    expect(pathCalls[0]).toContain("loose=false");
    expect(pathCalls.at(-1)).toContain("loose=true");
  });
});
