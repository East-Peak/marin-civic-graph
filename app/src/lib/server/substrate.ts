import "server-only";

import Database from "better-sqlite3";
import path from "node:path";

let substrateDb: Database.Database | null = null;

export type ServingBackend = "substrate" | "live";

export function servingBackend(): ServingBackend {
  return process.env.SERVING_BACKEND === "substrate" ? "substrate" : "live";
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
