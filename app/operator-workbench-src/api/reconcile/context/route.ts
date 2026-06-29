// POST /api/reconcile/context — the whitelisted Neo4j consequence projection for a batch
// of cases (operator-only, build-excluded). Read-only + redaction-safe. Thin wrapper over
// fetchContext; the queries live in _lib/operator-context.ts (shared with the bench page).
import { NextResponse } from "next/server";
import { operatorEnabled } from "@/lib/operator-gate";
import { fetchContext } from "../../../_lib/operator-context";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  if (!operatorEnabled()) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  let body: { items?: { vendor_id?: string; anchor_id?: string }[] };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const items = (body.items ?? []).filter((i): i is { vendor_id: string; anchor_id?: string } => Boolean(i?.vendor_id));
  try {
    return NextResponse.json({ results: await fetchContext(items) });
  } catch (err) {
    console.error("[reconcile/context] failed:", err); // detail to server logs, not the response
    return NextResponse.json({ error: "context failed" }, { status: 500 });
  }
}
