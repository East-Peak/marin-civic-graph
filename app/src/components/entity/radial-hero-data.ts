// Shared (non-client, non-server) module: serializable RadialHero data shape
// plus the EntityPayload → RadialHeroData projection.
//
// Lives outside the `"use client"` radial-hero.tsx so the server entity-page
// composer can call toRadialHeroData without triggering "client function on
// the server" errors, and without importing the client bundle.

import type {
  EntityEdge,
  EntityPayload,
  Neighbor,
} from "@/lib/server/entity-loader";
import type { NodeType } from "@/lib/type-display";

/**
 * Serializable subset of EntityPayload. Must exclude `properties` — the
 * loader returns Neo4j Integer objects on numeric props, which React will
 * reject at the server→client boundary.
 */
export type RadialHeroData = {
  id: string;
  type: NodeType;
  label: string;
  neighbors: Neighbor[];
  edges: EntityEdge[];
  neighbor_total: number;
};

export function toRadialHeroData(entity: EntityPayload): RadialHeroData {
  return {
    id: entity.id,
    type: entity.type,
    label: entity.label,
    neighbors: entity.neighbors,
    edges: entity.edges,
    neighbor_total: entity.neighbor_total,
  };
}
