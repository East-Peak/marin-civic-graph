// app/src/tests/lib/id-aliases.test.ts
import { describe, it, expect } from "vitest";
import { resolveIdAlias } from "@/lib/id-aliases";

describe("id-aliases", () => {
  it("passes through canonical ids unchanged", () => {
    expect(resolveIdAlias("person-kate-colin")).toEqual({
      id: "person-kate-colin",
      type: "Person",
    });
  });

  it("resolves actor- → person- for Person urls", () => {
    expect(resolveIdAlias("actor-kate-colin", "Person")).toEqual({
      id: "person-kate-colin",
      type: "Person",
    });
  });

  it("resolves inst- → org- for Organization urls", () => {
    expect(resolveIdAlias("inst-san-rafael-city-council", "Organization")).toEqual({
      id: "org-san-rafael-city-council",
      type: "Organization",
    });
  });

  it("resolves eid- → filing- for Filing urls", () => {
    expect(resolveIdAlias("eid-kate-colin-2024", "Filing")).toEqual({
      id: "filing-kate-colin-2024",
      type: "Filing",
    });
  });

  it("infers type from id prefix when context omitted", () => {
    expect(resolveIdAlias("project-san-rafael-merrydale")).toEqual({
      id: "project-san-rafael-merrydale",
      type: "Project",
    });
  });

  it("returns null for unrecognized ids", () => {
    expect(resolveIdAlias("gibberish-xyz")).toBeNull();
  });

  // M1b RESIDUAL 1 — real agenda ids are `agenda-item-*`; the old hand-rolled
  // CANONICAL_PREFIX_MAP carried a stale `agendaitem-` key that never matched.
  // Now routed through the registry-derived resolveTypeFromId (single source).
  it("resolves the real agenda-item- prefix (was stale agendaitem-)", () => {
    expect(resolveIdAlias("agenda-item-2024-08-19-5a")).toEqual({
      id: "agenda-item-2024-08-19-5a",
      type: "AgendaItem",
    });
  });
});
