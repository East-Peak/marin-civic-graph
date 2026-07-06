// Operator-only server helper: run a project Python script (venv) and parse its JSON
// stdout. Lives inside the build-excluded operator route group (never in a public build).
//
// Paths come from env vars set by `npm run dev:operator` (OPERATOR_REPO_ROOT + the venv
// OPERATOR_PYTHON) — NOT static literals. This is deliberate: a literal ".venv/bin/python"
// path makes Turbopack try to trace+bundle the venv symlink (which points outside the repo
// root) and panic at build. Reading them from env keeps the build clean. All values are
// server-fixed (never request-derived).
import { execFileSync } from "node:child_process";
import path from "node:path";

function repoRoot(): string {
  const r = process.env.OPERATOR_REPO_ROOT;
  if (!r) throw new Error("OPERATOR_REPO_ROOT not set — run via `npm run dev:operator`");
  return r;
}

function pythonBin(): string {
  const p = process.env.OPERATOR_PYTHON;
  if (!p) throw new Error("OPERATOR_PYTHON not set — run via `npm run dev:operator`");
  return p;
}

/** Resolve a path under the repo root (segments joined to a runtime base — not traced). */
export function repoPath(...segments: string[]): string {
  return path.join(repoRoot(), ...segments);
}

export const DATA = {
  readModel: () => repoPath("data", "review", "reconciliation", "read-model.jsonl"),
  attachLedger: () => repoPath("data", "identity", "assertions.jsonl"),
  einCandidates: () => repoPath("data", "review", "phaseB-ein-review", "vendor-ein-candidates.jsonl"),
  sosCandidates: () => repoPath("data", "review", "phaseC-sos-review", "vendor-sos-candidates.jsonl"),
  committeeCandidates: () => repoPath("data", "review", "fppc-committee-review", "committee-candidates.jsonl"),
  attachDir: () => repoPath("data", "review", "attach"),
};

export function runPython<T = unknown>(script: string, args: string[]): T {
  const stdout = execFileSync(pythonBin(), [repoPath("scripts", script), ...args], {
    encoding: "utf-8",
    maxBuffer: 64 * 1024 * 1024,
  });
  return JSON.parse(stdout) as T;
}
