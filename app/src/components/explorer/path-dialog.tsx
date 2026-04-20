"use client";

// Pathfinding modal for the full-screen explorer per spec §5.6.
//
// Two inputs (source + target), a "loose" checkbox, a "Find path" button. On
// submit, calls /api/path and renders the resulting chain of nodes with type
// badges. "PATH VIA LOOSE MATCH" tag appears when the server returns
// loose_match: true (§5.6). "Highlight on canvas" emits the path's node/edge
// identifiers to the parent so it can paint them with the amber ring.
//
// The source/target inputs are plain text IDs for this Plan 3 scaffolding.
// Plan 4 is expected to wire in /api/search autocomplete — we already have a
// `fetchSuggestions` hook wired up so that a drop-down can be added without
// restructuring the component.

import { useEffect, useRef, useState } from "react";
import { edgeKey, type EdgeLike } from "@/lib/explorer/explorer-state";

// ---------------------------------------------------------------------------
// API shapes — mirror lib/server/path-finder.ts PathResult.
// ---------------------------------------------------------------------------

type PathNode = { id: string; type: string; label: string };
type PathEdge = { source: string; target: string; type: string; weight: number };
type PathResult =
  | {
      found: true;
      loose_match: boolean;
      path: { nodes: PathNode[]; edges: PathEdge[]; weight: number };
    }
  | { found: false };

type SearchResult = {
  id: string;
  type: string;
  search_label: string;
};

// ---------------------------------------------------------------------------
// Public props
// ---------------------------------------------------------------------------

export type HighlightPathArgs = {
  nodeIds: string[];
  edgeKeys: string[];
};

export type PathDialogProps = {
  open: boolean;
  onClose: () => void;
  onHighlightPath: (args: HighlightPathArgs) => void;
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PathDialog({ open, onClose, onHighlightPath }: PathDialogProps) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [loose, setLoose] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PathResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Debounced suggestions per field — kept optional; text-entry still works
  // even if the /api/search call fails.
  const [fromSuggestions, setFromSuggestions] = useState<SearchResult[]>([]);
  const [toSuggestions, setToSuggestions] = useState<SearchResult[]>([]);
  const fromDebounce = useRef<number | null>(null);
  const toDebounce = useRef<number | null>(null);

  useEffect(() => {
    if (!open) {
      // Reset transient state when dialog closes so the next open starts fresh.
      setResult(null);
      setError(null);
    }
  }, [open]);

  function debouncedSearch(
    q: string,
    setSuggestions: (s: SearchResult[]) => void,
    ref: React.MutableRefObject<number | null>,
  ) {
    if (ref.current) window.clearTimeout(ref.current);
    if (!q.trim() || q.length < 2) {
      setSuggestions([]);
      return;
    }
    ref.current = window.setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        if (!res.ok) return;
        const json = (await res.json()) as { results: SearchResult[] };
        setSuggestions(json.results.slice(0, 6));
      } catch {
        /* ignore — suggestions are optional */
      }
    }, 250);
  }

  async function onSubmit() {
    if (!from.trim() || !to.trim()) {
      setError("both source and target are required");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(
        `/api/path?from=${encodeURIComponent(from.trim())}&to=${encodeURIComponent(to.trim())}&loose=${loose ? "true" : "false"}`,
      );
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        setError(body.error ?? "pathfinding failed");
      } else {
        setResult((await res.json()) as PathResult);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div
      data-testid="path-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[480px] max-w-[95vw] rounded border border-border-primary bg-panel p-4 font-mono text-xs text-body"
      >
        <div
          className="mb-3 text-hairline"
          style={{ fontFamily: "var(--font-vt323)", fontSize: "16px", letterSpacing: "0.08em" }}
        >
          FIND PATH
        </div>

        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-hairline uppercase">source</span>
            <input
              aria-label="source"
              value={from}
              onChange={(e) => {
                setFrom(e.target.value);
                debouncedSearch(e.target.value, setFromSuggestions, fromDebounce);
              }}
              placeholder="node id or name"
              className="rounded border border-[#262b35] bg-surface px-2 py-1 text-body focus:outline-none focus:ring-1 focus:ring-[#a4e8bf]"
            />
            {fromSuggestions.length > 0 && (
              <ul className="max-h-40 overflow-auto rounded border border-[#262b35] bg-panel">
                {fromSuggestions.map((s) => (
                  <li
                    key={s.id}
                    className="cursor-pointer px-2 py-1 text-[11px] hover:bg-surface"
                    onClick={() => {
                      setFrom(s.id);
                      setFromSuggestions([]);
                    }}
                  >
                    <span className="text-hairline">[{s.type}] </span>
                    {s.search_label}
                  </li>
                ))}
              </ul>
            )}
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-hairline uppercase">target</span>
            <input
              aria-label="target"
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                debouncedSearch(e.target.value, setToSuggestions, toDebounce);
              }}
              placeholder="node id or name"
              className="rounded border border-[#262b35] bg-surface px-2 py-1 text-body focus:outline-none focus:ring-1 focus:ring-[#a4e8bf]"
            />
            {toSuggestions.length > 0 && (
              <ul className="max-h-40 overflow-auto rounded border border-[#262b35] bg-panel">
                {toSuggestions.map((s) => (
                  <li
                    key={s.id}
                    className="cursor-pointer px-2 py-1 text-[11px] hover:bg-surface"
                    onClick={() => {
                      setTo(s.id);
                      setToSuggestions([]);
                    }}
                  >
                    <span className="text-hairline">[{s.type}] </span>
                    {s.search_label}
                  </li>
                ))}
              </ul>
            )}
          </label>

          <label className="flex items-center gap-2">
            <input
              aria-label="loose"
              type="checkbox"
              checked={loose}
              onChange={(e) => setLoose(e.target.checked)}
              className="accent-[#a4e8bf]"
            />
            <span className="text-dim">loose path (admits records / places / issues as hops)</span>
          </label>

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={onSubmit}
              disabled={loading}
              className="rounded border border-[#a4e8bf] bg-surface px-2.5 py-1 text-[11px] text-body disabled:opacity-50"
            >
              {loading ? "finding…" : "find path"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-[#262b35] bg-panel px-2.5 py-1 text-[11px] text-dim hover:text-body"
            >
              close
            </button>
          </div>
        </div>

        {error && <div className="mt-3 text-[11px] text-[#f2b441]">{error}</div>}

        {result && result.found && (
          <div className="mt-3 border-t border-border-hairline pt-3" data-testid="path-result">
            {result.loose_match && (
              <div className="mb-1 text-[10px] uppercase tracking-wider text-[#f2b441]">
                PATH VIA LOOSE MATCH
              </div>
            )}
            <div className="flex flex-wrap items-center gap-1 text-[11px]">
              {result.path.nodes.map((n, i) => (
                <span key={`${n.id}-${i}`} className="flex items-center gap-1">
                  <span className="rounded border border-[#262b35] bg-surface px-1.5 py-0.5">
                    <span className="text-hairline">[{n.type}] </span>
                    <span className="text-body">{n.label}</span>
                  </span>
                  {i < result.path.nodes.length - 1 && (
                    <span className="text-hairline">→</span>
                  )}
                </span>
              ))}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-hairline">weight {result.path.weight}</span>
              <button
                type="button"
                onClick={() => {
                  const edgeKeys = result.path.edges.map((e) =>
                    edgeKey({ source: e.source, target: e.target, type: e.type } as EdgeLike),
                  );
                  onHighlightPath({
                    nodeIds: result.path.nodes.map((n) => n.id),
                    edgeKeys,
                  });
                }}
                className="rounded border border-[#a4e8bf] bg-surface px-2 py-0.5 text-[10px] text-body"
              >
                highlight on canvas
              </button>
            </div>
          </div>
        )}

        {result && !result.found && (
          <div
            className="mt-3 border-t border-border-hairline pt-3 text-[11px] text-dim"
            data-testid="path-no-result"
          >
            no path under{" "}
            {loose ? "loose rules" : "default rules"}
            {!loose && (
              <>
                {" · "}
                <button
                  type="button"
                  onClick={() => {
                    setLoose(true);
                    onSubmit();
                  }}
                  className="underline hover:text-body"
                >
                  try loose
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
