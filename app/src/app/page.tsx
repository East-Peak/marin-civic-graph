import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { PromptSearch } from "@/components/layout/prompt-search";
import { CatalogList } from "@/components/home/catalog-list";
import { SignatureSubgraph } from "@/components/home/signature-subgraph";
import { TrackingThreads } from "@/components/home/tracking-threads";
import type { NodeType } from "@/lib/type-display";
import { ALL_TYPES } from "@/lib/type-display";

type StatusResponse = {
  connected: boolean;
  node_count: number;
  edge_count: number;
  jurisdiction_count: number;
  ingest_at: string | null;
  subgraphs_built_at: string | null;
};

type CatalogResponse = {
  built_at: string;
  counts: Partial<Record<NodeType, number>>;
};

function blankCounts(): Record<NodeType, number> {
  return Object.fromEntries(ALL_TYPES.map((t) => [t, 0])) as Record<NodeType, number>;
}

async function fetchStatus(): Promise<StatusResponse> {
  try {
    const res = await fetch(`${process.env.APP_URL ?? "http://localhost:3000"}/api/status`, {
      cache: "no-store",
    });
    return (await res.json()) as StatusResponse;
  } catch {
    return {
      connected: false,
      node_count: 0,
      edge_count: 0,
      jurisdiction_count: 0,
      ingest_at: null,
      subgraphs_built_at: null,
    };
  }
}

async function fetchCatalog(): Promise<CatalogResponse> {
  try {
    const res = await fetch(`${process.env.APP_URL ?? "http://localhost:3000"}/api/catalog`, {
      cache: "no-store",
    });
    return (await res.json()) as CatalogResponse;
  } catch {
    return { built_at: new Date().toISOString(), counts: {} };
  }
}

export default async function Home() {
  const [status, catalog] = await Promise.all([fetchStatus(), fetchCatalog()]);
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
