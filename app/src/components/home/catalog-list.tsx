import Link from "next/link";
import { urlSegmentForType, displayNameForType, type NodeType } from "@/lib/type-display";

// Grouping per spec §3.4 — display only; each row still maps to /browse/{type}.
// Exported for the node-type parity test (EXHAUSTIVE_GROUPING): these groups +
// the Record footer section below must cover every NodeType exactly once.
export const GROUPS: { heading: string; types: NodeType[] }[] = [
  { heading: "People & organizations", types: ["Person", "Organization"] },
  { heading: "Governance", types: ["Meeting", "AgendaItem", "Decision", "Seat", "SeatService"] },
  { heading: "Elections & campaigns", types: ["Election", "Candidacy", "Committee", "Filing", "MoneyFlow"] },
  { heading: "Programs, projects, agreements", types: ["Program", "Project", "Agreement", "Amendment"] },
  { heading: "Legal", types: ["Case", "Proceeding"] },
  { heading: "Context", types: ["Place", "Issue"] },
];

export type CatalogListProps = {
  counts: Record<NodeType, number>;
};

export function CatalogList({ counts }: CatalogListProps) {
  return (
    <div className="p-[18px]">
      <h2 className="mb-3 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-dim">
        Catalog
      </h2>
      <div className="font-mono text-xs">
        {GROUPS.map((group) => (
          <div key={group.heading} className="mb-3">
            <div className="mb-1 font-medium text-[10px] uppercase tracking-[0.14em] text-hairline">
              {group.heading}
            </div>
            {group.types.map((type) => (
              <Link
                key={type}
                href={`/browse/${urlSegmentForType(type)}`}
                className="flex justify-between rounded-sm px-1.5 py-1 text-body hover:bg-surface"
              >
                <span>{displayNameForType(type)}</span>
                <span className="text-hairline">{(counts[type] ?? 0).toLocaleString()}</span>
              </Link>
            ))}
          </div>
        ))}
        <div className="mt-4 border-t border-border-hairline pt-3">
          <div className="mb-1 font-medium text-[10px] uppercase tracking-[0.14em] text-hairline">
            Records
          </div>
          <Link
            href="/browse/record"
            className="flex justify-between rounded-sm px-1.5 py-1 text-body hover:bg-surface"
          >
            <span>{displayNameForType("Record")}</span>
            <span className="text-hairline">{(counts.Record ?? 0).toLocaleString()}</span>
          </Link>
        </div>
      </div>
    </div>
  );
}
