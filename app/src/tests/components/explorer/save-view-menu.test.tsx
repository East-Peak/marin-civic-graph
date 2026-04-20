import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SaveViewMenu } from "@/components/explorer/save-view-menu";
import {
  parseUrlToState,
  type ExplorerState,
} from "@/lib/explorer/explorer-state";

const INGEST = "2026-04-14T09:00:00Z";

function baseState(): ExplorerState {
  return parseUrlToState(new URLSearchParams("?focus=person-kate-colin"), INGEST);
}

// Minimal in-memory localStorage shim — vitest's jsdom variant in this
// project exposes localStorage as a getter that doesn't implement .clear()
// reliably; this shim keeps tests hermetic regardless.
function installLocalStorage() {
  const store = new Map<string, string>();
  const ls = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => {
      store.set(k, String(v));
    },
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size;
    },
  };
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: ls,
  });
}

describe("SaveViewMenu", () => {
  beforeEach(() => {
    installLocalStorage();
  });

  it("does not render when open=false", () => {
    render(<SaveViewMenu open={false} state={baseState()} onClose={() => {}} onLoadView={() => {}} />);
    expect(screen.queryByTestId("save-view-menu")).toBeNull();
  });

  it("saves the current state to localStorage when save is clicked", () => {
    render(<SaveViewMenu open={true} state={baseState()} onClose={() => {}} onLoadView={() => {}} />);
    const nameInput = screen.getByLabelText(/view name/i);
    fireEvent.change(nameInput, { target: { value: "merrydale-sweep" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    const raw = window.localStorage.getItem("openmarin_saved_views");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw ?? "{}") as Record<string, { state: ExplorerState }>;
    expect(parsed["merrydale-sweep"]).toBeDefined();
    expect(parsed["merrydale-sweep"].state.focus).toBe("person-kate-colin");
  });

  it("lists existing saved views and calls onLoadView when one is clicked", () => {
    // Seeded values mimic the on-disk (serialized) shape — Sets as arrays.
    const alphaBase = baseState();
    window.localStorage.setItem(
      "openmarin_saved_views",
      JSON.stringify({
        alpha: {
          state: {
            ...alphaBase,
            focus: "person-alpha",
            loadedNodeIds: Array.from(alphaBase.loadedNodeIds),
            loadedEdgeKeys: Array.from(alphaBase.loadedEdgeKeys),
          },
          saved_at: "2026-04-19T00:00:00Z",
        },
      }),
    );

    const onLoadView = vi.fn();
    render(<SaveViewMenu open={true} state={baseState()} onClose={() => {}} onLoadView={onLoadView} />);
    fireEvent.click(screen.getByRole("button", { name: /load alpha/i }));
    expect(onLoadView).toHaveBeenCalled();
    // Fix 7: onLoadView is now handed a SavedViewLoad {state, nodes, edges}
    // instead of a bare ExplorerState.
    const passed = onLoadView.mock.calls[0][0] as { state: ExplorerState; nodes: unknown[]; edges: unknown[] };
    expect(passed.state.focus).toBe("person-alpha");
    expect(Array.isArray(passed.nodes)).toBe(true);
    expect(Array.isArray(passed.edges)).toBe(true);
  });

  it("deletes a saved view when the × button is clicked", () => {
    const alpha = baseState();
    window.localStorage.setItem(
      "openmarin_saved_views",
      JSON.stringify({
        alpha: {
          state: {
            ...alpha,
            loadedNodeIds: Array.from(alpha.loadedNodeIds),
            loadedEdgeKeys: Array.from(alpha.loadedEdgeKeys),
          },
          saved_at: "2026-04-19T00:00:00Z",
        },
      }),
    );
    render(<SaveViewMenu open={true} state={baseState()} onClose={() => {}} onLoadView={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /delete alpha/i }));
    const raw = window.localStorage.getItem("openmarin_saved_views");
    const parsed = JSON.parse(raw ?? "{}") as Record<string, unknown>;
    expect(parsed.alpha).toBeUndefined();
  });

  it("exports current state as JSON (via Blob URL)", () => {
    const originalCreate = window.URL.createObjectURL;
    const mockCreate = vi.fn(() => "blob:mock");
    window.URL.createObjectURL = mockCreate;
    const revoke = vi.fn();
    window.URL.revokeObjectURL = revoke;

    render(<SaveViewMenu open={true} state={baseState()} onClose={() => {}} onLoadView={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /export json/i }));
    expect(mockCreate).toHaveBeenCalled();

    window.URL.createObjectURL = originalCreate;
  });

  // -------------------------------------------------------------------------
  // Fix 7: save-view persists full canvas payload, not just state
  // -------------------------------------------------------------------------

  it("fix 7: save writes the canvas payload returned by getCanvasPayload", () => {
    const getCanvasPayload = vi.fn(() => ({
      nodes: [
        {
          id: "person-kate-colin",
          type: "Person" as const,
          label: "Kate Colin",
          route: "/person/kate-colin",
          ring: 0,
          event_date: null,
        },
        {
          id: "decision-x",
          type: "Decision" as const,
          label: "Decision X",
          route: "/decision/x",
          ring: 1,
          event_date: "2024-05-12",
        },
      ],
      edges: [
        {
          source: "person-kate-colin",
          target: "decision-x",
          type: "CAST_VOTE",
          style: "governance" as const,
        },
      ],
    }));

    render(
      <SaveViewMenu
        open={true}
        state={baseState()}
        getCanvasPayload={getCanvasPayload}
        onClose={() => {}}
        onLoadView={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText(/view name/i), { target: { value: "merrydale-sweep" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    const raw = window.localStorage.getItem("openmarin_saved_views");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw ?? "{}") as Record<
      string,
      { state: ExplorerState; nodes: unknown[]; edges: unknown[] }
    >;
    expect(parsed["merrydale-sweep"].nodes).toHaveLength(2);
    expect(parsed["merrydale-sweep"].edges).toHaveLength(1);
    expect(getCanvasPayload).toHaveBeenCalledTimes(1);
  });

  it("fix 7: load passes nodes + edges alongside state", () => {
    const nodes = [
      {
        id: "decision-x",
        type: "Decision" as const,
        label: "Dec X",
        route: "/decision/x",
        ring: 1,
        event_date: "2024-05-12",
      },
    ];
    const edges = [
      {
        source: "person-alpha",
        target: "decision-x",
        type: "CAST_VOTE",
        style: "governance" as const,
      },
    ];
    const alpha = baseState();
    window.localStorage.setItem(
      "openmarin_saved_views",
      JSON.stringify({
        alpha: {
          state: {
            ...alpha,
            focus: "person-alpha",
            loadedNodeIds: Array.from(alpha.loadedNodeIds),
            loadedEdgeKeys: Array.from(alpha.loadedEdgeKeys),
          },
          nodes,
          edges,
          saved_at: "2026-04-19T00:00:00Z",
        },
      }),
    );

    const onLoadView = vi.fn();
    render(
      <SaveViewMenu
        open={true}
        state={baseState()}
        onClose={() => {}}
        onLoadView={onLoadView}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /load alpha/i }));
    const arg = onLoadView.mock.calls[0][0];
    expect(arg.state.focus).toBe("person-alpha");
    expect(arg.nodes).toEqual(nodes);
    expect(arg.edges).toEqual(edges);
  });

  it("caps saved views at 20", () => {
    const base = baseState();
    const serializedBase = {
      ...base,
      loadedNodeIds: Array.from(base.loadedNodeIds),
      loadedEdgeKeys: Array.from(base.loadedEdgeKeys),
    };
    const existing: Record<string, { state: typeof serializedBase; saved_at: string }> = {};
    for (let i = 0; i < 20; i++) {
      existing[`view-${i}`] = {
        state: serializedBase,
        saved_at: new Date(2020, 0, i + 1).toISOString(),
      };
    }
    window.localStorage.setItem("openmarin_saved_views", JSON.stringify(existing));

    render(<SaveViewMenu open={true} state={baseState()} onClose={() => {}} onLoadView={() => {}} />);
    fireEvent.change(screen.getByLabelText(/view name/i), { target: { value: "view-21" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    const parsed = JSON.parse(
      window.localStorage.getItem("openmarin_saved_views") ?? "{}",
    ) as Record<string, unknown>;
    expect(Object.keys(parsed).length).toBeLessThanOrEqual(20);
    expect(parsed["view-21"]).toBeDefined();
    // The oldest should have been evicted.
    expect(parsed["view-0"]).toBeUndefined();
  });
});
