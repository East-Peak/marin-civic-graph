// app/src/tests/components/data/data-filters.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: replaceMock,
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/data/san-rafael-decisions-since-2019",
}));

import { DataFilters } from "@/components/data/data-filters";
import { findDataQuery } from "@/lib/server/data-queries";

describe("DataFilters", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    vi.useFakeTimers();
  });

  it("renders one input per declared filter", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    render(<DataFilters def={def} values={{}} />);
    expect(screen.getByLabelText(/^From$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^To$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Institution id/i)).toBeInTheDocument();
  });

  it("renders a <select> for select filters with the declared options", () => {
    const def = findDataQuery("money-flows-by-year")!;
    render(<DataFilters def={def} values={{}} />);
    const typeSelect = screen.getByLabelText(/Flow type/i) as HTMLSelectElement;
    expect(typeSelect.tagName).toBe("SELECT");
    const opts = Array.from(typeSelect.options).map((o) => o.value);
    expect(opts).toContain("contribution");
    expect(opts).toContain("expenditure");
    expect(opts).toContain("behest");
  });

  it("renders number input for amount filters", () => {
    const def = findDataQuery("money-flows-by-year")!;
    render(<DataFilters def={def} values={{}} />);
    const min = screen.getByLabelText(/Min amount/i) as HTMLInputElement;
    expect(min.type).toBe("number");
  });

  it("renders date input for date filters", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    render(<DataFilters def={def} values={{}} />);
    const from = screen.getByLabelText(/^From$/i) as HTMLInputElement;
    expect(from.type).toBe("date");
  });

  it("pushes to URL on select change", () => {
    const def = findDataQuery("money-flows-by-year")!;
    render(<DataFilters def={def} values={{}} />);
    const typeSelect = screen.getByLabelText(/Flow type/i) as HTMLSelectElement;
    fireEvent.change(typeSelect, { target: { value: "contribution" } });
    expect(replaceMock).toHaveBeenCalled();
    const url = replaceMock.mock.calls.at(-1)?.[0] as string;
    expect(url).toContain("flow_type=contribution");
  });

  it("debounces text-field changes before pushing to URL", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    render(<DataFilters def={def} values={{}} />);
    const inst = screen.getByLabelText(/Institution id/i);
    fireEvent.change(inst, { target: { value: "o" } });
    fireEvent.change(inst, { target: { value: "org-sr" } });
    // No replace yet — debounce still pending.
    expect(replaceMock).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(replaceMock).toHaveBeenCalled();
    const url = replaceMock.mock.calls.at(-1)?.[0] as string;
    expect(url).toContain("institution_id=org-sr");
  });

  it("marks required filters with an asterisk", () => {
    const def = findDataQuery("evidence-records-supporting")!;
    render(<DataFilters def={def} values={{}} />);
    expect(screen.getByText(/Target id \*/i)).toBeInTheDocument();
  });

  it("shows a 'No filters' message when the query declares none", () => {
    const def = findDataQuery("qa-validation-gaps")!;
    render(<DataFilters def={def} values={{}} />);
    expect(screen.getByText(/No filters/i)).toBeInTheDocument();
  });

  it("hydrates input values from the supplied `values` prop", () => {
    const def = findDataQuery("san-rafael-decisions-since-2019")!;
    render(<DataFilters def={def} values={{ from_date: "2024-06-01" }} />);
    const from = screen.getByLabelText(/^From$/i) as HTMLInputElement;
    expect(from.value).toBe("2024-06-01");
  });
});
