import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { loadStatus } from "@/lib/server/homepage-data";
import { loadEntity } from "@/lib/server/entity-loader";
import type { EntityPayload } from "@/lib/server/entity-loader";
import { ExplorerClient } from "./explorer-client";

// Force dynamic — the explorer must reflect the live INGEST timestamp and
// (when focused) a live entity neighborhood query.
export const dynamic = "force-dynamic";

/**
 * Turn a canonical id like "person-kate-colin" or "seatservice-mayor-sr" into
 * (typeSegment, slug) suitable for loadEntity(). Mirrors the reverse of
 * candidateIdFromSegment() in entity-loader.ts: the type prefix is the type's
 * URL segment with dashes collapsed, and the slug is the rest.
 *
 * We can't know ahead of time which of "seatservice" vs "seat-service" the
 * prefix came from — entity-loader.candidateIdFromSegment collapses the
 * URL segment, so the id prefix is always the dash-free version. Return the
 * dash-free prefix and let loadEntity() re-expand via its internal lookup.
 */
async function loadEntityByFullId(id: string): Promise<EntityPayload | null> {
  const dashIdx = id.indexOf("-");
  if (dashIdx < 0) return null;
  const prefix = id.slice(0, dashIdx);
  const slug = id.slice(dashIdx + 1);
  return loadEntity(prefix, slug);
}

export default async function GraphPage({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string }>;
}) {
  const { focus } = await searchParams;
  const [status, initialEntity] = await Promise.all([
    loadStatus(),
    focus ? loadEntityByFullId(focus) : Promise.resolve(null),
  ]);

  // EntityPayload contains Neo4j Integer values on properties — strip them
  // before the boundary so React accepts the prop. The explorer-client
  // doesn't read `properties` directly.
  const serializable = initialEntity
    ? {
        ...initialEntity,
        properties: {},
      }
    : null;

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <StatusBar
        connected={status.connected}
        nodeCount={status.node_count}
        edgeCount={status.edge_count}
        jurisdictionCount={status.jurisdiction_count}
        ingestAt={status.ingest_at}
        subgraphsBuiltAt={status.subgraphs_built_at}
      />
      <NavHeader currentPath="/graph" />
      <ExplorerClient initial={serializable} ingestAt={status.ingest_at} />
    </div>
  );
}
