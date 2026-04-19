"use client";

// Tier 1 radial hero — Cytoscape `concentric` layout per spec §5.1 + §5.1.1 +
// §6.2. Focus node at center, neighbors on rings 1/2/3. Labels are shown for
// focus + ring-1 always; ring-2 and ring-3 labels are hidden by default.
// Click on a node → navigate to its entity page via Next router.
// Overflow footer appears when neighbor_total exceeds rendered neighbors.

import { useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ElementDefinition, LayoutOptions, NodeSingular } from "cytoscape";
import { CytoscapeBase } from "@/components/graph/cytoscape-base";
import {
  colorClassForType,
  glowForRole,
  shapeForType,
  sizeForRole,
} from "@/components/graph/obsidian-style";
import type { Neighbor } from "@/lib/server/entity-loader";
import type { RadialHeroData } from "@/components/entity/radial-hero-data";

type NodeRole = "focus" | "primary" | "secondary";

function roleForRing(ring: 1 | 2 | 3): NodeRole {
  if (ring === 1) return "primary";
  return "secondary";
}

function visibleLabelFor(role: NodeRole, label: string): string {
  return role === "focus" || role === "primary" ? label : "";
}

function toElements(entity: RadialHeroData): ElementDefinition[] {
  // Focus node first.
  const focusColorClass = colorClassForType(entity.type);
  const focusShape = shapeForType(entity.type);
  const focusSize = sizeForRole("focus");
  const focusGlow = glowForRole("focus", focusColorClass);

  const nodes: ElementDefinition[] = [
    {
      data: {
        id: entity.id,
        visibleLabel: entity.label,
        role: "focus",
        ring: 0,
        colorClass: focusColorClass,
        shape: focusColorClass ? "circle" : focusShape,
        size: String(focusSize),
        glowBlur: focusGlow.blur,
        glowColor: focusGlow.color,
        route: "",
      },
    },
    ...entity.neighbors.map((n: Neighbor): ElementDefinition => {
      const role = roleForRing(n.ring);
      const colorClass = colorClassForType(n.type);
      const shape = shapeForType(n.type);
      const size = sizeForRole(role);
      const glow = glowForRole(role, colorClass);
      return {
        data: {
          id: n.id,
          visibleLabel: visibleLabelFor(role, n.label),
          label: n.label, // kept in data for potential hover use
          role,
          ring: n.ring,
          colorClass,
          shape: colorClass ? "circle" : shape,
          size: String(size),
          glowBlur: glow.blur,
          glowColor: glow.color,
          route: n.route,
        },
      };
    }),
  ];

  const seen = new Set<string>(nodes.map((n) => String(n.data.id)));
  const edges: ElementDefinition[] = entity.edges
    .filter((e) => seen.has(e.source) && seen.has(e.target))
    .map((e, i) => ({
      data: {
        id: `e-${i}-${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        style: e.style,
      },
    }));

  return [...nodes, ...edges];
}

const concentricLayout: LayoutOptions = {
  name: "concentric",
  // Higher concentric value = closer to center.
  // Focus=4, ring1=3, ring2=2, ring3=1.
  concentric: function (node: NodeSingular) {
    const role = node.data("role");
    if (role === "focus") return 4;
    const ring = Number(node.data("ring"));
    if (ring === 1) return 3;
    if (ring === 2) return 2;
    return 1;
  },
  // Each distinct concentric value becomes its own ring.
  levelWidth: function () {
    return 1;
  },
  minNodeSpacing: 30,
  spacingFactor: 1.1,
  animate: false,
  padding: 20,
  avoidOverlap: true,
  fit: true,
} as unknown as LayoutOptions;

export function RadialHero({ data }: { data: RadialHeroData }) {
  const router = useRouter();
  const elements = useMemo(() => toElements(data), [data]);

  const overflow = data.neighbor_total - data.neighbors.length;
  const typeUpper = data.type.toUpperCase();

  return (
    <div className="relative h-full min-h-[420px] w-full" data-testid="radial-hero">
      <div
        className="pointer-events-none absolute right-5 top-4 z-10 font-mono uppercase text-hairline"
        style={{ fontSize: "10px", letterSpacing: "0.12em" }}
        data-testid="radial-hero-kicker"
      >
        ENTITY · {typeUpper}
      </div>
      <CytoscapeBase
        elements={elements}
        layout={concentricLayout}
        onNodeClick={(id) => {
          if (id === data.id) return; // focus node is a no-op
          const n = data.neighbors.find((x) => x.id === id);
          if (n) router.push(n.route);
        }}
        className="h-full w-full"
      />
      {overflow > 0 && (
        <div
          className="absolute bottom-3 left-5 z-10 font-mono text-hairline"
          style={{ fontSize: "10px", letterSpacing: "0.04em" }}
          data-testid="radial-hero-overflow"
        >
          +{overflow} more neighbors ·{" "}
          <Link
            href={`/graph?focus=${encodeURIComponent(data.id)}`}
            className="underline hover:text-dim"
          >
            see /graph
          </Link>
        </div>
      )}
    </div>
  );
}
