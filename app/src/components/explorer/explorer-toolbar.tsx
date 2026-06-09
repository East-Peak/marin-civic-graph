"use client";

// Docked toolbar for the full-screen explorer per spec §6.3.
//
// Renders compact Plex-Mono chips for:
//   - HOP slider (1..4)
//   - 21 node-type filter chips, grouped visually
//   - 4 edge-class filter chips
//   - Time range (paired <input type="date">; fancy two-thumb slider is Plan 4 polish)
//   - Pathfinding button
//   - Save-view button
//
// Pure controlled component — all state lives in the parent via `state` prop,
// every change is emitted through `onStateChange(newState)`.

import type {
  EdgeFilterClass,
  ExplorerState,
  HopSlider,
} from "@/lib/explorer/explorer-state";
import { ALL_TYPES, type NodeType } from "@/lib/type-display";

// Visual grouping per the Task 8 note. Preserves spec §6.3 order enough for
// the user to scan by family. Types not in any group would fall through, so
// we include every NodeType in exactly one bucket.
// Exported for the node-type parity test (EXHAUSTIVE_GROUPING) — every NodeType
// must be in exactly one filter group.
export const FILTER_GROUPS: { label: string; types: NodeType[] }[] = [
  { label: "people", types: ["Person", "Organization", "Committee"] },
  { label: "governance", types: ["Seat", "SeatService", "Meeting", "AgendaItem", "Decision"] },
  { label: "campaigns", types: ["Election", "Candidacy", "Filing", "MoneyFlow"] },
  { label: "projects", types: ["Project", "Program", "Agreement", "Amendment"] },
  { label: "legal", types: ["Case", "Proceeding"] },
  { label: "context", types: ["Place", "Issue"] },
  { label: "records", types: ["Record"] },
];

// Sanity: the groups must cover every NodeType exactly once. Catches a future
// spec addition that forgets to add to a group.
const _COVERED = new Set(FILTER_GROUPS.flatMap((g) => g.types));
for (const t of ALL_TYPES) {
  if (!_COVERED.has(t)) {
    // Log but don't throw — the UI stays usable with the type ungrouped.
    console.warn(`[explorer-toolbar] node type ${t} is not in any filter group`);
  }
}

const EDGE_FILTER_ORDER: { key: EdgeFilterClass; label: string }[] = [
  { key: "governance", label: "governance" },
  { key: "money", label: "money" },
  { key: "legalConstrains", label: "legal" },
  { key: "universal", label: "universal" },
];

export type ExplorerToolbarProps = {
  state: ExplorerState;
  onStateChange: (next: ExplorerState) => void;
  onOpenPath: () => void;
  onOpenSaveView: () => void;
};

export function ExplorerToolbar({
  state,
  onStateChange,
  onOpenPath,
  onOpenSaveView,
}: ExplorerToolbarProps) {
  function setHop(v: number) {
    const clamped = Math.max(1, Math.min(4, Math.round(v))) as HopSlider;
    onStateChange({ ...state, hop: clamped });
  }

  function toggleNodeFilter(t: NodeType) {
    onStateChange({
      ...state,
      nodeFilters: { ...state.nodeFilters, [t]: !state.nodeFilters[t] },
    });
  }

  function toggleEdgeFilter(k: EdgeFilterClass) {
    onStateChange({
      ...state,
      edgeFilters: { ...state.edgeFilters, [k]: !state.edgeFilters[k] },
    });
  }

  function setTimeFrom(v: string) {
    onStateChange({ ...state, timeFrom: v });
  }

  function setTimeTo(v: string) {
    onStateChange({ ...state, timeTo: v });
  }

  return (
    <div
      className="flex flex-wrap items-center gap-3 border-b border-border-hairline bg-panel px-4 py-2 font-mono text-[11px] text-dim"
      data-testid="explorer-toolbar"
    >
      <div className="flex items-center gap-2">
        <label
          className="text-hairline"
          style={{ fontFamily: "var(--font-vt323)", fontSize: "14px", letterSpacing: "0.08em" }}
        >
          HOP {state.hop}
        </label>
        <input
          aria-label="hop"
          type="range"
          min="1"
          max="4"
          step="1"
          value={state.hop}
          onChange={(e) => setHop(Number(e.target.value))}
          className="h-1 w-20 accent-[#a4e8bf]"
        />
      </div>

      {FILTER_GROUPS.map((group) => (
        <div key={group.label} className="flex items-center gap-1">
          <span className="mr-1 text-hairline uppercase">{group.label}</span>
          {group.types.map((t) => {
            const active = state.nodeFilters[t];
            return (
              <button
                key={t}
                type="button"
                data-testid={`node-filter-${t}`}
                data-active={active ? "true" : "false"}
                onClick={() => toggleNodeFilter(t)}
                className={
                  "rounded border px-1.5 py-0.5 text-[10px] " +
                  (active
                    ? "border-[#a4e8bf] bg-surface text-body"
                    : "border-[#262b35] bg-panel text-hairline hover:text-dim")
                }
              >
                {t}
              </button>
            );
          })}
        </div>
      ))}

      <div className="flex items-center gap-1">
        <span className="mr-1 text-hairline uppercase">edges</span>
        {EDGE_FILTER_ORDER.map((edge) => {
          const active = state.edgeFilters[edge.key];
          return (
            <button
              key={edge.key}
              type="button"
              data-testid={`edge-filter-${edge.key}`}
              data-active={active ? "true" : "false"}
              onClick={() => toggleEdgeFilter(edge.key)}
              className={
                "rounded border px-1.5 py-0.5 text-[10px] " +
                (active
                  ? "border-[#a4e8bf] bg-surface text-body"
                  : "border-[#262b35] bg-panel text-hairline hover:text-dim")
              }
            >
              {edge.label}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-1">
        <label className="text-hairline uppercase" htmlFor="explorer-from">from</label>
        <input
          id="explorer-from"
          type="date"
          value={state.timeFrom}
          onChange={(e) => setTimeFrom(e.target.value)}
          className="rounded border border-[#262b35] bg-panel px-1.5 py-0.5 text-[10px] text-body"
        />
        <label className="text-hairline uppercase" htmlFor="explorer-to">to</label>
        <input
          id="explorer-to"
          type="date"
          value={state.timeTo}
          onChange={(e) => setTimeTo(e.target.value)}
          className="rounded border border-[#262b35] bg-panel px-1.5 py-0.5 text-[10px] text-body"
        />
      </div>

      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={onOpenPath}
          className="rounded border border-[#262b35] bg-panel px-2 py-0.5 text-[10px] text-dim hover:text-body"
        >
          find path
        </button>
        <button
          type="button"
          onClick={onOpenSaveView}
          className="rounded border border-[#262b35] bg-panel px-2 py-0.5 text-[10px] text-dim hover:text-body"
        >
          save view
        </button>
      </div>
    </div>
  );
}
