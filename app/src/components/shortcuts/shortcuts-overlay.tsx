"use client";

// Task 4 will flesh out the cheat-sheet visual. For now this stub is enough
// for the provider + tests to verify open/close semantics.

export type ShortcutsOverlayProps = {
  open: boolean;
  onClose: () => void;
};

export function ShortcutsOverlay({ open, onClose }: ShortcutsOverlayProps) {
  if (!open) return null;
  return (
    <div
      data-testid="shortcuts-overlay"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[480px] max-w-[95vw] rounded border border-border-primary bg-panel p-4 font-mono text-xs text-body"
      >
        SHORTCUTS
      </div>
    </div>
  );
}
