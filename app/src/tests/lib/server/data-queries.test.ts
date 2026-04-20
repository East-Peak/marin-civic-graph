// app/src/tests/lib/server/data-queries.test.ts
import { describe, it, expect } from "vitest";
import {
  DATA_QUERIES,
  findDataQuery,
  applyFilterDefaults,
} from "@/lib/server/data-queries";

describe("DATA_QUERIES", () => {
  it("exposes exactly the 10 predefined slugs from spec §8", () => {
    const slugs = DATA_QUERIES.map((q) => q.slug);
    expect(slugs).toEqual([
      "san-rafael-decisions-since-2019",
      "money-flows-by-year",
      "filings-by-person-or-committee",
      "current-officeholders-form-coverage",
      "agreements-and-amendments-for-project",
      "legal-proceedings-affecting-local",
      "evidence-records-supporting",
      "local-pressure-ranking-sr",
      "campaign-money-near-decisions",
      "qa-validation-gaps",
    ]);
  });

  it("every query has a non-empty display_name, description, and >=1 column", () => {
    for (const q of DATA_QUERIES) {
      expect(q.display_name.length).toBeGreaterThan(0);
      expect(q.description.length).toBeGreaterThan(0);
      expect(q.columns.length).toBeGreaterThan(0);
    }
  });

  it("every filter declares a known type", () => {
    const allowed = new Set(["date", "amount", "select", "text"]);
    for (const q of DATA_QUERIES) {
      for (const f of q.filters) {
        expect(allowed.has(f.type)).toBe(true);
      }
    }
  });
});

describe("findDataQuery", () => {
  it("returns the query by slug", () => {
    const q = findDataQuery("san-rafael-decisions-since-2019");
    expect(q).not.toBeNull();
    expect(q?.display_name).toMatch(/San Rafael/);
  });

  it("returns null for an unknown slug", () => {
    expect(findDataQuery("definitely-not-a-real-query")).toBeNull();
  });
});

describe("cypher builders", () => {
  it("never embed user filter values as literals — uses $param placeholders only", () => {
    const hostile = {
      from_date: "'; DROP DATABASE; //",
      to_date: "2024-12-31",
      institution_id: "\"}) MATCH (evil) //",
      min_amount: "1'; DELETE //",
      year: "2024'; //",
      flow_type: "contribution' OR 1=1 //",
      filing_type: "form_460'; //",
      filer_id: "person-evil' //",
      jurisdiction_id: "place-x' //",
      project_id: "project-x' OR 1=1 //",
      case_id: "case-x' //",
      target_id: "decision-x' //",
      window_days: "30'; //",
      jurisdiction: "san-rafael' //",
    };
    for (const q of DATA_QUERIES) {
      const { query, params } = q.cypher(hostile);
      // No template-literal interpolation at all.
      expect(query).not.toContain("${");
      // No hostile fragments embedded in the query string.
      expect(query).not.toContain("DROP DATABASE");
      expect(query).not.toContain("DELETE");
      expect(query).not.toContain("OR 1=1");
      // Params is an object (possibly empty for no-filter queries).
      expect(typeof params).toBe("object");
    }
  });

  it("San Rafael decisions: defaults from_date to 2019-01-01 when blank", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    const built = def.cypher({});
    expect(built.params.from_date).toBe("2019-01-01");
    expect(built.params.institution_id).toBeNull();
    expect(built.query).toMatch(/\$from_date/);
    expect(built.query).toMatch(/\$to_date/);
    expect(built.query).toMatch(/\$institution_id/);
  });

  it("San Rafael decisions: honors caller-provided values", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    const built = def.cypher({
      from_date: "2024-01-01",
      to_date: "2024-06-30",
      institution_id: "org-san-rafael-city-council",
    });
    expect(built.params.from_date).toBe("2024-01-01");
    expect(built.params.to_date).toBe("2024-06-30");
    expect(built.params.institution_id).toBe("org-san-rafael-city-council");
  });

  it("money-flows: coerces min_amount to a number, passes year as prefix", () => {
    const def = findDataQuery("money-flows-by-year")!;
    const built = def.cypher({ min_amount: "5000", year: "2024", flow_type: "contribution" });
    expect(built.params.min_amount).toBe(5000);
    expect(built.params.year_prefix).toBe("2024-");
    expect(built.params.flow_type).toBe("contribution");
  });

  it("money-flows: year_prefix is null when year is blank", () => {
    const def = findDataQuery("money-flows-by-year")!;
    const built = def.cypher({});
    expect(built.params.year_prefix).toBeNull();
    expect(built.params.min_amount).toBe(1000);
  });

  it("evidence-records: target_id passes through as-is", () => {
    const def = findDataQuery("evidence-records-supporting")!;
    const built = def.cypher({ target_id: "decision-abc" });
    expect(built.params.target_id).toBe("decision-abc");
  });

  it("qa-validation-gaps: emits no-param query", () => {
    const def = findDataQuery("qa-validation-gaps")!;
    const built = def.cypher({});
    expect(Object.keys(built.params)).toEqual([]);
    expect(built.query.length).toBeGreaterThan(0);
  });

  it("campaign-money-near-decisions: coerces window_days to number, defaults to 30", () => {
    const def = findDataQuery("campaign-money-near-decisions")!;
    const a = def.cypher({ window_days: "14", jurisdiction: "san-rafael" });
    expect(a.params.window_days).toBe(14);
    const b = def.cypher({});
    expect(b.params.window_days).toBe(30);
    expect(b.params.jurisdiction).toBe("san-rafael");
  });
});

describe("applyFilterDefaults", () => {
  it("merges caller values with each filter's declared default", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    const merged = applyFilterDefaults(def, { to_date: "2026-01-01" });
    expect(merged.from_date).toBe("2019-01-01"); // default
    expect(merged.to_date).toBe("2026-01-01");   // provided wins
    expect(merged.institution_id).toBeUndefined(); // no default, not provided
  });

  it("treats empty strings as missing (re-applies default)", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    const merged = applyFilterDefaults(def, { from_date: "" });
    expect(merged.from_date).toBe("2019-01-01");
  });
});
