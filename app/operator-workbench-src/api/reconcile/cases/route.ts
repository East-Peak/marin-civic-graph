// GET /api/reconcile/cases — the queue read path. Shells to reconciliation_overlay.overlay_cases
// (the proven Python: static read model + live ledger-status overlay). Operator-only,
// build-excluded; gated at runtime as defense-in-depth.
import { NextResponse } from "next/server";
import { operatorEnabled } from "@/lib/operator-gate";
import { DATA, runPython } from "../../../_lib/operator-python";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!operatorEnabled()) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const cases = runPython<unknown[]>("reconciliation_overlay.py", [
    "--read-model", DATA.readModel(),
    "--ledger", DATA.attachLedger(),
  ]);
  return NextResponse.json({ cases, count: cases.length });
}
