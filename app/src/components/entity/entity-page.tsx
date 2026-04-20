// Shared entity-page layout composer per spec §7.1 (Tier 1) + §7.2 (Tier 2).
//
// Composition order:
//   StatusBar → NavHeader → HeroTitle
//   → (Tier 1) HeroStats
//   → main grid: (Tier 1) RadialHero 70% + FactsPanel 30%
//                (Tier 2)                  FactsPanel full width
//   → Connections
//   → (Tier 1) TimelineRibbon
//   → EditorialCallout (optional)
//   → EvidenceDrawer
//
// Batch F completes the Tier 1 picture: HeroStats, RadialHero (Cytoscape
// concentric), and TimelineRibbon are real.

import type { EntityPayload } from "@/lib/server/entity-loader";
import type { NodeType } from "@/lib/type-display";
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { HeroTitle } from "@/components/entity/hero-title";
import { HeroStats } from "@/components/entity/hero-stats";
import { RadialHero } from "@/components/entity/radial-hero";
import { toRadialHeroData } from "@/components/entity/radial-hero-data";
import { FactsPanel } from "@/components/entity/facts-panel";
import { Connections } from "@/components/entity/connections";
import { TimelineRibbon } from "@/components/entity/timeline-ribbon";
import { EditorialCallout } from "@/components/entity/editorial-callout";
import { EvidenceDrawer } from "@/components/entity/evidence-drawer";
import { RecentEntityTracker } from "@/components/shortcuts/recent-entity-tracker";
import { loadStatus } from "@/lib/server/homepage-data";
import { loadEvidence } from "@/lib/server/entity-evidence";
import { urlSegmentForType } from "@/lib/type-display";

/**
 * Tier 1 focus types — mirrors entity-loader.ts. Exported so Batch F
 * components can use the same set without re-deriving it.
 */
export const TIER_1_FOCUS_TYPES: ReadonlySet<NodeType> = new Set<NodeType>([
  "Person",
  "Decision",
  "Project",
  "Program",
  "Case",
  "Meeting",
  "Filing",
  "Committee",
]);

export function isTier1(type: NodeType): boolean {
  return TIER_1_FOCUS_TYPES.has(type);
}

function routeFor(entity: EntityPayload): string {
  const slug = entity.id.includes("-") ? entity.id.slice(entity.id.indexOf("-") + 1) : entity.id;
  return `/${urlSegmentForType(entity.type)}/${slug}`;
}

/**
 * Record-focus source link (Codex round 1 fix 7). A Record page goes
 * through the Tier-2 shell, so without this the Record's own
 * preferred_public_url never gets prominent treatment — the evidence
 * drawer lists Records that evidence OTHER entities, not records whose
 * focus IS a Record. This component sits above the facts panel.
 */
export function RecordSourceLink({ entity }: { entity: EntityPayload }) {
  const url = entity.properties.preferred_public_url;
  const artifact = entity.properties.preferred_display_artifact;
  if (typeof url === "string" && url.length > 0) {
    return (
      <div className="mx-[18px] mt-3" data-testid="record-source-link">
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded border border-border-primary bg-panel px-4 py-2 font-mono text-sm text-body hover:bg-surface"
        >
          <span className="text-[10px] uppercase tracking-[0.12em] text-hairline">source</span>
          <span>{typeof artifact === "string" && artifact.length > 0 ? artifact : "open source"}</span>
          <span className="text-dim">↗</span>
        </a>
      </div>
    );
  }
  return (
    <div
      className="mx-[18px] mt-3 rounded border border-border-primary bg-panel px-4 py-2 font-mono text-sm text-dim"
      data-testid="record-source-link-empty"
    >
      no public source captured
    </div>
  );
}

export async function EntityPage({ entity }: { entity: EntityPayload }) {
  const [status, records] = await Promise.all([
    loadStatus(),
    loadEvidence(entity.id).catch((err) => {
      console.warn(`[entity-page] evidence load failed for ${entity.id}:`, err);
      return [];
    }),
  ]);

  const tier1 = isTier1(entity.type);
  const currentPath = routeFor(entity);

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
      <NavHeader currentPath={currentPath} />
      <HeroTitle entity={entity} />
      {tier1 && <HeroStats entity={entity} />}
      {entity.type === "Record" && <RecordSourceLink entity={entity} />}

      <div
        className="mx-[18px] mt-4 grid gap-4"
        style={{ gridTemplateColumns: tier1 ? "7fr 3fr" : "1fr" }}
      >
        {tier1 && (
          <div
            className="relative min-h-[420px] rounded border border-border-primary"
            style={{
              background:
                "radial-gradient(ellipse at center,#121821 0%,#05070a 90%)",
            }}
          >
            <RadialHero data={toRadialHeroData(entity)} />
          </div>
        )}
        <div>
          <FactsPanel entity={entity} />
        </div>
      </div>

      <Connections entity={entity} />

      {tier1 && <TimelineRibbon entity={entity} />}

      <EditorialCallout entity={entity} />

      <EvidenceDrawer records={records} />

      <RecentEntityTracker
        entity={{ id: entity.id, type: entity.type, search_label: entity.label }}
      />
    </div>
  );
}
