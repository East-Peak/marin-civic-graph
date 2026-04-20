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

  // Remember the element that had focus when a dialog opened, so we can
  // restore it on close (a11y: focus should not land on <body> after a
  // modal closes — it should return to whatever triggered the open).
  //
  // Capture happens synchronously in `openPalette` / `openOverlay` BEFORE
  // the dialog mounts, because once the dialog renders its own useEffect
  // steals focus to the input / close button, and by the time our own
  // effect runs `document.activeElement` would already be the dialog.
  const previouslyFocusedByPalette = useRef<HTMLElement | null>(null);
  const previouslyFocusedByOverlay = useRef<HTMLElement | null>(null);

  const openPalette = useCallback(() => {
    previouslyFocusedByPalette.current =
      (document.activeElement as HTMLElement | null) ?? null;
    setPaletteOpen(true);
  }, []);

  const togglePalette = useCallback(() => {
    setPaletteOpen((v) => {
      if (!v) {
        previouslyFocusedByPalette.current =
          (document.activeElement as HTMLElement | null) ?? null;
      }
      return !v;
    });
  }, []);

  const openOverlay = useCallback(() => {
    previouslyFocusedByOverlay.current =
      (document.activeElement as HTMLElement | null) ?? null;
    setOverlayOpen(true);
  }, []);

  // Wrap the state setter used by the PaletteContext so consumers (the
  // palette itself, click-to-dismiss) get focus-restoration for free.
  const setPaletteOpenExternal = useCallback((next: boolean) => {
    setPaletteOpen((prev) => {
      if (!prev && next) {
        previouslyFocusedByPalette.current =
          (document.activeElement as HTMLElement | null) ?? null;
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (!paletteOpen) {
      const el = previouslyFocusedByPalette.current;
      previouslyFocusedByPalette.current = null;
      if (el && el.isConnected) {
        el.focus();
      }
    }
  }, [paletteOpen]);

  useEffect(() => {
    if (!overlayOpen) {
      const el = previouslyFocusedByOverlay.current;
      previouslyFocusedByOverlay.current = null;
      if (el && el.isConnected) {
        el.focus();
      }
    }
  }, [overlayOpen]);

  const handleEvent = useCallback(
    (e: KeyboardEvent) => {
      // While any modal is open the dialog owns the keyboard. The window
      // listener must not produce fresh chord events (no new `g h`
      // navigation, no new `?` overlay) — only Escape is handled globally
      // as a failsafe close. The palette's own onKeyDown handler also
      // catches Escape, but we keep this here so the overlay (which has
      // no text input to own key events) still closes.
      //
      // Before returning we still block reserved browser chords (⌘K / Ctrl+K
      // for the omnibox, "/" for quick-find) so the browser's own UI doesn't
      // steal focus from our open dialog when e.g. focus is on the palette's
      // "include records" checkbox or the overlay's close button.
      if (paletteOpen || overlayOpen) {
        const isPaletteChord =
          (e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K");
        const isQuickFind =
          e.key === "/" &&
          !(
            e.target instanceof HTMLInputElement ||
            e.target instanceof HTMLTextAreaElement
          );
        if (isPaletteChord || isQuickFind) {
          e.preventDefault();
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setPaletteOpen(false);
          setOverlayOpen(false);
        }
        return;
      }

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
            togglePalette();
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
              openPalette();
            }
            break;
          }
          case "navigate":
            router.push(ev.to);
            break;
          case "overlay":
            if (ev.open) {
              openOverlay();
            } else {
              setOverlayOpen(false);
            }
            break;
          case "escape":
            setPaletteOpen(false);
            setOverlayOpen(false);
            break;
        }
      }
    },
    [router, paletteOpen, overlayOpen, togglePalette, openPalette, openOverlay],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleEvent);
    return () => window.removeEventListener("keydown", handleEvent);
  }, [handleEvent]);

  return (
    <PaletteContext.Provider value={{ open: paletteOpen, setOpen: setPaletteOpenExternal }}>
      {children}
      <CommandPalette />
      <ShortcutsOverlay open={overlayOpen} onClose={() => setOverlayOpen(false)} />
    </PaletteContext.Provider>
  );
}
