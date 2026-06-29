// Operator-local route group — copied into src/app/(operator-workbench)/ ONLY under
// OPERATOR_WORKBENCH=1. NEVER in a public build. Server component: gate + fetch the
// overlaid cases (reconcile_cases) + best-effort Neo4j consequence context, then hand the
// serializable data to the interactive client bench (Slice 3). The write path the bench
// POSTs to (/api/reconcile/decide) is itself build-excluded + runtime-gated.
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";
import { fetchContext, type ContextEntry } from "../_lib/operator-context";
import { DATA, runPython } from "../_lib/operator-python";
import type { Case } from "../_lib/bench-types";
import { Bench } from "./Bench";

export const dynamic = "force-dynamic";

export default async function ReconcilePage() {
  if (!operatorEnabled()) notFound(); // defense-in-depth if ever shipped/leaked
  const cases = runPython<Case[]>("reconcile_cases.py", [
    "--read-model", DATA.readModel(),
    "--ledger", DATA.attachLedger(),
  ]);

  // Best-effort consequence enrichment — the bench degrades to ids + "graph unavailable"
  // (and disables bulk, which requires a confirmed no-collision) if the graph is down.
  let context: Record<string, ContextEntry> = {};
  let ctxError = false;
  try {
    context = await fetchContext(
      cases.map((c) => ({
        vendor_id: c.candidate_joins[0].left_ref.local_id,
        anchor_id: c.candidate_joins[0].right_ref.local_id,
      })),
    );
  } catch {
    ctxError = true;
  }

  return <Bench initialCases={cases} context={context} ctxError={ctxError} />;
}
