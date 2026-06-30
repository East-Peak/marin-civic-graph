"use client";
// The interactive Identity Attach Workbench (Slice 3). A decision surface over the
// Goal-1 read model: left queue (needs-review by $ / recommended / rejected / done),
// center side-by-side (vendor + money vs registry public fields) with the AI verdict and
// the lightweight consequence summary, and Approve / Reject(kind) / Unsure actions wired
// to POST /api/reconcile/decide. Decisions are optimistic — the row moves immediately and
// is reconciled against the writer's response (reverted on failure). Keyboard: j/k move,
// a approve, r reject (current evidence), R reject (entity distinct), u unsure.
//
// Operator-only: this file lives outside src/app and is copied into the route group ONLY
// under OPERATOR_WORKBENCH=1 — never in a public build. The Neo4j context arrives as a
// plain serializable prop from the server page; this component never touches the DB.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Case, ContextEntry } from "../_lib/bench-types";
import {
  applyControls,
  bucketize,
  DEFAULT_CONTROLS,
  displayName,
  investigationLinks,
  KEY_FIELD,
  proposedKey,
  statusAfter,
  usd,
  vendorId,
  type BenchRow,
  type Bucket,
  type DecideResponse,
  type QueueControls,
  type SortKey,
} from "../_lib/bench-logic";

type Props = {
  initialCases: Case[];
  context: Record<string, ContextEntry>;
  reviewer?: string;
  ctxError?: boolean;
};

type Action = "approve" | "reject" | "unsure";
type RejectionKind = "current_evidence" | "entity_distinct";

const TABS: { key: Bucket; label: string }[] = [
  { key: "needsReview", label: "Needs review" },
  { key: "recommended", label: "Recommended" },
  { key: "rejected", label: "Rejected" },
  { key: "done", label: "Done" },
];

const STATUS_LABEL: Record<string, string> = {
  none: "unreviewed",
  requeued: "requeued",
  approved: "approved",
  superseded: "superseded",
  deterministic: "deterministic",
  rejected_current_evidence: "rejected · evidence",
  rejected_entity_distinct: "rejected · distinct",
  unsure: "unsure (skipped)",
};

const optimisticStatus = (action: Action, kind?: RejectionKind): string =>
  action === "approve" ? "approved" : action === "unsure" ? "unsure" : `rejected_${kind ?? "current_evidence"}`;

function nextSelection(list: BenchRow[], decidedId: string): string | null {
  const i = list.findIndex((r) => r.case_id === decidedId);
  if (i < 0) return list[0]?.case_id ?? null;
  return (list[i + 1] ?? list[i - 1])?.case_id ?? null;
}

export function Bench({ initialCases, context, reviewer = "operator", ctxError = false }: Props) {
  const [rows, setRows] = useState<BenchRow[]>(() =>
    initialCases.map((c) => ({ ...c, displayStatus: c.current_ledger_status })),
  );
  const [tab, setTab] = useState<Bucket>("needsReview");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bulkText, setBulkText] = useState("");
  const [deselected, setDeselected] = useState<Set<string>>(() => new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [controls, setControls] = useState<QueueControls>(DEFAULT_CONTROLS);
  // Per-case in-flight guard (authoritative + synchronous, so two events in one tick can't
  // both submit the same case). The optimistic move also unmounts the case's controls.
  const inFlight = useRef<Set<string>>(new Set());

  const buckets = useMemo(() => bucketize(rows, context), [rows, context]);
  // The displayed list = the active bucket after the operator's filters + sort.
  const activeList = useMemo(() => applyControls(buckets[tab], context, controls), [buckets, tab, context, controls]);
  const bucketTotal = buckets[tab].length;
  // Any change to the visible set (tab, filter, sort, deselection) clears a typed bulk
  // confirmation, so an armed count can never apply to a set the operator didn't review.
  const resetArm = useCallback(() => setBulkText(""), []);
  const setSort = (key: SortKey) => {
    setControls((c) =>
      c.sortKey === key
        ? { ...c, sortDir: c.sortDir === "asc" ? "desc" : "asc" }
        : { ...c, sortKey: key, sortDir: key === "name" ? "asc" : "desc" },
    );
    resetArm();
  };
  const changeControls = (fn: (c: QueueControls) => QueueControls) => {
    setControls(fn);
    resetArm();
  };
  const counts = useMemo(
    () => ({
      needsReview: buckets.needsReview.length,
      recommended: buckets.recommended.length,
      rejected: buckets.rejected.length,
      done: buckets.done.length,
    }),
    [buckets],
  );

  // Effective selection, derived at render (no effect): the explicit pick when it's still
  // in the active list, otherwise the top of the list. Keeps selection valid across tab
  // switches and decisions without a setState-in-effect cascade.
  const effectiveId = activeList.some((r) => r.case_id === selectedId)
    ? selectedId
    : (activeList[0]?.case_id ?? null);
  const selected = rows.find((r) => r.case_id === effectiveId) ?? null;
  const selectedCtx = selected ? context[vendorId(selected)] : undefined;

  const post = useCallback(
    async (caseId: string, action: Action, kind?: RejectionKind) => {
      const body: Record<string, string> = { case_id: caseId, action, reviewer };
      if (action === "reject" && kind) body.rejection_kind = kind;
      const res = await fetch("/api/reconcile/decide", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      // Read text first so a non-JSON failure (HTML 500, proxy error, empty body) surfaces
      // the real status instead of throwing an opaque JSON parse error.
      const text = await res.text();
      let data: (DecideResponse & { error?: string }) | null = null;
      try {
        data = text ? (JSON.parse(text) as DecideResponse & { error?: string }) : null;
      } catch {
        data = null;
      }
      if (!res.ok) throw new Error(data?.error ?? `decide failed (${res.status})`);
      if (!data) throw new Error(`decide returned no body (${res.status})`);
      return data;
    },
    [reviewer],
  );

  const decide = useCallback(
    (caseId: string, action: Action, kind?: RejectionKind) => {
      if (inFlight.current.has(caseId)) return; // already deciding this case
      const prior = rows.find((r) => r.case_id === caseId)?.displayStatus;
      if (prior === undefined) return;
      inFlight.current.add(caseId);
      // optimistic: advance selection to the next case (decide always targets the
      // current selection), then move this one out of the active queue
      setSelectedId(nextSelection(activeList, caseId));
      setRows((rs) => rs.map((r) => (r.case_id === caseId ? { ...r, displayStatus: optimisticStatus(action, kind) } : r)));
      post(caseId, action, kind)
        .then((data) => {
          const reconciled = statusAfter(action, kind, data);
          setRows((rs) => rs.map((r) => (r.case_id === caseId ? { ...r, displayStatus: reconciled } : r)));
        })
        .catch((err: unknown) => {
          setRows((rs) => rs.map((r) => (r.case_id === caseId ? { ...r, displayStatus: prior } : r))); // revert
          setError(`${caseId}: ${err instanceof Error ? err.message : String(err)}`);
        })
        .finally(() => inFlight.current.delete(caseId));
    },
    [rows, activeList, post],
  );

  // Keyboard bench controls (ignored while typing in a field or with a command modifier).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const idx = activeList.findIndex((r) => r.case_id === effectiveId);
      if (e.key === "j") {
        e.preventDefault();
        setSelectedId(activeList[Math.min(idx + 1, activeList.length - 1)]?.case_id ?? effectiveId);
      } else if (e.key === "k") {
        e.preventDefault();
        setSelectedId(activeList[Math.max(idx, 1) - 1]?.case_id ?? effectiveId);
      } else if (effectiveId && !e.repeat && (e.key === "a" || e.key === "r" || e.key === "R" || e.key === "u")) {
        e.preventDefault();
        if (e.key === "a") decide(effectiveId, "approve");
        else if (e.key === "r" && !e.shiftKey) decide(effectiveId, "reject", "current_evidence");
        else if (e.key === "R") decide(effectiveId, "reject", "entity_distinct");
        else if (e.key === "u") decide(effectiveId, "unsure");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeList, effectiveId, decide]);

  // --- bulk path (recommended tab) ------------------------------------------
  // Targets = what's visible in the recommended queue (filters applied) minus deselected,
  // so "Approve N" matches exactly what the operator sees.
  const bulkTargets = useMemo(
    () => (tab === "recommended" ? activeList.filter((r) => !deselected.has(r.case_id)) : []),
    [tab, activeList, deselected],
  );
  const bulkArmed = bulkText.trim() === String(bulkTargets.length) && bulkTargets.length > 0 && !bulkRunning;

  const runBulk = useCallback(async () => {
    if (!bulkArmed) return;
    setBulkRunning(true);
    setError(null);
    // Freeze the exact target set (id + prior status) the operator confirmed, skipping any
    // case already being decided individually, and claim them in the in-flight guard so a
    // concurrent single decision can't double-submit. A failed write reverts to its real prior.
    const targets = bulkTargets
      .filter((r) => !inFlight.current.has(r.case_id))
      .map((r) => ({ id: r.case_id, prior: r.displayStatus }));
    targets.forEach((t) => inFlight.current.add(t.id));
    const ids = new Set(targets.map((t) => t.id));
    setRows((rs) => rs.map((r) => (ids.has(r.case_id) ? { ...r, displayStatus: "approved" } : r)));
    for (const { id, prior } of targets) {
      try {
        const data = await post(id, "approve");
        const reconciled = statusAfter("approve", undefined, data);
        setRows((rs) => rs.map((r) => (r.case_id === id ? { ...r, displayStatus: reconciled } : r)));
      } catch (err: unknown) {
        setRows((rs) => rs.map((r) => (r.case_id === id ? { ...r, displayStatus: prior } : r))); // revert to prior
        setError(`${id}: ${err instanceof Error ? err.message : String(err)}`);
      } finally {
        inFlight.current.delete(id);
      }
    }
    setBulkText("");
    setBulkRunning(false);
  }, [bulkArmed, bulkTargets, post]);

  // --- render ---------------------------------------------------------------
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", height: "100vh", display: "flex", flexDirection: "column" }}>
      <header style={{ padding: "12px 20px", borderBottom: "1px solid #e5e5e5" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
          <h1 style={{ margin: 0, fontSize: 18 }}>Identity Attach Workbench</h1>
          <span style={{ color: "#777", fontSize: 13 }}>
            {rows.length.toLocaleString()} cases
            {ctxError ? " · ⚠ graph context unavailable" : " · enriched with money + departments"}
          </span>
          <span style={{ marginLeft: "auto", color: "#999", fontSize: 12, fontFamily: "monospace" }}>
            j/k move · a approve · r reject (evidence) · R reject (distinct) · u unsure
          </span>
        </div>
        <nav style={{ display: "flex", gap: 6, marginTop: 10 }}>
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              data-testid={`tab-${key}`}
              onClick={() => {
                setTab(key);
                resetArm();
              }}
              style={{
                padding: "5px 12px",
                borderRadius: 6,
                border: "1px solid",
                borderColor: tab === key ? "#2563eb" : "#ddd",
                background: tab === key ? "#eff6ff" : "#fff",
                color: tab === key ? "#1d4ed8" : "#333",
                cursor: "pointer",
                fontSize: 13,
              }}
            >
              {label} <strong>{counts[key]}</strong>
            </button>
          ))}
        </nav>
      </header>

      {error ? (
        <div role="alert" style={{ background: "#fef2f2", color: "#b00", padding: "6px 20px", fontSize: 13 }}>
          {error}
        </div>
      ) : null}

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Queue */}
        <section style={{ width: 420, borderRight: "1px solid #e5e5e5", overflow: "auto" }}>
          <Controls controls={controls} setControls={changeControls} setSort={setSort} showing={activeList.length} total={bucketTotal} />
          {tab === "recommended" ? (
            <BulkBar
              targetCount={bulkTargets.length}
              total={bucketTotal}
              armed={bulkArmed}
              running={bulkRunning}
              text={bulkText}
              onText={setBulkText}
              onRun={runBulk}
            />
          ) : null}
          {activeList.length === 0 ? (
            <p style={{ color: "#999", padding: 20, fontSize: 13 }}>Nothing in this queue.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {activeList.map((r) => {
                const cx = context[vendorId(r)];
                const isSel = r.case_id === effectiveId;
                const showCheckbox = tab === "recommended";
                return (
                  <li
                    key={r.case_id}
                    data-testid={`row-${r.case_id}`}
                    data-selected={isSel || undefined}
                    onClick={() => setSelectedId(r.case_id)}
                    style={{
                      padding: "8px 12px",
                      borderBottom: "1px solid #f0f0f0",
                      background: isSel ? "#eff6ff" : "#fff",
                      cursor: "pointer",
                      display: "flex",
                      gap: 8,
                      alignItems: "center",
                    }}
                  >
                    {showCheckbox ? (
                      <input
                        type="checkbox"
                        checked={!deselected.has(r.case_id)}
                        disabled={bulkRunning}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => {
                          setDeselected((d) => {
                            const n = new Set(d);
                            if (e.target.checked) n.delete(r.case_id);
                            else n.add(r.case_id);
                            return n;
                          });
                          resetArm();
                        }}
                      />
                    ) : null}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {displayName(r, cx)}
                        {cx?.key_collision ? <span style={{ color: "#b00", marginLeft: 6 }} title={cx.collides_with.join(", ")}>⚠</span> : null}
                      </div>
                      <div style={{ fontSize: 11, color: "#888" }}>
                        {cx ? usd(cx.money_total) : "—"} · {r.candidate_joins[0].left_ref.source_id}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* Detail */}
        <section data-testid="detail" style={{ flex: 1, overflow: "auto", padding: 24 }}>
          {selected ? (
            <CaseDetail row={selected} ctx={selectedCtx} onDecide={decide} />
          ) : (
            <p style={{ color: "#999" }}>Select a case to review.</p>
          )}
        </section>
      </div>
    </main>
  );
}

const chipStyle = (active: boolean) =>
  ({
    padding: "2px 8px",
    borderRadius: 4,
    border: "1px solid",
    borderColor: active ? "#2563eb" : "#ddd",
    background: active ? "#eff6ff" : "#fff",
    color: active ? "#1d4ed8" : "#555",
    cursor: "pointer",
    fontSize: 11,
  }) as const;

const VERDICTS: [QueueControls["verdict"], string][] = [
  ["all", "All"],
  ["same", "Same"],
  ["different", "Different"],
  ["unsure", "Unsure"],
];
const NAMES: [QueueControls["nameMatch"], string][] = [
  ["all", "All"],
  ["exact", "Exact"],
  ["fuzzy", "Fuzzy"],
];
const MONEYS: [number, string][] = [
  [0, "Any $"],
  [10000, "≥$10k"],
  [50000, "≥$50k"],
  [100000, "≥$100k"],
];
const SORTS: [SortKey, string][] = [
  ["money", "$"],
  ["name", "Name"],
  ["ai", "AI"],
];

function Controls({
  controls,
  setControls,
  setSort,
  showing,
  total,
}: {
  controls: QueueControls;
  setControls: (fn: (c: QueueControls) => QueueControls) => void;
  setSort: (k: SortKey) => void;
  showing: number;
  total: number;
}) {
  const set = (patch: Partial<QueueControls>) => setControls((c) => ({ ...c, ...patch }));
  const group = (label: string, children: ReactNode) => (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{ fontSize: 10, color: "#999", textTransform: "uppercase" }}>{label}</span>
      {children}
    </div>
  );
  return (
    <div style={{ position: "sticky", top: 0, zIndex: 1, background: "#fff", borderBottom: "1px solid #e5e5e5", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
      <input
        data-testid="q-search"
        value={controls.search}
        onChange={(e) => set({ search: e.target.value })}
        placeholder="search name / registry / key…"
        style={{ padding: "4px 8px", border: "1px solid #ccc", borderRadius: 4, fontSize: 12 }}
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {group(
          "AI",
          VERDICTS.map(([v, label]) => (
            <button key={v} data-testid={`q-verdict-${v}`} onClick={() => set({ verdict: v })} style={chipStyle(controls.verdict === v)}>
              {label}
            </button>
          )),
        )}
        {group(
          "Name",
          NAMES.map(([v, label]) => (
            <button key={v} data-testid={`q-name-${v}`} onClick={() => set({ nameMatch: v })} style={chipStyle(controls.nameMatch === v)}>
              {label}
            </button>
          )),
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {group(
          "$≥",
          MONEYS.map(([v, label]) => (
            <button key={v} data-testid={`q-money-${v}`} onClick={() => set({ minMoney: v })} style={chipStyle(controls.minMoney === v)}>
              {label}
            </button>
          )),
        )}
        {group(
          "Sort",
          SORTS.map(([v, label]) => {
            const active = controls.sortKey === v;
            return (
              <button key={v} data-testid={`q-sort-${v}`} onClick={() => setSort(v)} style={chipStyle(active)}>
                {label} {active ? (controls.sortDir === "asc" ? "▲" : "▼") : ""}
              </button>
            );
          }),
        )}
      </div>
      <div style={{ fontSize: 11, color: "#999" }}>
        showing {showing.toLocaleString()} of {total.toLocaleString()}
      </div>
    </div>
  );
}

function BulkBar(props: {
  targetCount: number;
  total: number;
  armed: boolean;
  running: boolean;
  text: string;
  onText: (v: string) => void;
  onRun: () => void;
}) {
  return (
    <div style={{ padding: "12px 12px", borderBottom: "1px solid #e5e5e5", background: "#fafafa" }}>
      <div style={{ fontSize: 12, color: "#555", marginBottom: 6 }}>
        <strong>{props.targetCount}</strong> selected
        {props.targetCount !== props.total ? ` (of ${props.total} recommended)` : ""} — exact name + key, AI&nbsp;≥&nbsp;0.9,
        no collision. Deselect to exclude, then type <strong>{props.targetCount}</strong> to confirm.
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          data-testid="bulk-confirm"
          value={props.text}
          onChange={(e) => props.onText(e.target.value)}
          placeholder={String(props.targetCount)}
          style={{ width: 80, padding: "4px 8px", border: "1px solid #ccc", borderRadius: 4, fontSize: 13 }}
        />
        <button
          data-testid="bulk-approve"
          disabled={!props.armed}
          onClick={props.onRun}
          style={{
            padding: "4px 12px",
            borderRadius: 4,
            border: "1px solid",
            borderColor: props.armed ? "#16a34a" : "#ddd",
            background: props.armed ? "#16a34a" : "#f3f4f6",
            color: props.armed ? "#fff" : "#999",
            cursor: props.armed ? "pointer" : "not-allowed",
            fontSize: 13,
          }}
        >
          {props.running ? "Approving…" : `Approve ${props.targetCount} selected`}
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, color: "#999" }}>{label}</div>
      <div style={{ fontSize: 14, fontFamily: mono ? "monospace" : undefined }}>{value}</div>
    </div>
  );
}

function CaseDetail({
  row,
  ctx,
  onDecide,
}: {
  row: BenchRow;
  ctx: ContextEntry | undefined;
  onDecide: (caseId: string, action: Action, kind?: RejectionKind) => void;
}) {
  const j = row.candidate_joins[0];
  const ai = row.ai_reviews[0];
  const pubFields = j.right_ref.public_fields;
  const card = { border: "1px solid #e5e5e5", borderRadius: 8, padding: 16, flex: 1, minWidth: 0 } as const;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: 12, fontFamily: "monospace", color: "#999" }}>{row.case_id}</span>
        <span style={{ fontSize: 12, color: "#666" }}>{STATUS_LABEL[row.displayStatus] ?? row.displayStatus}</span>
      </div>

      <div style={{ display: "flex", gap: 16, margin: "12px 0" }}>
        <div style={card}>
          <div style={{ fontSize: 11, color: "#2563eb", fontWeight: 600, marginBottom: 10 }}>COUNTY VENDOR</div>
          <Field label="Name" value={displayName(row, ctx)} />
          <Field label="Vendor id" value={j.left_ref.local_id} mono />
          <Field label="Money in" value={ctx ? `${usd(ctx.money_total)} · ${ctx.flow_count} flows` : "—"} />
          <Field label="Paying departments" value={ctx?.departments?.length ? ctx.departments.join(", ") : "—"} />
        </div>
        <div style={card}>
          <div style={{ fontSize: 11, color: "#7c3aed", fontWeight: 600, marginBottom: 10 }}>REGISTRY ANCHOR</div>
          <Field label="Name" value={j.right_ref.display_label} />
          <Field label="Proposed key" value={proposedKey(row)} mono />
          {Object.entries(pubFields)
            .filter(([k]) => k !== KEY_FIELD[j.left_ref.source_id]) // already shown as Proposed key
            .map(([k, v]) => (
              <Field key={k} label={k} value={String(v)} mono />
            ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, margin: "12px 0", fontSize: 13 }}>
        <div style={{ ...card }}>
          <div style={{ fontSize: 11, color: "#999", fontWeight: 600, marginBottom: 6 }}>AI VERDICT (advisory)</div>
          {ai ? (
            <div>
              <strong>{ai.verdict}</strong> · {ai.signal_strength.toFixed(2)}
              {ai.reason ? <div style={{ color: "#666", marginTop: 4 }}>{ai.reason}</div> : null}
            </div>
          ) : (
            <span style={{ color: "#999" }}>none</span>
          )}
          <div style={{ color: "#888", marginTop: 6, fontSize: 12 }}>signals: {j.signals.join(", ") || "—"}</div>
        </div>
        <div style={{ ...card }}>
          <div style={{ fontSize: 11, color: "#999", fontWeight: 600, marginBottom: 6 }}>CONSEQUENCE</div>
          {ctx ? (
            <div>
              {usd(ctx.money_total)} across {ctx.flow_count} flows
              {ctx.key_collision ? (
                <div style={{ color: "#b00", marginTop: 4 }}>⚠ key already in use by {ctx.collides_with.join(", ")}</div>
              ) : (
                <div style={{ color: "#16a34a", marginTop: 4 }}>key is free</div>
              )}
            </div>
          ) : (
            <span style={{ color: "#999" }}>graph context unavailable</span>
          )}
          {row.bulk_eligible ? <div style={{ color: "#16a34a", marginTop: 6, fontSize: 12 }}>✓ bulk-eligible</div> : null}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "4px 0" }}>
        <span style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, color: "#999" }}>Investigate</span>
        {investigationLinks(row).map((l) => (
          <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13, color: "#2563eb" }}>
            {l.label} ↗
          </a>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <ActionButton color="#16a34a" onClick={() => onDecide(row.case_id, "approve")}>Approve</ActionButton>
        <ActionButton color="#d97706" onClick={() => onDecide(row.case_id, "reject", "current_evidence")}>Reject (evidence)</ActionButton>
        <ActionButton color="#dc2626" onClick={() => onDecide(row.case_id, "reject", "entity_distinct")}>Reject (distinct)</ActionButton>
        <ActionButton color="#6b7280" onClick={() => onDecide(row.case_id, "unsure")}>Unsure</ActionButton>
      </div>
    </div>
  );
}

function ActionButton({ color, onClick, children }: { color: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{ padding: "8px 16px", borderRadius: 6, border: `1px solid ${color}`, background: "#fff", color, cursor: "pointer", fontSize: 14, fontWeight: 500 }}
    >
      {children}
    </button>
  );
}
