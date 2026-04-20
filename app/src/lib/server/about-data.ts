// app/src/lib/server/about-data.ts
//
// Server-only loader for the /about page's jurisdictions list.
//
// The graph uses :Place with place_type in {'city','town','county'} for
// jurisdictions — there is no :Jurisdiction label (see loadStatus() in
// homepage-data.ts for precedent). We filter to those place_types so we
// don't leak neighborhoods, regions, or other place shapes onto the page.

import "server-only";
import { runQuery } from "@/lib/neo4j";

export type Jurisdiction = {
  name: string;
  type: string;
};

export async function loadJurisdictions(): Promise<Jurisdiction[]> {
  try {
    const records = await runQuery(
      `
      MATCH (p:Place)
      WHERE p.place_type IN ['city', 'town', 'county']
      RETURN p.name AS name, coalesce(p.place_type, '') AS type
      ORDER BY p.name ASC
      `,
    );
    return records.map((r) => ({
      name: String(r.get("name") ?? ""),
      type: String(r.get("type") ?? ""),
    }));
  } catch {
    return [];
  }
}
