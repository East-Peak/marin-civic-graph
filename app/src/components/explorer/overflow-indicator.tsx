"use client";

// Per-node overflow indicator per spec §6.3.
//
// A static `+{N} more` text chip that sits in the corner of the canvas. The
// explorer-client batches these into a tray — click on a node, cap hits,
// we surface a floating note so the investigator knows more is available.
//
// Intentionally non-interactive in Plan 3: clicking the originating node a
// second time triggers the "next batch" behavior described in the spec.

export type OverflowItem = {
  /** Node id the overflow pertains to. */
  nodeId: string;
  /** Best-effort human label for the node ("Kate Colin" vs the id). */
  label: string;
  /** Remaining neighbor count — displayed as "+N". */
  remaining: number;
};

export type OverflowIndicatorProps = {
  items: OverflowItem[];
};

export function OverflowIndicator({ items }: OverflowIndicatorProps) {
  if (items.length === 0) return null;
  return (
    <div
      data-testid="overflow-indicator"
      className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-w-[40%] flex-col gap-1 font-mono text-[10px] text-hairline"
    >
      {items.slice(0, 6).map((item) => (
        <div
          key={item.nodeId}
          className="rounded border border-[#262b35] bg-panel/80 px-1.5 py-0.5"
        >
          <span className="text-dim">{item.label}</span>{" "}
          <span className="text-[#a4e8bf]">+{item.remaining} more</span>
        </div>
      ))}
      {items.length > 6 && (
        <div className="text-hairline">…and {items.length - 6} more nodes with overflow</div>
      )}
    </div>
  );
}
