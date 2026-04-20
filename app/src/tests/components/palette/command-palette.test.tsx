import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useState } from "react";
import { CommandPalette } from "@/components/palette/command-palette";
import { PaletteContext } from "@/components/shortcuts/keyboard-shortcuts-provider";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

type FetchCall = string;
const fetchCalls: FetchCall[] = [];

function mockFetch(
  handler: (url: string) => { ok: boolean; json: unknown; status?: number },
) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    fetchCalls.push(url);
    const r = handler(url);
    return {
      ok: r.ok,
      status: r.status ?? 200,
      json: async () => r.json,
    } as Response;
  }) as unknown as typeof fetch;
}

// Drive open state from a local provider so tests can observe setOpen(false).
function Harness({ initialOpen = true }: { initialOpen?: boolean }) {
  const [open, setOpen] = useState(initialOpen);
  return (
    <PaletteContext.Provider value={{ open, setOpen }}>
      <CommandPalette />
      <div data-testid="open-state">{open ? "open" : "closed"}</div>
    </PaletteContext.Provider>
  );
}

describe("CommandPalette", () => {
  beforeEach(() => {
    push.mockReset();
    fetchCalls.length = 0;
    vi.useFakeTimers();
    // sessionStorage — fake so Recent Entities reads work.
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not render when closed", () => {
    render(<Harness initialOpen={false} />);
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });

  it("shows Quick Jumps when open with empty query", () => {
    render(<Harness />);
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    expect(screen.getByText("go home")).toBeInTheDocument();
    expect(screen.getByText("go graph")).toBeInTheDocument();
    expect(screen.getByText("go data")).toBeInTheDocument();
    expect(screen.getByText("go chat")).toBeInTheDocument();
    expect(screen.getByText("go about")).toBeInTheDocument();
  });

  it("debounces input and fetches /api/search after 150ms", async () => {
    mockFetch(() => ({
      ok: true,
      json: {
        results: [
          {
            id: "person-kate-colin",
            type: "Person",
            search_label: "Kate Colin",
            key_fact: "San Rafael City Council",
            search_rank: 1.0,
          },
        ],
      },
    }));
    render(<Harness />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "kate" } });
    expect(fetchCalls.length).toBe(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(fetchCalls.length).toBeGreaterThan(0);
    expect(fetchCalls[0]).toContain("/api/search");
    expect(fetchCalls[0]).toContain("q=kate");
    expect(fetchCalls[0]).toContain("include_records=false");
  });

  it("toggling include records fires a refetch with include_records=true", async () => {
    mockFetch(() => ({
      ok: true,
      json: { results: [] },
    }));
    render(<Harness />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "kate" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    const box = screen.getByLabelText(/include records/i) as HTMLInputElement;
    fireEvent.click(box);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(fetchCalls.some((u) => u.includes("include_records=true"))).toBe(true);
  });

  it("Arrow Down moves selection and Enter routes to selected item", async () => {
    mockFetch(() => ({
      ok: true,
      json: {
        results: [
          {
            id: "person-kate-colin",
            type: "Person",
            search_label: "Kate Colin",
            key_fact: null,
            search_rank: 1.0,
            route: "/person/kate-colin",
          },
          {
            id: "person-eli-beckman",
            type: "Person",
            search_label: "Eli Beckman",
            key_fact: null,
            search_rank: 0.9,
            route: "/person/eli-beckman",
          },
        ],
      },
    }));
    render(<Harness />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "kate" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(screen.getByText("Kate Colin")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/person/eli-beckman");
    expect(screen.getByTestId("open-state").textContent).toBe("closed");
  });

  it("Escape closes the palette", () => {
    render(<Harness />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.getByTestId("open-state").textContent).toBe("closed");
  });

  it("Quick Jump Enter routes (empty query path)", () => {
    render(<Harness />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    // Default selection is 0 — but Quick Jumps appear after Recent Entities.
    // With sessionStorage empty, Quick Jumps ARE the first items. Go home is
    // at index 0.
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/");
  });

  it("stale fetch does not overwrite fresher response", async () => {
    // Drive two overlapping fetches: query A resolves SLOW, query B resolves
    // FAST. Even though A's debounced fetch fires first, the user has
    // already typed B by the time A's response lands — B's results must
    // stay on screen.
    const deferred: Array<{ resolve: (v: { results: unknown[] }) => void }> = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      fetchCalls.push(url);
      return await new Promise<Response>((resolveRes) => {
        deferred.push({
          resolve: (json) =>
            resolveRes({
              ok: true,
              status: 200,
              json: async () => json,
            } as Response),
        });
      });
    }) as unknown as typeof fetch;

    render(<Harness />);
    const input = screen.getByRole("combobox") as HTMLInputElement;

    // Query A — "kate"
    fireEvent.change(input, { target: { value: "kate" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    // Query B — "eli" (replaces A before A resolves)
    fireEvent.change(input, { target: { value: "eli" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(deferred.length).toBe(2);

    // Resolve B first (fresh), THEN A (stale).
    await act(async () => {
      deferred[1].resolve({
        results: [
          {
            id: "person-eli-beckman",
            type: "Person",
            search_label: "Eli Beckman",
            key_fact: null,
            search_rank: 0.9,
            route: "/person/eli-beckman",
          },
        ],
      });
      // Let the microtask settle so setResults fires for B.
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      deferred[0].resolve({
        results: [
          {
            id: "person-kate-colin",
            type: "Person",
            search_label: "Kate Colin",
            key_fact: null,
            search_rank: 1.0,
            route: "/person/kate-colin",
          },
        ],
      });
      await vi.advanceTimersByTimeAsync(0);
    });

    // B's results must be what's displayed — A must have been dropped.
    expect(screen.getByText("Eli Beckman")).toBeInTheDocument();
    expect(screen.queryByText("Kate Colin")).toBeNull();
  });

  it("palette root has dialog semantics (role + aria-modal + aria-label)", () => {
    render(<Harness />);
    const root = screen.getByTestId("command-palette");
    expect(root.getAttribute("role")).toBe("dialog");
    expect(root.getAttribute("aria-modal")).toBe("true");
    expect(root.getAttribute("aria-label")).toBe("command palette");
  });

  it("combobox aria-activedescendant points at the selected option", async () => {
    mockFetch(() => ({
      ok: true,
      json: {
        results: [
          {
            id: "person-kate-colin",
            type: "Person",
            search_label: "Kate Colin",
            key_fact: null,
            search_rank: 1.0,
            route: "/person/kate-colin",
          },
          {
            id: "person-eli-beckman",
            type: "Person",
            search_label: "Eli Beckman",
            key_fact: null,
            search_rank: 0.9,
            route: "/person/eli-beckman",
          },
        ],
      },
    }));
    render(<Harness />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "k" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(input.getAttribute("aria-activedescendant")).toBe("palette-item-0");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe("palette-item-1");
    // And the selected row is actually marked aria-selected.
    const options = screen.getAllByRole("option");
    expect(options[1].getAttribute("aria-selected")).toBe("true");
    expect(options[0].getAttribute("aria-selected")).toBe("false");
  });
});
