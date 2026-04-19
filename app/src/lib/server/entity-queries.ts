// Cypher string builders for the entity-page radial hero (§5.1.1).
//
// Two builder families:
// - buildMustShowQuery(focusType): UNION ALL of per-relationship patterns for
//   the focus type's must-show contract (§5.1.1 must-show table).
// - buildPhase2FillQuery(focusType): UNION ALL of 11 per-type sub-queries with
//   quotas and ranking keys from the §5.1.1 Phase-2 table.
//
// Both consume live relationship names via specEdges(...) → SPEC_TO_LIVE so any
// change to the live edge catalog lands here automatically. Hard-coding live
// edge names would be a drift risk.
//
// The returned strings are parameterized:
// - $focus_id: canonical node id (e.g., "person-kate-colin")
// - $must_show_ids: string[] — ids returned by Query 1 (Phase-2 only)
// - $cap: number — aggregate node cap (default 40)
// - $must_show_count: number — must_show_ids.length (Phase-2 only)

import "server-only";
import { PHASE2_WHITELIST_LIVE, specToLive } from "@/lib/edge-vocabulary";
import type { NodeType } from "@/lib/type-display";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MustShowRow = {
  id: string;
  type: NodeType;
  label: string;
  ring: 1 | 2 | 3;
  relationship: string; // the live edge (or composite path tag) that admitted this node
};

export type Phase2Row = {
  id: string;
  type: NodeType;
  label: string;
  ring: 1 | 2;
  rank_value: number | null;
};

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Pipe-joined live edge string for a Cypher relationship-type list, given spec §3 names. */
function specEdges(...names: string[]): string {
  const all = names.flatMap((n) => specToLive(n));
  const unique = Array.from(new Set(all));
  if (unique.length === 0) {
    // All-empty (e.g., CONSTRAINS alone). Return a known-impossible type so the
    // pattern still parses but matches nothing — safer than an empty ":" list
    // which is a Cypher syntax error.
    return "__NO_LIVE_EDGE__";
  }
  return unique.join("|");
}

/** PHASE2_WHITELIST_LIVE as a pipe-separated pattern for relationship-type lists. */
const PHASE2_PATTERN = PHASE2_WHITELIST_LIVE.join("|");

/** Shared projection tail — turns a node `n` into `{id, type, label, ring, relationship}`. */
function projectMustShow(nodeVar: string, ringExpr: string, relExpr: string): string {
  return `
  RETURN DISTINCT ${nodeVar}.id AS id,
    labels(${nodeVar}) AS labels,
    coalesce(${nodeVar}.search_label, ${nodeVar}.name, ${nodeVar}.id) AS label,
    ${ringExpr} AS ring,
    ${relExpr} AS relationship`;
}

// ---------------------------------------------------------------------------
// Per-type must-show builders
// ---------------------------------------------------------------------------

function buildPersonMustShow(): string {
  // All spec names resolve as follows (Batch A mapping):
  //   HELD_BY        → HELD_BY
  //   FOR_SEAT       → FOR_SEAT
  //   CONTROLLED_BY  → CONTROLLED_BY, CONTROLLED_BY_COMMITTEE
  //   BY_PERSON      → CANDIDATE_ACTOR
  //   PARTY_TO       → PARTY_TO
  //   AT_INSTITUTION → AT_INSTITUTION
  return `
// SeatService via inverse HELD_BY (ring 1)
MATCH (f:Person {id: $focus_id})<-[:${specEdges("HELD_BY")}]-(n:SeatService)
${projectMustShow("n", "1", "'HELD_BY'")}

UNION

// Seat via SeatService-FOR_SEAT (ring 2 — 2-hop through SeatService)
MATCH (f:Person {id: $focus_id})<-[:${specEdges("HELD_BY")}]-(:SeatService)-[:${specEdges("FOR_SEAT")}]->(n:Seat)
${projectMustShow("n", "2", "'FOR_SEAT'")}

UNION

// Committee via inverse CONTROLLED_BY (ring 1)
MATCH (f:Person {id: $focus_id})<-[:${specEdges("CONTROLLED_BY")}]-(n:Committee)
${projectMustShow("n", "1", "'CONTROLLED_BY'")}

UNION

// Candidacy via inverse BY_PERSON (ring 1)
MATCH (f:Person {id: $focus_id})<-[:${specEdges("BY_PERSON")}]-(n:Candidacy)
${projectMustShow("n", "1", "'BY_PERSON'")}

UNION

// Case via PARTY_TO (ring 1 — direction intentionally undirected; PARTY_TO
// points Person→Case in live graph, but an undirected match is the safe default).
MATCH (f:Person {id: $focus_id})-[:${specEdges("PARTY_TO")}]-(n:Case)
${projectMustShow("n", "1", "'PARTY_TO'")}

UNION

// Organization via 3-hop Person→SeatService→Seat→Organization (ring 3 — the
// only 3-hop must-show in the contract, per §5.1.1).
MATCH (f:Person {id: $focus_id})<-[:${specEdges("HELD_BY")}]-(:SeatService)-[:${specEdges("FOR_SEAT")}]->(:Seat)-[:${specEdges("AT_INSTITUTION")}]->(n)
WHERE n:Organization OR n:Government
${projectMustShow("n", "3", "'AT_INSTITUTION'")}
`;
}

function buildDecisionMustShow(): string {
  // AT_MEETING → AT_MEETING, DECIDED_AT
  // ABOUT_ITEM → ABOUT_AGENDA_ITEM
  // DECIDED_BY → DECIDED_BY
  // CAST_VOTE  → CAST_VOTE
  // ABOUT_PROJECT → RELATES_TO_PROJECT (weak-family collapse)
  // ABOUT_PROGRAM → RELATES_TO_PROGRAM
  // CONSTRAINS → [] (not materialized — returns nothing)
  return `
MATCH (f:Decision {id: $focus_id})-[:${specEdges("AT_MEETING")}]->(n:Meeting)
${projectMustShow("n", "1", "'AT_MEETING'")}

UNION

MATCH (f:Decision {id: $focus_id})-[:${specEdges("ABOUT_ITEM")}]->(n:AgendaItem)
${projectMustShow("n", "1", "'ABOUT_AGENDA_ITEM'")}

UNION

MATCH (f:Decision {id: $focus_id})-[:${specEdges("DECIDED_BY")}]->(n)
WHERE n:Organization OR n:Government
${projectMustShow("n", "1", "'DECIDED_BY'")}

UNION

MATCH (f:Decision {id: $focus_id})<-[:${specEdges("CAST_VOTE")}]-(n:Person)
${projectMustShow("n", "1", "'CAST_VOTE'")}

UNION

MATCH (f:Decision {id: $focus_id})-[:${specEdges("ABOUT_PROJECT")}]->(n:Project)
${projectMustShow("n", "1", "'ABOUT_PROJECT'")}

UNION

MATCH (f:Decision {id: $focus_id})-[:${specEdges("ABOUT_PROGRAM")}]->(n:Program)
${projectMustShow("n", "1", "'ABOUT_PROGRAM'")}

UNION

// Case via inverse CONSTRAINS. CONSTRAINS is not yet materialized in the
// live graph (spec §3 notes this) — the __NO_LIVE_EDGE__ token ensures the
// pattern still parses but never matches until ingestion lands.
MATCH (f:Decision {id: $focus_id})<-[:${specEdges("CONSTRAINS")}]-(n:Case)
${projectMustShow("n", "1", "'CONSTRAINS'")}
`;
}

function buildProjectMustShow(): string {
  // FOR_PROJECT → RELATES_TO_PROJECT (weak-family collapse)
  // AMENDS      → AMENDS_AGREEMENT
  // ABOUT_PROJECT → RELATES_TO_PROJECT
  // ABOUT_PROGRAM → RELATES_TO_PROGRAM
  return `
// Agreement via inverse FOR_PROJECT (ring 1)
MATCH (f:Project {id: $focus_id})<-[:${specEdges("FOR_PROJECT")}]-(n:Agreement)
${projectMustShow("n", "1", "'FOR_PROJECT'")}

UNION

// Amendment via inverse AMENDS — 2-hop via Agreement (ring 2)
MATCH (f:Project {id: $focus_id})<-[:${specEdges("FOR_PROJECT")}]-(:Agreement)<-[:${specEdges("AMENDS")}]-(n:Amendment)
${projectMustShow("n", "2", "'AMENDS'")}

UNION

// Decision via inverse ABOUT_PROJECT (ring 1)
MATCH (f:Project {id: $focus_id})<-[:${specEdges("ABOUT_PROJECT")}]-(n:Decision)
${projectMustShow("n", "1", "'ABOUT_PROJECT'")}

UNION

// Program via 2-hop (Project)<-(Decision)-(Program) (ring 2)
MATCH (f:Project {id: $focus_id})<-[:${specEdges("ABOUT_PROJECT")}]-(:Decision)-[:${specEdges("ABOUT_PROGRAM")}]->(n:Program)
${projectMustShow("n", "2", "'ABOUT_PROGRAM'")}
`;
}

function buildProgramMustShow(): string {
  return `
// Decision via inverse ABOUT_PROGRAM (ring 1)
MATCH (f:Program {id: $focus_id})<-[:${specEdges("ABOUT_PROGRAM")}]-(n:Decision)
${projectMustShow("n", "1", "'ABOUT_PROGRAM'")}

UNION

// Project via 2-hop (Program)<-(Decision)-(Project) (ring 2)
MATCH (f:Program {id: $focus_id})<-[:${specEdges("ABOUT_PROGRAM")}]-(:Decision)-[:${specEdges("ABOUT_PROJECT")}]->(n:Project)
${projectMustShow("n", "2", "'ABOUT_PROJECT'")}

UNION

// Case via 2-hop (Program)<-(Decision)<-(Case) via CONSTRAINS (ring 2 —
// empty until CONSTRAINS materializes).
MATCH (f:Program {id: $focus_id})<-[:${specEdges("ABOUT_PROGRAM")}]-(:Decision)<-[:${specEdges("CONSTRAINS")}]-(n:Case)
${projectMustShow("n", "2", "'CONSTRAINS'")}
`;
}

function buildCaseMustShow(): string {
  // PART_OF → PART_OF_MEETING, PART_OF_CASE (we only need PART_OF_CASE here, but
  // the relationship-type list allows both — the :Proceeding label constrains
  // the match.)
  // HEARD_IN → HEARD_IN, HEARD_BY
  // PARTY_TO → PARTY_TO
  // CONSTRAINS → [] (empty until materialized)
  return `
// Proceeding via inverse PART_OF (PART_OF_CASE) (ring 1)
MATCH (f:Case {id: $focus_id})<-[:${specEdges("PART_OF")}]-(n:Proceeding)
${projectMustShow("n", "1", "'PART_OF_CASE'")}

UNION

// Court (Organization:Court) via HEARD_IN (ring 1)
MATCH (f:Case {id: $focus_id})-[:${specEdges("HEARD_IN")}]->(n)
WHERE n:Organization OR n:Court
${projectMustShow("n", "1", "'HEARD_IN'")}

UNION

// Person/Organization via inverse PARTY_TO (ring 1)
MATCH (f:Case {id: $focus_id})<-[:${specEdges("PARTY_TO")}]-(n)
WHERE n:Person OR n:Organization
${projectMustShow("n", "1", "'PARTY_TO'")}

UNION

// Decision via CONSTRAINS (ring 1 — empty until CONSTRAINS materializes)
MATCH (f:Case {id: $focus_id})-[:${specEdges("CONSTRAINS")}]->(n:Decision)
${projectMustShow("n", "1", "'CONSTRAINS'")}
`;
}

function buildMeetingMustShow(): string {
  return `
// Organization via AT_INSTITUTION (ring 1)
MATCH (f:Meeting {id: $focus_id})-[:${specEdges("AT_INSTITUTION")}]->(n)
WHERE n:Organization OR n:Government
${projectMustShow("n", "1", "'AT_INSTITUTION'")}

UNION

// AgendaItem via inverse PART_OF (PART_OF_MEETING) (ring 1)
MATCH (f:Meeting {id: $focus_id})<-[:${specEdges("PART_OF")}]-(n:AgendaItem)
${projectMustShow("n", "1", "'PART_OF_MEETING'")}

UNION

// Decision via inverse AT_MEETING (ring 1)
MATCH (f:Meeting {id: $focus_id})<-[:${specEdges("AT_MEETING")}]-(n:Decision)
${projectMustShow("n", "1", "'AT_MEETING'")}
`;
}

function buildFilingMustShow(): string {
  // FILED_BY → FILED_BY, FILED_BY_COMMITTEE, OFFICIAL_FILER
  // FOR_ELECTION → FOR_ELECTION
  // DISCLOSED_IN → DISCLOSED_IN_FILING
  return `
// Person or Committee via FILED_BY (ring 1)
MATCH (f:Filing {id: $focus_id})-[:${specEdges("FILED_BY")}]->(n)
WHERE n:Person OR n:Committee
${projectMustShow("n", "1", "'FILED_BY'")}

UNION

// Election via FOR_ELECTION (ring 1)
MATCH (f:Filing {id: $focus_id})-[:${specEdges("FOR_ELECTION")}]->(n:Election)
${projectMustShow("n", "1", "'FOR_ELECTION'")}

UNION

// MoneyFlow via inverse DISCLOSED_IN (ring 1)
MATCH (f:Filing {id: $focus_id})<-[:${specEdges("DISCLOSED_IN")}]-(n:MoneyFlow)
${projectMustShow("n", "1", "'DISCLOSED_IN_FILING'")}
`;
}

function buildCommitteeMustShow(): string {
  return `
// Person via CONTROLLED_BY (ring 1)
MATCH (f:Committee {id: $focus_id})-[:${specEdges("CONTROLLED_BY")}]->(n:Person)
${projectMustShow("n", "1", "'CONTROLLED_BY'")}

UNION

// Filing via inverse FILED_BY (ring 1 — where filing points at this committee)
MATCH (f:Committee {id: $focus_id})<-[:${specEdges("FILED_BY")}]-(n:Filing)
${projectMustShow("n", "1", "'FILED_BY'")}
`;
}

// ---------------------------------------------------------------------------
// Public builders
// ---------------------------------------------------------------------------

export function buildMustShowQuery(focusType: NodeType): string {
  switch (focusType) {
    case "Person":
      return buildPersonMustShow();
    case "Decision":
      return buildDecisionMustShow();
    case "Project":
      return buildProjectMustShow();
    case "Program":
      return buildProgramMustShow();
    case "Case":
      return buildCaseMustShow();
    case "Meeting":
      return buildMeetingMustShow();
    case "Filing":
      return buildFilingMustShow();
    case "Committee":
      return buildCommitteeMustShow();
    default:
      throw new Error(`Unsupported Tier 1 focus type: ${focusType}`);
  }
}

// ---------------------------------------------------------------------------
// Phase-2 fill — same UNION ALL for every Tier 1 focus type. The per-type
// quotas, ranking keys, and tie-breaks come straight from §5.1.1's table.
// ---------------------------------------------------------------------------

// Quota table (§5.1.1), in type-priority order (top row drops last under the
// aggregate cap):
//   1. MoneyFlow     — 8, amount DESC, flow_date DESC, id ASC
//   2. Decision      — 8, decided_at DESC, id ASC
//   3. Filing        — 6, signed_at DESC, id ASC
//   4. Meeting       — 6, meeting_date DESC, id ASC
//   5. Person        — 6, edges_to_must_show DESC, id ASC
//   6. Organization  — 4, edges_to_must_show DESC, id ASC
//   7. AgendaItem    — 4, item_number ASC, id ASC
//   8. Amendment     — 2, effective_date DESC, id ASC
//   9. Proceeding    — 4, date DESC, id ASC
//  10. Election      — 2, election_date DESC, id ASC
//  11. Candidacy     — 2, id ASC (linked Election.election_date DESC deferred —
//                       requires sub-query; id ASC is the locked tie-break)

type Phase2SubSpec = {
  /** Cypher node label to anchor on (e.g., `"MoneyFlow"`). */
  typeLabel: string;
  /** Literal type string returned in `type` column (e.g., `'MoneyFlow'`). */
  typeLiteral: string;
  /** Priority — lower numbers survive aggregate cap truncation. */
  typePriority: number;
  /** ORDER BY clause (without the leading `ORDER BY`). */
  orderBy: string;
  /** Per-type LIMIT. */
  limit: number;
  /**
   * Cypher expression for `rank_value` in the projection. Usually the first
   * sort key (e.g., `c.amount`). For Person/Organization sub-queries this is
   * `edges_to_must_show` (the derived count from the OPTIONAL MATCH step).
   */
  rankValueExpr: string;
  /**
   * Optional extra clause inserted between the anchor MATCH and the RETURN.
   * Used by Person/Organization to count edges into the must-show set.
   */
  extraClause?: string;
};

function phase2Sub(spec: Phase2SubSpec): string {
  // The 2-hop MATCH can return the same `c` multiple times (multiple paths).
  // We dedupe via `WITH DISTINCT c` BEFORE the aggregation / EXISTS step so:
  //   1. The EXISTS subquery can reference `c` (allowed before DISTINCT is
  //      applied at the outer level).
  //   2. The ORDER BY clause in RETURN can reference `c.*` properties because
  //      we omit DISTINCT from the RETURN (already deduped upstream).
  //
  // For Person/Organization, the OPTIONAL MATCH + count aggregation is what
  // actually guarantees one row per c (count(r) collapses duplicates), so
  // the `WITH DISTINCT c` becomes redundant but harmless.
  const extra = spec.extraClause ?? "";
  const dedupStep = extra
    ? "" // aggregation in `extra` already produces one row per c
    : "\n  WITH DISTINCT c, focus_id, must_show_ids";
  return `
  WITH $focus_id AS focus_id, $must_show_ids AS must_show_ids
  MATCH (f {id: focus_id})-[:${PHASE2_PATTERN}*1..2]-(c:${spec.typeLabel})
  WHERE c.id <> $focus_id AND NOT c.id IN $must_show_ids${dedupStep}
  ${extra}
  RETURN c.id AS id,
    labels(c) AS labels,
    coalesce(c.search_label, c.name, c.id) AS label,
    '${spec.typeLiteral}' AS type,
    CASE WHEN EXISTS { MATCH ({id: focus_id})-[:${PHASE2_PATTERN}]-(c) } THEN 1 ELSE 2 END AS ring,
    ${spec.rankValueExpr} AS rank_value,
    ${spec.typePriority} AS type_priority
  ORDER BY ${spec.orderBy}
  LIMIT ${spec.limit}`;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function buildPhase2FillQuery(focusType: NodeType): string {
  // focusType is currently unused — the §5.1.1 quota table is not per-focus-type.
  // Keep the parameter so the signature matches buildMustShowQuery and so a
  // future per-focus specialization (e.g., suppress Person quota when focus is
  // Person) can land without an API change.

  // Person/Organization need an OPTIONAL MATCH step to count edges into the
  // must-show set — the "edges back into must-show" centrality substitute
  // locked by §5.1.1's Person/Organization ranking metric.
  const edgesToMustShow = `
  OPTIONAL MATCH (c)-[r]-(m) WHERE m.id IN must_show_ids
  WITH c, count(r) AS edges_to_must_show, focus_id, must_show_ids`;

  const subs: Phase2SubSpec[] = [
    {
      typeLabel: "MoneyFlow",
      typeLiteral: "MoneyFlow",
      typePriority: 1,
      orderBy: "c.amount DESC, c.flow_date DESC, c.id ASC",
      limit: 8,
      rankValueExpr: "c.amount",
    },
    {
      typeLabel: "Decision",
      typeLiteral: "Decision",
      typePriority: 2,
      orderBy: "c.decided_at DESC, c.id ASC",
      limit: 8,
      rankValueExpr: "c.decided_at",
    },
    {
      typeLabel: "Filing",
      typeLiteral: "Filing",
      typePriority: 3,
      orderBy: "c.signed_at DESC, c.id ASC",
      limit: 6,
      rankValueExpr: "c.signed_at",
    },
    {
      typeLabel: "Meeting",
      typeLiteral: "Meeting",
      typePriority: 4,
      orderBy: "c.meeting_date DESC, c.id ASC",
      limit: 6,
      rankValueExpr: "c.meeting_date",
    },
    {
      typeLabel: "Person",
      typeLiteral: "Person",
      typePriority: 5,
      orderBy: "edges_to_must_show DESC, c.id ASC",
      limit: 6,
      rankValueExpr: "edges_to_must_show",
      extraClause: edgesToMustShow,
    },
    {
      typeLabel: "Organization",
      typeLiteral: "Organization",
      typePriority: 6,
      orderBy: "edges_to_must_show DESC, c.id ASC",
      limit: 4,
      rankValueExpr: "edges_to_must_show",
      extraClause: edgesToMustShow,
    },
    {
      typeLabel: "AgendaItem",
      typeLiteral: "AgendaItem",
      typePriority: 7,
      orderBy: "c.item_number ASC, c.id ASC",
      limit: 4,
      rankValueExpr: "c.item_number",
    },
    {
      typeLabel: "Amendment",
      typeLiteral: "Amendment",
      typePriority: 8,
      orderBy: "c.effective_date DESC, c.id ASC",
      limit: 2,
      rankValueExpr: "c.effective_date",
    },
    {
      typeLabel: "Proceeding",
      typeLiteral: "Proceeding",
      typePriority: 9,
      orderBy: "c.date DESC, c.id ASC",
      limit: 4,
      rankValueExpr: "c.date",
    },
    {
      typeLabel: "Election",
      typeLiteral: "Election",
      typePriority: 10,
      orderBy: "c.election_date DESC, c.id ASC",
      limit: 2,
      rankValueExpr: "c.election_date",
    },
    {
      typeLabel: "Candidacy",
      typeLiteral: "Candidacy",
      typePriority: 11,
      orderBy: "c.id ASC",
      limit: 2,
      rankValueExpr: "c.id",
    },
  ];

  const body = subs.map((s) => phase2Sub(s)).join("\nUNION ALL\n");

  return `CALL {
${body}
}
RETURN id, labels, label, type, ring, rank_value, type_priority
ORDER BY type_priority ASC
`;
}

// ---------------------------------------------------------------------------
// Edges-among-selected — once Query 1 and Query 2 produce the selection set,
// fetch every whitelisted edge between any two selected nodes for rendering.
// ---------------------------------------------------------------------------

export function buildEdgesAmongSelectedQuery(): string {
  return `
MATCH (a)-[r]-(b)
WHERE a.id IN $ids AND b.id IN $ids AND a.id < b.id
  AND type(r) IN $whitelist
RETURN DISTINCT a.id AS source, b.id AS target, type(r) AS rel_type,
  startNode(r).id AS start_id, endNode(r).id AS end_id
`;
}

// ---------------------------------------------------------------------------
// Tier 2 — simple 1-hop neighborhood along whitelist, cap 40.
// ---------------------------------------------------------------------------

export function buildTier2NeighborhoodQuery(): string {
  return `
MATCH (f {id: $focus_id})-[r:${PHASE2_PATTERN}]-(n)
WHERE NOT n:Place AND NOT n:Issue AND n.id <> $focus_id
RETURN DISTINCT n.id AS id,
  labels(n) AS labels,
  coalesce(n.search_label, n.name, n.id) AS label,
  1 AS ring,
  type(r) AS relationship,
  startNode(r).id AS start_id,
  endNode(r).id AS end_id
LIMIT 40
`;
}
