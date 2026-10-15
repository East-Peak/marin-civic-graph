// The public properties of a relationship (registry/edge-properties.json). Both serving modes pass every edge's
// properties through sanitizeEdgeProps, so a payload carries only allowlisted, in-vocabulary values; anything else is
// dropped and counted (counts only — never a value, never an unlisted property's name). An edge with no public
// property has no `props` key at all: undefined is the one "no property" form. Several relationships for one
// (start, type, end) keep their public props only when they all agree; disagreeing duplicates show none (and are
// counted) rather than an arbitrary one — the same rule the bake applies (scripts/public_edge_props.py).

import { EDGE_PROPERTY_ALLOWLIST } from "@/lib/edge-properties.generated";

type Allowlist = typeof EDGE_PROPERTY_ALLOWLIST;

export type Vote = Allowlist["CAST_VOTE"]["vote"][number];

export type EdgeProps = {
  -readonly [Prop in keyof Allowlist[keyof Allowlist]]?: Allowlist[keyof Allowlist][Prop][number];
};

export type EdgePropStats = {
  dropped_out_of_vocabulary: number;
  dropped_non_allowlisted: number;
  suppressed_conflicting_duplicates: number;
};

export function newEdgePropStats(): EdgePropStats {
  return { dropped_out_of_vocabulary: 0, dropped_non_allowlisted: 0, suppressed_conflicting_duplicates: 0 };
}

/** One aggregate line for a log, or null when nothing was dropped. Counts only. */
export function describeDroppedEdgeProps(stats: EdgePropStats): string | null {
  const { dropped_out_of_vocabulary: oov, dropped_non_allowlisted: unlisted, suppressed_conflicting_duplicates: dup } =
    stats;
  if (oov === 0 && unlisted === 0 && dup === 0) return null;
  return `${oov} out-of-vocabulary, ${unlisted} non-allowlisted, ${dup} conflicting duplicate(s)`;
}

const ALLOWLIST: Readonly<Record<string, Readonly<Record<string, readonly string[]>>>> = EDGE_PROPERTY_ALLOWLIST;

export function carriesEdgeProps(rel: string): boolean {
  return Object.hasOwn(ALLOWLIST, rel);
}

function stableKey(props: EdgeProps | undefined): string {
  return props === undefined ? "" : JSON.stringify(props, Object.keys(props).sort());
}

export function sameEdgeProps(a: EdgeProps | undefined, b: EdgeProps | undefined): boolean {
  return stableKey(a) === stableKey(b);
}

export function sanitizeEdgeProps(rel: string, raw: unknown, stats?: EdgePropStats): EdgeProps | undefined {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const allowed = Object.hasOwn(ALLOWLIST, rel) ? ALLOWLIST[rel] : {};
  const kept: Record<string, string> = {};
  for (const [prop, value] of Object.entries(raw)) {
    if (value === null || value === undefined) continue; // Neo4j cannot store null: it means "not set".
    if (!Object.hasOwn(allowed, prop)) {
      if (stats) stats.dropped_non_allowlisted += 1;
    } else if (typeof value === "string" && allowed[prop].includes(value)) {
      kept[prop] = value;
    } else if (stats) {
      stats.dropped_out_of_vocabulary += 1;
    }
  }
  return Object.keys(kept).length > 0 ? (kept as EdgeProps) : undefined;
}

/** Cypher projecting each allowlisted property explicitly, per relationship type — never properties(r). */
export function edgePropsProjection(relVar: string): string {
  if (!/^[a-z][a-z_]*$/.test(relVar)) throw new Error(`edgePropsProjection: bad variable ${relVar}`);
  const branches = Object.entries(ALLOWLIST).map(([rel, props]) => {
    const fields = Object.keys(props).map((prop) => `${prop}: ${relVar}.${prop}`);
    return `WHEN '${rel}' THEN {${fields.join(", ")}}`;
  });
  return `CASE type(${relVar}) ${branches.join(" ")} ELSE null END`;
}

/** What a connection card says about a vote. Absent and recused members did not vote, and the label says so. */
export const VOTE_LABEL: Record<Vote, string> = {
  aye: "voted aye",
  no: "voted no",
  abstain: "abstained",
  absent: "absent",
  recused: "recused",
};
