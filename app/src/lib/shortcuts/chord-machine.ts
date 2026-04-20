export type ChordEvent =
  | { kind: "palette" }
  | { kind: "focus-search" }
  | { kind: "navigate"; to: "/" | "/graph" | "/data" | "/chat" }
  | { kind: "overlay"; open: boolean }
  | { kind: "escape" };

export type KeyState = {
  buffer: string | null;
  buffer_at: number;
};

const CHORD_WINDOW_MS = 800;

const CHORD_NAV: Record<string, "/" | "/graph" | "/data" | "/chat"> = {
  h: "/",
  g: "/graph",
  d: "/data",
  c: "/chat",
};

export function initState(): KeyState {
  return { buffer: null, buffer_at: 0 };
}

function isTextInput(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return true;
  if (target.getAttribute("contenteditable") === "true") return true;
  return false;
}

export function handleKey(
  state: KeyState,
  e: {
    key: string;
    meta: boolean;
    ctrl: boolean;
    target: EventTarget | null;
    isComposing?: boolean;
  },
  nowMs: number,
): { state: KeyState; events: ChordEvent[] } {
  // During IME composition (e.g. Japanese/Chinese input) all keys belong to
  // the composer — Escape cancels the composition, Enter commits it, and
  // single letters feed candidate windows. Our shortcuts must not steal.
  if (e.isComposing === true) {
    return { state, events: [] };
  }

  // Escape always emits, even inside text inputs (exit focus / close modal).
  if (e.key === "Escape") {
    return { state: initState(), events: [{ kind: "escape" }] };
  }

  // ⌘K / Ctrl+K — palette. Works inside inputs too: the modifier means the
  // user is explicitly invoking a command, not typing.
  if ((e.meta || e.ctrl) && (e.key === "k" || e.key === "K")) {
    return { state: initState(), events: [{ kind: "palette" }] };
  }

  // Inside a text input: swallow non-modifier shortcuts. Single keys like
  // "/", "?", "g" would conflict with typing.
  if (isTextInput(e.target)) {
    return { state, events: [] };
  }

  // Drop an expired buffer before processing this key.
  let working: KeyState = state;
  if (working.buffer !== null && nowMs - working.buffer_at > CHORD_WINDOW_MS) {
    working = initState();
  }

  // Complete an in-flight chord if the leader is buffered.
  if (working.buffer === "g") {
    const to = CHORD_NAV[e.key];
    if (to) {
      return { state: initState(), events: [{ kind: "navigate", to } satisfies ChordEvent] };
    }
    // Second key doesn't complete — drop buffer, fall through to normal handling.
    working = initState();
  }

  // Single-key shortcuts that do not require modifiers.
  if (e.key === "/") {
    return { state: initState(), events: [{ kind: "focus-search" }] };
  }

  if (e.key === "?") {
    return { state: initState(), events: [{ kind: "overlay", open: true }] };
  }

  // Chord leader.
  if (e.key === "g") {
    return { state: { buffer: "g", buffer_at: nowMs }, events: [] };
  }

  return { state: working, events: [] };
}
