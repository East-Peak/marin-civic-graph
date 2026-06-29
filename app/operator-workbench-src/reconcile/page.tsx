// Operator-local route group — copied into src/app/(operator-workbench)/ ONLY under
// OPERATOR_WORKBENCH=1 (scripts/copy-operator-workbench.mjs). NEVER present in a public
// build. The bench UI is built here in Slice 3.
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";

export const dynamic = "force-dynamic";

export default function ReconcilePage() {
  if (!operatorEnabled()) notFound(); // defense-in-depth if ever shipped/leaked
  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1>Identity Attach Workbench</h1>
      <p>Operator-local reconcile bench. Slice 1 scaffolding — UI lands in Slice 3.</p>
    </main>
  );
}
