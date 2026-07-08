// Neighbor cards grouped by relationship (edge) type. Per spec §7.1 item 7.
// Each group: Plex Mono 10px uppercase heading + list of clickable cards.
// Each card: type badge + Plex Sans title + mini-meta. Whole card is a link.

import Link from "next/link";
import type { EntityPayload, Neighbor } from "@/lib/server/entity-loader";
import { canonicalType } from "@/lib/canonical-type";
import { displayNameForType, urlSegmentForType } from "@/lib/type-display";

type Grouped = {
  relType: string;
  neighbors: Neighbor[];
};

function humanizeRel(rel: string): string {
  // e.g. PARTICIPATES_IN → participates in
  return rel.toLowerCase().replace(/_/g, " ");
}

function groupNeighborsByRel(entity: EntityPayload): Grouped[] {
  const byId = new Map(entity.neighbors.map((n) => [n.id, n]));
  const groups = new Map<string, Neighbor[]>();

  for (const edge of entity.edges) {
    // Edge touching the focus: group the other endpoint under its rel type.
    const otherId =
      edge.source === entity.id
        ? edge.target
        : edge.target === entity.id
          ? edge.source
          : null;
    if (!otherId) continue;
    const n = byId.get(otherId);
    if (!n) continue;
    if (!groups.has(edge.type)) groups.set(edge.type, []);
    const list = groups.get(edge.type)!;
    if (!list.find((x) => x.id === n.id)) list.push(n);
  }

  // Any neighbors not picked up by an edge (orphans) go under "related".
  const claimed = new Set<string>();
  for (const list of groups.values()) for (const n of list) claimed.add(n.id);
  const orphans = entity.neighbors.filter((n) => !claimed.has(n.id));
  if (orphans.length > 0) {
    groups.set("RELATED", orphans);
  }

  // Sort groups by relation name and cards within each group by id, so the
  // same entity renders the same Connections layout every time regardless of
  // AuraDB's traversal plan. RELATED goes last as a catch-all.
  const entries = Array.from(groups.entries())
    .map(([relType, neighbors]): Grouped => ({
      relType,
      neighbors: [...neighbors].sort((a, b) => a.id.localeCompare(b.id)),
    }))
    .sort((a, b) => {
      if (a.relType === "RELATED" && b.relType !== "RELATED") return 1;
      if (b.relType === "RELATED" && a.relType !== "RELATED") return -1;
      return a.relType.localeCompare(b.relType);
    });

  return entries;
}

function neighborMiniMeta(n: Neighbor): string | null {
  // We don't have deep props on neighbors; show type display name as a stable
  // mini-meta line below the card title.
  return displayNameForType(n.type);
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function routeForId(id: string): string | null {
  const type = canonicalType([], id);
  if (!type) return null;
  const slug = id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
  return `/${urlSegmentForType(type)}/${slug}`;
}

function VerifiedMoneyBlock({ entity }: { entity: EntityPayload }) {
  const rollup = entity.money_rollup;
  if (!rollup) return null;

  return (
    <div className="border border-border-hairline bg-panel" data-testid="verified-money">
      <div
        className="border-b border-border-hairline px-3 py-2 font-mono uppercase text-dim"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
      >
        VERIFIED MONEY
      </div>
      <div className="grid gap-3 px-3 py-3 font-mono md:grid-cols-[220px_1fr]">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="text-body" style={{ fontSize: "16px" }}>
              {formatMoney(rollup.money_in_total)}
            </div>
            <div className="text-hairline" style={{ fontSize: "10px", letterSpacing: "0.08em" }}>
              {rollup.flows_in_count} in
            </div>
          </div>
          <div>
            <div className="text-body" style={{ fontSize: "16px" }}>
              {formatMoney(rollup.money_out_total)}
            </div>
            <div className="text-hairline" style={{ fontSize: "10px", letterSpacing: "0.08em" }}>
              {rollup.flows_out_count} out
            </div>
          </div>
        </div>
        {rollup.top_counterparties.length > 0 && (
          <ul className="grid gap-1">
            {rollup.top_counterparties.map((counterparty) => {
              const route = routeForId(counterparty.id);
              const inner = (
                <>
                  <span className="text-body">{counterparty.label}</span>
                  <span className="text-hairline">{formatMoney(counterparty.total)}</span>
                </>
              );
              return (
                <li key={counterparty.id}>
                  {route ? (
                    <Link
                      href={route}
                      className="grid grid-cols-[1fr_auto] gap-3 border border-border-hairline px-2 py-1.5 hover:bg-surface"
                      style={{ fontSize: "11px" }}
                    >
                      {inner}
                    </Link>
                  ) : (
                    <div
                      className="grid grid-cols-[1fr_auto] gap-3 border border-border-hairline px-2 py-1.5"
                      style={{ fontSize: "11px" }}
                    >
                      {inner}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

export function Connections({ entity }: { entity: EntityPayload }) {
  const hasNeighbors = entity.neighbors.length > 0;
  const hasMoney = entity.money_rollup !== undefined && entity.money_rollup !== null;
  if (!hasNeighbors && !hasMoney) return null;

  const groups = hasNeighbors ? groupNeighborsByRel(entity) : [];
  const overflow = entity.neighbor_total - entity.neighbors.length;

  return (
    <section className="px-[18px] py-6" data-testid="connections">
      <div className="grid gap-6">
        <VerifiedMoneyBlock entity={entity} />
        {hasNeighbors && (
          <>
            <div
              className="font-mono uppercase text-dim"
              style={{ fontSize: "10px", letterSpacing: "0.14em" }}
            >
              Connections
            </div>
            {groups.map((g) => (
              <div key={g.relType} data-testid="connection-group">
                <div
                  className="mb-2 font-mono uppercase text-hairline"
                  style={{ fontSize: "10px", letterSpacing: "0.14em" }}
                  data-testid="connection-group-heading"
                >
                  {humanizeRel(g.relType)}
                  <span className="ml-2 text-hairline">{g.neighbors.length}</span>
                </div>
                <ul className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
                  {g.neighbors.map((n) => (
                    <li key={n.id}>
                      <Link
                        href={n.route}
                        className="block border border-border-hairline bg-panel px-3 py-2.5 transition hover:border-[#262b35] hover:bg-surface"
                      >
                        <div
                          className="font-mono uppercase text-dim"
                          style={{ fontSize: "10px", letterSpacing: "0.14em" }}
                        >
                          {n.type}
                        </div>
                        <div
                          className="mt-1 text-body"
                          style={{
                            fontFamily: "var(--font-plex-sans), ui-sans-serif, sans-serif",
                            fontWeight: 500,
                            fontSize: "13.5px",
                            lineHeight: 1.35,
                          }}
                        >
                          {n.label}
                        </div>
                        {neighborMiniMeta(n) && (
                          <div
                            className="mt-1 font-mono text-hairline"
                            style={{ fontSize: "11px" }}
                          >
                            {neighborMiniMeta(n)}
                          </div>
                        )}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </>
        )}
      </div>
      {hasNeighbors && overflow > 0 && (
        <div className="mt-4">
          <Link
            href={`/graph?focus=${encodeURIComponent(entity.id)}`}
            className="font-mono text-dim hover:text-body"
            style={{ fontSize: "11px", letterSpacing: "0.08em" }}
            data-testid="connections-overflow"
          >
            + {overflow} more connections →
          </Link>
        </div>
      )}
    </section>
  );
}
