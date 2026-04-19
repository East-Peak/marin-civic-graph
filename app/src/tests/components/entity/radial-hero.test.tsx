import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ElementDefinition } from "cytoscape";
import { RadialHero } from "@/components/entity/radial-hero";
import { toRadialHeroData } from "@/components/entity/radial-hero-data";
import type { EntityPayload } from "@/lib/server/entity-loader";

// Capture elements passed to CytoscapeBase so we can assert on the data shape
// without rendering a real cytoscape canvas.
vi.mock("@/components/graph/cytoscape-base", () => ({
  CytoscapeBase: (props: { elements: ElementDefinition[] }) => {
    (globalThis as unknown as { __radialElements?: ElementDefinition[] }).__radialElements =
      props.elements;
    return <div data-testid="cy-stub" />;
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

function makeEntity(overrides: Partial<EntityPayload> = {}): EntityPayload {
  return {
    id: "person-kate-colin",
    type: "Person",
    label: "Kate Colin",
    properties: { id: "person-kate-colin" },
    neighbors: [],
    edges: [],
    neighbor_total: 0,
    ...overrides,
  };
}

describe("RadialHero", () => {
  it("emits elements with a focus node first and ring data on neighbors", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "seatservice-mayor-sr",
          type: "SeatService",
          label: "Mayor — San Rafael",
          route: "/seat-service/mayor-sr",
          ring: 1,
          role: "must-show",
        },
        {
          id: "meeting-sr-2024-08-19",
          type: "Meeting",
          label: "SR City Council — 2024-08-19",
          route: "/meeting/sr-2024-08-19",
          ring: 2,
          role: "must-show",
        },
      ],
      edges: [],
      neighbor_total: 2,
    });
    render(<RadialHero data={toRadialHeroData(entity)} />);

    const elements = (globalThis as unknown as { __radialElements: ElementDefinition[] })
      .__radialElements;
    expect(elements).toBeDefined();

    const nodes = elements.filter((e) => !("source" in (e.data as Record<string, unknown>)));
    expect(nodes[0].data.id).toBe("person-kate-colin");
    expect(nodes[0].data.role).toBe("focus");
    expect(nodes[0].data.visibleLabel).toBe("Kate Colin");

    const ring1 = nodes.find((n) => n.data.id === "seatservice-mayor-sr")!;
    expect(ring1.data.ring).toBe(1);
    expect(ring1.data.role).toBe("primary");
    // ring-1 = always-visible label
    expect(ring1.data.visibleLabel).toBe("Mayor — San Rafael");

    const ring2 = nodes.find((n) => n.data.id === "meeting-sr-2024-08-19")!;
    expect(ring2.data.ring).toBe(2);
    expect(ring2.data.role).toBe("secondary");
    // ring-2 labels are hover-only in the stylesheet
    expect(ring2.data.visibleLabel).toBe("");
  });

  it("renders the ENTITY · TYPE kicker in the corner", () => {
    render(<RadialHero data={toRadialHeroData(makeEntity({ type: "Person" }))} />);
    expect(screen.getByTestId("radial-hero-kicker").textContent).toContain("ENTITY");
    expect(screen.getByTestId("radial-hero-kicker").textContent).toContain("PERSON");
  });

  it("renders the overflow footer when neighbor_total exceeds neighbors + focus", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-x",
          type: "Meeting",
          label: "Meeting X",
          route: "/meeting/x",
          ring: 1,
          role: "must-show",
        },
      ],
      neighbor_total: 10,
    });
    render(<RadialHero data={toRadialHeroData(entity)} />);
    const overflow = screen.getByTestId("radial-hero-overflow");
    expect(overflow.textContent).toContain("+9 more neighbors");
    const link = overflow.querySelector("a");
    expect(link?.getAttribute("href")).toContain("/graph?focus=person-kate-colin");
  });

  it("does not render overflow when neighbors match neighbor_total", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-x",
          type: "Meeting",
          label: "Meeting X",
          route: "/meeting/x",
          ring: 1,
          role: "must-show",
        },
      ],
      neighbor_total: 1,
    });
    render(<RadialHero data={toRadialHeroData(entity)} />);
    expect(screen.queryByTestId("radial-hero-overflow")).toBeNull();
  });

  it("includes only edges whose source and target are in the neighborhood", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-x",
          type: "Meeting",
          label: "Meeting X",
          route: "/meeting/x",
          ring: 1,
          role: "must-show",
        },
      ],
      edges: [
        { source: "person-kate-colin", target: "meeting-x", type: "ATTENDED", style: "governance" },
        { source: "person-kate-colin", target: "some-orphan", type: "MENTIONS", style: "governance" },
      ],
      neighbor_total: 1,
    });
    render(<RadialHero data={toRadialHeroData(entity)} />);
    const elements = (globalThis as unknown as { __radialElements: ElementDefinition[] })
      .__radialElements;
    const edges = elements.filter((e) =>
      typeof (e.data as Record<string, unknown>).source === "string",
    );
    expect(edges).toHaveLength(1);
    expect((edges[0].data as Record<string, unknown>).target).toBe("meeting-x");
  });
});
