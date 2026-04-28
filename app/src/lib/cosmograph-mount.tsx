"use client";

import { useEffect, useRef } from "react";
import { Graph } from "@cosmograph/cosmos";
import type { CosmosInputNode, CosmosInputLink } from "@cosmograph/cosmos";
import type {
  ConstellationNode, ConstellationEdge,
} from "@/lib/constellation-types";
import type { SpriteAtlas } from "@/components/constellation/sprite-atlas";

export type ConstellationCanvasProps = {
  nodes: ConstellationNode[];
  edges: ConstellationEdge[];
  spritesA: SpriteAtlas | null;
  spritesB: SpriteAtlas | null;
  onNodeClick: (id: string) => void;
};

export function ConstellationCanvas({
  nodes,
  edges,
  onNodeClick,
}: ConstellationCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const graphRef = useRef<Graph<CosmosInputNode, CosmosInputLink> | null>(null);

  useEffect(() => {
    if (!canvasRef.current) return;

    const g = new Graph(canvasRef.current, {
      backgroundColor: "#07090d",
      // Disable force-directed simulation — positions come from UMAP (§4.2).
      disableSimulation: true,
      events: {
        onClick: (node) => {
          if (node?.id) onNodeClick(node.id);
        },
      },
    });
    graphRef.current = g;

    g.setData(
      nodes.map((n) => ({ id: n.id, x: n.x, y: n.y })),
      edges.map((e) => ({ source: e.s, target: e.t })),
      // Don't start simulation — UMAP positions are authoritative.
      false,
    );

    g.fitView();

    return () => {
      g.destroy();
      graphRef.current = null;
    };
  }, [nodes, edges, onNodeClick]);

  return (
    <canvas
      ref={canvasRef}
      data-testid="constellation-canvas"
      className="h-full w-full"
    />
  );
}
