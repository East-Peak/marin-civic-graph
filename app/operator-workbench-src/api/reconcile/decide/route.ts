// POST /api/reconcile/decide — operator-only write route. Build-excluded from public
// builds (lives outside src/app; copied in only under OPERATOR_WORKBENCH=1, never on a
// deploy). The runtime gate is defense-in-depth on top of that physical exclusion. Slice
// 4 wires the body to scripts/reconcile_writer.apply_decision via a subprocess.
import { NextResponse } from "next/server";
import { operatorEnabled } from "@/lib/operator-gate";

export const dynamic = "force-dynamic";

export async function POST() {
  if (!operatorEnabled()) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ error: "not implemented (Slice 4)" }, { status: 501 });
}
