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
      if (error?.code !== "MODULE_NOT_FOUND") {
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
const Database = loadBetterSqlite3();
const backend = Database ? "better-sqlite3" : "sqlite3-cli";
const rows = Database ? readEdgesWithBetterSqlite3(Database) : readEdgesWithSqliteCli();
const adjacency = buildAdjacency(rows);
const wallMs = performance.now() - start;

const metrics = {
  sqlite_path: sqlitePath,
  backend,
  dependency_note: Database
    ? null
    : `better-sqlite3 not found under app/node_modules; install with: ${installHint}`,
  edge_count: rows.length,
  adjacency_sources: adjacency.size,
  adjacency_entries: rows.length,
  wall_ms: Number(wallMs.toFixed(3)),
  memory_usage: process.memoryUsage(),
};

console.log(JSON.stringify(metrics, null, 2));
