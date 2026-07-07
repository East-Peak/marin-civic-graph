// Interaction tests for the Identity Attach Workbench bench component (Slice 3).
// Covers selection, the side-by-side detail, the four decision paths (approve / reject
// current_evidence / reject entity_distinct / unsure) via both buttons and keyboard, the
// optimistic row move from the writer's response, and the rule-gated bulk confirmation.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor, within } from "@testing-library/react";
import { Bench } from "../../../operator-workbench-src/reconcile/Bench";
import type { Case, ContextEntry } from "../../../operator-workbench-src/_lib/bench-types";

type CaseOver = Partial<Case> & {
  vendor?: string;
  src?: string;
  key?: string;
  name?: string;
  regName?: string;
  city?: string;
  signals?: string[];
  aiVerdict?: string;
  aiConf?: number;
  confidence?: Case["confidence"];
};

function mkCase(over: CaseOver = {}): Case {
  const vendor = over.vendor ?? "org-county-vendor-1";
  const src = over.src ?? "ein";
  const keyField = src === "ein" ? "registry_ein" : src === "committee_id" ? "committee_id" : "sos_id";
  const pubFields: Record<string, unknown> = { [keyField]: over.key ?? "94-3041517" };
  if (over.city) pubFields.principal_city = over.city;
  return {
    case_id: over.case_id ?? `attach|anchor-1|${vendor}`,
    candidate_joins: over.candidate_joins ?? [
      {
        left_ref: { source_id: src, local_id: vendor, display_label: over.name ?? "RAW VENDOR", public_fields: {} },
        right_ref: {
          source_id: src,
          local_id: "anchor-1",
          display_label: over.regName ?? "Registry Name",
          public_fields: pubFields,
        },
        signals: over.signals ?? ["normalized_name_exact"],
        signal_strength: 0.95,
      },
    ],
    ai_reviews: over.ai_reviews ?? [
      { verdict: over.aiVerdict ?? "same", reason: "exact name + key", signal_strength: over.aiConf ?? 0.97 },
    ],
    current_ledger_status: over.current_ledger_status ?? "none",
    bulk_eligible: over.bulk_eligible ?? false,
    review_flags: over.review_flags ?? {},
    ...(over.confidence ? { confidence: over.confidence } : {}),
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

  it("makes committee_id rows actionable and posts decisions", async () => {
    const fetchMock = vi.fn<(u: RequestInfo | URL, i?: RequestInit) => Promise<Response>>(() => okJson({ result: "created", assertion: { status: "approved" }, same_as: {} }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Bench initialCases={[mkCase({ case_id: "committee-case", vendor: "committee-vendor", src: "committee_id", key: "1470249" })]} context={{ "committee-vendor": mkCtx() }} />);

    const detail = within(screen.getByTestId("detail"));
    expect(detail.getByText("1470249")).toBeInTheDocument();
    expect(detail.getByRole("button", { name: /^Approve$/i })).toBeEnabled();
    expect(detail.getByRole("button", { name: /^Reject \(evidence\)$/i })).toBeEnabled();
    expect(detail.getByRole("button", { name: /^Reject \(distinct\)$/i })).toBeEnabled();
    expect(detail.getByRole("button", { name: /^Unsure$/i })).toBeEnabled();

    act(() => {
      fireEvent.keyDown(window, { key: "a" });
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(lastDecideBody(fetchMock)).toMatchObject({ case_id: "committee-case", action: "approve" });
  });

  it("renders active confidence band chips in the queue and detail pane", () => {
    render(
      <Bench
        initialCases={[mkCase({ case_id: "c1", vendor: "v1", aiConf: 0.97, confidence: { band: "high", status: "active" } })]}
        context={{ v1: mkCtx() }}
      />,
    );

    expect(within(screen.getByTestId("row-c1")).getByTestId("confidence-chip-high")).toHaveTextContent("High");
    const detail = within(screen.getByTestId("detail"));
    expect(detail.getByTestId("confidence-chip-high")).toHaveTextContent("High");
  });

  it("does not render the raw signal-strength float by default, only behind dbg", () => {
    render(
      <Bench
        initialCases={[mkCase({ case_id: "c1", vendor: "v1", aiConf: 0.97, confidence: { band: "high", status: "active" } })]}
        context={{ v1: mkCtx() }}
      />,
    );

    const detail = within(screen.getByTestId("detail"));
    expect(detail.queryByText("0.97")).not.toBeInTheDocument();

    act(() => {
      fireEvent.click(detail.getByRole("button", { name: "dbg" }));
    });

    expect(detail.getByText("0.97")).toBeInTheDocument();
  });

  it("renders selected-vendor rollup dollars without raw floats", () => {
    render(
      <Bench
        initialCases={[mkCase({ case_id: "c1", vendor: "v1", confidence: { band: "high", status: "active" } })]}
        context={{
          v1: mkCtx({
            money_total: 1000,
            rollup_totals: { verified: 250, high_confidence: 750, unattributed: 0 },
          }),
        }}
      />,
    );

    const detail = within(screen.getByTestId("detail"));
    expect(detail.getByText("Verified")).toBeInTheDocument();
    expect(detail.getByText("$250")).toBeInTheDocument();
    expect(detail.getByText("High-confidence")).toBeInTheDocument();
    expect(detail.getByText("$750")).toBeInTheDocument();
    expect(detail.getByText("Unattributed")).toBeInTheDocument();
    expect(detail.getByText("$0")).toBeInTheDocument();
    expect(detail.queryByText(/\d\.\d{2}/)).not.toBeInTheDocument();
  });
});

describe("Bench queue controls", () => {
  const rowIds = () => screen.getAllByTestId(/^row-/).map((el) => el.getAttribute("data-testid"));
  const cases = [
    mkCase({ case_id: "a", vendor: "v1", aiVerdict: "same", aiConf: 0.95, signals: ["normalized_name_exact"], name: "Alpha Foundation" }),
    mkCase({ case_id: "b", vendor: "v2", aiVerdict: "different", aiConf: 0.4, signals: ["token_overlap"], name: "Beta LLC" }),
    mkCase({ case_id: "c", vendor: "v3", aiVerdict: "unsure", aiConf: 0.6, signals: ["token_overlap"], name: "Gamma Trust" }),
  ];
  const ctx = {
    v1: mkCtx({ money_total: 900, display_label: "Alpha Foundation" }),
    v2: mkCtx({ money_total: 100, display_label: "Beta LLC" }),
    v3: mkCtx({ money_total: 5000, display_label: "Gamma Trust" }),
  };

  it("filters the visible queue by free-text search", () => {
    render(<Bench initialCases={cases} context={ctx} />);
    act(() => {
      fireEvent.change(screen.getByTestId("q-search"), { target: { value: "gamma" } });
    });
    expect(rowIds()).toEqual(["row-c"]);
  });

  it("filters by AI verdict", () => {
    render(<Bench initialCases={cases} context={ctx} />);
    act(() => {
      fireEvent.click(screen.getByTestId("q-verdict-different"));
    });
    expect(rowIds()).toEqual(["row-b"]);
  });

  it("filters by confidence band chips", () => {
    const banded = [
      mkCase({ case_id: "high", vendor: "v1", confidence: { band: "high", status: "active" } }),
      mkCase({ case_id: "medium", vendor: "v2", confidence: { band: "medium", status: "active" } }),
      mkCase({ case_id: "low", vendor: "v3", confidence: { band: "low", status: "active" } }),
      mkCase({ case_id: "masked", vendor: "v4", confidence: { band: "high", status: "superseded_by_assertion" } }),
    ];
    render(
      <Bench
        initialCases={banded}
        context={{
          v1: mkCtx({ money_total: 400 }),
          v2: mkCtx({ money_total: 300 }),
          v3: mkCtx({ money_total: 200 }),
          v4: mkCtx({ money_total: 100 }),
        }}
      />,
    );

    act(() => {
      fireEvent.click(screen.getByTestId("q-band-high"));
    });

    expect(rowIds()).toEqual(["row-high"]);
  });

  it("toggles sort direction on the active key", () => {
    render(<Bench initialCases={cases} context={ctx} />);
    // default money desc: 5000, 900, 100
    expect(rowIds()).toEqual(["row-c", "row-a", "row-b"]);
    act(() => {
      fireEvent.click(screen.getByTestId("q-sort-money")); // active key → flip to asc
    });
    expect(rowIds()).toEqual(["row-b", "row-a", "row-c"]);
  });

  it("disarms the bulk confirmation when a filter changes (no stale-set approve)", () => {
    const bulk = [
      mkCase({ case_id: "b1", vendor: "v1", bulk_eligible: true }),
      mkCase({ case_id: "b2", vendor: "v2", bulk_eligible: true }),
    ];
    render(<Bench initialCases={bulk} context={{ v1: mkCtx(), v2: mkCtx() }} />);
    act(() => {
      fireEvent.click(screen.getByTestId("tab-recommended"));
    });
    act(() => {
      fireEvent.change(screen.getByTestId("bulk-confirm"), { target: { value: "2" } });
    });
    expect((screen.getByTestId("bulk-approve") as HTMLButtonElement).disabled).toBe(false);
    // changing a filter must clear the typed confirmation → button disarms
    act(() => {
      fireEvent.click(screen.getByTestId("q-name-exact"));
    });
    expect((screen.getByTestId("bulk-confirm") as HTMLInputElement).value).toBe("");
    expect((screen.getByTestId("bulk-approve") as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders investigation links in the detail pane", () => {
    render(<Bench initialCases={[mkCase({ case_id: "c1", vendor: "v1", src: "ein", key: "94-3041517", name: "Buckelew" })]} context={{ v1: mkCtx({ display_label: "Buckelew Programs" }) }} />);
    const pp = screen.getByRole("link", { name: /ProPublica/i });
    expect(pp).toHaveAttribute("href", "https://projects.propublica.org/nonprofits/organizations/943041517");
    expect(screen.getByRole("link", { name: /Web search/i })).toHaveAttribute("href", expect.stringContaining("google.com/search"));
  });
});
