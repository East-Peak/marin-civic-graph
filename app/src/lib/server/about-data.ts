// app/src/lib/server/about-data.ts
//
// Server-only loader for the /about page's jurisdictions list.
//
// The graph uses :Place with place_type in {'city','town','county'} for
// jurisdictions — there is no :Jurisdiction label (see loadStatus() in
// homepage-data.ts for precedent). We import JURISDICTION_PLACE_TYPES so
// both the list here and the status-bar count agree on which Place nodes
// count as jurisdictions.

import "server-only";
import { runQuery } from "@/lib/neo4j";
import { JURISDICTION_PLACE_TYPES } from "@/lib/server/jurisdiction-types";

export type Jurisdiction = {
  name: string;
  type: string;
};

export async function loadJurisdictions(): Promise<Jurisdiction[]> {
  try {
    const records = await runQuery(
      `
      MATCH (p:Place)
      WHERE p.place_type IN $place_types
      RETURN p.name AS name, coalesce(p.place_type, '') AS type
      ORDER BY p.name ASC
      `,
      { place_types: JURISDICTION_PLACE_TYPES },
    );
    return records.map((r) => ({
      name: String(r.get("name") ?? ""),
      type: String(r.get("type") ?? ""),
    }));
  } catch {
    return [];
  }
}
