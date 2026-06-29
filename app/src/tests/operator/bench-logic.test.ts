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
  type BenchRow,
} from "../../../operator-workbench-src/_lib/bench-logic";
import type { Case, ContextEntry } from "../../../operator-workbench-src/_lib/bench-types";

function mkCase(over: Partial<Case> & { vendor?: string; src?: string; key?: string } = {}): Case {
  const vendor = over.vendor ?? "org-county-vendor-1";
  const src = over.src ?? "ein";
  const keyField = src === "ein" ? "registry_ein" : "sos_id";
  return {
    case_id: over.case_id ?? `attach|anchor-1|${vendor}`,
    candidate_joins: over.candidate_joins ?? [
      {
        left_ref: { source_id: src, local_id: vendor, display_label: "RAW VENDOR NAME", public_fields: {} },
        right_ref: {
          source_id: src,
          local_id: "anchor-1",
          display_label: "Registry Name",
          public_fields: { [keyField]: over.key ?? "123456789" },
        },
        signals: ["normalized_name_exact"],
        signal_strength: 0.95,
      },
    ],
    ai_reviews: over.ai_reviews ?? [{ verdict: "same", reason: "exact name + key", signal_strength: 0.97 }],
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
