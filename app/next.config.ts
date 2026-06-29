import type { NextConfig } from "next";
import { rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Build-safety preflight (Tranche-2 Slice 1). Runs on EVERY `next build`/`next dev`
// before route collection — so it CANNOT be bypassed by a Vercel build-command override
// that skips the npm `prebuild` hook. It removes the operator route group UNLESS this is
// a local operator session (OPERATOR_WORKBENCH=1 with NO deploy/CI signal). A public or
// deployed build therefore never collects /reconcile or /api/reconcile/*.
// Anchored to THIS config file's directory (not process.cwd()), so it resolves correctly
// even when invoked as `next build app` from the repo root.
const HERE = path.dirname(fileURLToPath(import.meta.url));
const OPERATOR_DEST = path.join(HERE, "src", "app", "(operator-workbench)");
const ON_DEPLOY = Boolean(process.env.VERCEL || process.env.VERCEL_ENV || process.env.CI);
const LOCAL_OPERATOR = process.env.OPERATOR_WORKBENCH === "1" && !ON_DEPLOY;
if (!LOCAL_OPERATOR) {
  rmSync(OPERATOR_DEST, { recursive: true, force: true });
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
