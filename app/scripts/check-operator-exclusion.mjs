// app/scripts/check-operator-exclusion.mjs
// THE build-safety guarantee (spec §5.1). Proves the operator route group is
// non-deployable by doing real builds and inspecting Next's App Router manifest:
//   A) operator build (OPERATOR_WORKBENCH=1) → manifest MUST contain the operator routes
//   B) public build (no OPERATOR_WORKBENCH, run AFTER A) → manifest MUST contain NONE
//      (this also exercises the stale-copy regression: A leaves a copy, B's prebuild
//       must remove it before building).
// Exits non-zero on any leak. Run via `npm run check:operator-exclusion`.
import { execSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(__dirname, "..");
const MANIFEST = path.join(APP, ".next", "server", "app-paths-manifest.json");
const OPERATOR_MARKERS = ["/reconcile", "/api/reconcile", "/minutes"];
// The minutes text reader (operator-workbench-src/_lib/minutes-text.ts) names the index's env var; a public
// build that contains it could serve minutes text, which names private people.
const MINUTES_READER_MARKERS = ["MINUTES_TEXT_DB_PATH", "minutes-text.sqlite"];

// Guard: the generated route group must NEVER be a tracked file (gitignore is not enough
// — `git add -f` or a stray commit could ship it). Run before anything else.
const tracked = execSync("git ls-files 'src/app/(operator-workbench)'", { cwd: APP }).toString().trim();
if (tracked) {
  throw new Error(`generated operator route group is COMMITTED (must be gitignored only):\n${tracked}`);
}
console.log("[0] ✓ no operator route-group files are tracked in git");

// No text-bearing response either: the minutes reader must be absent from the public build's output (and present
// in the operator build's, so this check can fail).
function filesUnder(dir) {
  // Symlinks inside .next point at node_modules (never generated output): not followed.
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? filesUnder(path.join(dir, e.name)) : e.isFile() ? [path.join(dir, e.name)] : [],
  );
}
function minutesReaderFiles() {
  return filesUnder(path.join(APP, ".next")).filter((f) => {
    if (f.includes(`${path.sep}cache${path.sep}`)) return false; // build cache, never served
    const text = readFileSync(f).toString("latin1");
    return MINUTES_READER_MARKERS.some((m) => text.includes(m));
  });
}

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
const hasMinutes = present.some((t) => t.includes("/minutes"));
if (!hasPage || !hasDecideApi || !hasCasesApi || !hasMinutes) {
  throw new Error(
    `operator build missing routes (page=${hasPage}, decide=${hasDecideApi}, cases=${hasCasesApi}, minutes=${hasMinutes}); saw: ${present.join(", ") || "none"}`,
  );
}
console.log(`  ✓ present: ${present.join(", ")}`);
if (minutesReaderFiles().length === 0) {
  throw new Error("operator build has no minutes text reader: the public-build reader check would prove nothing");
}
console.log("  ✓ operator build contains the minutes text reader");

console.log("[B] public build (after operator copy) — routes must be ABSENT");
const leaked = operatorRoutesIn(build(false));
if (leaked.length > 0) {
  throw new Error(`LEAK: public build contains operator routes: ${leaked.join(", ")}`);
}
console.log("  ✓ none present (stale operator copy was cleaned by the public prebuild)");

const readerIn = minutesReaderFiles();
if (readerIn.length > 0) {
  throw new Error(`LEAK: public build contains the minutes text reader:\n${readerIn.join("\n")}`);
}
console.log("  ✓ public build output contains no minutes text reader");

console.log("PASS: operator route group is non-deployable.");
