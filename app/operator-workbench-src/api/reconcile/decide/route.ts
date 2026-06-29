// POST /api/reconcile/decide — operator-only write route. Build-excluded from public
// builds (lives outside src/app; copied in only under OPERATOR_WORKBENCH=1, never on a
// deploy). Shells to reconcile_decide.py → reconcile_writer.apply_decision (the proven
// Goal-A writer: atomic, idempotent, superseding; materializes the SAME_AS handoff). The
// runtime gate is defense-in-depth on top of the physical build exclusion.
import { NextResponse } from "next/server";
import { operatorEnabled } from "@/lib/operator-gate";
import { DATA, runPython } from "../../../_lib/operator-python";

export const dynamic = "force-dynamic";

const ACTIONS = new Set(["approve", "reject", "unsure"]);
const ALLOWED_ORIGINS = new Set(["http://127.0.0.1:3000", "http://localhost:3000"]);

export async function POST(request: Request) {
  if (!operatorEnabled()) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  // CSRF defense-in-depth (operator-local): same-origin only + JSON content type. A
  // cross-origin browser POST with application/json triggers a CORS preflight this route
  // never allows, so it's blocked; the Origin check covers any that slip through.
  const origin = request.headers.get("origin");
  if (origin && !ALLOWED_ORIGINS.has(origin)) {
    return NextResponse.json({ error: "forbidden origin" }, { status: 403 });
  }
  if (!request.headers.get("content-type")?.includes("application/json")) {
    return NextResponse.json({ error: "content-type must be application/json" }, { status: 415 });
  }
  // Optional shared-secret token (when OPERATOR_TOKEN is set by dev:operator).
  const token = process.env.OPERATOR_TOKEN;
  if (token && request.headers.get("x-operator-token") !== token) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  let body: { case_id?: string; action?: string; reviewer?: string; rejection_kind?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const { case_id, action, reviewer, rejection_kind } = body;
  if (!case_id || !action || !ACTIONS.has(action)) {
    return NextResponse.json({ error: "case_id and a valid action (approve|reject|unsure) are required" }, { status: 400 });
  }
  if (action === "reject" && rejection_kind !== "current_evidence" && rejection_kind !== "entity_distinct") {
    return NextResponse.json({ error: "reject requires rejection_kind (current_evidence|entity_distinct)" }, { status: 400 });
  }

  const args = [
    "--case-id", case_id,
    "--action", action,
    "--reviewer", reviewer || "operator",
    "--decided-at", new Date().toISOString(),
    "--read-model", DATA.readModel(),
    "--ein-candidates", DATA.einCandidates(),
    "--sos-candidates", DATA.sosCandidates(),
    "--ledger", DATA.attachLedger(),
    "--attach-dir", DATA.attachDir(),
  ];
  if (action === "reject" && rejection_kind) {
    args.push("--rejection-kind", rejection_kind);
  }

  try {
    const result = runPython<{ result: string; assertion: unknown; same_as: unknown }>("reconcile_decide.py", args);
    return NextResponse.json(result);
  } catch (err) {
    console.error("[reconcile/decide] failed:", err); // detail to server logs, not the response
    return NextResponse.json({ error: "decide failed" }, { status: 500 });
  }
}
