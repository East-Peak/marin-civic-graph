// Operator-local route group — copied into src/app/(operator-workbench)/ ONLY under
// OPERATOR_WORKBENCH=1. NEVER in a public build. Slice 2a: cases list from the proven
// overlay (reconcile_cases). Slice 2b: enriched best-effort with the Neo4j consequence
// context (real name · money-in · departments · key-collision). The full side-by-side
// bench is Slice 3.
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";
import { fetchContext, type ContextEntry } from "../_lib/operator-context";
import { DATA, runPython } from "../_lib/operator-python";

export const dynamic = "force-dynamic";

type Ref = { source_id: string; local_id: string; display_label: string; public_fields: Record<string, unknown> };
type Join = { left_ref: Ref; right_ref: Ref; signals: string[]; signal_strength: number };
type AiReview = { verdict: string; signal_strength: number };
type Case = {
  case_id: string;
  candidate_joins: Join[];
  ai_reviews: AiReview[];
  current_ledger_status: string;
  bulk_eligible: boolean;
  review_flags: Record<string, boolean>;
};

const KEY_FIELD: Record<string, string> = { ein: "registry_ein", sos_id: "sos_id", committee_id: "committee_id" };
const usd = (n: number) => `$${Math.round(n).toLocaleString()}`;

export default async function ReconcilePage() {
  if (!operatorEnabled()) notFound(); // defense-in-depth if ever shipped/leaked
  const cases = runPython<Case[]>("reconcile_cases.py", [
    "--read-model", DATA.readModel(),
    "--ledger", DATA.attachLedger(),
  ]);

  // Best-effort consequence enrichment — falls back to slugs if the graph is unreachable.
  let ctx: Record<string, ContextEntry> = {};
  let ctxError = false;
  try {
    ctx = await fetchContext(
      cases.map((c) => ({
        vendor_id: c.candidate_joins[0].left_ref.local_id,
        anchor_id: c.candidate_joins[0].right_ref.local_id,
      })),
    );
  } catch {
    ctxError = true;
  }

  const bulk = cases.filter((c) => c.bulk_eligible).length;
  const rows = [...cases].sort((a, b) => {
    const ma = ctx[a.candidate_joins[0].left_ref.local_id]?.money_total ?? -1;
    const mb = ctx[b.candidate_joins[0].left_ref.local_id]?.money_total ?? -1;
    return Number(b.bulk_eligible) - Number(a.bulk_eligible) || mb - ma || a.case_id.localeCompare(b.case_id);
  });

  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif", maxWidth: 1280 }}>
      <h1 style={{ marginBottom: 4 }}>Identity Attach Workbench</h1>
      <p style={{ color: "#555", marginTop: 0 }}>
        {cases.length.toLocaleString()} attach cases · {bulk.toLocaleString()} bulk-eligible
        {ctxError ? " · ⚠ graph context unavailable (showing ids only)" : " · enriched with money + departments"}
      </p>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
            {["Vendor", "Money in", "Department", "Source", "Proposed key", "AI", "Status", "Bulk"].map((h) => (
              <th key={h} style={{ padding: "6px 8px" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const j = c.candidate_joins[0];
            const src = j.left_ref.source_id;
            const cx = ctx[j.left_ref.local_id];
            const key = (j.right_ref.public_fields[KEY_FIELD[src]] as string) ?? "—";
            const ai = c.ai_reviews[0];
            return (
              <tr key={c.case_id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "6px 8px" }}>
                  {cx?.display_label ?? j.left_ref.display_label}
                  {cx?.key_collision ? <span title={cx.collides_with.join(", ")} style={{ color: "#b00", marginLeft: 6 }}>⚠ key in use</span> : null}
                </td>
                <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {cx ? usd(cx.money_total) : "—"}{cx && cx.flow_count ? <span style={{ color: "#999" }}> ·{cx.flow_count}</span> : null}
                </td>
                <td style={{ padding: "6px 8px", color: "#444" }}>{cx?.departments?.[0] ?? ""}</td>
                <td style={{ padding: "6px 8px" }}>{src}</td>
                <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>{key}</td>
                <td style={{ padding: "6px 8px" }}>{ai ? `${ai.verdict} ${ai.signal_strength.toFixed(2)}` : "—"}</td>
                <td style={{ padding: "6px 8px" }}>{c.current_ledger_status}</td>
                <td style={{ padding: "6px 8px" }}>{c.bulk_eligible ? "✓" : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </main>
  );
}
