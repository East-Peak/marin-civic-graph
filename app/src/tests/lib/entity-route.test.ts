// app/src/tests/lib/entity-route.test.ts
//
// One reversible id <-> route mapping for every entity link. Before this, twelve copies
// cut the id at its first hyphen and the page rebuilt `<segment>-<slug>`: that only
// round-trips when the id prefix equals the URL segment, so every `permit-` Project
// (51K), every `agenda-item-` AgendaItem (15K) and the `doc-` Records 404'd (2026-09-29).
import { describe, it, expect } from "vitest";
import { entityRoute, resolveEntityId, typeForSegment } from "@/lib/entity-route";
import { TYPE_BY_ID_PREFIX, type NodeType } from "@/lib/node-types.generated";
import { urlSegmentForType } from "@/lib/type-display";

function lookupIn(nodes: Record<string, NodeType>) {
  return (id: string): NodeType | null => nodes[id] ?? null;
}

function roundTrip(id: string, type: NodeType, nodes: Record<string, NodeType> = { [id]: type }) {
  const route = entityRoute(id, type);
  const [, segment, slug] = route.split("/");
  return { route, resolved: resolveEntityId(segment, decodeURIComponent(slug), lookupIn(nodes)) };
}

describe("entityRoute", () => {
  it("strips a registered prefix of the entity's own type", () => {
    expect(entityRoute("person-kate-colin", "Person")).toBe("/person/kate-colin");
    expect(entityRoute("org-san-rafael-city-council", "Organization")).toBe(
      "/organization/san-rafael-city-council",
    );
    expect(entityRoute("agenda-item-2019-01-22-sr-1", "AgendaItem")).toBe("/agenda-item/2019-01-22-sr-1");
  });

  it("keeps the whole id when its prefix is not registered for that type", () => {
    expect(entityRoute("permit-marin-IN_B10577_10577", "Project")).toBe(
      "/project/permit-marin-IN_B10577_10577",
    );
    expect(entityRoute("doc-2023-12-14-implementation-plan", "Record")).toBe(
      "/record/doc-2023-12-14-implementation-plan",
    );
  });

  it("encodes a slug that is not URL-safe", () => {
    expect(entityRoute("project-a b/c", "Project")).toBe("/project/a%20b%2Fc");
  });
});

describe("resolveEntityId", () => {
  it.each([
    ["person-kate-colin", "Person"],
    ["org-san-rafael-city-council", "Organization"],
    ["agenda-item-2019-01-22-sr-1", "AgendaItem"],
    ["permit-marin-IN_B10577_10577", "Project"],
    ["doc-2023-12-14-implementation-plan", "Record"],
    ["inst-legacy-council", "Organization"],
    ["project-a b/c", "Project"],
  ] as [string, NodeType][])("round-trips %s", (id, type) => {
    expect(roundTrip(id, type).resolved).toBe(id);
  });

  it("round-trips every registered id prefix", () => {
    for (const [prefix, type] of Object.entries(TYPE_BY_ID_PREFIX)) {
      expect(roundTrip(`${prefix}sample-1`, type).resolved, prefix).toBe(`${prefix}sample-1`);
    }
  });

  it("never resolves an entity of another type under this segment", () => {
    const lookup = lookupIn({ "person-kate-colin": "Person" });
    expect(resolveEntityId("project", "person-kate-colin", lookup)).toBeNull();
  });

  it("returns null for an unknown segment or a missing id", () => {
    const lookup = lookupIn({ "person-kate-colin": "Person" });
    expect(resolveEntityId("no-such-type", "kate-colin", lookup)).toBeNull();
    expect(resolveEntityId("person", "nobody", lookup)).toBeNull();
  });

  it("still serves a legacy segment's old route (/actor/kate-colin → person-kate-colin)", () => {
    const lookup = lookupIn({ "person-kate-colin": "Person" });
    expect(resolveEntityId("actor", "kate-colin", lookup)).toBe("person-kate-colin");
  });

  it("still honours legacy id aliases (actor- → person-)", () => {
    const lookup = lookupIn({ "person-kate-colin": "Person" });
    expect(resolveEntityId("person", "actor-kate-colin", lookup)).toBe("person-kate-colin");
  });
});

describe("typeForSegment", () => {
  it("inverts urlSegmentForType for every prefixed type", () => {
    for (const type of new Set(Object.values(TYPE_BY_ID_PREFIX))) {
      expect(typeForSegment(urlSegmentForType(type))).toBe(type);
    }
  });
});
