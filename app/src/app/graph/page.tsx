import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { loadStatus } from "@/lib/server/homepage-data";
import { loadEntityById } from "@/lib/server/entity-loader";
import type { EntityPayload } from "@/lib/server/entity-loader";
import { ExplorerClient } from "./explorer-client";

// Force dynamic — the explorer must reflect the live INGEST timestamp and
// (when focused) a live entity neighborhood query.
export const dynamic = "force-dynamic";

export default async function GraphPage({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string }>;
}) {
  const { focus } = await searchParams;
  const [status, initialEntity] = await Promise.all([
    loadStatus(),
    focus ? loadEntityById(focus) : Promise.resolve(null),
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
