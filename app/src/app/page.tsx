import "server-only";
import { loadStatus } from "@/lib/server/homepage-data";
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { ConstellationClient } from "@/app/_components/constellation-client";

export const dynamic = "force-dynamic";

export default async function Home() {
  const status = await loadStatus();
  return (
    <main className="min-h-screen bg-background">
      <StatusBar
        connected={status.connected}
        nodeCount={status.node_count}
        edgeCount={status.edge_count}
        jurisdictionCount={status.jurisdiction_count}
        ingestAt={status.ingest_at}
        subgraphsBuiltAt={status.subgraphs_built_at}
      />
      <NavHeader currentPath="/" />
      <ConstellationClient />
    </main>
  );
}
