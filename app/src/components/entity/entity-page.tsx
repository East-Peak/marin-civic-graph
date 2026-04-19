// Phase-D placeholder: renders the loader's EntityPayload as a JSON dump.
// Phase E/F replace this with the real radial hero + facts panel per §7.1/§7.2.
import type { EntityPayload } from "@/lib/server/entity-loader";

export function EntityPage({ entity }: { entity: EntityPayload }) {
  return (
    <div className="min-h-screen bg-bg p-8 font-mono text-body">
      <pre className="whitespace-pre-wrap text-xs">
        {JSON.stringify(entity, null, 2)}
      </pre>
    </div>
  );
}
