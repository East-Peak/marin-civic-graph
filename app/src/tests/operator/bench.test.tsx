// Interaction tests for the Identity Attach Workbench bench component (Slice 3).
// Covers selection, the side-by-side detail, the four decision paths (approve / reject
// current_evidence / reject entity_distinct / unsure) via both buttons and keyboard, the
// optimistic row move from the writer's response, and the rule-gated bulk confirmation.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor, within } from "@testing-library/react";
import { Bench } from "../../../operator-workbench-src/reconcile/Bench";
import type { Case, ContextEntry } from "../../../operator-workbench-src/_lib/bench-types";

function mkCase(over: Partial<Case> & { vendor?: string; src?: string; key?: string } = {}): Case {
  const vendor = over.vendor ?? "org-county-vendor-1";
  const src = over.src ?? "ein";
  const keyField = src === "ein" ? "registry_ein" : "sos_id";
  return {
    case_id: over.case_id ?? `attach|anchor-1|${vendor}`,
    candidate_joins: over.candidate_joins ?? [
      {
        left_ref: { source_id: src, local_id: vendor, display_label: "RAW VENDOR", public_fields: {} },
        right_ref: {
          source_id: src,
          local_id: "anchor-1",
          display_label: "Registry Name",
          public_fields: { [keyField]: over.key ?? "94-3041517" },
        },
        signals: ["normalized_name_exact"],
        signal_strength: 0.95,
      },
    ],
    ai_reviews: over.ai_reviews ?? [{ verdict: "same", reason: "exact name + key", signal_strength: 0.97 }],
    current_ledger_status: over.current_ledger_status ?? "none",
    bulk_eligible: over.bulk_eligible ?? false,
    review_flags: over.review_flags ?? {},
  };
}

function mkCtx(over: Partial<ContextEntry> = {}): ContextEntry {
  return { display_label: "Ten Thousand Degrees", money_total: 19285, flow_count: 3, departments: ["Cultural Services"], key_collision: false, collides_with: [], ...over };
}

function okJson(body: unknown): Promise<Response> {
  // post() reads the body as text then parses, so expose text() (covers non-JSON paths too).
  return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) } as Response);
}

function errorResponse(status: number, text: string): Promise<Response> {
  return Promise.resolve({ ok: false, status, text: () => Promise.resolve(text) } as Response);
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

type FetchMock = ReturnType<typeof vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>>;

function lastDecideBody(fetchMock: FetchMock) {
  const call = fetchMock.mock.calls.findLast((c) => String(c[0]).includes("/api/reconcile/decide"));
  return JSON.parse((call?.[1] as RequestInit).body as string);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("Bench", () => {
  it("renders the needs-review queue with a count and selects the top case", () => {
    const cases = [
      mkCase({ case_id: "c-big", vendor: "v1" }),
      mkCase({ case_id: "c-small", vendor: "v2" }),
    ];
    const ctx = { v1: mkCtx({ money_total: 900, display_label: "Big Org" }), v2: mkCtx({ money_total: 10, display_label: "Small Org" }) };
    render(<Bench initialCases={cases} context={ctx} />);

    expect(screen.getByTestId("tab-needsReview").textContent).toMatch(/2/);
    // top of the queue ($900) is auto-selected and shown in the detail pane
    const detail = screen.getByTestId("detail");
    expect(within(detail).getByText("Big Org")).toBeInTheDocument();
    expect(within(detail).getByText("Registry Name")).toBeInTheDocument();
    expect(within(detail).getByText("94-3041517")).toBeInTheDocument();
    expect(within(detail).getByText(/same/)).toBeInTheDocument();
  });

  it("approves the selected case and moves it out of needs-review", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => okJson({ result: "created", assertion: { status: "approved" }, same_as: {} }));
    vi.stubGlobal("fetch", fetchMock);
    const cases = [mkCase({ case_id: "c1", vendor: "v1" })];
    render(<Bench initialCases={cases} context={{ v1: mkCtx() }} />);

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /^Approve$/i }));
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/reconcile/decide");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).headers).toMatchObject({ "content-type": "application/json" });
    expect(lastDecideBody(fetchMock)).toMatchObject({ case_id: "c1", action: "approve" });

    await waitFor(() => expect(screen.getByTestId("tab-needsReview").textContent).toMatch(/0/));
    expect(screen.getByTestId("tab-done").textContent).toMatch(/1/);
  });

  it("approves via the 'a' keyboard shortcut", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => okJson({ result: "created", assertion: { status: "approved" }, same_as: {} }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Bench initialCases={[mkCase({ case_id: "c1", vendor: "v1" })]} context={{ v1: mkCtx() }} />);

    act(() => {
      fireEvent.keyDown(window, { key: "a" });
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(lastDecideBody(fetchMock)).toMatchObject({ case_id: "c1", action: "approve" });
  });

  it("rejects with current_evidence on 'r' and entity_distinct on 'R'", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => okJson({ result: "created", assertion: { status: "rejected_current_evidence" }, same_as: null }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Bench initialCases={[mkCase({ case_id: "c1", vendor: "v1" }), mkCase({ case_id: "c2", vendor: "v2" })]} context={{ v1: mkCtx({ money_total: 900 }), v2: mkCtx({ money_total: 10 }) }} />);

    act(() => {
      fireEvent.keyDown(window, { key: "r" });
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(lastDecideBody(fetchMock)).toMatchObject({ action: "reject", rejection_kind: "current_evidence" });

    act(() => {
      fireEvent.keyDown(window, { key: "R", shiftKey: true });
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(lastDecideBody(fetchMock)).toMatchObject({ action: "reject", rejection_kind: "entity_distinct" });
  });

  it("marks unsure on 'u'", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => okJson({ result: "unsure", assertion: null, same_as: null }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Bench initialCases={[mkCase({ case_id: "c1", vendor: "v1" })]} context={{ v1: mkCtx() }} />);

    act(() => {
      fireEvent.keyDown(window, { key: "u" });
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(lastDecideBody(fetchMock)).toMatchObject({ case_id: "c1", action: "unsure" });
  });

  it("gates bulk approval behind a typed confirmation of the exact count", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => okJson({ result: "created", assertion: { status: "approved" }, same_as: {} }));
    vi.stubGlobal("fetch", fetchMock);
    const cases = [
      mkCase({ case_id: "b1", vendor: "v1", bulk_eligible: true }),
      mkCase({ case_id: "b2", vendor: "v2", bulk_eligible: true }),
    ];
    const ctx = { v1: mkCtx({ key_collision: false }), v2: mkCtx({ key_collision: false }) };
    render(<Bench initialCases={cases} context={ctx} />);

    act(() => {
      fireEvent.click(screen.getByTestId("tab-recommended"));
    });
    expect(screen.getByTestId("tab-recommended").textContent).toMatch(/2/);

    const confirm = screen.getByTestId("bulk-confirm") as HTMLInputElement;
    const approveBtn = screen.getByTestId("bulk-approve") as HTMLButtonElement;
    expect(approveBtn.disabled).toBe(true);

    // wrong count keeps it disabled
    act(() => {
      fireEvent.change(confirm, { target: { value: "1" } });
    });
    expect(approveBtn.disabled).toBe(true);

    // exact count enables it; clicking writes one assertion per eligible case
    act(() => {
      fireEvent.change(confirm, { target: { value: "2" } });
    });
    expect(approveBtn.disabled).toBe(false);
    act(() => {
      fireEvent.click(approveBtn);
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const bodies = fetchMock.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string));
    expect(bodies.every((b) => b.action === "approve")).toBe(true);
    expect(new Set(bodies.map((b) => b.case_id))).toEqual(new Set(["b1", "b2"]));
    await waitFor(() => expect(screen.getByTestId("tab-done").textContent).toMatch(/2/));
  });

  it("does not double-submit while a decision for that case is in flight", async () => {
    const d = deferred<Response>();
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => d.promise);
    vi.stubGlobal("fetch", fetchMock);
    render(<Bench initialCases={[mkCase({ case_id: "c1", vendor: "v1" })]} context={{ v1: mkCtx() }} />);

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /^Approve$/i }));
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    // second attempt while the first is still pending must be ignored
    act(() => {
      fireEvent.keyDown(window, { key: "a" });
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // releasing the in-flight request lets the row settle
    act(() => {
      d.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify({ result: "created", assertion: { status: "approved" }, same_as: {} })) } as Response);
    });
    await waitFor(() => expect(screen.getByTestId("tab-done").textContent).toMatch(/1/));
  });

  it("ignores auto-repeated decision keys (held key)", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => okJson({ result: "created", assertion: { status: "approved" }, same_as: {} }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Bench initialCases={[mkCase({ case_id: "c1", vendor: "v1" })]} context={{ v1: mkCtx() }} />);
    act(() => {
      fireEvent.keyDown(window, { key: "a", repeat: true });
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces a non-JSON error response and reverts the optimistic move", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => errorResponse(500, "<html>internal error</html>"));
    vi.stubGlobal("fetch", fetchMock);
    render(<Bench initialCases={[mkCase({ case_id: "c1", vendor: "v1" })]} context={{ v1: mkCtx() }} />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /^Approve$/i }));
    });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/500/));
    // not stuck optimistic — the row is back in needs-review
    expect(screen.getByTestId("tab-needsReview").textContent).toMatch(/1/);
    expect(screen.getByTestId("tab-done").textContent).toMatch(/0/);
  });
});
