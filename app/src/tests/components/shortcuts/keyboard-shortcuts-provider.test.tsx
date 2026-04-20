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

  it("/ routes to /search?q= when there is no homepage prompt-search input", () => {
    render(
      <KeyboardShortcutsProvider>
        <div />
      </KeyboardShortcutsProvider>,
    );
    act(() => {
      fireEvent.keyDown(window, { key: "/" });
    });
    expect(push).toHaveBeenCalledWith("/search?q=");
  });
});
