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
          isComposing: e.isComposing,
        },
        now,
      );
      chordState.current = state;

      // If the chord machine produced any event, the browser's default
      // (⌘K omnibox, "/" quick-find, etc.) would conflict with our shortcut.
      // Suppress it. Only our shortcuts are affected; unrelated keys fall
      // through untouched.
      if (events.length > 0) {
        e.preventDefault();
      }

      for (const ev of events) {
        switch (ev.kind) {
          case "palette":
            // ⌘K toggles.
            setPaletteOpen((v) => !v);
            break;
          case "focus-search": {
            // Prefer focusing a visible input[name="q"] (homepage prompt
            // search, search page input). Otherwise open the palette — do
            // NOT push to /search?q= since that forces a navigation with
            // nothing to search for yet.
            const input = document.querySelector<HTMLInputElement>(
              'input[name="q"]',
            );
            if (input) {
              input.focus();
            } else {
              setPaletteOpen(true);
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
