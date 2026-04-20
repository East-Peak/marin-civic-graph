// Explorer state module — single source of truth for the URL + sessionStorage
// surface area behind the /graph explorer.
//
// Per spec §5.4 + §6.3 + Plan 3 Task 5:
//
//   * `ExplorerState` captures the full investigation state: focus, hop
//     slider, per-type node filters (21), edge-class filters (4),
//     time-slider range, and the client-side loaded-nodes / loaded-edges
//     memoization (for dedup + refresh continuity).
//
//   * URL ↔ state mapping is bidirectional (`parseUrlToState`,
//     `stateToUrl`). Refreshing the page puts the user back at the same
//     investigation. The URL is the canonical representation; sessionStorage
//     is the cache of "what have we loaded from the network so far."
//
//   * `mergeExpansion` accepts the response of `/api/expand` and folds new
//     nodes + edges into the loaded sets, preserving the state's other
//     fields (immutable-update style).
//
//   * `defaultTimeRange` computes the §5.4 default slider range ("last 5
//     years from ingest, floored by earliest loaded event").
//
//   * `autoEnableFiltersForFocus` per §6.3 — when the focus type is Record /
//     Place / Issue / AgendaItem (the usually-off node types), auto-enable
//     its filter so the hero has something to render.
//
// The module is pure TypeScript — no React, no DOM, no fetch — so it's
// trivially testable and safe to import from both client and server.

import { ALL_TYPES, type NodeType } from "@/lib/type-display";
import {
  LEGAL_EDGES_LIVE,
  MONEY_EDGES_LIVE,
  PHASE2_WHITELIST_LIVE,
} from "@/lib/edge-vocabulary";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type EdgeFilterClass =
  | "governance"
  | "money"
  | "legalConstrains"
  | "universal";

export type NodeFilters = Record<NodeType, boolean>;

export type EdgeFilters = Record<EdgeFilterClass, boolean>;

export type HopSlider = 1 | 2 | 3 | 4;

export type ExplorerState = {
  focus: string | null;
  hop: HopSlider;
  nodeFilters: NodeFilters;
  edgeFilters: EdgeFilters;
  /** ISO date (YYYY-MM-DD). */
  timeFrom: string;
  /** ISO date (YYYY-MM-DD). */
  timeTo: string;
  /** Loaded node ids — populated as the user expands. */
  loadedNodeIds: Set<string>;
  /**
   * Loaded edge "keys" — sorted tuple "a|b|relType" to dedupe
   * regardless of direction. The explorer renders edges undirected, so
   * (a, b, CAST_VOTE) and (b, a, CAST_VOTE) are the same logical edge.
   */
  loadedEdgeKeys: Set<string>;
};

// Minimal shape of a "neighbor from /api/expand" — this module only needs the
// id to merge into state. Callers are free to pass richer shapes (e.g., the
// NeighborRow from the expand route) — we read only the `.id`.
export type NeighborLike = { id: string };

export type EdgeLike = {
  source: string;
  target: string;
  type: string;
};

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

// Per spec §6.3 — usually-off node filters. Record/Place/Issue/AgendaItem are
// structural hubs; the focus-type waiver re-enables them when they're the
// focus.
const DEFAULT_OFF_TYPES: ReadonlySet<NodeType> = new Set<NodeType>([
  "Record",
  "Place",
  "Issue",
  "AgendaItem",
]);

function buildDefaultNodeFilters(): NodeFilters {
  const filters = {} as NodeFilters;
  for (const t of ALL_TYPES) {
    filters[t] = !DEFAULT_OFF_TYPES.has(t);
  }
  return filters;
}

function buildDefaultEdgeFilters(): EdgeFilters {
  return {
    governance: true,
    money: true,
    legalConstrains: true,
    universal: false,
  };
}

// ---------------------------------------------------------------------------
// Default time range — spec §5.4: last 5 years ending at ingestAt, with the
// earliest-event floor applied by mergeExpansion (widens left edge only).
// ---------------------------------------------------------------------------

const FIVE_YEARS_MS = 5 * 365 * 24 * 60 * 60 * 1000;

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function parseIsoDate(s: string): Date {
  // Append T00:00:00Z so the "YYYY-MM-DD" parse is interpreted as UTC
  // midnight, avoiding timezone-dependent off-by-one-day surprises.
  const d = new Date(s.length === 10 ? `${s}T00:00:00Z` : s);
  if (Number.isNaN(d.getTime())) {
    throw new Error(`Invalid ISO date: ${s}`);
  }
  return d;
}

/**
 * Compute the default `{from, to}` range for the explorer's time slider
 * per spec §5.4 — "last 5 years ending at ingestAt".
 *
 * The earliest-event floor is a separate concern; apply it via
 * `mergeExpansion` as the loaded subgraph grows.
 */
export function defaultTimeRange(ingestAt: string): { from: string; to: string } {
  const to = parseIsoDate(ingestAt);
  const from = new Date(to.getTime() - FIVE_YEARS_MS);
  return { from: toIsoDate(from), to: toIsoDate(to) };
}

// ---------------------------------------------------------------------------
// URL parsing / serializing
// ---------------------------------------------------------------------------

/**
 * Canonical URL param names. Kept in one place so a typo in one function
 * shows up immediately in the other (and in the tests).
 */
const URL_KEYS = {
  focus: "focus",
  hop: "hop",
  nodeFilters: "nodes",
  edgeFilters: "edges",
  timeFrom: "from",
  timeTo: "to",
} as const;

export function parseUrlToState(
  params: URLSearchParams,
  ingestAt: string,
): ExplorerState {
  const focus = params.get(URL_KEYS.focus)?.trim() || null;

  // Hop — clamp to 1..4 (default 2 per spec §6.3 Expand contract).
  const hopRaw = Number(params.get(URL_KEYS.hop) ?? "2");
  const hop = (
    Number.isInteger(hopRaw) && hopRaw >= 1 && hopRaw <= 4 ? hopRaw : 2
  ) as HopSlider;

  // Node filters — URL param is a comma-list of ENABLED node types. Absent
  // param means "use defaults." An explicit empty string means "all off."
  let nodeFilters: NodeFilters;
  const nodesParam = params.get(URL_KEYS.nodeFilters);
  if (nodesParam === null) {
    nodeFilters = buildDefaultNodeFilters();
  } else {
    const enabled = new Set(
      nodesParam
        .split(",")
        .map((s) => s.trim())
        .filter((s): s is NodeType => (ALL_TYPES as readonly string[]).includes(s)),
    );
    nodeFilters = {} as NodeFilters;
    for (const t of ALL_TYPES) {
      nodeFilters[t] = enabled.has(t);
    }
  }

  // Edge filters — URL param is a comma-list of ENABLED edge classes.
  let edgeFilters: EdgeFilters;
  const edgesParam = params.get(URL_KEYS.edgeFilters);
  if (edgesParam === null) {
    edgeFilters = buildDefaultEdgeFilters();
  } else {
    const enabled = new Set<string>(
      edgesParam
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    );
    edgeFilters = {
      governance: enabled.has("governance"),
      money: enabled.has("money"),
      legalConstrains: enabled.has("legalConstrains"),
      universal: enabled.has("universal"),
    };
  }

  // Time range — default per §5.4 when absent.
  const defaultRange = defaultTimeRange(ingestAt);
  const timeFrom = params.get(URL_KEYS.timeFrom) ?? defaultRange.from;
  const timeTo = params.get(URL_KEYS.timeTo) ?? defaultRange.to;

  return {
    focus,
    hop,
    nodeFilters,
    edgeFilters,
    timeFrom,
    timeTo,
    loadedNodeIds: new Set(focus ? [focus] : []),
    loadedEdgeKeys: new Set(),
  };
}

/**
 * Serialize ExplorerState to a URLSearchParams. Omits keys that match the
 * default so URLs stay short — "?focus=kate" instead of 6 redundant params.
 *
 * The default baseline is computed against `ingestAt` only when `timeFrom/To`
 * need it. Since `stateToUrl` doesn't have ingestAt, we simply keep the
 * time fields as they are — round-tripping through `parseUrlToState` with a
 * matching `ingestAt` reproduces them.
 */
export function stateToUrl(state: ExplorerState): URLSearchParams {
  const p = new URLSearchParams();
  if (state.focus) p.set(URL_KEYS.focus, state.focus);
  if (state.hop !== 2) p.set(URL_KEYS.hop, String(state.hop));

  // Node filters: only emit if they differ from default.
  const defaultNodes = buildDefaultNodeFilters();
  const nodeDiffers = ALL_TYPES.some((t) => state.nodeFilters[t] !== defaultNodes[t]);
  if (nodeDiffers) {
    const enabled = ALL_TYPES.filter((t) => state.nodeFilters[t]);
    p.set(URL_KEYS.nodeFilters, enabled.join(","));
  }

  // Edge filters: only emit if they differ from default.
  const defaultEdges = buildDefaultEdgeFilters();
  const edgeDiffers =
    state.edgeFilters.governance !== defaultEdges.governance ||
    state.edgeFilters.money !== defaultEdges.money ||
    state.edgeFilters.legalConstrains !== defaultEdges.legalConstrains ||
    state.edgeFilters.universal !== defaultEdges.universal;
  if (edgeDiffers) {
    const enabled: EdgeFilterClass[] = [];
    if (state.edgeFilters.governance) enabled.push("governance");
    if (state.edgeFilters.money) enabled.push("money");
    if (state.edgeFilters.legalConstrains) enabled.push("legalConstrains");
    if (state.edgeFilters.universal) enabled.push("universal");
    p.set(URL_KEYS.edgeFilters, enabled.join(","));
  }

  // Time range: always emit when focus exists — the user may want to share
  // a URL pinned to a specific time window.
  p.set(URL_KEYS.timeFrom, state.timeFrom);
  p.set(URL_KEYS.timeTo, state.timeTo);

  return p;
}

// ---------------------------------------------------------------------------
// mergeExpansion — fold /api/expand response into state
// ---------------------------------------------------------------------------

/**
 * Build the canonical undirected key for an edge — sorted (source, target)
 * joined with the relationship type. Two edges with the same endpoints +
 * rel type dedupe to one.
 */
export function edgeKey(edge: EdgeLike): string {
  const [a, b] = [edge.source, edge.target].sort();
  return `${a}|${b}|${edge.type}`;
}

export function mergeExpansion(
  state: ExplorerState,
  nodes: NeighborLike[],
  edges: EdgeLike[],
): ExplorerState {
  const loadedNodeIds = new Set(state.loadedNodeIds);
  for (const n of nodes) loadedNodeIds.add(n.id);

  const loadedEdgeKeys = new Set(state.loadedEdgeKeys);
  for (const e of edges) loadedEdgeKeys.add(edgeKey(e));

  return {
    ...state,
    loadedNodeIds,
    loadedEdgeKeys,
  };
}

// ---------------------------------------------------------------------------
// autoEnableFiltersForFocus — §6.3 waiver
// ---------------------------------------------------------------------------

/**
 * Per spec §6.3: when the focus is a usually-off type, auto-enable the
 * corresponding node filter (and the universal edge class when the focus is
 * Record/Place/Issue — since those types' only reliable edges are the
 * universals).
 */
export function autoEnableFiltersForFocus(
  state: ExplorerState,
  focusType: NodeType,
): ExplorerState {
  // Copy the filters — don't mutate.
  const nodeFilters: NodeFilters = { ...state.nodeFilters };
  const edgeFilters: EdgeFilters = { ...state.edgeFilters };

  if (DEFAULT_OFF_TYPES.has(focusType)) {
    nodeFilters[focusType] = true;
  }

  // The three types that depend on universal edges get the universal
  // edge-filter enabled. AgendaItem doesn't — its PART_OF edge is already
  // inside the Phase-2 whitelist.
  if (focusType === "Record" || focusType === "Place" || focusType === "Issue") {
    edgeFilters.universal = true;
  }

  return { ...state, nodeFilters, edgeFilters };
}

// ---------------------------------------------------------------------------
// Edge-class derivation — maps the 4 edge-filter classes onto concrete live
// edge names so /api/expand can enforce the filter at the traversal level.
// ---------------------------------------------------------------------------

/**
 * The subset of PHASE2_WHITELIST_LIVE that the "governance" edge class owns —
 * i.e., the whitelist minus the edges classified under "money" or
 * "legal-constrains" styles. These are the edges that get traversal-excluded
 * when the user toggles the "governance" edge chip OFF.
 *
 * Kept as a derived constant (not re-derived per call) so the invariant
 * "governance ∪ money ∪ legal-constrains = whitelist" is visible at module
 * load time.
 */
export const GOVERNANCE_EDGES_LIVE: string[] = PHASE2_WHITELIST_LIVE.filter(
  (e) => !MONEY_EDGES_LIVE.includes(e) && !LEGAL_EDGES_LIVE.includes(e),
);

/**
 * Given the current edgeFilters state, compute the list of live edge names
 * that must be excluded from the /api/expand traversal relationship list.
 *
 * Rules:
 *   - governance OFF → exclude GOVERNANCE_EDGES_LIVE
 *   - money OFF      → exclude MONEY_EDGES_LIVE
 *   - legalConstrains OFF → exclude LEGAL_EDGES_LIVE
 *
 * The "universal" class is not excluded here; it's a positive-add (see
 * `includeUniversalsForState`) because PHASE2_WHITELIST_LIVE doesn't include
 * the universals by default.
 */
export function edgeClassificationExcludes(state: ExplorerState): string[] {
  const excludes = new Set<string>();
  if (!state.edgeFilters.governance) {
    for (const e of GOVERNANCE_EDGES_LIVE) excludes.add(e);
  }
  if (!state.edgeFilters.money) {
    for (const e of MONEY_EDGES_LIVE) excludes.add(e);
  }
  if (!state.edgeFilters.legalConstrains) {
    for (const e of LEGAL_EDGES_LIVE) excludes.add(e);
  }
  return Array.from(excludes);
}

/**
 * Mirror of the UI's "include universal edges" toggle — returns the value of
 * `state.edgeFilters.universal`. Kept as a named helper so it can be
 * imported alongside `edgeClassificationExcludes` wherever expand URLs are
 * constructed.
 */
export function includeUniversalsForState(state: ExplorerState): boolean {
  return state.edgeFilters.universal;
}

// ---------------------------------------------------------------------------
// Time-range widening — spec §5.4 "earliest loaded event floor"
// ---------------------------------------------------------------------------

/**
 * Widen `state.timeFrom` to cover the earliest event_date among the provided
 * loaded nodes. If no loaded node has an event_date earlier than the current
 * `timeFrom`, the state is returned unchanged.
 *
 * Callers pass the per-node event dates keyed by id (or as a flat array). This
 * module does not reach into Cytoscape — the client is expected to collect
 * the relevant date props from its canvas and hand them in.
 *
 * Per spec §5.4: "last 5 years from ingest, floored by earliest loaded event."
 * The right edge (`timeTo`) is never mutated by this helper.
 */
export function widenTimeRangeForLoadedSubgraph(
  state: ExplorerState,
  eventDates: Iterable<string | null | undefined>,
): ExplorerState {
  let earliest: string | null = null;
  for (const raw of eventDates) {
    if (!raw) continue;
    const d = raw.slice(0, 10);
    if (d.length !== 10) continue;
    if (earliest === null || d < earliest) earliest = d;
  }
  if (earliest === null) return state;
  if (earliest >= state.timeFrom) return state;
  return { ...state, timeFrom: earliest };
}
