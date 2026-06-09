// app/src/lib/id-aliases.ts
import {
  TYPE_BY_ID_PREFIX,
  resolveTypeFromId,
  type NodeType,
} from "./node-types.generated";

// Per spec §4.2. Legacy id-STRING rewrites from earlier projection stages
// (actor-x → person-x). This map only canonicalizes the id text; the TYPE
// resolution comes from the registry-derived resolveTypeFromId — one source,
// so the real `agenda-item-` prefix resolves correctly everywhere.
const LEGACY_ID_REWRITE: Record<string, string> = {
  "actor-": "person-",
  "inst-": "org-",
  "eid-": "filing-",
};

export type ResolvedId = { id: string; type: NodeType };

export function resolveIdAlias(id: string, contextType?: NodeType): ResolvedId | null {
  let canonicalId = id;
  for (const [legacy, canonical] of Object.entries(LEGACY_ID_REWRITE)) {
    if (id.startsWith(legacy)) {
      // Only apply if context is compatible (actor- → person- only makes sense
      // for Person). The canonical prefix's type comes from the registry map.
      const resolvedType = TYPE_BY_ID_PREFIX[canonical];
      if (contextType && contextType !== resolvedType) continue;
      canonicalId = canonical + id.slice(legacy.length);
      break;
    }
  }
  const type = resolveTypeFromId(canonicalId);
  if (type === null) return null;
  if (contextType && contextType !== type) return null;
  return { id: canonicalId, type };
}
