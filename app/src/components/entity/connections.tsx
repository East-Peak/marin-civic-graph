// Neighbor cards grouped by relationship (edge) type. Per spec §7.1 item 7.
// Each group: Plex Mono 10px uppercase heading + list of clickable cards.
// Each card: type badge + Plex Sans title + mini-meta. Whole card is a link.

import Link from "next/link";
import type { EntityPayload, Neighbor } from "@/lib/server/entity-loader";
import { displayNameForType } from "@/lib/type-display";

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

  return Array.from(groups.entries()).map(([relType, neighbors]) => ({
    relType,
    neighbors,
  }));
}

function neighborMiniMeta(n: Neighbor): string | null {
  // We don't have deep props on neighbors; show type display name as a stable
  // mini-meta line below the card title.
  return displayNameForType(n.type);
}

export function Connections({ entity }: { entity: EntityPayload }) {
  if (entity.neighbors.length === 0) return null;

  const groups = groupNeighborsByRel(entity);
  const overflow = entity.neighbor_total - entity.neighbors.length;

  return (
    <section className="px-[18px] py-6" data-testid="connections">
      <div
        className="mb-3 font-mono uppercase text-dim"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
      >
        Connections
      </div>
      <div className="grid gap-6">
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
      </div>
      {overflow > 0 && (
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
