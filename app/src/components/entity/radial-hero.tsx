// Stub for Batch F. Reserves the radial-hero layout slot so Tier 1 pages
// render with correct proportions; the Cytoscape implementation lands in
// Plan 2 Batch F, Task 18.

import type { EntityPayload } from "@/lib/server/entity-loader";

export function RadialHero({ entity }: { entity: EntityPayload }) {
  void entity;
  return (
    <div
      className="flex min-h-[420px] items-center justify-center bg-[radial-gradient(ellipse_at_center,#121821_0%,#05070a_90%)]"
      data-testid="radial-hero-stub"
    >
      <span className="font-mono text-xs text-hairline">radial hero — Batch F</span>
    </div>
  );
}
