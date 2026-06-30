// Pure-logic tests for the Identity Attach Workbench bench (Slice 3). The bench's
// queue bucketing, bulk gating (incl. the graph collision filter), decision→status
// mapping, and display helpers are extracted to a React-free module so they can be
// TDD'd directly. The interactive component is covered in bench.test.tsx.
import { describe, it, expect } from "vitest";
import {
  usd,
  proposedKey,
  displayName,
  moneyOf,
  statusAfter,
  clientBulkEligible,
  bucketOf,
  bucketize,
  aiVerdictOf,
  isNameExact,
  applyControls,
  investigationLinks,
  DEFAULT_CONTROLS,
  type BenchRow,
  type QueueControls,
} from "../../../operator-workbench-src/_lib/bench-logic";
import type { Case, ContextEntry } from "../../../operator-workbench-src/_lib/bench-types";

type CaseOver = Partial<Case> & {
  vendor?: string;
  src?: string;
  key?: string;
  name?: string;
  regName?: string;
  city?: string;
  signals?: string[];
  aiVerdict?: string;
  aiConf?: number;
};

function mkCase(over: CaseOver = {}): Case {
  const vendor = over.vendor ?? "org-county-vendor-1";
  const src = over.src ?? "ein";
  const keyField = src === "ein" ? "registry_ein" : "sos_id";
  const pubFields: Record<string, unknown> = { [keyField]: over.key ?? "123456789" };
  if (over.city) pubFields.principal_city = over.city;
  return {
    case_id: over.case_id ?? `attach|anchor-1|${vendor}`,
    candidate_joins: over.candidate_joins ?? [
      {
        left_ref: { source_id: src, local_id: vendor, display_label: over.name ?? "RAW VENDOR NAME", public_fields: {} },
        right_ref: {
          source_id: src,
          local_id: "anchor-1",
          display_label: over.regName ?? "Registry Name",
          public_fields: pubFields,
        },
        signals: over.signals ?? ["normalized_name_exact"],
        signal_strength: 0.95,
      },
    ],
    ai_reviews: over.ai_reviews ?? [
      { verdict: over.aiVerdict ?? "same", reason: "exact name + key", signal_strength: over.aiConf ?? 0.97 },
    ],
    current_ledger_status: over.current_ledger_status ?? "none",
    bulk_eligible: over.bulk_eligible ?? false,
    review_flags: over.review_flags ?? {},
  };
}

function mkCtx(over: Partial<ContextEntry> = {}): ContextEntry {
  return {
    display_label: "10,000 Degrees",
    money_total: 19285,
    flow_count: 3,
    departments: ["Cultural Services"],
    key_collision: false,
    collides_with: [],
    ...over,
  };
}

function row(c: Case, displayStatus?: string): BenchRow {
  return { ...c, displayStatus: displayStatus ?? c.current_ledger_status };
}

describe("usd", () => {
  it("formats whole dollars with grouping", () => {
    expect(usd(19285)).toBe("$19,285");
    expect(usd(0)).toBe("$0");
    expect(usd(1834.7)).toBe("$1,835");
  });
});

describe("proposedKey", () => {
  it("reads the registry_ein for an ein lane", () => {
    expect(proposedKey(mkCase({ src: "ein", key: "94-3041517" }))).toBe("94-3041517");
  });
  it("reads the sos_id for an sos lane", () => {
    expect(proposedKey(mkCase({ src: "sos_id", key: "C1234567" }))).toBe("C1234567");
  });
  it("falls back to em-dash when the key field is absent", () => {
    const c = mkCase();
    c.candidate_joins[0].right_ref.public_fields = {};
    expect(proposedKey(c)).toBe("—");
  });
});

describe("displayName", () => {
  it("prefers the graph display_label", () => {
    expect(displayName(mkCase(), mkCtx({ display_label: "Real Name Inc" }))).toBe("Real Name Inc");
  });
  it("falls back to the raw vendor ref label when context is missing", () => {
    expect(displayName(mkCase(), undefined)).toBe("RAW VENDOR NAME");
  });
  it("falls back when the graph label is null", () => {
    expect(displayName(mkCase(), mkCtx({ display_label: null }))).toBe("RAW VENDOR NAME");
  });
});

describe("moneyOf", () => {
  it("returns the context money_total", () => {
    expect(moneyOf(mkCase(), { "org-county-vendor-1": mkCtx({ money_total: 5000 }) })).toBe(5000);
  });
  it("returns -1 when there is no context (sorts to the bottom)", () => {
    expect(moneyOf(mkCase(), {})).toBe(-1);
  });
});

describe("statusAfter", () => {
  it("uses the server assertion status on approve", () => {
    expect(statusAfter("approve", undefined, { result: "created", assertion: { status: "approved" }, same_as: {} })).toBe("approved");
  });
  it("defaults approve to approved when no assertion is returned", () => {
    expect(statusAfter("approve", undefined, { result: "created", assertion: null, same_as: null })).toBe("approved");
  });
  it("maps reject current_evidence", () => {
    expect(statusAfter("reject", "current_evidence", { result: "created", assertion: { status: "rejected_current_evidence" }, same_as: null })).toBe("rejected_current_evidence");
  });
  it("derives reject entity_distinct even with no assertion echoed", () => {
    expect(statusAfter("reject", "entity_distinct", { result: "created", assertion: null, same_as: null })).toBe("rejected_entity_distinct");
  });
  it("marks unsure as a session skip", () => {
    expect(statusAfter("unsure", undefined, { result: "unsure", assertion: null, same_as: null })).toBe("unsure");
  });
  it("ignores an unknown echoed status and falls back to the derived one", () => {
    expect(statusAfter("approve", undefined, { result: "created", assertion: { status: "bogus" }, same_as: {} })).toBe("approved");
    expect(statusAfter("reject", "entity_distinct", { result: "created", assertion: { status: "weird" }, same_as: null })).toBe("rejected_entity_distinct");
  });
});

describe("clientBulkEligible", () => {
  const eligible = mkCase({ bulk_eligible: true, current_ledger_status: "none" });
  it("is true for a bulk-eligible, unresolved case with context and no collision", () => {
    expect(clientBulkEligible(row(eligible), mkCtx({ key_collision: false }))).toBe(true);
  });
  it("is false when the graph reports a key collision", () => {
    expect(clientBulkEligible(row(eligible), mkCtx({ key_collision: true }))).toBe(false);
  });
  it("is false when the read model did not mark it bulk-eligible", () => {
    expect(clientBulkEligible(row(mkCase({ bulk_eligible: false })), mkCtx())).toBe(false);
  });
  it("is false once the case is resolved", () => {
    expect(clientBulkEligible(row(eligible, "approved"), mkCtx())).toBe(false);
  });
  it("is false when graph context is unavailable (cannot confirm no-collision)", () => {
    expect(clientBulkEligible(row(eligible), undefined)).toBe(false);
  });
});

describe("bucketOf", () => {
  it("routes an unresolved recommended case to recommended", () => {
    expect(bucketOf("none", true)).toBe("recommended");
  });
  it("routes an unresolved non-recommended case to needsReview", () => {
    expect(bucketOf("none", false)).toBe("needsReview");
  });
  it("routes requeued to needsReview", () => {
    expect(bucketOf("requeued", false)).toBe("needsReview");
  });
  it("routes rejections to rejected", () => {
    expect(bucketOf("rejected_current_evidence", false)).toBe("rejected");
    expect(bucketOf("rejected_entity_distinct", false)).toBe("rejected");
  });
  it("routes approvals and the like to done", () => {
    expect(bucketOf("approved", false)).toBe("done");
    expect(bucketOf("superseded", false)).toBe("done");
    expect(bucketOf("deterministic", false)).toBe("done");
  });
  it("routes session-unsure to done", () => {
    expect(bucketOf("unsure", false)).toBe("done");
  });
});

describe("bucketize", () => {
  it("groups rows and sorts needs-review + recommended by money desc", () => {
    const cases = [
      mkCase({ case_id: "a", vendor: "v1", bulk_eligible: false }),
      mkCase({ case_id: "b", vendor: "v2", bulk_eligible: false }),
      mkCase({ case_id: "c", vendor: "v3", bulk_eligible: true }),
      mkCase({ case_id: "d", vendor: "v4", bulk_eligible: true }),
      mkCase({ case_id: "e", vendor: "v5", current_ledger_status: "approved" }),
      mkCase({ case_id: "f", vendor: "v6", current_ledger_status: "rejected_entity_distinct" }),
    ];
    const ctx: Record<string, ContextEntry> = {
      v1: mkCtx({ money_total: 100 }),
      v2: mkCtx({ money_total: 900 }),
      v3: mkCtx({ money_total: 50 }),
      v4: mkCtx({ money_total: 800 }),
      v5: mkCtx(),
      v6: mkCtx(),
    };
    const b = bucketize(cases.map((c) => row(c)), ctx);
    expect(b.needsReview.map((r) => r.case_id)).toEqual(["b", "a"]); // 900 before 100
    expect(b.recommended.map((r) => r.case_id)).toEqual(["d", "c"]); // 800 before 50
    expect(b.done.map((r) => r.case_id)).toEqual(["e"]);
    expect(b.rejected.map((r) => r.case_id)).toEqual(["f"]);
  });

  it("demotes a bulk-eligible case with a collision out of recommended into needsReview", () => {
    const cases = [mkCase({ case_id: "x", vendor: "vx", bulk_eligible: true })];
    const ctx = { vx: mkCtx({ key_collision: true, money_total: 10 }) };
    const b = bucketize(cases.map((c) => row(c)), ctx);
    expect(b.recommended).toHaveLength(0);
    expect(b.needsReview.map((r) => r.case_id)).toEqual(["x"]);
  });
});

describe("aiVerdictOf / isNameExact", () => {
  it("reads the first AI verdict", () => {
    expect(aiVerdictOf(mkCase({ aiVerdict: "different" }))).toBe("different");
  });
  it("returns null when there is no AI review", () => {
    expect(aiVerdictOf(mkCase({ ai_reviews: [] }))).toBeNull();
  });
  it("detects a normalized-name-exact signal", () => {
    expect(isNameExact(mkCase({ signals: ["normalized_name_exact"] }))).toBe(true);
    expect(isNameExact(mkCase({ signals: ["token_overlap"] }))).toBe(false);
  });
});

describe("applyControls", () => {
  const ctx: Record<string, ContextEntry> = {
    v1: mkCtx({ money_total: 900, display_label: "Alpha Foundation" }),
    v2: mkCtx({ money_total: 100, display_label: "Beta LLC" }),
    v3: mkCtx({ money_total: 5000, display_label: "Gamma Trust" }),
  };
  const rows = [
    row(mkCase({ case_id: "a", vendor: "v1", aiVerdict: "same", aiConf: 0.95, signals: ["normalized_name_exact"], regName: "Alpha" })),
    row(mkCase({ case_id: "b", vendor: "v2", aiVerdict: "different", aiConf: 0.4, signals: ["token_overlap"], regName: "Beta" })),
    row(mkCase({ case_id: "c", vendor: "v3", aiVerdict: "unsure", aiConf: 0.6, signals: ["token_overlap"], regName: "Gamma" })),
  ];
  const ctrl = (over: Partial<QueueControls>): QueueControls => ({ ...DEFAULT_CONTROLS, ...over });

  it("defaults to money descending (matches the queue default)", () => {
    expect(applyControls(rows, ctx, DEFAULT_CONTROLS).map((r) => r.case_id)).toEqual(["c", "a", "b"]); // 5000, 900, 100
  });
  it("sorts money ascending when direction flips", () => {
    expect(applyControls(rows, ctx, ctrl({ sortKey: "money", sortDir: "asc" })).map((r) => r.case_id)).toEqual(["b", "a", "c"]);
  });
  it("sorts by AI confidence", () => {
    expect(applyControls(rows, ctx, ctrl({ sortKey: "ai", sortDir: "desc" })).map((r) => r.case_id)).toEqual(["a", "c", "b"]); // .95,.6,.4
  });
  it("filters by AI verdict", () => {
    expect(applyControls(rows, ctx, ctrl({ verdict: "same" })).map((r) => r.case_id)).toEqual(["a"]);
    expect(applyControls(rows, ctx, ctrl({ verdict: "different" })).map((r) => r.case_id)).toEqual(["b"]);
  });
  it("filters by name-match exactness", () => {
    expect(applyControls(rows, ctx, ctrl({ nameMatch: "exact" })).map((r) => r.case_id)).toEqual(["a"]);
    expect(new Set(applyControls(rows, ctx, ctrl({ nameMatch: "fuzzy" })).map((r) => r.case_id))).toEqual(new Set(["b", "c"]));
  });
  it("filters by a money floor", () => {
    expect(applyControls(rows, ctx, ctrl({ minMoney: 500 })).map((r) => r.case_id)).toEqual(["c", "a"]); // 5000, 900
  });
  it("searches across vendor name, registry name, and key (case-insensitive)", () => {
    expect(applyControls(rows, ctx, ctrl({ search: "gamma" })).map((r) => r.case_id)).toEqual(["c"]);
    expect(applyControls(rows, ctx, ctrl({ search: "BETA" })).map((r) => r.case_id)).toEqual(["b"]);
  });
  it("ignores a too-short search (< 2 chars) rather than false-matching everything", () => {
    expect(applyControls(rows, ctx, ctrl({ search: "a" })).map((r) => r.case_id).length).toBe(3);
  });
});

describe("investigationLinks", () => {
  it("links an EIN case to ProPublica (9 digits) + a web search on the registry org name", () => {
    const links = investigationLinks(mkCase({ src: "ein", key: "94-3041517", regName: "Buckelew Programs", city: "Novato" }));
    expect(links.find((l) => /propublica/i.test(l.url))?.url).toBe("https://projects.propublica.org/nonprofits/organizations/943041517");
    const ws = links.find((l) => /google\.com\/search/.test(l.url));
    expect(decodeURIComponent(ws!.url)).toContain("Buckelew Programs");
    expect(decodeURIComponent(ws!.url)).toContain("Novato");
  });
  it("omits ProPublica for a malformed (non-9-digit) EIN", () => {
    const links = investigationLinks(mkCase({ src: "ein", key: "12" }));
    expect(links.some((l) => /propublica/.test(l.url))).toBe(false);
    expect(links.some((l) => /google\.com\/search/.test(l.url))).toBe(true);
  });
  it("links an SOS case to CA bizfile + a web search", () => {
    const links = investigationLinks(mkCase({ src: "sos_id", key: "1085358", regName: "Wra, Inc.", city: "San Rafael" }));
    expect(links.some((l) => /bizfileonline\.sos\.ca\.gov/.test(l.url))).toBe(true);
    expect(links.some((l) => /google\.com\/search/.test(l.url))).toBe(true);
  });
  it("searches the registry org name, never the raw vendor string (redaction-safe)", () => {
    const links = investigationLinks(mkCase({ src: "ein", key: "123456789", name: "JOHN Q SMITH", regName: "Smith Foundation" }));
    const ws = links.find((l) => /google\.com\/search/.test(l.url))!;
    expect(decodeURIComponent(ws.url)).toContain("Smith Foundation");
    expect(decodeURIComponent(ws.url)).not.toContain("JOHN Q SMITH");
  });
});
