// Stub for Batch F. Horizontal temporal strip lands in Plan 2 Batch F,
// Task 19. Empty placeholder so Tier 1 pages reserve the space.

import type { EntityPayload } from "@/lib/server/entity-loader";

export function TimelineRibbon({ entity }: { entity: EntityPayload }) {
  void entity;
  return (
    <div
      className="mx-[18px] my-6 flex h-[90px] items-center border border-border-hairline bg-panel px-4 text-hairline"
      data-testid="timeline-ribbon-stub"
    >
      <span className="font-mono" style={{ fontSize: "11px", letterSpacing: "0.08em" }}>
        timeline ribbon — Batch F
      </span>
    </div>
  );
}
