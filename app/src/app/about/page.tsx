import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { loadStatus, loadCatalog } from "@/lib/server/homepage-data";
import { loadJurisdictions } from "@/lib/server/about-data";
import { ALL_TYPES, displayNameForType, type NodeType } from "@/lib/type-display";

export const dynamic = "force-dynamic";

const SECTION_HEADING: React.CSSProperties = {
  fontFamily: "var(--font-vt323)",
  fontSize: "18px",
  letterSpacing: "0.08em",
};

const STACK: { label: string; detail: string }[] = [
  { label: "Next.js 16", detail: "App Router, React Server Components." },
  { label: "React 19", detail: "Client interactivity for palette, explorer, chat." },
  { label: "Neo4j AuraDB", detail: "Graph store for nodes, edges, and properties." },
  { label: "Cytoscape.js", detail: "Radial and force-directed graph rendering." },
  { label: "IBM Plex + VT323", detail: "Typography: Plex Sans/Mono/Serif plus VT323 terminal." },
  { label: "TypeScript", detail: "End-to-end types from loader to UI." },
];

export default async function AboutPage() {
  const [status, catalog, jurisdictionsResult] = await Promise.all([
    loadStatus(),
    loadCatalog(),
    loadJurisdictions(),
  ]);
  const counts = catalog.counts ?? {};
  const rows = ALL_TYPES.map((t) => ({
    type: t,
    name: displayNameForType(t),
    count: counts[t as NodeType] ?? 0,
  })).filter((r) => r.count > 0);

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
      <NavHeader currentPath="/about" />

      <div className="mx-[18px] mt-6 max-w-3xl pb-16">
        <h1
          className="text-body"
          style={{ fontFamily: "var(--font-vt323)", fontSize: "40px", lineHeight: "1.1" }}
        >
          about Open Marin
        </h1>

        <section className="mt-8">
          <h2 className="mb-2 text-body" style={SECTION_HEADING}>
            WHAT OPEN MARIN IS
          </h2>
          <p className="font-sans text-[14px] leading-[1.55] text-body">
            Open Marin is a dark-mode, terminal-flavored civic-intelligence
            workstation for Marin County. It ingests meeting minutes, rulings,
            filings, contributions, and grants from city and county government
            into a well-structured graph, so you can query how and why
            decisions got made — and trace every claim back to the primary
            source it came from. The product is invite-only and built for
            return users doing investigations, not first-time casual visitors.
          </p>
        </section>

        <section className="mt-8">
          <h2 className="mb-2 text-body" style={SECTION_HEADING}>
            WHAT&rsquo;S IN THE GRAPH
          </h2>
          <div className="rounded border border-border-primary bg-panel">
            {rows.length === 0 ? (
              <div className="px-3 py-2 font-mono text-xs text-dim">
                catalog unavailable
              </div>
            ) : (
              rows.map((row, i) => (
                <div
                  key={row.type}
                  className={
                    "flex items-center justify-between px-3 py-1.5 font-mono text-xs" +
                    (i < rows.length - 1 ? " border-b border-border-hairline" : "")
                  }
                >
                  <span className="text-body">{row.name}</span>
                  <span className="text-hairline">
                    {row.count.toLocaleString()}
                  </span>
                </div>
              ))
            )}
          </div>
          {catalog.built_at && (
            <div
              data-testid="catalog-snapshot"
              className="mt-2 font-mono text-[11px] text-dim"
            >
              snapshot from {catalog.built_at.slice(0, 10)} — live count may differ
            </div>
          )}
        </section>

        <section className="mt-8">
          <h2 className="mb-2 text-body" style={SECTION_HEADING}>
            METHODOLOGY
          </h2>
          <p className="font-sans text-[14px] leading-[1.55] text-body">
            Every node and every edge in this graph traces back to a primary
            source — a staff report, a meeting packet, a court filing, a
            Form 700, a Form 460, a signed contract. We do not paraphrase,
            summarize, or infer facts that the record itself does not state.
            When the provenance is incomplete or unclear, the entity is
            flagged rather than polished. This discipline is the point: it is
            what lets investigations built on Open Marin survive being
            challenged.
          </p>
        </section>

        <section className="mt-8">
          <h2 className="mb-2 text-body" style={SECTION_HEADING}>
            JURISDICTIONS
          </h2>
          <div className="rounded border border-border-primary bg-panel px-3 py-3 font-mono text-xs text-body">
            {!jurisdictionsResult.ok ? (
              <div data-testid="jurisdictions-error" className="text-dim">
                Jurisdictions unavailable (database connection error).
              </div>
            ) : jurisdictionsResult.jurisdictions.length === 0 ? (
              <div data-testid="jurisdictions-empty" className="text-dim">
                No jurisdictions found.
              </div>
            ) : (
              <div
                data-testid="jurisdictions-list"
                className="flex flex-wrap gap-x-4 gap-y-1"
              >
                {jurisdictionsResult.jurisdictions.map((j) => (
                  <span key={j.name}>{j.name}</span>
                ))}
              </div>
            )}
            <div className="mt-2 text-dim">
              Plus county-wide campaign finance and Form 700 filings.
            </div>
          </div>
        </section>

        <section className="mt-8">
          <h2 className="mb-2 text-body" style={SECTION_HEADING}>
            BUILT WITH
          </h2>
          <div className="rounded border border-border-primary bg-panel">
            {STACK.map((item, i) => (
              <div
                key={item.label}
                className={
                  "flex items-baseline justify-between gap-4 px-3 py-1.5 font-mono text-xs" +
                  (i < STACK.length - 1 ? " border-b border-border-hairline" : "")
                }
              >
                <span className="text-body">{item.label}</span>
                <span className="text-right text-dim">{item.detail}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-8">
          <h2 className="mb-2 text-body" style={SECTION_HEADING}>
            CREDITS
          </h2>
          <p className="font-sans text-[14px] leading-[1.55] text-body">
            Stuart Watson, East Peak Advisors. Built with Claude.
          </p>
        </section>
      </div>
    </div>
  );
}
