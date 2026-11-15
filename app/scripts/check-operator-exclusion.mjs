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
const OPERATOR_MARKERS = ["/reconcile", "/api/reconcile", "/minutes", "/actors", "/cases"];
// The operator index readers name their index's env var and file. A public build containing one could serve the
// minutes text (private people) or the actor index (research on named people and organizations).
const READERS = {
  "minutes text": ["MINUTES_TEXT_DB_PATH", "minutes-text.sqlite"], // operator-workbench-src/_lib/minutes-text.ts
  actor: ["ACTORS_DB_PATH", "actors.sqlite"], // operator-workbench-src/_lib/actors.ts
};

// Guard: the generated route group must NEVER be a tracked file (gitignore is not enough
// — `git add -f` or a stray commit could ship it). Run before anything else.
const tracked = execSync("git ls-files 'src/app/(operator-workbench)'", { cwd: APP }).toString().trim();
if (tracked) {
  throw new Error(`generated operator route group is COMMITTED (must be gitignored only):\n${tracked}`);
}
console.log("[0] ✓ no operator route-group files are tracked in git");

// No text-bearing response either: each reader must be absent from the public build's output (and present in the
// operator build's, so this check can fail).
function filesUnder(dir) {
  // Symlinks inside .next point at node_modules (never generated output): not followed.
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? filesUnder(path.join(dir, e.name)) : e.isFile() ? [path.join(dir, e.name)] : [],
  );
}
function readerFiles(markers) {
  return filesUnder(path.join(APP, ".next")).filter((f) => {
    if (f.includes(`${path.sep}cache${path.sep}`)) return false; // build cache, never served
    const text = readFileSync(f).toString("latin1");
    return markers.some((m) => text.includes(m));
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
const hasActors = present.some((t) => t.includes("/actors/page"));
const hasActor = present.some((t) => t.includes("/actors/[slug]"));
const hasCase = present.some((t) => t.includes("/cases/[docket]"));
if (!hasPage || !hasDecideApi || !hasCasesApi || !hasMinutes || !hasActors || !hasActor || !hasCase) {
  throw new Error(
    `operator build missing routes (page=${hasPage}, decide=${hasDecideApi}, cases=${hasCasesApi}, minutes=${hasMinutes}, actors=${hasActors}, actor=${hasActor}, case=${hasCase}); saw: ${present.join(", ") || "none"}`,
  );
}
console.log(`  ✓ present: ${present.join(", ")}`);
for (const [name, markers] of Object.entries(READERS)) {
  if (readerFiles(markers).length === 0) {
    throw new Error(`operator build has no ${name} reader: the public-build reader check would prove nothing`);
  }
  console.log(`  ✓ operator build contains the ${name} reader`);
}

console.log("[B] public build (after operator copy) — routes must be ABSENT");
const leaked = operatorRoutesIn(build(false));
if (leaked.length > 0) {
  throw new Error(`LEAK: public build contains operator routes: ${leaked.join(", ")}`);
}
console.log("  ✓ none present (stale operator copy was cleaned by the public prebuild)");

for (const [name, markers] of Object.entries(READERS)) {
  const readerIn = readerFiles(markers);
  if (readerIn.length > 0) {
    throw new Error(`LEAK: public build contains the ${name} reader:\n${readerIn.join("\n")}`);
  }
  console.log(`  ✓ public build output contains no ${name} reader`);
}

console.log("PASS: operator route group is non-deployable.");
