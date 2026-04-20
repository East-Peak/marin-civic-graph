"use client";

// Save-view menu for the full-screen explorer per spec §6.3.
//
// Stores up to 20 named ExplorerStates under localStorage key
// `openmarin_saved_views`. The state is JSON-serialized with Sets expanded to
// arrays (and collapsed back on load), since Set doesn't round-trip through
// JSON.stringify.
//
// Also offers a one-shot JSON export (download of the current state).
//
// The parent handles the actual navigation on load by consuming the
// ExplorerState passed through `onLoadView` and pushing the URL.

import { useEffect, useState } from "react";
import type { ExplorerState } from "@/lib/explorer/explorer-state";

const STORAGE_KEY = "openmarin_saved_views";
const MAX_SAVED = 20;

// The on-disk shape stores Sets as arrays to survive JSON.
type SerializedExplorerState = Omit<ExplorerState, "loadedNodeIds" | "loadedEdgeKeys"> & {
  loadedNodeIds: string[];
  loadedEdgeKeys: string[];
};

export type SavedView = {
  state: SerializedExplorerState;
  saved_at: string;
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
    return JSON.parse(raw) as Record<string, SavedView>;
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
  onClose: () => void;
  onLoadView: (state: ExplorerState) => void;
};

export function SaveViewMenu({ open, state, onClose, onLoadView }: SaveViewMenuProps) {
  const [name, setName] = useState("");
  const [saved, setSaved] = useState<Record<string, SavedView>>({});

  useEffect(() => {
    if (open) setSaved(readSaved());
  }, [open]);

  if (!open) return null;

  function save() {
    const trimmedName = name.trim();
    if (!trimmedName) return;
    const next: Record<string, SavedView> = {
      ...saved,
      [trimmedName]: {
        state: serialize(state),
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
    onLoadView(deserialize(v.state));
  }

  function exportJson() {
    const blob = new Blob([JSON.stringify(serialize(state), null, 2)], {
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
