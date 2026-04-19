"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { ElementDefinition } from "cytoscape";
import { CytoscapeBase } from "@/components/graph/cytoscape-base";
import { colorClassForType, glowForRole, shapeForType, sizeForRole } from "@/components/graph/obsidian-style";
import type { SubgraphBundle, SubgraphManifest } from "@/lib/types";

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return (await res.json()) as T;
}

function pickSlug(manifest: SubgraphManifest): string | null {
  if (manifest.subgraphs.length === 0) return null;
  const i = Math.floor(Math.random() * manifest.subgraphs.length);
  return manifest.subgraphs[i].slug;
}

function toElements(bundle: SubgraphBundle): ElementDefinition[] {
  const nodes: ElementDefinition[] = bundle.nodes.map((n) => {
    const colorClass = colorClassForType(n.type);
    const shape = shapeForType(n.type);
    const size = sizeForRole(n.role);
    const glow = glowForRole(n.role, colorClass);
    return {
      data: {
        id: n.id,
        visibleLabel: n.role === "focus" || n.role === "primary" ? n.label : "",
        role: n.role,
        colorClass,
        shape: colorClass ? "circle" : shape,
        size: String(size),
        glowBlur: glow.blur,
        glowColor: glow.color,
        route: n.route,
      },
    };
  });
  const edges: ElementDefinition[] = bundle.edges.map((e, i) => ({
    data: {
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      style: e.style,
    },
  }));
  return [...nodes, ...edges];
}

export function SignatureSubgraph() {
  const router = useRouter();
  const [bundle, setBundle] = useState<SubgraphBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const manifest = await fetchJSON<SubgraphManifest>("/subgraphs/manifest.json");
        const slug = pickSlug(manifest);
        if (!slug) throw new Error("no subgraphs available");
        const b = await fetchJSON<SubgraphBundle>(`/subgraphs/${slug}.json`);
        if (!cancelled) setBundle(b);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "load failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-dim">
        {`signature-subgraph unavailable: ${error}`}
      </div>
    );
  }

  if (!bundle) {
    return <div className="flex h-full items-center justify-center text-hairline">loading…</div>;
  }

  const elements = toElements(bundle);

  return (
    <div className="relative h-full w-full">
      <div className="absolute right-5 top-4 z-10 font-mono text-[10px] uppercase tracking-[0.12em] text-hairline">
        {bundle.headline_stats.kicker}
      </div>
      <CytoscapeBase
        elements={elements}
        onNodeClick={(id) => {
          const node = bundle.nodes.find((n) => n.id === id);
          if (node) router.push(node.route);
        }}
        className="h-full w-full"
      />
      <div
        className="absolute bottom-4 left-5 z-10 text-body"
        style={{ fontFamily: "var(--font-vt323)", fontSize: "16px", letterSpacing: "0.04em" }}
      >
        {bundle.headline_stats.caption}
      </div>
    </div>
  );
}
