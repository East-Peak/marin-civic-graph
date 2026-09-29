// app/src/lib/entity-route.ts
//
// The one id <-> route mapping for entity links. A route is `/<segment>/<slug>`:
// the slug is the id minus a prefix REGISTERED FOR THAT TYPE (TYPE_BY_ID_PREFIX),
// or the whole id when its prefix is not one (a `permit-` Project, a `doc-` Record).
// resolveEntityId inverts it by trying each of the type's prefixes, then the slug as
// a whole id, then the legacy aliases — and never returns a node of another type.
import { resolveIdAlias } from "./id-aliases";
import { TYPE_BY_ID_PREFIX, type NodeType } from "./node-types.generated";
import { ALL_TYPES, urlSegmentForType } from "./type-display";

const PREFIXES_BY_TYPE = new Map<NodeType, string[]>();
for (const [prefix, type] of Object.entries(TYPE_BY_ID_PREFIX)) {
  PREFIXES_BY_TYPE.set(type, [...(PREFIXES_BY_TYPE.get(type) ?? []), prefix]);
}
for (const prefixes of PREFIXES_BY_TYPE.values()) {
  prefixes.sort((a, b) => b.length - a.length); // longest first
}

export function typeForSegment(segment: string): NodeType | null {
  return ALL_TYPES.find((type) => urlSegmentForType(type) === segment) ?? null;
}

export function entityRoute(id: string, type: NodeType): string {
  const prefix = (PREFIXES_BY_TYPE.get(type) ?? []).find((p) => id.startsWith(p));
  const slug = prefix ? id.slice(prefix.length) : id;
  return `/${urlSegmentForType(type)}/${encodeURIComponent(slug)}`;
}

/** Route for an id whose type is only known from its prefix; null if unregistered. */
export function entityRouteForId(id: string, type?: NodeType | null): string | null {
  const resolved = type ?? resolveIdAlias(id)?.type ?? null;
  return resolved ? entityRoute(id, resolved) : null;
}

/**
 * The id a route names, or null. `lookupType` returns a stored node's type, or null
 * when no node has that id. `slug` is the decoded path segment.
 */
export function resolveEntityId(
  segment: string,
  slug: string,
  lookupType: (id: string) => NodeType | null,
): string | null {
  const type = typeForSegment(segment);
  if (!type) {
    // A legacy segment (/actor/…, /inst/…): the old route was `<segment>-<slug>`.
    const alias = resolveIdAlias(`${segment}-${slug}`);
    return alias && lookupType(alias.id) === alias.type ? alias.id : null;
  }
  const isOfType = (id: string) => lookupType(id) === type;

  for (const prefix of PREFIXES_BY_TYPE.get(type) ?? []) {
    if (isOfType(prefix + slug)) return prefix + slug;
  }
  if (isOfType(slug)) return slug;

  const alias = resolveIdAlias(slug, type);
  if (alias && isOfType(alias.id)) return alias.id;
  return null;
}
