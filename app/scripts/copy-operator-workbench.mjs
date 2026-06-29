// app/scripts/copy-operator-workbench.mjs
// FAIL-CLOSED operator route-group mount. ALWAYS removes the generated route group from
// src/app first; then copies it back ONLY when OPERATOR_WORKBENCH=1. So a public build
// (predev/prebuild without OPERATOR_WORKBENCH) NEVER contains /reconcile or
// /api/reconcile/* — even if a prior `dev:operator` left a stale copy behind.
//
// The destination is FIXED (never request- or arg-configurable) by design.
import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "..", "operator-workbench-src");
const DEST = path.resolve(__dirname, "..", "src", "app", "(operator-workbench)");

const ON_DEPLOY = Boolean(process.env.VERCEL || process.env.VERCEL_ENV || process.env.CI);

async function main() {
  await rm(DEST, { recursive: true, force: true }); // fail-closed: always remove first
  if (process.env.OPERATOR_WORKBENCH !== "1") {
    console.log("operator workbench EXCLUDED (OPERATOR_WORKBENCH != 1)");
    return;
  }
  if (ON_DEPLOY) {
    // Hard stop: never mount the operator routes on a deploy/CI build even if the flag leaks.
    console.error("REFUSING to mount operator workbench: deploy/CI signal present (VERCEL/VERCEL_ENV/CI)");
    process.exit(1);
  }
  await mkdir(DEST, { recursive: true });
  await cp(SRC, DEST, { recursive: true });
  console.log(`operator workbench MOUNTED → ${DEST}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
