import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { PromptSearch } from "@/components/layout/prompt-search";
import { CatalogList } from "@/components/home/catalog-list";
import { SignatureSubgraph } from "@/components/home/signature-subgraph";
import { TrackingThreads } from "@/components/home/tracking-threads";
import { loadStatus, loadCatalog } from "@/lib/server/homepage-data";
import { ALL_TYPES, type NodeType } from "@/lib/type-display";

// Render on each request so status-bar INGEST timestamp and catalog counts reflect
// the latest refresh, not the build timestamp. Otherwise Next.js statically
// prerenders this route and freezes the data at deploy time.
export const dynamic = "force-dynamic";

function blankCounts(): Record<NodeType, number> {
  return Object.fromEntries(ALL_TYPES.map((t) => [t, 0])) as Record<NodeType, number>;
}

export default async function Home() {
  const [status, catalog] = await Promise.all([loadStatus(), loadCatalog()]);
  const counts = { ...blankCounts(), ...catalog.counts };

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
      <NavHeader currentPath="/" />
      <PromptSearch />
      <div className="mx-[18px] mt-4 grid grid-cols-[25%_50%_25%] border border-border-primary bg-bg">
        <div className="border-r border-border-hairline">
          <CatalogList counts={counts} />
        </div>
        <div className="min-h-[420px] bg-[radial-gradient(ellipse_at_center,#121821_0%,#05070a_90%)]">
          <SignatureSubgraph />
        </div>
        <div className="border-l border-border-hairline">
          <TrackingThreads />
        </div>
      </div>
    </div>
  );
}
