"use client";

// Global keyboard shortcut layer (spec §4.4). Installs a single window-level
// keydown listener, routes through the pure chord state machine, and
// dispatches outcomes into router.push / palette / overlay state.
//
// The palette's open-state is exposed via PaletteContext so the
// CommandPalette component (rendered below children) can subscribe without
// prop-drilling through the app tree.

import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { handleKey, initState, type KeyState } from "@/lib/shortcuts/chord-machine";
import { CommandPalette } from "@/components/palette/command-palette";
import { ShortcutsOverlay } from "@/components/shortcuts/shortcuts-overlay";

export const PaletteContext = createContext<{
  open: boolean;
  setOpen: (b: boolean) => void;
}>({
  open: false,
  setOpen: () => {},
});

export function KeyboardShortcutsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [overlayOpen, setOverlayOpen] = useState(false);
  const router = useRouter();

  // Buffer state for chord detection lives in a ref so the keydown listener
  // always reads the current value without re-binding on every event.
  const chordState = useRef<KeyState>(initState());

  const handleEvent = useCallback(
    (e: KeyboardEvent) => {
      const now = Date.now();
      const { state, events } = handleKey(
        chordState.current,
        {
          key: e.key,
          meta: e.metaKey,
          ctrl: e.ctrlKey,
          target: e.target,
        },
        now,
      );
      chordState.current = state;

      for (const ev of events) {
        switch (ev.kind) {
          case "palette":
            // ⌘K toggles.
            setPaletteOpen((v) => !v);
            break;
          case "focus-search": {
            // Prefer focusing the visible homepage prompt-search input; fall
            // back to /search?q= so the user lands somewhere they can type.
            const input = document.querySelector<HTMLInputElement>(
              'input[name="q"]',
            );
            if (input) {
              e.preventDefault();
              input.focus();
            } else {
              router.push("/search?q=");
            }
            break;
          }
          case "navigate":
            router.push(ev.to);
            break;
          case "overlay":
            setOverlayOpen(ev.open);
            break;
          case "escape":
            setPaletteOpen(false);
            setOverlayOpen(false);
            break;
        }
      }
    },
    [router],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleEvent);
    return () => window.removeEventListener("keydown", handleEvent);
  }, [handleEvent]);

  return (
    <PaletteContext.Provider value={{ open: paletteOpen, setOpen: setPaletteOpen }}>
      {children}
      <CommandPalette />
      <ShortcutsOverlay open={overlayOpen} onClose={() => setOverlayOpen(false)} />
    </PaletteContext.Provider>
  );
}
