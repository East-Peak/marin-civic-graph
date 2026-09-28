import "server-only";

import Database from "better-sqlite3";
import path from "node:path";

let substrateDb: Database.Database | null = null;

export type ServingBackend = "substrate" | "live";

// Substrate by default: Aura was deleted 2026-07-08, so a deploy that forgets
// this env var must serve the baked artifact rather than reach for a database
// that no longer exists. "live" (local Neo4j) is an explicit opt-in.
export function servingBackend(): ServingBackend {
  return process.env.SERVING_BACKEND === "live" ? "live" : "substrate";
}

export function substrateDbPath(): string {
  const configured = process.env.SUBSTRATE_DB_PATH;
  if (configured && configured.trim() !== "") {
    return path.resolve(configured);
  }
  return path.resolve(process.cwd(), "..", "data", "exports", "public-substrate.sqlite");
}

export function getSubstrateDb(): Database.Database {
  if (substrateDb) return substrateDb;
  substrateDb = new Database(substrateDbPath(), {
    readonly: true,
    fileMustExist: true,
  });
  return substrateDb;
}

export function closeSubstrateDb(): void {
  if (substrateDb) {
    substrateDb.close();
    substrateDb = null;
  }
}
