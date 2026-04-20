// app/src/components/data/data-query-nav.tsx
//
// Left-rail nav for the /data explorer. Lists the 10 predefined queries;
// active slug is highlighted. Plex Mono, matches the Catalog rail styling on
// the homepage.

import Link from "next/link";
import { DATA_QUERIES } from "@/lib/server/data-queries";

export type DataQueryNavProps = {
  /** Active query slug, or `null` when on the /data index. */
  activeSlug: string | null;
};

export function DataQueryNav({ activeSlug }: DataQueryNavProps) {
  return (
    <aside className="w-[240px] shrink-0 border-r border-border-hairline bg-bg p-[18px]">
      <h2 className="mb-3 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-dim">
        Predefined queries
      </h2>
      <nav className="font-mono text-xs">
        {DATA_QUERIES.map((q) => {
          const isActive = q.slug === activeSlug;
          return (
            <Link
              key={q.slug}
              href={`/data/${q.slug}`}
              className={
                isActive
                  ? "mb-0.5 block rounded-sm border-l-2 border-[#a4e8bf] bg-surface px-2 py-1.5 text-body"
                  : "mb-0.5 block rounded-sm border-l-2 border-transparent px-2 py-1.5 text-body hover:bg-surface"
              }
              aria-current={isActive ? "page" : undefined}
            >
              {q.display_name}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
