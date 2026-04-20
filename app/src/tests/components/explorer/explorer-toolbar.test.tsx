import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ExplorerToolbar } from "@/components/explorer/explorer-toolbar";
import { parseUrlToState, type ExplorerState } from "@/lib/explorer/explorer-state";

const INGEST = "2026-04-14T09:00:00Z";

function makeState(overrides: Partial<ExplorerState> = {}): ExplorerState {
  const base = parseUrlToState(new URLSearchParams(), INGEST);
  return { ...base, ...overrides };
}

describe("ExplorerToolbar", () => {
  it("renders a HOP indicator reflecting state.hop", () => {
    const state = makeState({ hop: 3 });
    render(<ExplorerToolbar state={state} onStateChange={() => {}} onOpenPath={() => {}} onOpenSaveView={() => {}} />);
    expect(screen.getByText(/HOP 3/i)).toBeInTheDocument();
  });

  it("emits state changes when the hop slider moves", () => {
    const state = makeState({ hop: 2 });
    const onStateChange = vi.fn();
    render(<ExplorerToolbar state={state} onStateChange={onStateChange} onOpenPath={() => {}} onOpenSaveView={() => {}} />);
    const slider = screen.getByLabelText(/hop/i) as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "4" } });
    expect(onStateChange).toHaveBeenCalled();
    const nextState = onStateChange.mock.calls[0][0] as ExplorerState;
    expect(nextState.hop).toBe(4);
  });

  it("clamps hop slider to 1..4 via the input attributes", () => {
    const state = makeState({ hop: 2 });
    render(<ExplorerToolbar state={state} onStateChange={() => {}} onOpenPath={() => {}} onOpenSaveView={() => {}} />);
    const slider = screen.getByLabelText(/hop/i) as HTMLInputElement;
    expect(slider.min).toBe("1");
    expect(slider.max).toBe("4");
  });

  it("reflects default node filters — Record/Place/Issue/AgendaItem off", () => {
    const state = makeState();
    render(<ExplorerToolbar state={state} onStateChange={() => {}} onOpenPath={() => {}} onOpenSaveView={() => {}} />);
    const record = screen.getByTestId("node-filter-Record");
    const person = screen.getByTestId("node-filter-Person");
    expect(record.getAttribute("data-active")).toBe("false");
    expect(person.getAttribute("data-active")).toBe("true");
  });

  it("toggles a node filter on click", () => {
    const state = makeState();
    const onStateChange = vi.fn();
    render(<ExplorerToolbar state={state} onStateChange={onStateChange} onOpenPath={() => {}} onOpenSaveView={() => {}} />);
    const chip = screen.getByTestId("node-filter-Record");
    fireEvent.click(chip);
    expect(onStateChange).toHaveBeenCalled();
    const next = onStateChange.mock.calls[0][0] as ExplorerState;
    expect(next.nodeFilters.Record).toBe(true);
  });

  it("toggles an edge filter on click", () => {
    const state = makeState();
    const onStateChange = vi.fn();
    render(<ExplorerToolbar state={state} onStateChange={onStateChange} onOpenPath={() => {}} onOpenSaveView={() => {}} />);
    const chip = screen.getByTestId("edge-filter-money");
    expect(chip.getAttribute("data-active")).toBe("true");
    fireEvent.click(chip);
    const next = onStateChange.mock.calls[0][0] as ExplorerState;
    expect(next.edgeFilters.money).toBe(false);
  });

  it("fires the path + save-view callbacks", () => {
    const onOpenPath = vi.fn();
    const onOpenSaveView = vi.fn();
    render(
      <ExplorerToolbar
        state={makeState()}
        onStateChange={() => {}}
        onOpenPath={onOpenPath}
        onOpenSaveView={onOpenSaveView}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /find path/i }));
    fireEvent.click(screen.getByRole("button", { name: /save view/i }));
    expect(onOpenPath).toHaveBeenCalled();
    expect(onOpenSaveView).toHaveBeenCalled();
  });

  it("updates the time range when the date inputs change", () => {
    const state = makeState();
    const onStateChange = vi.fn();
    render(<ExplorerToolbar state={state} onStateChange={onStateChange} onOpenPath={() => {}} onOpenSaveView={() => {}} />);
    const from = screen.getByLabelText(/from/i) as HTMLInputElement;
    fireEvent.change(from, { target: { value: "2023-01-01" } });
    const next = onStateChange.mock.calls[0][0] as ExplorerState;
    expect(next.timeFrom).toBe("2023-01-01");
  });
});
