"use client";

import { useEffect, useRef } from "react";

export type ShortcutsOverlayProps = {
  open: boolean;
  onClose: () => void;
};

type Row = { keys: string; desc: string };

const ROWS: Row[] = [
  { keys: "\u2318K", desc: "Open palette" },
  { keys: "/", desc: "Focus search" },
  { keys: "g h", desc: "Home" },
  { keys: "g g", desc: "Graph" },
  { keys: "g d", desc: "Data" },
  { keys: "g c", desc: "Chat" },
  { keys: "?", desc: "Show this overlay" },
  { keys: "esc", desc: "Close modal / clear focus" },
];

export function ShortcutsOverlay({ open, onClose }: ShortcutsOverlayProps) {
  // When the overlay opens, move focus into the dialog (to the close button).
  // Screen readers and keyboard users otherwise get stranded on whatever
  // fired `?` — usually <body>.
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) {
      closeRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;
  return (
    <div
      data-testid="shortcuts-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="keyboard shortcuts"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[520px] max-w-[95vw] rounded border border-border-primary bg-panel p-4 font-mono text-xs text-body shadow-xl"
      >
        <div
          className="mb-3 text-body"
          style={{
            fontFamily: "var(--font-vt323)",
            fontSize: "16px",
            letterSpacing: "0.08em",
          }}
        >
          KEYBOARD SHORTCUTS
        </div>

        <div className="border-t border-border-hairline">
          {ROWS.map((row) => (
            <div
              key={row.keys}
              className="flex items-center justify-between border-b border-border-hairline px-1 py-1.5"
            >
              <kbd className="rounded border border-border-hairline bg-surface px-1.5 py-0.5 text-[10px] text-body">
                {row.keys}
              </kbd>
              <span className="text-dim">{row.desc}</span>
            </div>
          ))}
        </div>

        <div className="mt-3 flex justify-end">
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="rounded border border-[#262b35] bg-panel px-3 py-1 text-[11px] text-dim hover:bg-surface"
          >
            close
          </button>
        </div>
      </div>
    </div>
  );
}
