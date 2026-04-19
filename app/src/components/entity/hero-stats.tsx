// Stub for Batch F. VT323 30px hero stat strip lands in Plan 2 Batch F,
// Task 17. Rendered (empty) only for Tier 1 focus types so the layout
// reserves its horizontal band.

import type { EntityPayload } from "@/lib/server/entity-loader";

export function HeroStats({ entity }: { entity: EntityPayload }) {
  void entity;
  return (
    <div
      className="mx-[18px] flex items-center gap-8 border-y border-border-hairline bg-panel px-4 py-3 text-hairline"
      data-testid="hero-stats-stub"
    >
      <span className="font-mono" style={{ fontSize: "11px", letterSpacing: "0.08em" }}>
        hero stats — Batch F
      </span>
    </div>
  );
}
