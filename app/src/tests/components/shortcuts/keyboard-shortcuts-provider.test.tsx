import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useContext } from "react";
import {
  KeyboardShortcutsProvider,
  PaletteContext,
} from "@/components/shortcuts/keyboard-shortcuts-provider";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

// Small consumer that exposes palette open-state to the DOM so tests can
// assert against it without poking at internal state.
function PaletteProbe() {
  const { open } = useContext(PaletteContext);
  return <div data-testid="palette-open">{open ? "open" : "closed"}</div>;
}

describe("KeyboardShortcutsProvider", () => {
  beforeEach(() => {
    push.mockReset();
  });

  afterEach(() => {
    // Leave body clean so overlay/palette portals don't leak between tests.
  });

  it("renders children", () => {
    render(
      <KeyboardShortcutsProvider>
        <div data-testid="child">hello</div>
      </KeyboardShortcutsProvider>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("⌘K opens the palette via PaletteContext", () => {
    render(
      <KeyboardShortcutsProvider>
        <PaletteProbe />
      </KeyboardShortcutsProvider>,
    );
    expect(screen.getByTestId("palette-open").textContent).toBe("closed");
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    expect(screen.getByTestId("palette-open").textContent).toBe("open");
  });

  it("g g navigates to /graph", () => {
    render(
      <KeyboardShortcutsProvider>
        <div />
      </KeyboardShortcutsProvider>,
    );
    act(() => {
      fireEvent.keyDown(window, { key: "g" });
      fireEvent.keyDown(window, { key: "g" });
    });
    expect(push).toHaveBeenCalledWith("/graph");
  });

  it("? opens the shortcuts overlay", () => {
    render(
      <KeyboardShortcutsProvider>
        <div />
      </KeyboardShortcutsProvider>,
    );
    expect(screen.queryByTestId("shortcuts-overlay")).toBeNull();
    act(() => {
      fireEvent.keyDown(window, { key: "?" });
    });
    expect(screen.getByTestId("shortcuts-overlay")).toBeInTheDocument();
  });

  it("chord suppressed when focus is in a text input", () => {
    render(
      <KeyboardShortcutsProvider>
        <input data-testid="focusable" />
      </KeyboardShortcutsProvider>,
    );
    const input = screen.getByTestId("focusable") as HTMLInputElement;
    input.focus();
    act(() => {
      // Fire on the input so e.target matches the focused input; the chord
      // machine suppresses everything except Escape inside text inputs.
      fireEvent.keyDown(input, { key: "g" });
      fireEvent.keyDown(input, { key: "h" });
    });
    expect(push).not.toHaveBeenCalled();
  });

  it("Escape closes an open shortcuts overlay", () => {
    render(
      <KeyboardShortcutsProvider>
        <div />
      </KeyboardShortcutsProvider>,
    );
    act(() => {
      fireEvent.keyDown(window, { key: "?" });
    });
    expect(screen.getByTestId("shortcuts-overlay")).toBeInTheDocument();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByTestId("shortcuts-overlay")).toBeNull();
  });

  it("/ focuses a visible input[name=q] when present", () => {
    render(
      <KeyboardShortcutsProvider>
        <input name="q" data-testid="q" />
      </KeyboardShortcutsProvider>,
    );
    const q = screen.getByTestId("q") as HTMLInputElement;
    expect(document.activeElement).not.toBe(q);
    act(() => {
      fireEvent.keyDown(window, { key: "/" });
    });
    expect(document.activeElement).toBe(q);
    expect(push).not.toHaveBeenCalled();
  });

  it("/ opens the palette when there is no homepage prompt-search input", () => {
    render(
      <KeyboardShortcutsProvider>
        <PaletteProbe />
      </KeyboardShortcutsProvider>,
    );
    expect(screen.getByTestId("palette-open").textContent).toBe("closed");
    act(() => {
      fireEvent.keyDown(window, { key: "/" });
    });
    expect(screen.getByTestId("palette-open").textContent).toBe("open");
    expect(push).not.toHaveBeenCalled();
  });

  it("⌘K keydown has preventDefault called (blocks browser omnibox)", () => {
    render(
      <KeyboardShortcutsProvider>
        <div />
      </KeyboardShortcutsProvider>,
    );
    const ev = new KeyboardEvent("keydown", {
      key: "k",
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      window.dispatchEvent(ev);
    });
    expect(ev.defaultPrevented).toBe(true);
  });

  it("an unhandled key does NOT have preventDefault called", () => {
    render(
      <KeyboardShortcutsProvider>
        <div />
      </KeyboardShortcutsProvider>,
    );
    const ev = new KeyboardEvent("keydown", {
      key: "x",
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      window.dispatchEvent(ev);
    });
    expect(ev.defaultPrevented).toBe(false);
  });

  it("while palette is open, chord keys do NOT fire navigation", () => {
    render(
      <KeyboardShortcutsProvider>
        <PaletteProbe />
      </KeyboardShortcutsProvider>,
    );
    // Open the palette first.
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    expect(screen.getByTestId("palette-open").textContent).toBe("open");
    // Now a `g g` chord must NOT navigate — the palette owns the keyboard.
    act(() => {
      fireEvent.keyDown(window, { key: "g" });
      fireEvent.keyDown(window, { key: "g" });
    });
    expect(push).not.toHaveBeenCalled();
  });

  it("while overlay is open, ⌘K does NOT open the palette", () => {
    render(
      <KeyboardShortcutsProvider>
        <PaletteProbe />
      </KeyboardShortcutsProvider>,
    );
    // Open the overlay first.
    act(() => {
      fireEvent.keyDown(window, { key: "?" });
    });
    expect(screen.getByTestId("shortcuts-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("palette-open").textContent).toBe("closed");
    // ⌘K should be suppressed while overlay is open — overlay takes precedence.
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    expect(screen.getByTestId("palette-open").textContent).toBe("closed");
  });

  it("while overlay is open, Escape closes it", () => {
    render(
      <KeyboardShortcutsProvider>
        <div />
      </KeyboardShortcutsProvider>,
    );
    act(() => {
      fireEvent.keyDown(window, { key: "?" });
    });
    expect(screen.getByTestId("shortcuts-overlay")).toBeInTheDocument();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByTestId("shortcuts-overlay")).toBeNull();
  });

  it("opening the overlay restores focus on close", () => {
    render(
      <KeyboardShortcutsProvider>
        <button data-testid="trigger">trigger</button>
      </KeyboardShortcutsProvider>,
    );
    const trigger = screen.getByTestId("trigger") as HTMLButtonElement;
    trigger.focus();
    expect(document.activeElement).toBe(trigger);
    act(() => {
      fireEvent.keyDown(window, { key: "?" });
    });
    // Overlay moved focus to its close button.
    expect(document.activeElement).not.toBe(trigger);
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(screen.queryByTestId("shortcuts-overlay")).toBeNull();
    // Focus restored to the originally-focused element.
    expect(document.activeElement).toBe(trigger);
  });
});
