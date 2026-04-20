"use client";

// Save-view menu for the full-screen explorer per spec §6.3.
//
// Stores up to 20 named ExplorerStates under localStorage key
// `openmarin_saved_views`. The state is JSON-serialized with Sets expanded to
// arrays (and collapsed back on load), since Set doesn't round-trip through
// JSON.stringify.
//
// Per fix 7: the on-disk shape also carries the full investigation canvas —
// every node + edge the user has loaded — so that restoring a view rebuilds
// the graph they were looking at, not just the focus + filter chip state.
//
// Also offers a one-shot JSON export (download of the current state).
//
// The parent handles the actual navigation on load by consuming the
// ExplorerState + nodes + edges passed through `onLoadView` and pushing the
// URL.

import { useCallback, useState } from "react";
import type { ExplorerState } from "@/lib/explorer/explorer-state";
import type { NodeType } from "@/lib/type-display";

const STORAGE_KEY = "openmarin_saved_views";
const MAX_SAVED = 20;

// The on-disk shape stores Sets as arrays to survive JSON.
type SerializedExplorerState = Omit<ExplorerState, "loadedNodeIds" | "loadedEdgeKeys"> & {
  loadedNodeIds: string[];
  loadedEdgeKeys: string[];
};

// Per fix 7: the serializable subset of a canvas node. Mirrors the NodeRow
// shape the explorer client passes through `nodeToElement` but stripped of
// anything the renderer derives at paint time (size, glow, etc.). We keep
// type + label + event_date so re-layout reconstructs the same radial map.
export type SavedViewNode = {
  id: string;
  type: NodeType;
  label: string;
  route: string;
  ring: number;
  event_date?: string | null;
};

// Per fix 7: canvas edge counterpart to SavedViewNode.
export type SavedViewEdge = {
  source: string;
  target: string;
  type: string;
  style: "governance" | "money" | "legal-constrains";
};

export type SavedView = {
  state: SerializedExplorerState;
  nodes: SavedViewNode[];
  edges: SavedViewEdge[];
  saved_at: string;
};

export type SavedViewLoad = {
  state: ExplorerState;
  nodes: SavedViewNode[];
  edges: SavedViewEdge[];
};

function serialize(state: ExplorerState): SerializedExplorerState {
  return {
    ...state,
    loadedNodeIds: Array.from(state.loadedNodeIds),
    loadedEdgeKeys: Array.from(state.loadedEdgeKeys),
  };
}

function deserialize(s: SerializedExplorerState): ExplorerState {
  return {
    ...s,
    loadedNodeIds: new Set(s.loadedNodeIds),
    loadedEdgeKeys: new Set(s.loadedEdgeKeys),
  };
}

function readSaved(): Record<string, SavedView> {
  if (typeof window === "undefined") return {};
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as Record<string, Partial<SavedView>>;
    // Coerce pre-fix-7 entries (no nodes/edges) to the new shape so old
    // stored views don't crash the UI — they just restore with an empty
    // canvas payload, same behavior as before.
    const out: Record<string, SavedView> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (!v || !v.state) continue;
      out[k] = {
        state: v.state as SerializedExplorerState,
        nodes: Array.isArray(v.nodes) ? (v.nodes as SavedViewNode[]) : [],
        edges: Array.isArray(v.edges) ? (v.edges as SavedViewEdge[]) : [],
        saved_at: typeof v.saved_at === "string" ? v.saved_at : new Date().toISOString(),
      };
    }
    return out;
  } catch {
    return {};
  }
}

function writeSaved(views: Record<string, SavedView>) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(views));
}

function enforceCap(views: Record<string, SavedView>): Record<string, SavedView> {
  const entries = Object.entries(views);
  if (entries.length <= MAX_SAVED) return views;
  // Sort by saved_at ASC and drop the oldest until we're at the cap.
  entries.sort(([, a], [, b]) => a.saved_at.localeCompare(b.saved_at));
  const trimmed = entries.slice(entries.length - MAX_SAVED);
  return Object.fromEntries(trimmed);
}

// ---------------------------------------------------------------------------
// Public props
// ---------------------------------------------------------------------------

export type SaveViewMenuProps = {
  open: boolean;
  state: ExplorerState;
  /** Supplier of the current canvas payload. Called at save-time so the
   *  parent can snapshot Cytoscape's live nodes/edges into the saved view. */
  getCanvasPayload?: () => { nodes: SavedViewNode[]; edges: SavedViewEdge[] };
  onClose: () => void;
  onLoadView: (loaded: SavedViewLoad) => void;
};

export function SaveViewMenu({
  open,
  state,
  getCanvasPayload,
  onClose,
  onLoadView,
}: SaveViewMenuProps) {
  const [name, setName] = useState("");
  // Read localStorage lazily on first render. Subsequent changes (save,
  // delete, cap-eviction) go through setSaved. Cross-tab mutation is a Plan 4
  // concern — for now, a single tab's view of the saved list is authoritative.
  const [saved, setSaved] = useState<Record<string, SavedView>>(() => readSaved());

  const snapshotPayload = useCallback(() => {
    if (getCanvasPayload) return getCanvasPayload();
    return { nodes: [] as SavedViewNode[], edges: [] as SavedViewEdge[] };
  }, [getCanvasPayload]);

  if (!open) return null;

  function save() {
    const trimmedName = name.trim();
    if (!trimmedName) return;
    const payload = snapshotPayload();
    const next: Record<string, SavedView> = {
      ...saved,
      [trimmedName]: {
        state: serialize(state),
        nodes: payload.nodes,
        edges: payload.edges,
        saved_at: new Date().toISOString(),
      },
    };
    const capped = enforceCap(next);
    writeSaved(capped);
    setSaved(capped);
    setName("");
  }

  function deleteView(key: string) {
    const next = { ...saved };
    delete next[key];
    writeSaved(next);
    setSaved(next);
  }

  function loadView(key: string) {
    const v = saved[key];
    if (!v) return;
    onLoadView({
      state: deserialize(v.state),
      nodes: v.nodes ?? [],
      edges: v.edges ?? [],
    });
  }

  function exportJson() {
    const payload = snapshotPayload();
    const dump = {
      state: serialize(state),
      nodes: payload.nodes,
      edges: payload.edges,
      saved_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(dump, null, 2)], {
      type: "application/json",
    });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const focus = state.focus ?? "view";
    a.download = `openmarin-${focus}-${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Don't revoke synchronously — the download may still need the URL in
    // some browsers. A microtask delay is plenty.
    setTimeout(() => window.URL.revokeObjectURL(url), 0);
  }

  const sortedKeys = Object.keys(saved).sort((a, b) => {
    return saved[b].saved_at.localeCompare(saved[a].saved_at);
  });

  return (
    <div
      data-testid="save-view-menu"
      className="fixed inset-0 z-50 flex items-start justify-end"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="mt-16 mr-4 w-[360px] max-w-[90vw] rounded border border-border-primary bg-panel p-3 font-mono text-xs text-body"
      >
        <div
          className="mb-2 text-hairline"
          style={{ fontFamily: "var(--font-vt323)", fontSize: "14px", letterSpacing: "0.08em" }}
        >
          SAVE VIEW
        </div>
        <div className="flex items-center gap-1">
          <input
            aria-label="view name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="name this view…"
            className="flex-1 rounded border border-[#262b35] bg-surface px-2 py-1 text-body focus:outline-none focus:ring-1 focus:ring-[#a4e8bf]"
          />
          <button
            type="button"
            onClick={save}
            className="rounded border border-[#a4e8bf] bg-surface px-2 py-1 text-[11px] text-body"
          >
            save
          </button>
          <button
            type="button"
            onClick={exportJson}
            className="rounded border border-[#262b35] bg-panel px-2 py-1 text-[11px] text-dim hover:text-body"
          >
            export JSON
          </button>
        </div>

        <div className="mt-3 max-h-[360px] overflow-auto">
          {sortedKeys.length === 0 && (
            <div className="py-2 text-hairline">no saved views yet</div>
          )}
          <ul>
            {sortedKeys.map((k) => (
              <li
                key={k}
                className="flex items-center justify-between border-b border-border-hairline py-1"
              >
                <button
                  type="button"
                  onClick={() => loadView(k)}
                  aria-label={`load ${k}`}
                  className="flex-1 text-left text-body hover:text-[#a4e8bf]"
                >
                  {k}
                </button>
                <span className="mx-2 text-[10px] text-hairline">
                  {saved[k].saved_at.slice(0, 10)}
                </span>
                <button
                  type="button"
                  onClick={() => deleteView(k)}
                  aria-label={`delete ${k}`}
                  className="text-hairline hover:text-[#f2b441]"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
