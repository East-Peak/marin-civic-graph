#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { performance } from "node:perf_hooks";

const DEFAULT_SQLITE_PATH = "data/exports/public-substrate.sqlite";
const sqlitePath = process.argv[2] || DEFAULT_SQLITE_PATH;
const installHint = "npm --prefix app install better-sqlite3";

function loadBetterSqlite3() {
  const candidates = [
    () => createRequire(new URL("../app/package.json", import.meta.url))("better-sqlite3"),
    () => createRequire(import.meta.url)("better-sqlite3"),
  ];
  for (const load of candidates) {
    try {
      return load();
    } catch (error) {
      if (error?.code !== "MODULE_NOT_FOUND" && error?.code !== "ERR_DLOPEN_FAILED") {
        throw error;
      }
    }
  }
  return null;
}

function readEdgesWithBetterSqlite3(Database) {
  const db = new Database(sqlitePath, { readonly: true, fileMustExist: true });
  try {
    return db.prepare("SELECT source, rel, target FROM edges").all();
  } finally {
    db.close();
  }
}

function readEdgesWithSqliteCli() {
  const result = spawnSync(
    "sqlite3",
    [
      "-json",
      sqlitePath,
      "SELECT source, rel, target FROM edges ORDER BY source, rel, target;",
    ],
    {
      encoding: "utf-8",
      maxBuffer: 256 * 1024 * 1024,
    },
  );
  if (result.error) {
    throw new Error(
      `better-sqlite3 is not installed and sqlite3 CLI is unavailable. Install with: ${installHint}`,
    );
  }
  if (result.status !== 0) {
    throw new Error(result.stderr.trim() || "sqlite3 CLI failed");
  }
  return JSON.parse(result.stdout.trim() || "[]");
}

function buildAdjacency(rows) {
  const adjacency = new Map();
  for (const row of rows) {
    const source = String(row.source);
    const rel = String(row.rel);
    const target = String(row.target);
    let outbound = adjacency.get(source);
    if (!outbound) {
      outbound = [];
      adjacency.set(source, outbound);
    }
    outbound.push([rel, target]);
  }
  return adjacency;
}

if (!existsSync(sqlitePath)) {
  console.error(`SQLite substrate not found: ${sqlitePath}`);
  process.exit(1);
}

const start = performance.now();
// A native module compiled for a different Node ABI fails with
// ERR_DLOPEN_FAILED, and newer better-sqlite3 only loads its addon when a
// database is opened, so the fallback has to wrap the read, not the require.
function readEdges() {
  const Database = loadBetterSqlite3();
  if (Database) {
    try {
      return { backend: "better-sqlite3", rows: readEdgesWithBetterSqlite3(Database) };
    } catch (error) {
      if (error?.code !== "ERR_DLOPEN_FAILED") throw error;
      console.error(`better-sqlite3 unusable (${error.code}); falling back to sqlite3 CLI`);
    }
  }
  return { backend: "sqlite3-cli", rows: readEdgesWithSqliteCli() };
}

const { backend, rows } = readEdges();
const adjacency = buildAdjacency(rows);
const wallMs = performance.now() - start;

const metrics = {
  sqlite_path: sqlitePath,
  backend,
  dependency_note:
    backend === "better-sqlite3"
      ? null
      : `better-sqlite3 missing or built for another Node ABI; fix with: ${installHint} (or npm --prefix app rebuild better-sqlite3)`,
  edge_count: rows.length,
  adjacency_sources: adjacency.size,
  adjacency_entries: rows.length,
  wall_ms: Number(wallMs.toFixed(3)),
  memory_usage: process.memoryUsage(),
};

console.log(JSON.stringify(metrics, null, 2));
