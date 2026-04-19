"use client";

import { useEffect, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions } from "cytoscape";
import fcose from "cytoscape-fcose";
import { obsidianStylesheet } from "./obsidian-style";

cytoscape.use(fcose);

export type CytoscapeBaseProps = {
  elements: ElementDefinition[];
  layout?: LayoutOptions;
  onNodeClick?: (id: string) => void;
  className?: string;
};

export function CytoscapeBase({ elements, layout, onNodeClick, className }: CytoscapeBaseProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: obsidianStylesheet,
      layout: layout ?? ({ name: "fcose", quality: "proof", animate: false } as LayoutOptions),
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;

    if (onNodeClick) {
      cy.on("tap", "node", (event) => {
        const id = event.target.id();
        onNodeClick(id);
      });
    }

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements, layout, onNodeClick]);

  return <div ref={containerRef} className={className ?? "h-full w-full"} />;
}
