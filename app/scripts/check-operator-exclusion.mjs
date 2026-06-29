// app/scripts/check-operator-exclusion.mjs
// THE build-safety guarantee (spec §5.1). Proves the operator route group is
// non-deployable by doing real builds and inspecting Next's App Router manifest:
//   A) operator build (OPERATOR_WORKBENCH=1) → manifest MUST contain the operator routes
//   B) public build (no OPERATOR_WORKBENCH, run AFTER A) → manifest MUST contain NONE
//      (this also exercises the stale-copy regression: A leaves a copy, B's prebuild
//       must remove it before building).
// Exits non-zero on any leak. Run via `npm run check:operator-exclusion`.
import { execSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(__dirname, "..");
const MANIFEST = path.join(APP, ".next", "server", "app-paths-manifest.json");
const OPERATOR_MARKERS = ["/reconcile", "/api/reconcile"];

// Guard: the generated route group must NEVER be a tracked file (gitignore is not enough
// — `git add -f` or a stray commit could ship it). Run before anything else.
const tracked = execSync("git ls-files 'src/app/(operator-workbench)'", { cwd: APP }).toString().trim();
if (tracked) {
  throw new Error(`generated operator route group is COMMITTED (must be gitignored only):\n${tracked}`);
}
console.log("[0] ✓ no operator route-group files are tracked in git");

function build(operator) {
  rmSync(path.join(APP, ".next"), { recursive: true, force: true });
  execSync("npm run build", {
    cwd: APP,
    stdio: "inherit",
    // Clear deploy/CI signals so step A can mount locally regardless of where this runs.
    env: { ...process.env, CI: "", VERCEL: "", VERCEL_ENV: "", OPERATOR_WORKBENCH: operator ? "1" : "" },
  });
  if (!existsSync(MANIFEST)) throw new Error(`manifest missing after build: ${MANIFEST}`);
  return JSON.parse(readFileSync(MANIFEST, "utf-8"));
}

function operatorRoutesIn(manifest) {
  const tokens = [...Object.keys(manifest), ...Object.values(manifest)].map(String);
  return [...new Set(tokens.filter((t) => OPERATOR_MARKERS.some((m) => t.includes(m))))];
}

console.log("[A] operator build — both operator routes must be PRESENT");
const present = operatorRoutesIn(build(true));
const hasPage = present.some((t) => t.includes("/reconcile") && !t.includes("/api/"));
const hasDecideApi = present.some((t) => t.includes("/api/reconcile/decide"));
const hasCasesApi = present.some((t) => t.includes("/api/reconcile/cases"));
if (!hasPage || !hasDecideApi || !hasCasesApi) {
  throw new Error(
    `operator build missing routes (page=${hasPage}, decide=${hasDecideApi}, cases=${hasCasesApi}); saw: ${present.join(", ") || "none"}`,
  );
}
console.log(`  ✓ present: ${present.join(", ")}`);

console.log("[B] public build (after operator copy) — routes must be ABSENT");
const leaked = operatorRoutesIn(build(false));
if (leaked.length > 0) {
  throw new Error(`LEAK: public build contains operator routes: ${leaked.join(", ")}`);
}
console.log("  ✓ none present (stale operator copy was cleaned by the public prebuild)");

console.log("PASS: operator route group is non-deployable.");
