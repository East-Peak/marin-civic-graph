// Operator-local route group — copied into src/app/(operator-workbench)/ ONLY under
// OPERATOR_WORKBENCH=1. NEVER in a public build. Slice 2a: a bare cases list rendered from
// the proven overlay (reconcile_cases). The real queue + side-by-side bench is Slice 3.
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";
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

export default function ReconcilePage() {
  if (!operatorEnabled()) notFound();
  const cases = runPython<Case[]>("reconcile_cases.py", [
    "--read-model", DATA.readModel(),
    "--ledger", DATA.attachLedger(),
  ]);
  const bulk = cases.filter((c) => c.bulk_eligible).length;
  const rows = [...cases].sort(
    (a, b) => Number(b.bulk_eligible) - Number(a.bulk_eligible) || a.case_id.localeCompare(b.case_id),
  );

  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif", maxWidth: 1100 }}>
      <h1 style={{ marginBottom: 4 }}>Identity Attach Workbench</h1>
      <p style={{ color: "#555", marginTop: 0 }}>
        {cases.length.toLocaleString()} attach cases · {bulk.toLocaleString()} bulk-eligible · Slice 2a bare list
      </p>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
            <th style={{ padding: "6px 8px" }}>Vendor</th>
            <th style={{ padding: "6px 8px" }}>Source</th>
            <th style={{ padding: "6px 8px" }}>Proposed key</th>
            <th style={{ padding: "6px 8px" }}>Signal</th>
            <th style={{ padding: "6px 8px" }}>AI</th>
            <th style={{ padding: "6px 8px" }}>Status</th>
            <th style={{ padding: "6px 8px" }}>Bulk</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const j = c.candidate_joins[0];
            const src = j.left_ref.source_id;
            const key = (j.right_ref.public_fields[KEY_FIELD[src]] as string) ?? "—";
            const ai = c.ai_reviews[0];
            return (
              <tr key={c.case_id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "6px 8px" }}>{j.left_ref.display_label}</td>
                <td style={{ padding: "6px 8px" }}>{src}</td>
                <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>{key}</td>
                <td style={{ padding: "6px 8px" }}>{j.signals.join(", ")}</td>
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
