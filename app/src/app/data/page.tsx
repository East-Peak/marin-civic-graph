// app/src/app/data/page.tsx
//
// /data index — left rail + welcome panel. Selecting a query navigates to
// /data/{slug}.

import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { DataQueryNav } from "@/components/data/data-query-nav";
import { loadStatus } from "@/lib/server/homepage-data";

export const dynamic = "force-dynamic";

export default async function DataHomePage() {
  const status = await loadStatus();
  return (
    <div className="min-h-screen bg-bg">
      <StatusBar
        connected={status.connected}
        nodeCount={status.node_count}
        edgeCount={status.edge_count}
        jurisdictionCount={status.jurisdiction_count}
        ingestAt={status.ingest_at}
        subgraphsBuiltAt={status.subgraphs_built_at}
      />
      <NavHeader currentPath="/data" />
      <div className="flex gap-0">
        <DataQueryNav activeSlug={null} />
        <div className="flex-1 p-8 font-mono text-sm text-dim">
          <h1 className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-hairline">
            Data explorer
          </h1>
          <p className="mb-1 text-body">Pick a query from the left rail.</p>
          <p className="text-dim">
            Each template runs a parameterized Cypher against AuraDB. Filters
            apply on the URL; the table sorts in-browser; CSV export is a
            single click.
          </p>
        </div>
      </div>
    </div>
  );
}
