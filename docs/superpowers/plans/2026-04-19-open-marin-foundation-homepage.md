# Open Marin Frontend — Plan 1: Foundation + Homepage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a deployable Next.js app on Vercel that renders the Open Marin homepage — status bar, nav header, prompt-styled search, left catalog (live counts from AuraDB), center signature subgraph (baked JSON rendered with Cytoscape in the Obsidian Glow language), right currently-tracking threads, and a live `/api/search` endpoint. This is Plan 1 of ~4; later plans handle entity pages, explorer + data pages, and command palette + auth + deploy polish.

**Architecture:**
- Next.js 16 App Router, deployed to Vercel with push-to-main.
- Neo4j AuraDB via `neo4j-driver` (JavaScript), singleton driver module, live Cypher for catalog and search; baked JSON bundles for the homepage signature subgraph (built from a Python script running locally, committed to the repo under `data/projected/graph-v1/signature-subgraphs/`).
- Graph visual language via Cytoscape.js + fcose. Shared styling module emits Obsidian Glow tokens for nodes and edges.
- Ingestion-layer additions (Python) for three new node properties — `search_label`, `search_terms`, `search_rank` — plus `preferred_public_url` / `preferred_display_artifact` / `has_public_source` on `Record`. These run as post-load Cypher updates against AuraDB after each ingestion run.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, Tailwind CSS 4, `neo4j-driver`, `cytoscape`, `cytoscape-fcose`, Vitest, Playwright (reuse existing install elsewhere only if needed; not required for this plan), IBM Plex Sans/Mono/Serif + VT323 via Google Fonts, Python 3.14 for ingestion scripts.

**Spec:** `docs/specs/2026-04-19-open-marin-frontend-design.md` (23-round Codex-reviewed). This plan implements §§1–5, §3.7, §6.1, and the ingestion-layer additions from §3.3 and §7.1. Entity pages (§7), explorer (§6.2, §6.3), data explorer (§8), chat (§9), and auth (spec §6 of v1) are out of scope for Plan 1.

**Supersedes:** the Next.js scaffolding portion of `docs/superpowers/plans/2026-04-14-nextjs-app-core-browse.md` (that plan's visual/product direction is obsolete; its foundation tasks are replaced by this plan).

**Prerequisite:** v1 migration (`docs/superpowers/plans/2026-04-14-migration-neo4j-foundation.md`) — graph loaded in AuraDB at `neo4j+s://<INSTANCE-ID>.databases.neo4j.io`. The existing projected graph at `data/projected/graph-v1/` is the source for the signature-subgraph builder.

---

## File Structure

Files created or modified by this plan, grouped by responsibility.

### Next.js app (new)

```
app/
  package.json                              Dependencies, scripts.
  tsconfig.json                             TypeScript config.
  next.config.ts                            Next.js config.
  tailwind.config.ts                        Tailwind theme (palette + fonts).
  postcss.config.mjs                        PostCSS config.
  vitest.config.ts                          Vitest config.
  .env.local.example                        Template for AuraDB creds.
  .env.local                                Real creds (gitignored).
  public/
    (default favicon left in place; deferred)
  src/
    app/
      layout.tsx                            Root layout: <html>, fonts, theme.
      page.tsx                              Homepage: 3-column hero.
      globals.css                           Palette CSS variables, base styles.
      api/
        status/route.ts                     GET /api/status — INGEST + SUBGRAPHS.
        catalog/route.ts                    GET /api/catalog.json — baked.
        search/route.ts                     GET /api/search?q=&include_records=.
        subgraphs/route.ts                  GET /api/subgraphs/manifest.json.
        subgraphs/[slug]/route.ts           GET /api/subgraphs/{slug}.json.
    components/
      layout/
        status-bar.tsx                      Top status bar.
        nav-header.tsx                      Brand + nav + ⌘K chip.
        prompt-search.tsx                   / -focusable search row.
      home/
        catalog-list.tsx                    Left column: catalog types + counts.
        signature-subgraph.tsx              Center: Cytoscape, Obsidian Glow.
        tracking-threads.tsx                Right column: thread cards.
      graph/
        cytoscape-base.tsx                  Shared Cytoscape React wrapper.
        obsidian-style.ts                   Node/edge style tokens.
    lib/
      neo4j.ts                              Driver singleton + query helper.
      palette.ts                            Typed palette tokens (mirrors tailwind).
      type-display.ts                       Per-type display name + URL segment.
      id-aliases.ts                         Legacy-prefix alias table (for §4.2).
      types.ts                              Shared TypeScript types.
      api-errors.ts                         Standard error response shape.
    tests/
      lib/
        neo4j.test.ts
        type-display.test.ts
      api/
        search.test.ts
        status.test.ts
      components/
        catalog-list.test.tsx
        signature-subgraph.test.tsx
```

### Ingestion-layer additions (Python, existing `scripts/` directory)

```
scripts/
  build_search_properties.py                Compute + write search_label / search_terms / search_rank on all 15 searchable types.
  build_record_preferred_urls.py            Compute preferred_public_url + preferred_display_artifact + has_public_source on all Record nodes.
  build_signature_subgraphs.py              Emit manifest + per-slug bundles under data/projected/graph-v1/signature-subgraphs/.
```

### Registry additions

```
registry/
  signature-subgraphs.yaml                  Curated bundle definitions (slug, focus_node_id, display_name, headline template).
  currently-tracking.yaml                   Hand-curated homepage thread cards.
  neo4j-schema.cypher                       (modified) Add openmarin_search_index composite full-text index + per-type search_rank property indexes.
```

### Committed build artifacts

```
data/projected/graph-v1/
  signature-subgraphs/                      Source of truth for bundles (committed).
    manifest.json                           (built) List of available bundles.
    {slug}.json                             (built) Per-bundle node/edge payload per §5.5.
```

Build step copies these to `app/public/subgraphs/` so Next.js serves them statically. That copy destination is gitignored — `data/projected/graph-v1/signature-subgraphs/` is the committed source.

---

## Conventions

- **Git:** push directly to `main` (per workspace memory for this project). Commit after each task. Use imperative present tense commit messages without type prefixes (e.g., `scaffold Next.js app`, `add search API endpoint`).
- **TDD:** write a failing test, run it, implement, run it, commit — for all logic (driver module, API endpoints, query construction, component rendering rules). Pure scaffolding (e.g., `create-next-app`, installing deps) skips the test-first loop — scaffolding is verified by running the app.
- **Dev server:** `cd app && npm run dev`. Production build: `npm run build`.
- **Type checking:** `npm run typecheck` (alias for `tsc --noEmit`). Add to each task's verification step after implementation.
- **Testing:** `npm test` (Vitest) for frontend; `python3.14 -m pytest tests/` for ingestion scripts (existing pattern).
- **Imports:** absolute from `src/` via `@/` alias (configure in Task 1).

---

## Task 1: Scaffold Next.js app

**Files:**
- Create: `app/` (entire directory via `create-next-app`).

- [ ] **Step 1: Run create-next-app from repo root**

```bash
cd /Users/tammypais/projects/marin-civic-graph
npx create-next-app@latest app --typescript --tailwind --eslint --app --src-dir --import-alias '@/*' --no-turbopack --use-npm
```

Accept all default prompts. This creates `app/` with Next.js 16, TypeScript, Tailwind 4, App Router, `src/` directory, `@/` alias.

- [ ] **Step 2: Verify scaffold works**

```bash
cd app
npm run dev
```

Expected: dev server starts on http://localhost:3000, opening it shows the default Next.js welcome page. Stop the server (`Ctrl-C`).

- [ ] **Step 3: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/
git commit -m "$(cat <<'EOF'
scaffold Next.js 16 app for Open Marin frontend

Default create-next-app output with TypeScript, Tailwind 4, App Router, src/ directory, @/ alias. Subsequent tasks replace the default homepage, add the Open Marin theme, Neo4j driver, and API routes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Install runtime dependencies

**Files:**
- Modify: `app/package.json`

- [ ] **Step 1: Install production deps**

```bash
cd app
npm install neo4j-driver cytoscape cytoscape-fcose
```

- [ ] **Step 2: Install dev deps**

```bash
npm install -D @types/cytoscape vitest @vitejs/plugin-react @testing-library/react @testing-library/jest-dom jsdom @vitest/ui
```

- [ ] **Step 3: Verify no install errors**

```bash
npm ls neo4j-driver cytoscape
```

Expected output includes `neo4j-driver@6.x.x` and `cytoscape@3.x.x`. (Major versions may shift; the command should not error.)

- [ ] **Step 4: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/package.json app/package-lock.json
git commit -m "$(cat <<'EOF'
install neo4j-driver, cytoscape, vitest for Open Marin

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wire env config

**Files:**
- Create: `app/.env.local.example`
- Create: `app/.env.local` (gitignored — verify by checking `app/.gitignore` contains `.env*`)

- [ ] **Step 1: Create `.env.local.example`**

```bash
cat > app/.env.local.example <<'EOF'
# Neo4j AuraDB connection
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password-here
NEO4J_DATABASE=neo4j
EOF
```

- [ ] **Step 2: Create real `.env.local`**

Read actual creds from `/Users/tammypais/Desktop/Neo4j-<INSTANCE-ID>-Created-2026-04-14.txt` (per workspace memory) and write `app/.env.local`:

```bash
# Use the actual values from the credentials file:
cat > app/.env.local <<'EOF'
NEO4J_URI=neo4j+s://<INSTANCE-ID>.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=<PASTE-REAL-PASSWORD-FROM-CREDENTIALS-FILE>
NEO4J_DATABASE=neo4j
EOF
```

- [ ] **Step 3: Verify .env.local is gitignored**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git check-ignore app/.env.local && echo "OK — gitignored"
```

Expected output: `OK — gitignored`.

- [ ] **Step 4: Commit only the example**

```bash
git add app/.env.local.example
git commit -m "$(cat <<'EOF'
add .env.local.example for AuraDB connection

.env.local with real creds is gitignored.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Configure Vitest

**Files:**
- Create: `app/vitest.config.ts`
- Create: `app/src/tests/setup.ts`
- Modify: `app/package.json` (add scripts)

- [ ] **Step 1: Create `vitest.config.ts`**

```typescript
// app/vitest.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
    },
  },
});
```

- [ ] **Step 2: Create `setup.ts`**

```typescript
// app/src/tests/setup.ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 3: Add scripts to `package.json`**

Open `app/package.json` and set the `scripts` object to include:

```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "next lint",
  "typecheck": "tsc --noEmit",
  "test": "vitest run",
  "test:watch": "vitest"
}
```

- [ ] **Step 4: Smoke-test by adding a throwaway test**

```typescript
// app/src/tests/smoke.test.ts
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("vitest is wired up", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 5: Run tests**

```bash
cd app && npm test
```

Expected: 1 passed, exit 0.

- [ ] **Step 6: Delete the smoke test and commit**

```bash
rm app/src/tests/smoke.test.ts
cd /Users/tammypais/projects/marin-civic-graph
git add app/vitest.config.ts app/src/tests/setup.ts app/package.json app/package-lock.json
git commit -m "$(cat <<'EOF'
configure Vitest with jsdom + Testing Library setup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Load Google Fonts + define palette

**Files:**
- Create: `app/src/lib/palette.ts`
- Modify: `app/src/app/layout.tsx`
- Modify: `app/src/app/globals.css`
- Modify: `app/tailwind.config.ts`

- [ ] **Step 1: Write `palette.ts` (typed tokens, single source of truth)**

Per spec §2.2. Mirrors the Tailwind theme we'll add in Step 4.

```typescript
// app/src/lib/palette.ts
export const palette = {
  background: "#07090d",
  panel: "#0b0d11",
  surface: "#14171d",
  borderPrimary: "#1f232b",
  borderHairline: "#1a1d24",
  bodyText: "#c2c8d2",
  dimText: "#7b8494",
  hairlineText: "#5e6573",
  node: {
    focus: "#ffffff",
    decision: "#a4e8bf",
    money: "#f2c77a",
    person: "#8db8ff",
    legal: "#e27a7a",
    organization: "#b8a8d9",
    projectProgram: "#d9a88d",
    generic: "#e8ecf3",
  },
  edge: {
    governance: "rgba(150, 180, 220, 0.22)",
    money: "rgba(220, 200, 140, 0.55)",
    legalConstrains: "rgba(226, 122, 122, 0.45)",
  },
} as const;

export type Palette = typeof palette;
```

- [ ] **Step 2: Rewrite `app/src/app/layout.tsx` to load fonts and apply the dark theme**

Per spec §2.3. IBM Plex Mono / Sans / Serif + VT323 via `next/font/google`.

```typescript
// app/src/app/layout.tsx
import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Serif, VT323 } from "next/font/google";
import "./globals.css";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
});

const plexSerif = IBM_Plex_Serif({
  subsets: ["latin"],
  weight: ["400"],
  style: ["italic"],
  variable: "--font-plex-serif",
});

const vt323 = VT323({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-vt323",
});

export const metadata: Metadata = {
  title: "Open Marin",
  description: "Civic intelligence for Marin County — primary-source public records.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable} ${plexSerif.variable} ${vt323.variable}`}>
      <body className="min-h-screen bg-bg text-body antialiased">{children}</body>
    </html>
  );
}
```

- [ ] **Step 3: Replace `app/src/app/globals.css` with Open Marin palette CSS variables**

```css
/* app/src/app/globals.css */
@import "tailwindcss";

:root {
  --color-bg: #07090d;
  --color-panel: #0b0d11;
  --color-surface: #14171d;
  --color-border-primary: #1f232b;
  --color-border-hairline: #1a1d24;
  --color-body: #c2c8d2;
  --color-dim: #7b8494;
  --color-hairline: #5e6573;

  --color-node-focus: #ffffff;
  --color-node-decision: #a4e8bf;
  --color-node-money: #f2c77a;
  --color-node-person: #8db8ff;
  --color-node-legal: #e27a7a;
  --color-node-organization: #b8a8d9;
  --color-node-project-program: #d9a88d;
  --color-node-generic: #e8ecf3;
}

body {
  font-family: var(--font-plex-sans), ui-sans-serif, system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.55;
}

@theme inline {
  --font-sans: var(--font-plex-sans);
  --font-mono: var(--font-plex-mono);
  --font-serif: var(--font-plex-serif);
  --font-terminal: var(--font-vt323);

  --color-bg: var(--color-bg);
  --color-panel: var(--color-panel);
  --color-surface: var(--color-surface);
  --color-border-primary: var(--color-border-primary);
  --color-border-hairline: var(--color-border-hairline);
  --color-body: var(--color-body);
  --color-dim: var(--color-dim);
  --color-hairline: var(--color-hairline);

  --color-node-focus: var(--color-node-focus);
  --color-node-decision: var(--color-node-decision);
  --color-node-money: var(--color-node-money);
  --color-node-person: var(--color-node-person);
  --color-node-legal: var(--color-node-legal);
  --color-node-organization: var(--color-node-organization);
  --color-node-project-program: var(--color-node-project-program);
  --color-node-generic: var(--color-node-generic);
}
```

*(Tailwind 4 uses `@theme inline` for design tokens. If create-next-app installed a different version, adapt syntax but preserve tokens.)*

- [ ] **Step 4: Replace `tailwind.config.ts`**

Tailwind 4 picks up tokens from `@theme inline`, but we also lock classes for any computed or dynamic usage. Keep config minimal:

```typescript
// app/tailwind.config.ts
import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {},
  plugins: [],
} satisfies Config;
```

- [ ] **Step 5: Verify dev server renders a dark page**

```bash
cd app && npm run dev
```

Visit http://localhost:3000 — page should render on the near-black `#07090d` background with Plex Sans body text. Stop server.

- [ ] **Step 6: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/lib/palette.ts app/src/app/layout.tsx app/src/app/globals.css app/tailwind.config.ts
git commit -m "$(cat <<'EOF'
add dark theme, palette tokens, IBM Plex + VT323 fonts

Open Marin palette (spec §2.2): near-black bg, colored node accents, terminal-flavored chrome. Fonts loaded via next/font/google: Plex Sans (body), Plex Mono (UI), Plex Serif Italic (callouts), VT323 (display).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Write Neo4j driver module (TDD)

**Files:**
- Create: `app/src/lib/neo4j.ts`
- Create: `app/src/tests/lib/neo4j.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// app/src/tests/lib/neo4j.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("neo4j driver module", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.NEO4J_URI = "neo4j+s://test.databases.neo4j.io";
    process.env.NEO4J_USER = "neo4j";
    process.env.NEO4J_PASSWORD = "test-password";
    process.env.NEO4J_DATABASE = "neo4j";
  });

  afterEach(() => {
    delete process.env.NEO4J_URI;
    delete process.env.NEO4J_USER;
    delete process.env.NEO4J_PASSWORD;
    delete process.env.NEO4J_DATABASE;
  });

  it("getDriver returns a singleton", async () => {
    const { getDriver } = await import("@/lib/neo4j");
    const a = getDriver();
    const b = getDriver();
    expect(a).toBe(b);
  });

  it("getDriver throws if NEO4J_URI missing", async () => {
    delete process.env.NEO4J_URI;
    const { getDriver } = await import("@/lib/neo4j");
    expect(() => getDriver()).toThrowError(/NEO4J_URI/);
  });

  it("runQuery returns result records", async () => {
    const { runQuery } = await import("@/lib/neo4j");
    const mockRun = vi.fn().mockResolvedValue({ records: [{ get: () => 42 }] });
    const mockSession = { run: mockRun, close: vi.fn() };

    // Monkey-patch driver.session() once
    const { getDriver } = await import("@/lib/neo4j");
    vi.spyOn(getDriver(), "session").mockReturnValue(mockSession as never);

    const records = await runQuery("RETURN 42 AS x", {});
    expect(records).toHaveLength(1);
    expect(mockRun).toHaveBeenCalledWith("RETURN 42 AS x", {});
    expect(mockSession.close).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run — expect failure**

```bash
cd app && npm test -- src/tests/lib/neo4j.test.ts
```

Expected: `Cannot find module '@/lib/neo4j'` or equivalent module-not-found error.

- [ ] **Step 3: Implement `neo4j.ts`**

```typescript
// app/src/lib/neo4j.ts
import neo4j, { type Driver, type Record as Neo4jRecord } from "neo4j-driver";

let driver: Driver | null = null;

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set — check .env.local`);
  }
  return value;
}

export function getDriver(): Driver {
  if (driver) return driver;
  const uri = requireEnv("NEO4J_URI");
  const user = requireEnv("NEO4J_USER");
  const password = requireEnv("NEO4J_PASSWORD");
  driver = neo4j.driver(uri, neo4j.auth.basic(user, password), {
    maxConnectionLifetime: 30 * 60 * 1000,
    maxConnectionPoolSize: 50,
    connectionAcquisitionTimeout: 30 * 1000,
  });
  return driver;
}

export async function runQuery(
  cypher: string,
  params: Record<string, unknown> = {},
): Promise<Neo4jRecord[]> {
  const database = process.env.NEO4J_DATABASE || "neo4j";
  const session = getDriver().session({ database });
  try {
    const result = await session.run(cypher, params);
    return result.records;
  } finally {
    await session.close();
  }
}

export async function closeDriver(): Promise<void> {
  if (driver) {
    await driver.close();
    driver = null;
  }
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd app && npm test -- src/tests/lib/neo4j.test.ts
```

Expected: 3 passed, exit 0.

- [ ] **Step 5: Type-check**

```bash
cd app && npm run typecheck
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/lib/neo4j.ts app/src/tests/lib/neo4j.test.ts
git commit -m "$(cat <<'EOF'
add Neo4j driver singleton + runQuery helper

Single driver instance shared across request lifetime. Session opened per-query, always closed in finally. Fails fast if required env vars are unset.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Write type-display module (TDD)

Per spec §4.1 and §4.2 — URL forms, display names. Single source of truth for per-type strings.

**Files:**
- Create: `app/src/lib/type-display.ts`
- Create: `app/src/tests/lib/type-display.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// app/src/tests/lib/type-display.test.ts
import { describe, it, expect } from "vitest";
import { urlSegmentForType, displayNameForType, ALL_TYPES, INDEXED_TYPES } from "@/lib/type-display";

describe("type-display", () => {
  it("urlSegmentForType returns kebab-case lowercase", () => {
    expect(urlSegmentForType("Person")).toBe("person");
    expect(urlSegmentForType("SeatService")).toBe("seat-service");
    expect(urlSegmentForType("MoneyFlow")).toBe("money-flow");
    expect(urlSegmentForType("AgendaItem")).toBe("agenda-item");
  });

  it("displayNameForType returns human label", () => {
    expect(displayNameForType("Person")).toBe("People");
    expect(displayNameForType("MoneyFlow")).toBe("Money flows");
    expect(displayNameForType("SeatService")).toBe("Seat services");
  });

  it("ALL_TYPES lists all 21 node types", () => {
    expect(ALL_TYPES).toHaveLength(21);
    expect(ALL_TYPES).toContain("Person");
    expect(ALL_TYPES).toContain("Record");
  });

  it("INDEXED_TYPES is the 14 default search corpus (Record excluded)", () => {
    expect(INDEXED_TYPES).toHaveLength(14);
    expect(INDEXED_TYPES).not.toContain("Record");
    expect(INDEXED_TYPES).toContain("Person");
  });
});
```

- [ ] **Step 2: Run — expect failure**

```bash
cd app && npm test -- src/tests/lib/type-display.test.ts
```

- [ ] **Step 3: Implement `type-display.ts`**

```typescript
// app/src/lib/type-display.ts
// Per spec §4.1 + §4.2. Do not fork — this is the single source of truth.

export const ALL_TYPES = [
  "Person",
  "Organization",
  "Committee",
  "Seat",
  "SeatService",
  "Election",
  "Candidacy",
  "Meeting",
  "AgendaItem",
  "Decision",
  "Filing",
  "MoneyFlow",
  "Case",
  "Proceeding",
  "Project",
  "Program",
  "Agreement",
  "Amendment",
  "Record",
  "Place",
  "Issue",
] as const;

export type NodeType = (typeof ALL_TYPES)[number];

// Search corpus per §3.3 — all entity types, Record handled as secondary bucket.
export const INDEXED_TYPES: NodeType[] = [
  "Person",
  "Organization",
  "Decision",
  "Project",
  "Program",
  "Case",
  "Meeting",
  "Filing",
  "Committee",
  "Agreement",
  "Amendment",
  "Election",
  "Place",
  "Issue",
];

const DISPLAY_NAMES: Record<NodeType, string> = {
  Person: "People",
  Organization: "Organizations",
  Committee: "Committees",
  Seat: "Seats",
  SeatService: "Seat services",
  Election: "Elections",
  Candidacy: "Candidacies",
  Meeting: "Meetings",
  AgendaItem: "Agenda items",
  Decision: "Decisions",
  Filing: "Filings",
  MoneyFlow: "Money flows",
  Case: "Cases",
  Proceeding: "Proceedings",
  Project: "Projects",
  Program: "Programs",
  Agreement: "Agreements",
  Amendment: "Amendments",
  Record: "Source records",
  Place: "Places",
  Issue: "Issues",
};

// Convert PascalCase to kebab-case for URLs.
export function urlSegmentForType(type: NodeType): string {
  return type.replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase();
}

export function displayNameForType(type: NodeType): string {
  return DISPLAY_NAMES[type];
}
```

- [ ] **Step 4: Run — expect pass**

```bash
cd app && npm test -- src/tests/lib/type-display.test.ts
```

- [ ] **Step 5: Type-check**

```bash
cd app && npm run typecheck
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/lib/type-display.ts app/src/tests/lib/type-display.test.ts
git commit -m "$(cat <<'EOF'
add type-display module: URL forms + display names + corpus lists

Single source of truth for per-type strings (§4.1, §4.2, §3.3). ALL_TYPES covers the 21 v1 node types; INDEXED_TYPES is the 14-type default search corpus (Record handled separately as secondary bucket).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Write id-aliases table (TDD)

Per spec §4.2 — resolve legacy `actor-*`, `inst-*`, `eid-*` prefixes to their current-schema equivalents.

**Files:**
- Create: `app/src/lib/id-aliases.ts`
- Create: `app/src/tests/lib/id-aliases.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// app/src/tests/lib/id-aliases.test.ts
import { describe, it, expect } from "vitest";
import { resolveIdAlias } from "@/lib/id-aliases";

describe("id-aliases", () => {
  it("passes through canonical ids unchanged", () => {
    expect(resolveIdAlias("person-kate-colin")).toEqual({
      id: "person-kate-colin",
      type: "Person",
    });
  });

  it("resolves actor- → person- for Person urls", () => {
    expect(resolveIdAlias("actor-kate-colin", "Person")).toEqual({
      id: "person-kate-colin",
      type: "Person",
    });
  });

  it("resolves inst- → org- for Organization urls", () => {
    expect(resolveIdAlias("inst-san-rafael-city-council", "Organization")).toEqual({
      id: "org-san-rafael-city-council",
      type: "Organization",
    });
  });

  it("resolves eid- → filing- for Filing urls", () => {
    expect(resolveIdAlias("eid-kate-colin-2024", "Filing")).toEqual({
      id: "filing-kate-colin-2024",
      type: "Filing",
    });
  });

  it("infers type from id prefix when context omitted", () => {
    expect(resolveIdAlias("project-san-rafael-merrydale")).toEqual({
      id: "project-san-rafael-merrydale",
      type: "Project",
    });
  });

  it("returns null for unrecognized ids", () => {
    expect(resolveIdAlias("gibberish-xyz")).toBeNull();
  });
});
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement `id-aliases.ts`**

```typescript
// app/src/lib/id-aliases.ts
import type { NodeType } from "./type-display";

// Per spec §4.2. Legacy prefixes from earlier projection stages.
const LEGACY_PREFIX_MAP: Record<string, string> = {
  "actor-": "person-",
  "inst-": "org-",
  "eid-": "filing-",
};

// Canonical id-prefix → NodeType.
const CANONICAL_PREFIX_MAP: Record<string, NodeType> = {
  "person-": "Person",
  "org-": "Organization",
  "committee-": "Committee",
  "seat-": "Seat",
  "seatservice-": "SeatService",
  "election-": "Election",
  "candidacy-": "Candidacy",
  "meeting-": "Meeting",
  "agendaitem-": "AgendaItem",
  "decision-": "Decision",
  "filing-": "Filing",
  "moneyflow-": "MoneyFlow",
  "case-": "Case",
  "proceeding-": "Proceeding",
  "project-": "Project",
  "program-": "Program",
  "agreement-": "Agreement",
  "amendment-": "Amendment",
  "record-": "Record",
  "place-": "Place",
  "issue-": "Issue",
};

export type ResolvedId = { id: string; type: NodeType };

export function resolveIdAlias(id: string, contextType?: NodeType): ResolvedId | null {
  let canonicalId = id;
  for (const [legacy, canonical] of Object.entries(LEGACY_PREFIX_MAP)) {
    if (id.startsWith(legacy)) {
      // Only apply if context is compatible (actor- → person- only makes sense for Person).
      const resolvedType = CANONICAL_PREFIX_MAP[canonical];
      if (contextType && contextType !== resolvedType) continue;
      canonicalId = canonical + id.slice(legacy.length);
      break;
    }
  }
  for (const [prefix, type] of Object.entries(CANONICAL_PREFIX_MAP)) {
    if (canonicalId.startsWith(prefix)) {
      if (contextType && contextType !== type) return null;
      return { id: canonicalId, type };
    }
  }
  return null;
}
```

- [ ] **Step 4: Run — expect pass**

- [ ] **Step 5: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/lib/id-aliases.ts app/src/tests/lib/id-aliases.test.ts
git commit -m "$(cat <<'EOF'
add id-aliases: resolve legacy actor-/inst-/eid- prefixes

Per spec §4.2. Maps legacy projection prefixes to canonical node ids so old deep-links keep resolving after the migration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Extend Neo4j schema — full-text index + search_rank property indexes

**Files:**
- Modify: `registry/neo4j-schema.cypher` (append new indexes)
- Create: `scripts/apply_search_index.py` (one-off runner for new indexes)

- [ ] **Step 1: Append full-text index definition**

Append to the end of `registry/neo4j-schema.cypher`:

```cypher
// ============================================================================
// Open Marin search index (spec §3.3)
// ============================================================================
// Composite full-text index spanning all 15 searchable types.
// One query hits every indexed type; Record ranked into a separate bucket client-side.

CREATE FULLTEXT INDEX openmarin_search_index IF NOT EXISTS
FOR (n:Person|Organization|Committee|Decision|Project|Program|Case|Meeting|Filing|Agreement|Amendment|Election|Place|Issue|Record)
ON EACH [n.search_label, n.search_terms];

// Per-type search_rank property indexes keep per-type filtering cheap.
CREATE INDEX person_search_rank IF NOT EXISTS FOR (n:Person) ON (n.search_rank);
CREATE INDEX organization_search_rank IF NOT EXISTS FOR (n:Organization) ON (n.search_rank);
CREATE INDEX committee_search_rank IF NOT EXISTS FOR (n:Committee) ON (n.search_rank);
CREATE INDEX decision_search_rank IF NOT EXISTS FOR (n:Decision) ON (n.search_rank);
CREATE INDEX project_search_rank IF NOT EXISTS FOR (n:Project) ON (n.search_rank);
CREATE INDEX program_search_rank IF NOT EXISTS FOR (n:Program) ON (n.search_rank);
CREATE INDEX case_search_rank IF NOT EXISTS FOR (n:Case) ON (n.search_rank);
CREATE INDEX meeting_search_rank IF NOT EXISTS FOR (n:Meeting) ON (n.search_rank);
CREATE INDEX filing_search_rank IF NOT EXISTS FOR (n:Filing) ON (n.search_rank);
CREATE INDEX agreement_search_rank IF NOT EXISTS FOR (n:Agreement) ON (n.search_rank);
CREATE INDEX amendment_search_rank IF NOT EXISTS FOR (n:Amendment) ON (n.search_rank);
CREATE INDEX election_search_rank IF NOT EXISTS FOR (n:Election) ON (n.search_rank);
CREATE INDEX place_search_rank IF NOT EXISTS FOR (n:Place) ON (n.search_rank);
CREATE INDEX issue_search_rank IF NOT EXISTS FOR (n:Issue) ON (n.search_rank);
CREATE INDEX record_search_rank IF NOT EXISTS FOR (n:Record) ON (n.search_rank);
```

- [ ] **Step 2: Create the apply script**

`scripts/apply_search_index.py` — idempotent runner for just the new indexes. Follows the pattern of existing ingestion scripts (same argparse, same env loading).

```python
#!/usr/bin/env python3
"""
Apply the Open Marin search index definitions against AuraDB.
Idempotent: uses `CREATE ... IF NOT EXISTS`. Safe to re-run.

Reads Neo4j credentials from environment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = REPO_ROOT / "registry" / "neo4j-schema.cypher"

# Statements we want to run. We apply the whole file — CREATE IF NOT EXISTS is idempotent.
def read_statements() -> list[str]:
    raw = SCHEMA_FILE.read_text()
    # Strip comment-only lines, then split on semicolons.
    cleaned = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("//"))
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    statements = read_statements()
    print(f"Applying {len(statements)} schema statements to {uri}")

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            for stmt in statements:
                first_line = stmt.splitlines()[0][:80]
                try:
                    session.run(stmt)
                    print(f"  ok  {first_line}")
                except Exception as exc:  # noqa: BLE001 — we want to surface anything
                    print(f"  ERR {first_line}: {exc}", file=sys.stderr)
                    return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Apply against AuraDB**

```bash
cd /Users/tammypais/projects/marin-civic-graph
# Make sure env is loaded (match the project's existing convention for Python scripts).
# If an .envrc / direnv is not in place, export manually from the credentials file.
export NEO4J_URI=neo4j+s://<INSTANCE-ID>.databases.neo4j.io
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='<REAL-PASSWORD>'
export NEO4J_DATABASE=neo4j
python3.14 scripts/apply_search_index.py
```

Expected: prints `ok <stmt>` for each. No errors. The indexes are idempotent.

- [ ] **Step 4: Commit**

```bash
git add registry/neo4j-schema.cypher scripts/apply_search_index.py
git commit -m "$(cat <<'EOF'
add openmarin_search_index + per-type search_rank indexes

Spec §3.3 requires a composite full-text index over (search_label, search_terms) across 15 searchable types (14 entities + Record) and per-type search_rank property indexes. Idempotent — safe to re-run. scripts/apply_search_index.py applies the entire schema file via CREATE IF NOT EXISTS.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Ingestion — compute and write search properties

Per spec §3.3. Add `search_label`, `search_terms`, `search_rank` as node properties on all 15 searchable types.

**Files:**
- Create: `scripts/build_search_properties.py`
- Create: `tests/scripts/test_build_search_properties.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/scripts/test_build_search_properties.py
"""Unit tests for search-property builders. We test pure functions here;
the Cypher side-effect runner is integration-tested manually against AuraDB."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_search_properties import (
    build_search_label,
    build_search_terms,
    compute_search_rank,
)


def test_person_label_uses_name():
    props = {"id": "person-kate-colin", "name": "Kate Colin", "aliases": []}
    assert build_search_label("Person", props) == "Kate Colin"


def test_meeting_label_combines_title_and_date():
    props = {
        "id": "meeting-san-rafael-2024-08-19",
        "title": "San Rafael City Council",
        "meeting_date": "2024-08-19",
    }
    assert (
        build_search_label("Meeting", props)
        == "San Rafael City Council — 2024-08-19"
    )


def test_filing_label_form_700():
    props = {
        "id": "filing-kate-colin-form-700-2024",
        "filing_type": "form_700",
        "signed_at": "2024-03-01",
        "filed_by_name": "Kate Colin",
    }
    assert (
        build_search_label("Filing", props)
        == "Form 700 · Kate Colin · 2024-03-01"
    )


def test_search_terms_lowercases_and_joins():
    props = {"id": "person-kate-colin", "name": "Kate Colin", "aliases": ["Mayor Colin"]}
    terms = build_search_terms("Person", props)
    assert "kate colin" in terms
    assert "mayor colin" in terms
    assert "person-kate-colin" in terms


def test_entity_search_rank_in_0_100():
    props = {"id": "person-kate-colin", "degree": 200}
    rank = compute_search_rank("Person", props)
    assert 0 <= rank <= 100


def test_record_search_rank_capped_at_30():
    props = {"id": "record-staff-report-1", "degree": 100}
    rank = compute_search_rank("Record", props)
    assert rank <= 30
```

- [ ] **Step 2: Run — expect failure**

```bash
cd /Users/tammypais/projects/marin-civic-graph
python3.14 -m pytest tests/scripts/test_build_search_properties.py -v
```

Expected: `ModuleNotFoundError: No module named 'build_search_properties'`.

- [ ] **Step 3: Implement `scripts/build_search_properties.py`**

```python
#!/usr/bin/env python3
"""
Compute and write search_label, search_terms, search_rank on every searchable node.
Runs post-ingestion against AuraDB. Idempotent — MERGE-style updates.

Per spec §3.3.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase, Session

INDEXED_TYPES = [
    "Person", "Organization", "Committee", "Decision", "Project", "Program",
    "Case", "Meeting", "Filing", "Agreement", "Amendment", "Election",
    "Place", "Issue",
]
ALL_SEARCHABLE_TYPES = INDEXED_TYPES + ["Record"]

# Type-weight table — additive prominence per type. Entities only; Record excluded.
TYPE_WEIGHT: dict[str, int] = {
    "Person": 20,
    "Organization": 18,
    "Decision": 16,
    "Project": 14,
    "Program": 14,
    "Case": 14,
    "Meeting": 10,
    "Filing": 10,
    "Committee": 10,
    "Agreement": 8,
    "Amendment": 6,
    "Election": 6,
    "Place": 4,
    "Issue": 4,
    "Record": 0,  # capped below 30 regardless
}


def build_search_label(type_name: str, props: dict) -> str:
    if type_name == "Person":
        return str(props.get("name") or props["id"])
    if type_name == "Organization":
        return str(props.get("name") or props["id"])
    if type_name == "Committee":
        return str(props.get("name") or props["id"])
    if type_name == "Decision":
        date = props.get("decided_at") or ""
        title = props.get("title") or props["id"]
        return f"{title} · {date}" if date else str(title)
    if type_name == "Project" or type_name == "Program":
        return str(props.get("name") or props["id"])
    if type_name == "Case":
        caption = props.get("caption") or props.get("name") or props["id"]
        return str(caption)
    if type_name == "Meeting":
        title = props.get("title") or "Meeting"
        date = props.get("meeting_date") or ""
        return f"{title} — {date}" if date else str(title)
    if type_name == "Filing":
        filing_type = props.get("filing_type", "Filing")
        filer = props.get("filed_by_name") or ""
        date = props.get("signed_at") or ""
        pretty_type = filing_type.replace("_", " ").title().replace("Form ", "Form ")
        parts = [pretty_type]
        if filer:
            parts.append(filer)
        if date:
            parts.append(date)
        return " · ".join(parts)
    if type_name == "Agreement":
        return str(props.get("name") or props["id"])
    if type_name == "Amendment":
        return str(props.get("name") or props["id"])
    if type_name == "Election":
        date = props.get("election_date") or ""
        kind = props.get("election_type") or "Election"
        return f"{kind} — {date}" if date else str(kind)
    if type_name == "Place":
        return str(props.get("name") or props["id"])
    if type_name == "Issue":
        return str(props.get("name") or props["id"])
    if type_name == "Record":
        record_type = props.get("record_type", "Record")
        parent_date = props.get("parent_date") or ""
        parent_title = props.get("parent_title") or ""
        parts = [record_type.replace("_", " ").title()]
        if parent_title:
            parts.append(parent_title)
        if parent_date:
            parts.append(parent_date)
        return " · ".join(parts)
    return str(props["id"])


def build_search_terms(type_name: str, props: dict) -> str:
    tokens: list[str] = [str(props["id"])]
    name = props.get("name")
    if name:
        tokens.append(str(name))
    for alias in props.get("aliases", []) or []:
        tokens.append(str(alias))
    # Type-specific extra tokens.
    if type_name == "Meeting":
        if props.get("title"):
            tokens.append(str(props["title"]))
        if props.get("meeting_date"):
            tokens.append(str(props["meeting_date"]))
        if props.get("institution_name"):
            tokens.append(str(props["institution_name"]))
    if type_name == "Decision":
        if props.get("title"):
            tokens.append(str(props["title"]))
        if props.get("decided_at"):
            tokens.append(str(props["decided_at"]))
    if type_name == "Filing":
        if props.get("filing_type"):
            tokens.append(str(props["filing_type"]))
        if props.get("filed_by_name"):
            tokens.append(str(props["filed_by_name"]))
    if type_name == "Record":
        if props.get("record_type"):
            tokens.append(str(props["record_type"]))
        if props.get("parent_title"):
            tokens.append(str(props["parent_title"]))
        if props.get("source_url"):
            # Add host only — tokenization would split paths.
            from urllib.parse import urlparse
            parsed = urlparse(str(props["source_url"]))
            if parsed.hostname:
                tokens.append(parsed.hostname)
    return " ".join(tok.lower() for tok in tokens if tok)


def compute_search_rank(type_name: str, props: dict) -> int:
    # Entities: 50 base + up to 30 from degree (log-scaled) + type_weight.
    # Records: capped at 30.
    degree = int(props.get("degree", 0) or 0)
    import math
    degree_component = min(30, int(25 * math.log1p(degree) / math.log(1000))) if degree > 0 else 0
    base = 50 + degree_component + TYPE_WEIGHT.get(type_name, 0)
    if type_name == "Record":
        return max(0, min(30, degree_component + 10))
    return max(0, min(100, base))


# --------- Cypher runner ----------

def update_type(session: Session, type_name: str) -> int:
    query = f"""
    MATCH (n:{type_name})
    OPTIONAL MATCH (n)-[r]-()
    WITH n, count(r) AS degree
    RETURN n, degree
    """
    records = session.run(query)
    updated = 0
    batch: list[dict] = []
    for record in records:
        node = record["n"]
        props = dict(node.items())
        props["degree"] = record["degree"]
        batch.append({
            "id": props["id"],
            "search_label": build_search_label(type_name, props),
            "search_terms": build_search_terms(type_name, props),
            "search_rank": compute_search_rank(type_name, props),
        })
        if len(batch) >= 500:
            _write_batch(session, type_name, batch)
            updated += len(batch)
            batch = []
    if batch:
        _write_batch(session, type_name, batch)
        updated += len(batch)
    return updated


def _write_batch(session: Session, type_name: str, rows: list[dict]) -> None:
    session.run(
        f"""
        UNWIND $rows AS row
        MATCH (n:{type_name} {{id: row.id}})
        SET n.search_label = row.search_label,
            n.search_terms = row.search_terms,
            n.search_rank = row.search_rank
        """,
        rows=rows,
    )


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    total = 0
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            for type_name in ALL_SEARCHABLE_TYPES:
                count = update_type(session, type_name)
                print(f"  {type_name}: {count} nodes updated")
                total += count
    print(f"Total updated: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd /Users/tammypais/projects/marin-civic-graph
python3.14 -m pytest tests/scripts/test_build_search_properties.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run against AuraDB**

```bash
export NEO4J_URI=neo4j+s://<INSTANCE-ID>.databases.neo4j.io
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='<REAL-PASSWORD>'
export NEO4J_DATABASE=neo4j
python3.14 scripts/build_search_properties.py
```

Expected: prints counts per type, total ~112K updated.

- [ ] **Step 6: Spot-check in AuraDB console**

Open https://console-preview.neo4j.io/?dbid=<INSTANCE-ID> and run:

```cypher
MATCH (n:Person {id: "person-kate-colin"})
RETURN n.search_label, n.search_terms, n.search_rank;
```

Expected: label is a human-readable string, terms contains lowercase tokens, rank in `[0, 100]`.

- [ ] **Step 7: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add scripts/build_search_properties.py tests/scripts/test_build_search_properties.py
git commit -m "$(cat <<'EOF'
add search_label / search_terms / search_rank ingestion pass

Spec §3.3 denormalizes per-type display + searchable tokens + integer rank onto every searchable node. Entities use full [0,100] range with type weight + log-scaled degree; Records capped at 30. Run post-ingestion (idempotent); frontend treats search_rank as opaque.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Ingestion — compute Record preferred public URL

Per spec §7.1 — normalize Record display fields so the evidence drawer works without leaking internal paths.

**Files:**
- Create: `scripts/build_record_preferred_urls.py`
- Create: `tests/scripts/test_build_record_preferred_urls.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/scripts/test_build_record_preferred_urls.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_record_preferred_urls import normalize_public_url, build_display_label


def test_https_url_passes_through():
    assert normalize_public_url("https://example.gov/foo.pdf") == "https://example.gov/foo.pdf"


def test_http_url_passes_through():
    assert normalize_public_url("http://example.gov/foo.pdf") == "http://example.gov/foo.pdf"


def test_protocol_relative_promoted_to_https():
    assert normalize_public_url("//example.gov/foo.pdf") == "https://example.gov/foo.pdf"


def test_relative_path_returns_none():
    assert normalize_public_url("/local/file.pdf") is None


def test_empty_returns_none():
    assert normalize_public_url("") is None
    assert normalize_public_url(None) is None


def test_display_label_from_record_type_and_extension():
    assert build_display_label("staff_report", "https://x.gov/doc.pdf") == "Staff report PDF"
    assert build_display_label("minutes", "https://x.gov/mins.html") == "Minutes page"
    assert build_display_label("agenda_packet", "") == "Agenda packet"
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement `scripts/build_record_preferred_urls.py`**

```python
#!/usr/bin/env python3
"""
Compute Record.preferred_public_url, Record.preferred_display_artifact, Record.has_public_source.
Per spec §7.1 evidence drawer contract.
"""
from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase


def normalize_public_url(source_url: str | None) -> str | None:
    if not source_url:
        return None
    s = source_url.strip()
    if not s:
        return None
    if s.startswith(("http://", "https://")):
        return s
    if s.startswith("//"):
        return "https:" + s
    # Anything else (file://, relative path, etc.) is not publicly reachable.
    return None


def build_display_label(record_type: str | None, url: str | None) -> str:
    rt = (record_type or "record").replace("_", " ").strip()
    rt = rt[:1].upper() + rt[1:] if rt else "Record"
    if not url:
        return rt
    lower = url.lower()
    if lower.endswith(".pdf"):
        return f"{rt} PDF"
    if lower.endswith((".html", ".htm")) or (lower.startswith("http") and not lower.rsplit("/", 1)[-1].count(".")):
        return f"{rt} page"
    if lower.endswith(".txt"):
        return f"{rt} text"
    return rt


BATCH_SIZE = 500


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    total = 0
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            cursor = session.run(
                "MATCH (r:Record) RETURN r.id AS id, r.source_url AS source_url, r.record_type AS record_type"
            )
            batch: list[dict] = []
            for record in cursor:
                preferred = normalize_public_url(record["source_url"])
                label = build_display_label(record["record_type"], preferred)
                batch.append({
                    "id": record["id"],
                    "preferred_public_url": preferred,
                    "preferred_display_artifact": label,
                    "has_public_source": preferred is not None,
                })
                if len(batch) >= BATCH_SIZE:
                    session.run(
                        """
                        UNWIND $rows AS row
                        MATCH (r:Record {id: row.id})
                        SET r.preferred_public_url = row.preferred_public_url,
                            r.preferred_display_artifact = row.preferred_display_artifact,
                            r.has_public_source = row.has_public_source
                        """,
                        rows=batch,
                    )
                    total += len(batch)
                    batch = []
            if batch:
                session.run(
                    """
                    UNWIND $rows AS row
                    MATCH (r:Record {id: row.id})
                    SET r.preferred_public_url = row.preferred_public_url,
                        r.preferred_display_artifact = row.preferred_display_artifact,
                        r.has_public_source = row.has_public_source
                    """,
                    rows=batch,
                )
                total += len(batch)
    print(f"Updated {total} Records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python3.14 -m pytest tests/scripts/test_build_record_preferred_urls.py -v
```

- [ ] **Step 5: Run against AuraDB**

```bash
python3.14 scripts/build_record_preferred_urls.py
```

Expected: prints `Updated <N> Records`.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_record_preferred_urls.py tests/scripts/test_build_record_preferred_urls.py
git commit -m "$(cat <<'EOF'
add Record preferred_public_url + display_artifact + has_public_source

Spec §7.1 evidence drawer contract. Normalizes protocol-relative URLs to https://; returns null for internal paths so the Vercel UI never leaks Mac-mini paths. Display artifact derived from record_type + file extension.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Define registry files for signature subgraphs and threads

Per spec §3.5 and §3.6 — curated content, committed to the repo.

**Files:**
- Create: `registry/signature-subgraphs.yaml`
- Create: `registry/currently-tracking.yaml`

- [ ] **Step 1: Create `registry/signature-subgraphs.yaml`**

```yaml
# Open Marin homepage signature subgraphs (spec §3.5, §5.5).
# Each entry defines a curated subgraph rotated on session load.
# The builder (scripts/build_signature_subgraphs.py) emits a JSON bundle per slug.
#
# Fields:
#   slug           URL-safe identifier (becomes /api/subgraphs/{slug}.json).
#   display_name   Human title shown in the caption kicker.
#   focus_node_id  Canonical id of the center (#ffffff) node.
#   headline_stats_template
#                  How to format the caption string. Use {{placeholders}} that
#                  the builder will resolve from the focus's computed stats.
subgraphs:
  - slug: merrydale-interim-shelter
    display_name: 350 Merrydale Interim Shelter
    focus_node_id: project-san-rafael-350-merrydale-interim-shelter
    headline_stats_template: "${{money_total}} · {{decision_count}} decisions · {{counterparty_count}} counterparties · {{record_count}} records"

  - slug: sanctioned-camping
    display_name: Sanctioned Camping Program
    focus_node_id: program-san-rafael-sanctioned-camping
    headline_stats_template: "{{case_count}} cases · {{decision_count}} decisions · {{record_count}} records"

  - slug: boyd-v-san-rafael
    display_name: Boyd v. City of San Rafael
    focus_node_id: case-boyd-v-city-of-san-rafael
    headline_stats_template: "federal · {{proceeding_count}} proceedings · constrains {{constrained_decision_count}} decisions"

  - slug: downtown-library-renovation
    display_name: Downtown Library Renovation
    focus_node_id: project-san-rafael-downtown-library-renovation
    headline_stats_template: "${{money_total}} · {{agreement_count}} agreements · {{record_count}} records"

  - slug: kate-colin
    display_name: Kate Colin — Mayor
    focus_node_id: person-kate-colin
    headline_stats_template: "Mayor · {{seat_service_count}} offices · {{filing_count}} filings · {{decision_count}} votes"

  - slug: resolution-15336
    display_name: Resolution 15336 (Merrydale)
    focus_node_id: decision-2025-11-17-resolution-15336
    headline_stats_template: "2025-11-17 · ${{money_total}} · {{person_count}} votes"

  - slug: grants-pass-v-johnson
    display_name: Grants Pass v. Johnson (SCOTUS)
    focus_node_id: case-city-of-grants-pass-v-johnson
    headline_stats_template: "SCOTUS · {{proceeding_count}} proceedings"

  - slug: form-803-colin-pge-canal
    display_name: Form 803 · Colin / PG&E / Canal Alliance
    focus_node_id: filing-form-803-kate-colin-2025-08-08
    headline_stats_template: "Form 803 · ${{money_total}} · PG&E → Canal Alliance"
```

- [ ] **Step 2: Create `registry/currently-tracking.yaml`**

```yaml
# Open Marin homepage "currently tracking" thread cards (spec §3.6).
# 4–5 entries, hand-curated.

threads:
  - title: 350 Merrydale Interim Shelter
    meta: project · San Rafael
    stat: $15.3M · 6 decisions
    href: /project/san-rafael-350-merrydale-interim-shelter

  - title: Sanctioned Camping Program
    meta: program · constrained by Boyd
    stat: 3 cases · 12 decisions
    href: /program/san-rafael-sanctioned-camping

  - title: Downtown Library Renovation
    meta: project · San Rafael
    stat: $15M+ · 3 agreements
    href: /project/san-rafael-downtown-library-renovation

  - title: Boyd v. City of San Rafael
    meta: case · federal
    stat: constrains 1 program
    href: /case/boyd-v-city-of-san-rafael
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add registry/signature-subgraphs.yaml registry/currently-tracking.yaml
git commit -m "$(cat <<'EOF'
add signature-subgraphs.yaml + currently-tracking.yaml registries

Per spec §3.5 and §3.6. Homepage signature-subgraph rotation candidates (8 curated threads) and right-column tracking threads (4 hand-curated cards).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Ingestion — build signature subgraph bundles

Per spec §5.5. Emit `manifest.json` and per-slug bundles under `data/projected/graph-v1/signature-subgraphs/`. These are committed artifacts so Vercel serves them statically.

**Files:**
- Create: `scripts/build_signature_subgraphs.py`
- Create: `tests/scripts/test_build_signature_subgraphs.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/scripts/test_build_signature_subgraphs.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_signature_subgraphs import (
    classify_edge_style,
    build_node_payload,
    expand_template,
)


def test_classify_money_edge():
    assert classify_edge_style("FROM_SOURCE") == "money"
    assert classify_edge_style("TO_TARGET") == "money"
    assert classify_edge_style("DISCLOSED_IN") == "money"
    assert classify_edge_style("UNDER_AGREEMENT") == "money"


def test_classify_legal_edge():
    assert classify_edge_style("CONSTRAINS") == "legal-constrains"


def test_classify_governance_default():
    assert classify_edge_style("AT_MEETING") == "governance"
    assert classify_edge_style("UNKNOWN_EDGE_TYPE") == "governance"


def test_node_payload_shape():
    node = {
        "id": "project-merrydale",
        "labels": ["Project"],
        "search_label": "Merrydale",
    }
    payload = build_node_payload(node, role="focus")
    assert payload["id"] == "project-merrydale"
    assert payload["type"] == "Project"
    assert payload["label"] == "Merrydale"
    assert payload["role"] == "focus"
    assert payload["route"] == "/graph?focus=project-merrydale"


def test_expand_template_replaces_placeholders():
    stats = {"money_total": "15,337,953", "decision_count": 6}
    tpl = "${{money_total}} · {{decision_count}} decisions"
    assert expand_template(tpl, stats) == "$15,337,953 · 6 decisions"


def test_expand_template_leaves_unknowns_blank():
    assert expand_template("{{missing}}", {}) == ""
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement `scripts/build_signature_subgraphs.py`**

```python
#!/usr/bin/env python3
"""
Build signature-subgraph JSON bundles per spec §5.5.

Reads registry/signature-subgraphs.yaml. For each entry, queries AuraDB to collect
the focus node + 2-hop neighborhood along the Phase-2 whitelist, computes headline
stats, and writes:
    data/projected/graph-v1/signature-subgraphs/manifest.json
    data/projected/graph-v1/signature-subgraphs/{slug}.json

Run after each successful ingestion. Nightly cron is a backstop (spec §3.7).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import yaml
from neo4j import GraphDatabase, Session

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "registry" / "signature-subgraphs.yaml"
OUT_DIR = REPO_ROOT / "data" / "projected" / "graph-v1" / "signature-subgraphs"

PHASE2_WHITELIST = [
    "CAST_VOTE", "AT_MEETING", "ABOUT_ITEM", "DECIDED_BY", "PART_OF", "HELD_BY",
    "FOR_SEAT", "RESULT_OF", "AT_INSTITUTION", "FROM_SOURCE", "TO_TARGET",
    "DISCLOSED_IN", "UNDER_AGREEMENT", "AMENDS", "CONTROLLED_BY", "FILED_BY",
    "BY_PERSON", "IN_ELECTION", "FOR_ELECTION", "FOR_PROJECT", "ABOUT_PROJECT",
    "ABOUT_PROGRAM", "PARTY_TO", "CONSTRAINS", "BETWEEN", "HEARD_IN",
]
WHITELIST_PATTERN = "|".join(PHASE2_WHITELIST)

MONEY_EDGES = {"FROM_SOURCE", "TO_TARGET", "DISCLOSED_IN", "UNDER_AGREEMENT"}
LEGAL_EDGES = {"CONSTRAINS"}

MAX_NODES = 50  # per §5.5 target ≤ 60 nodes; we sample conservatively.


def classify_edge_style(rel_type: str) -> str:
    if rel_type in MONEY_EDGES:
        return "money"
    if rel_type in LEGAL_EDGES:
        return "legal-constrains"
    return "governance"


def build_node_payload(node: dict, role: str) -> dict:
    node_id = node["id"]
    label = node.get("search_label") or node.get("name") or node_id
    type_name = node["labels"][0] if node.get("labels") else "Unknown"
    return {
        "id": node_id,
        "type": type_name,
        "label": label,
        "role": role,
        "route": f"/graph?focus={node_id}",
    }


def expand_template(template: str, stats: dict) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        val = stats.get(key)
        return str(val) if val is not None else ""
    return re.sub(r"\{\{(\w+)\}\}", repl, template).strip()


def fetch_subgraph(session: Session, focus_id: str) -> tuple[list[dict], list[dict], dict]:
    """Returns (nodes, edges, headline_stats)."""
    # Focus node + 1-hop + up to 2-hop along whitelist, capped at MAX_NODES.
    # Uses a single Cypher with APOC expandConfig-free pattern.
    query = f"""
    MATCH (f {{id: $focus_id}})
    OPTIONAL MATCH (f)-[r1:{WHITELIST_PATTERN}]-(n1)
    WHERE NOT n1:Place AND NOT n1:Issue
    WITH f, collect(DISTINCT {{node: n1, rel: r1}}) AS hop1_pairs
    UNWIND hop1_pairs AS p
    WITH f, hop1_pairs, p.node AS n1
    OPTIONAL MATCH (n1)-[r2:{WHITELIST_PATTERN}]-(n2)
    WHERE n2 <> f AND NOT n2:Place AND NOT n2:Issue
    WITH f, hop1_pairs, collect(DISTINCT {{src: n1, node: n2, rel: r2}}) AS hop2_pairs
    RETURN f, hop1_pairs, hop2_pairs
    LIMIT 1
    """
    record = session.run(query, focus_id=focus_id).single()
    if not record:
        raise RuntimeError(f"focus node not found: {focus_id}")

    focus = record["f"]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    # Add focus as role=focus.
    nodes[focus["id"]] = {
        "id": focus["id"],
        "labels": list(focus.labels),
        **dict(focus),
    }

    for pair in record["hop1_pairs"] or []:
        n1, r1 = pair["node"], pair["rel"]
        if n1 is None or r1 is None:
            continue
        if n1["id"] not in nodes:
            nodes[n1["id"]] = {"id": n1["id"], "labels": list(n1.labels), **dict(n1)}
        edges.append({
            "source": r1.start_node["id"],
            "target": r1.end_node["id"],
            "type": r1.type,
        })

    for pair in record["hop2_pairs"] or []:
        src, n2, r2 = pair.get("src"), pair.get("node"), pair.get("rel")
        if n2 is None or r2 is None or src is None:
            continue
        if n2["id"] in nodes or len(nodes) >= MAX_NODES:
            if r2.start_node["id"] in nodes and r2.end_node["id"] in nodes:
                edges.append({
                    "source": r2.start_node["id"],
                    "target": r2.end_node["id"],
                    "type": r2.type,
                })
            continue
        nodes[n2["id"]] = {"id": n2["id"], "labels": list(n2.labels), **dict(n2)}
        edges.append({
            "source": r2.start_node["id"],
            "target": r2.end_node["id"],
            "type": r2.type,
        })

    # Build headline stats by counting types in the neighborhood.
    stats = _compute_stats(nodes.values())
    return list(nodes.values()), edges, stats


def _compute_stats(nodes) -> dict:
    counts: dict[str, int] = {}
    money_total = 0
    for node in nodes:
        for lbl in node.get("labels", []):
            counts[lbl] = counts.get(lbl, 0) + 1
        if "MoneyFlow" in node.get("labels", []):
            try:
                money_total += int(float(node.get("amount") or 0))
            except (ValueError, TypeError):
                pass

    return {
        "money_total": f"{money_total:,}" if money_total else "0",
        "decision_count": counts.get("Decision", 0),
        "counterparty_count": counts.get("Organization", 0) + counts.get("Person", 0),
        "record_count": counts.get("Record", 0),
        "case_count": counts.get("Case", 0),
        "agreement_count": counts.get("Agreement", 0),
        "proceeding_count": counts.get("Proceeding", 0),
        "constrained_decision_count": counts.get("Decision", 0),
        "seat_service_count": counts.get("SeatService", 0),
        "filing_count": counts.get("Filing", 0),
        "person_count": counts.get("Person", 0),
    }


def assign_role(node_id: str, focus_id: str, hop1_ids: set[str]) -> str:
    if node_id == focus_id:
        return "focus"
    if node_id in hop1_ids:
        return "primary"
    return "secondary"


def build_bundle(session: Session, entry: dict, built_at: str) -> dict:
    raw_nodes, raw_edges, stats = fetch_subgraph(session, entry["focus_node_id"])
    focus_id = entry["focus_node_id"]
    hop1_ids = {
        e["target"] if e["source"] == focus_id else e["source"]
        for e in raw_edges
        if e["source"] == focus_id or e["target"] == focus_id
    }

    nodes = [build_node_payload(n, assign_role(n["id"], focus_id, hop1_ids)) for n in raw_nodes]
    edges = [
        {
            "source": e["source"],
            "target": e["target"],
            "type": e["type"],
            "style": classify_edge_style(e["type"]),
        }
        for e in raw_edges
    ]

    caption = expand_template(entry["headline_stats_template"], stats)
    kicker = f"SIGNATURE SUBGRAPH · {entry['display_name'].upper()}"

    return {
        "slug": entry["slug"],
        "display_name": entry["display_name"],
        "built_at": built_at,
        "focus_node_id": focus_id,
        "headline_stats": {"caption": caption, "kicker": kicker},
        "nodes": nodes,
        "edges": edges,
    }


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    registry = yaml.safe_load(REGISTRY.read_text())
    entries = registry["subgraphs"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    built_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    manifest_subgraphs = []
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            for entry in entries:
                try:
                    bundle = build_bundle(session, entry, built_at)
                except RuntimeError as exc:
                    print(f"  SKIP {entry['slug']}: {exc}", file=sys.stderr)
                    continue
                (OUT_DIR / f"{entry['slug']}.json").write_text(json.dumps(bundle, indent=2))
                manifest_subgraphs.append({
                    "slug": entry["slug"],
                    "display_name": entry["display_name"],
                    "focus_node_id": entry["focus_node_id"],
                })
                print(f"  {entry['slug']}: {len(bundle['nodes'])} nodes, {len(bundle['edges'])} edges")

    manifest = {"built_at": built_at, "subgraphs": manifest_subgraphs}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(manifest_subgraphs)} bundles + manifest to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Install PyYAML if needed**

```bash
cd /Users/tammypais/projects/marin-civic-graph
python3.14 -c "import yaml" 2>&1 || pip3.14 install PyYAML
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python3.14 -m pytest tests/scripts/test_build_signature_subgraphs.py -v
```

- [ ] **Step 6: Run against AuraDB**

```bash
export NEO4J_URI=neo4j+s://<INSTANCE-ID>.databases.neo4j.io
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='<REAL-PASSWORD>'
export NEO4J_DATABASE=neo4j
python3.14 scripts/build_signature_subgraphs.py
```

Expected: one JSON file per slug plus a `manifest.json` written under `data/projected/graph-v1/signature-subgraphs/`. Some slugs may SKIP if the focus node isn't loaded yet — the Merrydale and Kate Colin slugs should succeed.

- [ ] **Step 7: Spot-check a bundle**

```bash
python3.14 -c "import json; b = json.load(open('data/projected/graph-v1/signature-subgraphs/kate-colin.json')); print(b['headline_stats']['caption']); print(len(b['nodes']), 'nodes,', len(b['edges']), 'edges')"
```

Expected: reasonable caption string, nodes/edges counts > 0.

- [ ] **Step 8: Commit**

```bash
git add scripts/build_signature_subgraphs.py tests/scripts/test_build_signature_subgraphs.py data/projected/graph-v1/signature-subgraphs/
git commit -m "$(cat <<'EOF'
add signature-subgraph bundle builder + initial built artifacts

Spec §5.5. Python script queries AuraDB for each curated subgraph (registry/signature-subgraphs.yaml), builds 2-hop neighborhood along Phase-2 whitelist, classifies edges (money / legal-constrains / governance), computes per-type counts for the caption, and writes one JSON per slug plus a manifest. Committed so Vercel can serve them statically; rerun after each ingestion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: `/api/status` endpoint (TDD)

Spec §3.1 + §3.7. Returns INGEST + SUBGRAPHS timestamps + node/edge counts.

**Files:**
- Create: `app/src/app/api/status/route.ts`
- Create: `app/src/tests/api/status.test.ts`
- Create: `app/src/lib/api-errors.ts`

- [ ] **Step 1: Write the `api-errors` helper**

```typescript
// app/src/lib/api-errors.ts
export function jsonError(message: string, status = 500) {
  return Response.json({ error: message }, { status });
}
```

- [ ] **Step 2: Write the failing test**

```typescript
// app/src/tests/api/status.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/status/route";

describe("GET /api/status", () => {
  it("returns node_count, edge_count, jurisdiction_count, ingest_at", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) => ({
          node_count: { toNumber: () => 112431 } as unknown as number,
          edge_count: { toNumber: () => 141207 } as unknown as number,
          jurisdiction_count: { toNumber: () => 11 } as unknown as number,
          ingest_at: "2026-04-14T09:12:00Z",
        })[k],
      },
    ]);

    const res = await GET();
    const body = await res.json();
    expect(body).toEqual({
      connected: true,
      node_count: 112431,
      edge_count: 141207,
      jurisdiction_count: 11,
      ingest_at: "2026-04-14T09:12:00Z",
      subgraphs_built_at: expect.any(String),
    });
  });

  it("returns connected=false when query errors", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("conn refused"));

    const res = await GET();
    const body = await res.json();
    expect(body.connected).toBe(false);
  });
});
```

- [ ] **Step 3: Run — expect failure**

- [ ] **Step 4: Implement `app/src/app/api/status/route.ts`**

```typescript
// app/src/app/api/status/route.ts
import { runQuery } from "@/lib/neo4j";
import { readFile } from "node:fs/promises";
import path from "node:path";

// SUBGRAPHS timestamp comes from the static manifest copied into public/ by prebuild.
// Reading from public/ means process.cwd() resolution is stable across dev and Vercel.
async function readSubgraphsBuiltAt(): Promise<string | null> {
  try {
    const manifestPath = path.join(process.cwd(), "public", "subgraphs", "manifest.json");
    const content = await readFile(manifestPath, "utf-8");
    return (JSON.parse(content) as { built_at: string }).built_at;
  } catch {
    return null;
  }
}

export async function GET() {
  const subgraphsBuiltAt = (await readSubgraphsBuiltAt()) ?? null;

  try {
    const records = await runQuery(
      `
      MATCH (n)
      WITH count(n) AS node_count
      MATCH ()-[r]->()
      WITH node_count, count(r) AS edge_count
      MATCH (p:Place) WHERE p.place_type IN ['city', 'county']
      WITH node_count, edge_count, count(p) AS jurisdiction_count
      OPTIONAL MATCH (n) WHERE n.captured_at IS NOT NULL
      RETURN node_count, edge_count, jurisdiction_count,
             toString(max(n.captured_at)) AS ingest_at
      `,
    );

    const record = records[0];
    const toNumber = (v: unknown): number =>
      typeof v === "object" && v !== null && "toNumber" in v
        ? (v as { toNumber(): number }).toNumber()
        : Number(v);

    return Response.json({
      connected: true,
      node_count: toNumber(record.get("node_count")),
      edge_count: toNumber(record.get("edge_count")),
      jurisdiction_count: toNumber(record.get("jurisdiction_count")),
      ingest_at: record.get("ingest_at"),
      subgraphs_built_at: subgraphsBuiltAt,
    });
  } catch {
    return Response.json({
      connected: false,
      node_count: 0,
      edge_count: 0,
      jurisdiction_count: 0,
      ingest_at: null,
      subgraphs_built_at: subgraphsBuiltAt,
    });
  }
}
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd app && npm test -- src/tests/api/status.test.ts
```

- [ ] **Step 6: Smoke-test against live AuraDB**

```bash
cd app && npm run dev
```

Open http://localhost:3000/api/status in another terminal:

```bash
curl -s http://localhost:3000/api/status | python3 -m json.tool
```

Expected: JSON with `connected: true`, real node/edge counts, recent `ingest_at`.

Stop dev server.

- [ ] **Step 7: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/app/api/status/route.ts app/src/tests/api/status.test.ts app/src/lib/api-errors.ts
git commit -m "$(cat <<'EOF'
add /api/status endpoint for live status bar

Returns connected flag, node/edge/jurisdiction counts, INGEST timestamp (max captured_at across graph), and SUBGRAPHS build timestamp (from manifest.json). Falls back to connected=false on driver errors so the status bar can show a stale indicator instead of breaking.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: `/api/catalog` endpoint (TDD)

Spec §3.4. Serves per-type counts. Live Cypher, not a baked bundle for Plan 1 (we can migrate to baked later if latency matters).

**Files:**
- Create: `app/src/app/api/catalog/route.ts`
- Create: `app/src/tests/api/catalog.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// app/src/tests/api/catalog.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/catalog/route";

describe("GET /api/catalog", () => {
  it("returns counts keyed by NodeType", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) =>
          ({
            label: "Person",
            count: { toNumber: () => 2184 } as unknown as number,
          })[k],
      },
      {
        get: (k: string) =>
          ({
            label: "Decision",
            count: { toNumber: () => 1453 } as unknown as number,
          })[k],
      },
    ]);

    const res = await GET();
    const body = await res.json();
    expect(body.counts.Person).toBe(2184);
    expect(body.counts.Decision).toBe(1453);
  });
});
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement**

```typescript
// app/src/app/api/catalog/route.ts
import { runQuery } from "@/lib/neo4j";
import { ALL_TYPES, type NodeType } from "@/lib/type-display";

export async function GET() {
  const labels = ALL_TYPES;
  const records = await runQuery(
    `
    UNWIND $labels AS label
    CALL {
      WITH label
      CALL apoc.cypher.run('MATCH (n:' + label + ') RETURN count(n) AS c', {}) YIELD value
      RETURN value.c AS c
    }
    RETURN label, c AS count
    `,
    { labels },
  );

  const toNumber = (v: unknown): number =>
    typeof v === "object" && v !== null && "toNumber" in v
      ? (v as { toNumber(): number }).toNumber()
      : Number(v);

  const counts = Object.fromEntries(
    records.map((r) => [r.get("label") as NodeType, toNumber(r.get("count"))]),
  ) as Record<NodeType, number>;

  return Response.json({
    built_at: new Date().toISOString(),
    counts,
  });
}
```

*(If AuraDB does not have `apoc.cypher.run` available, fall back to one UNION per label. APOC is included on the AuraDB paid tier per the workspace note.)*

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Smoke-test against live DB**

```bash
cd app && npm run dev
curl -s http://localhost:3000/api/catalog | python3 -m json.tool | head -30
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/app/api/catalog/route.ts app/src/tests/api/catalog.test.ts
git commit -m "$(cat <<'EOF'
add /api/catalog endpoint for homepage left column

Returns counts keyed by the 21 NodeType labels. Uses apoc.cypher.run to avoid hand-writing 21 UNIONs; AuraDB Pro has APOC. Live Cypher for now; can migrate to a baked bundle if latency becomes an issue.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Static serving for subgraph bundles + prebuild copy

Serve bundles from `public/subgraphs/` (standard Next.js static serving). No API route needed. A `prebuild` npm script copies the source bundles from `data/projected/graph-v1/signature-subgraphs/` into `app/public/subgraphs/` before every `next build`.

**Files:**
- Modify: `app/package.json` (add `prebuild` script)
- Create: `app/scripts/copy-subgraphs.mjs` (tiny Node script)
- Modify: `app/.gitignore` (ignore `public/subgraphs/`)

- [ ] **Step 1: Write the copy script**

```javascript
// app/scripts/copy-subgraphs.mjs
// Copies data/projected/graph-v1/signature-subgraphs/* into app/public/subgraphs/
// so Next.js serves them as static assets. Runs automatically via prebuild.

import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "..", "..", "data", "projected", "graph-v1", "signature-subgraphs");
const DEST = path.resolve(__dirname, "..", "public", "subgraphs");

async function main() {
  await rm(DEST, { recursive: true, force: true });
  await mkdir(DEST, { recursive: true });
  await cp(SRC, DEST, { recursive: true });
  console.log(`copied subgraph bundles → ${DEST}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

- [ ] **Step 2: Wire scripts in `package.json`**

Update the `scripts` object in `app/package.json`:

```json
"scripts": {
  "predev": "node scripts/copy-subgraphs.mjs",
  "dev": "next dev",
  "prebuild": "node scripts/copy-subgraphs.mjs",
  "build": "next build",
  "start": "next start",
  "lint": "next lint",
  "typecheck": "tsc --noEmit",
  "test": "vitest run",
  "test:watch": "vitest",
  "verify": "npm run typecheck && npm run lint && npm test"
}
```

`predev` and `prebuild` both run the copy so dev and prod stay in sync.

- [ ] **Step 3: Gitignore the copy destination**

Append to `app/.gitignore`:

```
# Generated by scripts/copy-subgraphs.mjs
/public/subgraphs/
```

- [ ] **Step 4: Run the copy manually to verify**

```bash
cd app
node scripts/copy-subgraphs.mjs
ls public/subgraphs/
```

Expected: `manifest.json` plus one JSON file per slug that was built in Task 13.

- [ ] **Step 5: Verify static serving works**

```bash
cd app && npm run dev
```

In another terminal:

```bash
curl -s http://localhost:3000/subgraphs/manifest.json | python3 -m json.tool | head
curl -s http://localhost:3000/subgraphs/kate-colin.json | python3 -m json.tool | head
```

Expected: valid JSON in each case.

- [ ] **Step 6: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/scripts/copy-subgraphs.mjs app/package.json app/package-lock.json app/.gitignore
git commit -m "$(cat <<'EOF'
serve subgraph bundles statically via /subgraphs/

Prebuild copies data/projected/graph-v1/signature-subgraphs/ into app/public/subgraphs/ before next build. Bundles are reachable at /subgraphs/manifest.json and /subgraphs/{slug}.json — standard Next.js static serving, no API route, production-safe. public/subgraphs/ is gitignored; the committed source stays in data/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: `/api/search` endpoint (TDD)

Spec §3.3 — bucketed search, exact-id short-circuit, type-floor via buckets.

**Files:**
- Create: `app/src/app/api/search/route.ts`
- Create: `app/src/tests/api/search.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// app/src/tests/api/search.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/search/route";

function fakeNode(props: Record<string, unknown>) {
  return {
    properties: props,
    labels: props._labels as string[],
  };
}

describe("GET /api/search", () => {
  it("returns bucketed results: exact + entities + records", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) =>
          ({
            results: [
              fakeNode({
                _labels: ["Person"],
                id: "person-kate-colin",
                search_label: "Kate Colin",
                search_rank: 96,
                jurisdiction_name: "San Rafael",
              }),
            ],
          })[k],
      },
    ]);

    const req = new Request("http://localhost/api/search?q=kate+colin&include_records=false");
    const res = await GET(req);
    const body = await res.json();
    expect(body.results).toHaveLength(1);
    expect(body.results[0].id).toBe("person-kate-colin");
    expect(body.results[0].type).toBe("Person");
    expect(body.results[0].route).toBe("/person/kate-colin");
  });

  it("400 when q is empty", async () => {
    const req = new Request("http://localhost/api/search?q=");
    const res = await GET(req);
    expect(res.status).toBe(400);
  });
});
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement**

```typescript
// app/src/app/api/search/route.ts
import { runQuery } from "@/lib/neo4j";
import { jsonError } from "@/lib/api-errors";
import { urlSegmentForType, type NodeType } from "@/lib/type-display";

type Neo4jNode = {
  properties: Record<string, unknown>;
  labels: string[];
};

type SearchResult = {
  id: string;
  type: NodeType;
  search_label: string;
  route: string;
  key_fact: string | null;
  last_activity: string | null;
  jurisdiction: string | null;
  rank: number;
};

function nodeToResult(node: Neo4jNode): SearchResult {
  const props = node.properties;
  const type = (node.labels[0] as NodeType) ?? "Person";
  const id = String(props.id);
  const slug = id.includes("-") ? id.slice(id.indexOf("-") + 1) : id;
  const urlType = urlSegmentForType(type);
  return {
    id,
    type,
    search_label: String(props.search_label ?? id),
    route: `/${urlType}/${slug}`,
    key_fact: (props.search_key_fact as string) ?? null,
    last_activity: (props.search_last_activity as string) ?? null,
    jurisdiction: (props.jurisdiction_name as string) ?? null,
    rank: Number(props.search_rank ?? 0),
  };
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = (searchParams.get("q") ?? "").trim();
  const includeRecords = searchParams.get("include_records") === "true";
  if (!q) return jsonError("q required", 400);

  // Bucketed query per spec §3.3.
  const cypher = `
    // Stage 0: exact id (bypasses include_records)
    OPTIONAL MATCH (exact {id: $q})
    WITH exact
    WITH CASE WHEN exact IS NULL THEN [] ELSE [exact] END AS exact_list

    // Stage 1: entity bucket (never Records)
    CALL {
      WITH $q AS q
      CALL db.index.fulltext.queryNodes('openmarin_search_index', q) YIELD node, score
      WHERE NOT node:Record
      WITH node, score
      ORDER BY score DESC
      LIMIT 200
      WITH node, score, (score * 100 + coalesce(node.search_rank, 0)) AS combined_rank
      ORDER BY combined_rank DESC, node.id ASC
      LIMIT 50
      RETURN collect(node) AS entity_results
    }

    // Stage 2: record bucket
    CALL {
      WITH $q AS q, $include_records AS include_records
      CALL db.index.fulltext.queryNodes('openmarin_search_index', q) YIELD node, score
      WHERE include_records AND node:Record
      WITH node, score
      ORDER BY score DESC
      LIMIT 200
      WITH node, score, (score * 100 + coalesce(node.search_rank, 0)) AS combined_rank
      ORDER BY combined_rank DESC, node.captured_at DESC, node.id ASC
      LIMIT 50
      RETURN collect(node) AS record_results
    }

    WITH exact_list,
         [n IN entity_results WHERE NOT n IN exact_list] AS entities_deduped,
         [n IN record_results WHERE NOT n IN exact_list] AS records_deduped
    WITH (exact_list + entities_deduped + records_deduped)[..50] AS results
    RETURN results
  `;

  try {
    const records = await runQuery(cypher, { q, include_records: includeRecords });
    const nodes = records[0]?.get("results") as Neo4jNode[] | undefined;
    const results = (nodes ?? []).map(nodeToResult);
    return Response.json({
      query: q,
      built_at: new Date().toISOString(),
      results,
    });
  } catch (err) {
    return jsonError(
      `search failed: ${err instanceof Error ? err.message : "unknown"}`,
      500,
    );
  }
}
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Smoke-test against live AuraDB**

```bash
cd app && npm run dev
curl -s 'http://localhost:3000/api/search?q=kate+colin' | python3 -m json.tool | head -40
curl -s 'http://localhost:3000/api/search?q=merrydale&include_records=true' | python3 -m json.tool | head -40
```

Expected: non-empty `results` array, entities first, Records after (when included).

- [ ] **Step 6: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/app/api/search/route.ts app/src/tests/api/search.test.ts
git commit -m "$(cat <<'EOF'
add /api/search endpoint with bucketed ranking

Spec §3.3. Stage 0 exact-id (bypasses filter), Stage 1 entity bucket, Stage 2 record bucket (only if include_records=true). Entities always outrank Records via bucket concatenation — no additive floor that can fail on unbounded Lucene scores. Response shape matches spec: id, type, search_label, route (pre-computed), key_fact, last_activity, jurisdiction, rank.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Status bar component (TDD)

Spec §3.1. Consumes `/api/status`.

**Files:**
- Create: `app/src/components/layout/status-bar.tsx`
- Create: `app/src/tests/components/status-bar.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// app/src/tests/components/status-bar.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBar } from "@/components/layout/status-bar";

describe("StatusBar", () => {
  it("renders connected indicator + counts", () => {
    render(
      <StatusBar
        connected={true}
        nodeCount={112431}
        edgeCount={141207}
        jurisdictionCount={11}
        ingestAt="2026-04-14T09:12:00Z"
        subgraphsBuiltAt="2026-04-18T03:11:44Z"
      />,
    );
    expect(screen.getByText("CONNECTED")).toBeInTheDocument();
    expect(screen.getByText("112,431")).toBeInTheDocument();
    expect(screen.getByText("141,207")).toBeInTheDocument();
  });

  it("shows STALE tag when ingest is older than 14 days", () => {
    const ingestAt = new Date(Date.now() - 20 * 24 * 60 * 60 * 1000).toISOString();
    render(
      <StatusBar
        connected={true}
        nodeCount={1}
        edgeCount={1}
        jurisdictionCount={1}
        ingestAt={ingestAt}
        subgraphsBuiltAt={new Date().toISOString()}
      />,
    );
    expect(screen.getByText(/STALE: INGEST/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement**

```tsx
// app/src/components/layout/status-bar.tsx
const INGEST_STALE_DAYS = 14;
const SUBGRAPHS_STALE_DAYS = 7;

function daysSince(iso: string | null): number {
  if (!iso) return Infinity;
  const ms = Date.now() - new Date(iso).getTime();
  return ms / (24 * 60 * 60 * 1000);
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export type StatusBarProps = {
  connected: boolean;
  nodeCount: number;
  edgeCount: number;
  jurisdictionCount: number;
  ingestAt: string | null;
  subgraphsBuiltAt: string | null;
};

export function StatusBar({
  connected,
  nodeCount,
  edgeCount,
  jurisdictionCount,
  ingestAt,
  subgraphsBuiltAt,
}: StatusBarProps) {
  const ingestStale = daysSince(ingestAt) > INGEST_STALE_DAYS;
  const subgraphsStale = daysSince(subgraphsBuiltAt) > SUBGRAPHS_STALE_DAYS;
  const amber = !connected || ingestStale || subgraphsStale;
  const dotColor = amber ? "bg-[#f2b441]" : "bg-[#a4e8bf]";
  const dotGlow = amber
    ? "shadow-[0_0_6px_rgba(242,180,65,0.7)]"
    : "shadow-[0_0_6px_rgba(164,232,191,0.7)]";

  return (
    <div className="flex items-center gap-5 border-b border-border-hairline bg-panel px-5 py-1.5 font-mono text-[13px] tracking-[0.04em] text-dim">
      <span className="flex items-center">
        <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${dotColor} ${dotGlow}`} />
        <span style={{ fontFamily: "var(--font-vt323)", fontSize: "14px" }}>
          {connected ? "CONNECTED" : "DISCONNECTED"}
        </span>
      </span>
      <span>AURADB</span>
      <span>
        NODES{" "}
        <span style={{ fontFamily: "var(--font-vt323)", fontSize: "14px" }} className="text-body">
          {nodeCount.toLocaleString()}
        </span>
      </span>
      <span>
        EDGES{" "}
        <span style={{ fontFamily: "var(--font-vt323)", fontSize: "14px" }} className="text-body">
          {edgeCount.toLocaleString()}
        </span>
      </span>
      <span>
        JURISDICTIONS{" "}
        <span style={{ fontFamily: "var(--font-vt323)", fontSize: "14px" }} className="text-body">
          {jurisdictionCount}
        </span>
      </span>
      <span className="flex-1" />
      <span className="text-hairline">
        INGEST <span style={{ fontFamily: "var(--font-vt323)", fontSize: "14px" }}>{formatDate(ingestAt)}</span>
      </span>
      <span className="text-hairline">
        SUBGRAPHS <span style={{ fontFamily: "var(--font-vt323)", fontSize: "14px" }}>{formatDate(subgraphsBuiltAt)}</span>
      </span>
      {ingestStale && <span className="text-[#f2b441]">STALE: INGEST</span>}
      {subgraphsStale && <span className="text-[#f2b441]">STALE: SUBGRAPHS</span>}
    </div>
  );
}
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/components/layout/status-bar.tsx app/src/tests/components/status-bar.test.tsx
git commit -m "$(cat <<'EOF'
add StatusBar component

Spec §3.1. Connection dot (green=ok, amber=disconnected or stale), AURADB label, node/edge/jurisdiction VT323 values, right-aligned INGEST + SUBGRAPHS timestamps, inline STALE tags past thresholds (14 days ingest, 7 days subgraphs).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: Nav header component

Spec §3.2.

**Files:**
- Create: `app/src/components/layout/nav-header.tsx`

- [ ] **Step 1: Implement (no tests — purely presentational and link-based)**

```tsx
// app/src/components/layout/nav-header.tsx
import Link from "next/link";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/graph", label: "Graph" },
  { href: "/data", label: "Data" },
  { href: "/chat", label: "Chat" },
  { href: "/about", label: "About" },
];

export type NavHeaderProps = {
  currentPath: string;
};

export function NavHeader({ currentPath }: NavHeaderProps) {
  return (
    <div className="flex items-center gap-[22px] border-b border-border-hairline px-[18px] py-3.5">
      <div
        className="flex items-center text-body"
        style={{ fontFamily: "var(--font-vt323)", fontSize: "22px", letterSpacing: "0.08em" }}
      >
        OPEN MARIN
        <span className="ml-1 inline-block h-[18px] w-2 animate-[blink_1.1s_steps(1)_infinite] bg-[#a4e8bf] shadow-[0_0_4px_rgba(164,232,191,0.7)]" />
      </div>
      <nav className="flex gap-1 font-mono text-xs">
        {NAV_ITEMS.map((item) => {
          const isActive = currentPath === item.href || (item.href !== "/" && currentPath.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                isActive
                  ? "rounded border border-[#262b35] bg-surface px-2.5 py-1 text-body"
                  : "rounded border border-transparent px-2.5 py-1 text-dim hover:text-body"
              }
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="ml-auto flex items-center gap-1.5 font-mono text-[11px] text-hairline">
        <span>open palette</span>
        <kbd className="rounded border border-[#262b35] bg-surface px-1.5 py-0.5 text-[10px] text-dim">⌘</kbd>
        <kbd className="rounded border border-[#262b35] bg-surface px-1.5 py-0.5 text-[10px] text-dim">K</kbd>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add blink animation to globals.css**

Append to `app/src/app/globals.css`:

```css
@keyframes blink {
  50% {
    opacity: 0;
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add app/src/components/layout/nav-header.tsx app/src/app/globals.css
git commit -m "$(cat <<'EOF'
add NavHeader component

Spec §3.2. VT323 OPEN MARIN brand + blinking green cursor block; top nav with active-route highlight (surface bg + border); right-aligned ⌘K chip with kbd keys.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: Prompt search component

Spec §3.3. Non-functional beyond Enter → navigate (palette + results page come in later plans).

**Files:**
- Create: `app/src/components/layout/prompt-search.tsx`

- [ ] **Step 1: Implement**

```tsx
// app/src/components/layout/prompt-search.tsx
"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export function PromptSearch() {
  const ref = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        ref.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const q = (data.get("q") ?? "").toString().trim();
    if (q) router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <form
      onSubmit={onSubmit}
      className="mx-[18px] mt-3.5 flex items-center gap-2.5 rounded-md border border-[#262b35] bg-panel px-3 py-2.5 font-mono text-xs"
    >
      <span
        className="text-[#a4e8bf]"
        style={{ fontFamily: "var(--font-vt323)", fontSize: "16px", letterSpacing: "0.08em" }}
      >
        &gt;
      </span>
      <input
        ref={ref}
        name="q"
        placeholder="search any person, decision, project, money flow, filing, case…"
        className="flex-1 bg-transparent text-body placeholder:text-hairline focus:outline-none"
        aria-label="Search"
      />
    </form>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/components/layout/prompt-search.tsx
git commit -m "$(cat <<'EOF'
add PromptSearch component

Spec §3.3. Focusable by /; Enter navigates to /search?q=. VT323 green chevron, Plex Mono placeholder. Full search results page and command palette come in later plans.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 21: Catalog list component (TDD)

Spec §3.4.

**Files:**
- Create: `app/src/components/home/catalog-list.tsx`
- Create: `app/src/tests/components/catalog-list.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// app/src/tests/components/catalog-list.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CatalogList } from "@/components/home/catalog-list";

describe("CatalogList", () => {
  it("renders grouped types with counts", () => {
    render(
      <CatalogList
        counts={{
          Person: 2184,
          Organization: 1893,
          Meeting: 4500,
          AgendaItem: 0,
          Decision: 1453,
          Seat: 0,
          SeatService: 0,
          Election: 0,
          Candidacy: 0,
          Committee: 135,
          Filing: 1085,
          MoneyFlow: 11248,
          Program: 0,
          Project: 49133,
          Agreement: 0,
          Amendment: 0,
          Case: 477,
          Proceeding: 0,
          Place: 0,
          Issue: 0,
          Record: 38412,
        }}
      />,
    );
    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.getByText("2,184")).toBeInTheDocument();
    expect(screen.getByText("Money flows")).toBeInTheDocument();
    expect(screen.getByText("11,248")).toBeInTheDocument();
    // Records in its own section
    expect(screen.getByText("Source records")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement**

```tsx
// app/src/components/home/catalog-list.tsx
import Link from "next/link";
import { urlSegmentForType, displayNameForType, type NodeType } from "@/lib/type-display";

// Grouping per spec §3.4 — display only; each row still maps to /browse/{type}.
const GROUPS: { heading: string; types: NodeType[] }[] = [
  { heading: "People & organizations", types: ["Person", "Organization"] },
  { heading: "Governance", types: ["Meeting", "AgendaItem", "Decision", "Seat", "SeatService"] },
  { heading: "Elections & campaigns", types: ["Election", "Candidacy", "Committee", "Filing", "MoneyFlow"] },
  { heading: "Programs, projects, agreements", types: ["Program", "Project", "Agreement", "Amendment"] },
  { heading: "Legal", types: ["Case", "Proceeding"] },
  { heading: "Context", types: ["Place", "Issue"] },
];

export type CatalogListProps = {
  counts: Record<NodeType, number>;
};

export function CatalogList({ counts }: CatalogListProps) {
  return (
    <div className="p-[18px]">
      <h2 className="mb-3 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-dim">
        Catalog
      </h2>
      <div className="font-mono text-xs">
        {GROUPS.map((group) => (
          <div key={group.heading} className="mb-3">
            <div className="mb-1 font-medium text-[10px] uppercase tracking-[0.14em] text-hairline">
              {group.heading}
            </div>
            {group.types.map((type) => (
              <Link
                key={type}
                href={`/browse/${urlSegmentForType(type)}`}
                className="flex justify-between rounded-sm px-1.5 py-1 text-body hover:bg-surface"
              >
                <span>{displayNameForType(type)}</span>
                <span className="text-hairline">{(counts[type] ?? 0).toLocaleString()}</span>
              </Link>
            ))}
          </div>
        ))}
        <div className="mt-4 border-t border-border-hairline pt-3">
          <div className="mb-1 font-medium text-[10px] uppercase tracking-[0.14em] text-hairline">
            Records
          </div>
          <Link
            href="/browse/record"
            className="flex justify-between rounded-sm px-1.5 py-1 text-body hover:bg-surface"
          >
            <span>{displayNameForType("Record")}</span>
            <span className="text-hairline">{(counts.Record ?? 0).toLocaleString()}</span>
          </Link>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/components/home/catalog-list.tsx app/src/tests/components/catalog-list.test.tsx
git commit -m "$(cat <<'EOF'
add CatalogList component

Spec §3.4. 6 thematic groups + separate Records section. Every row links to /browse/{type} (paginated list view built in Plan 2). Plex Mono 12px rows with right-aligned dim counts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 22: Obsidian Glow Cytoscape style tokens

Single source of truth for graph rendering.

**Files:**
- Create: `app/src/components/graph/obsidian-style.ts`

- [ ] **Step 1: Implement**

```typescript
// app/src/components/graph/obsidian-style.ts
import type { StylesheetStyle } from "cytoscape";
import { palette } from "@/lib/palette";

// Per spec §5.1 + §5.2 + §2.2 shape encoding.
// Shape applies only to generic bucket at radius >= 5.

export const obsidianStylesheet: StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      "background-color": palette.node.generic,
      width: "data(size)",
      height: "data(size)",
      "border-width": 0,
      label: "data(visibleLabel)",
      "font-family": "IBM Plex Mono, ui-monospace, monospace",
      "font-size": "9px",
      color: "#b0b7c3",
      "text-valign": "bottom",
      "text-margin-y": 4,
      "shadow-blur": "data(glowBlur)",
      "shadow-color": "data(glowColor)",
      "shadow-opacity": 1,
    },
  },
  {
    selector: "node[role = 'focus']",
    style: { "background-color": palette.node.focus },
  },
  {
    selector: "node[colorClass = 'decision']",
    style: { "background-color": palette.node.decision },
  },
  {
    selector: "node[colorClass = 'money']",
    style: { "background-color": palette.node.money },
  },
  {
    selector: "node[colorClass = 'person']",
    style: { "background-color": palette.node.person },
  },
  {
    selector: "node[colorClass = 'legal']",
    style: { "background-color": palette.node.legal },
  },
  {
    selector: "node[colorClass = 'organization']",
    style: { "background-color": palette.node.organization },
  },
  {
    selector: "node[colorClass = 'projectProgram']",
    style: { "background-color": palette.node.projectProgram },
  },
  { selector: "node[shape = 'square']", style: { shape: "rectangle" } },
  { selector: "node[shape = 'ring']", style: { "background-opacity": 0, "border-width": 1.5, "border-color": palette.node.generic } },

  // Edges
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      "line-color": palette.edge.governance,
      width: 0.9,
      "target-arrow-shape": "none",
    },
  },
  {
    selector: "edge[style = 'money']",
    style: {
      "line-color": palette.edge.money,
      width: 1.2,
      "shadow-blur": 4,
      "shadow-color": palette.edge.money,
      "shadow-opacity": 0.6,
    },
  },
  {
    selector: "edge[style = 'legal-constrains']",
    style: {
      "line-color": palette.edge.legalConstrains,
      width: 1.1,
      "line-style": "dashed",
      "line-dash-pattern": [3, 3],
      "shadow-blur": 3,
      "shadow-color": palette.edge.legalConstrains,
      "shadow-opacity": 0.6,
    },
  },
];

// Per-type color class resolution (used when building Cytoscape data).
export function colorClassForType(type: string): string | null {
  switch (type) {
    case "Decision":
      return "decision";
    case "MoneyFlow":
      return "money";
    case "Person":
      return "person";
    case "Case":
    case "Proceeding":
      return "legal";
    case "Organization":
      return "organization";
    case "Project":
    case "Program":
      return "projectProgram";
    default:
      return null;
  }
}

// Shape encoding for generic bucket per §2.2.
export function shapeForType(type: string): "circle" | "square" | "ring" {
  if (["Place", "Issue"].includes(type)) return "square";
  if (["Seat", "SeatService", "Candidacy", "Committee"].includes(type)) return "ring";
  return "circle";
}

// Size by role per §5.1.
export function sizeForRole(role: string): number {
  if (role === "focus") return 22;
  if (role === "primary") return 14;
  if (role === "secondary") return 10;
  return 8;
}

// Glow blur by role + colorClass.
export function glowForRole(role: string, colorClass: string | null): { blur: number; color: string } {
  if (role === "focus") return { blur: 8, color: "#ffffff" };
  const color =
    colorClass === "money"
      ? palette.node.money
      : colorClass === "person"
        ? palette.node.person
        : colorClass === "legal"
          ? palette.node.legal
          : colorClass === "decision"
            ? palette.node.decision
            : colorClass === "organization"
              ? palette.node.organization
              : colorClass === "projectProgram"
                ? palette.node.projectProgram
                : palette.node.generic;
  return { blur: 5, color };
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/components/graph/obsidian-style.ts
git commit -m "$(cat <<'EOF'
add Obsidian Glow Cytoscape stylesheet + helpers

Spec §5.1 + §5.2 + §2.2. Node stylesheet (circle / square / ring per shape encoding), edge stylesheet (governance / money / legal-constrains), plus helpers: colorClassForType, shapeForType, sizeForRole, glowForRole.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 23: Cytoscape base component

Shared React wrapper around Cytoscape.

**Files:**
- Create: `app/src/components/graph/cytoscape-base.tsx`

- [ ] **Step 1: Implement**

```tsx
// app/src/components/graph/cytoscape-base.tsx
"use client";

import { useEffect, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions } from "cytoscape";
import fcose from "cytoscape-fcose";
import { obsidianStylesheet } from "./obsidian-style";

cytoscape.use(fcose);

export type CytoscapeBaseProps = {
  elements: ElementDefinition[];
  layout?: LayoutOptions;
  onNodeClick?: (id: string) => void;
  className?: string;
};

export function CytoscapeBase({ elements, layout, onNodeClick, className }: CytoscapeBaseProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: obsidianStylesheet,
      layout: layout ?? { name: "fcose", quality: "proof", animate: false } as LayoutOptions,
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;

    if (onNodeClick) {
      cy.on("tap", "node", (event) => {
        const id = event.target.id();
        onNodeClick(id);
      });
    }

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements, layout, onNodeClick]);

  return <div ref={containerRef} className={className ?? "h-full w-full"} />;
}
```

- [ ] **Step 2: Commit**

```bash
git add app/src/components/graph/cytoscape-base.tsx
git commit -m "$(cat <<'EOF'
add CytoscapeBase React wrapper

Mounts a Cytoscape instance, applies the Obsidian Glow stylesheet, runs the provided layout (default fcose). Tears down on unmount. Node-click callback wired through for downstream components.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 24: Signature subgraph component (TDD)

Spec §3.5 + §5.5. Picks a random bundle from the manifest, renders it with Cytoscape, handles click-to-navigate.

**Files:**
- Create: `app/src/components/home/signature-subgraph.tsx`
- Create: `app/src/tests/components/signature-subgraph.test.tsx`
- Create: `app/src/lib/types.ts`

- [ ] **Step 1: Write the types file**

```typescript
// app/src/lib/types.ts
import type { NodeType } from "./type-display";

export type SubgraphNode = {
  id: string;
  type: NodeType;
  label: string;
  role: "focus" | "primary" | "secondary";
  route: string;
};

export type SubgraphEdge = {
  source: string;
  target: string;
  type: string;
  style: "governance" | "money" | "legal-constrains";
};

export type SubgraphBundle = {
  slug: string;
  display_name: string;
  built_at: string;
  focus_node_id: string;
  headline_stats: { caption: string; kicker: string };
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
};

export type SubgraphManifest = {
  built_at: string;
  subgraphs: Array<{ slug: string; display_name: string; focus_node_id: string }>;
};
```

- [ ] **Step 2: Write the failing test**

```typescript
// app/src/tests/components/signature-subgraph.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SignatureSubgraph } from "@/components/home/signature-subgraph";

// Mock cytoscape-base to avoid DOM rendering the actual graph in tests.
vi.mock("@/components/graph/cytoscape-base", () => ({
  CytoscapeBase: (props: { onNodeClick?: (id: string) => void }) => {
    // Expose a deterministic test hook.
    (globalThis as unknown as { __onNodeClick?: typeof props.onNodeClick }).__onNodeClick =
      props.onNodeClick;
    return <div data-testid="cy-stub" />;
  },
}));

const manifest = {
  built_at: "2026-04-18T00:00:00Z",
  subgraphs: [
    { slug: "merrydale", display_name: "Merrydale", focus_node_id: "project-merrydale" },
  ],
};
const bundle = {
  slug: "merrydale",
  display_name: "Merrydale",
  built_at: "2026-04-18T00:00:00Z",
  focus_node_id: "project-merrydale",
  headline_stats: { caption: "$15.3M · 6 decisions", kicker: "SIGNATURE SUBGRAPH · MERRYDALE" },
  nodes: [
    { id: "project-merrydale", type: "Project", label: "Merrydale", role: "focus", route: "/graph?focus=project-merrydale" },
  ],
  edges: [],
};

beforeEach(() => {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const s = String(url);
    const body = s.includes("manifest.json") ? manifest : bundle;
    return new Response(JSON.stringify(body), { status: 200 });
  }) as unknown as typeof fetch;
});

describe("SignatureSubgraph", () => {
  it("renders caption + kicker after loading", async () => {
    render(<SignatureSubgraph />);
    await waitFor(() => expect(screen.getByText("$15.3M · 6 decisions")).toBeInTheDocument());
    expect(screen.getByText(/SIGNATURE SUBGRAPH · MERRYDALE/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run — expect failure**

- [ ] **Step 4: Implement**

```tsx
// app/src/components/home/signature-subgraph.tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { ElementDefinition } from "cytoscape";
import { CytoscapeBase } from "@/components/graph/cytoscape-base";
import { colorClassForType, glowForRole, shapeForType, sizeForRole } from "@/components/graph/obsidian-style";
import type { SubgraphBundle, SubgraphManifest } from "@/lib/types";

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return (await res.json()) as T;
}

function pickSlug(manifest: SubgraphManifest): string | null {
  if (manifest.subgraphs.length === 0) return null;
  const i = Math.floor(Math.random() * manifest.subgraphs.length);
  return manifest.subgraphs[i].slug;
}

function toElements(bundle: SubgraphBundle): ElementDefinition[] {
  const nodes: ElementDefinition[] = bundle.nodes.map((n) => {
    const colorClass = colorClassForType(n.type);
    const shape = shapeForType(n.type);
    const size = sizeForRole(n.role);
    const glow = glowForRole(n.role, colorClass);
    return {
      data: {
        id: n.id,
        visibleLabel: n.role === "focus" || n.role === "primary" ? n.label : "",
        role: n.role,
        colorClass,
        shape: colorClass ? "circle" : shape,
        size: String(size),
        glowBlur: glow.blur,
        glowColor: glow.color,
        route: n.route,
      },
    };
  });
  const edges: ElementDefinition[] = bundle.edges.map((e, i) => ({
    data: {
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      style: e.style,
    },
  }));
  return [...nodes, ...edges];
}

export function SignatureSubgraph() {
  const router = useRouter();
  const [bundle, setBundle] = useState<SubgraphBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const manifest = await fetchJSON<SubgraphManifest>("/subgraphs/manifest.json");
        const slug = pickSlug(manifest);
        if (!slug) throw new Error("no subgraphs available");
        const b = await fetchJSON<SubgraphBundle>(`/subgraphs/${slug}.json`);
        if (!cancelled) setBundle(b);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "load failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-dim">
        {`signature-subgraph unavailable: ${error}`}
      </div>
    );
  }

  if (!bundle) {
    return <div className="flex h-full items-center justify-center text-hairline">loading…</div>;
  }

  const elements = toElements(bundle);

  return (
    <div className="relative h-full w-full">
      <div className="absolute right-5 top-4 z-10 font-mono text-[10px] uppercase tracking-[0.12em] text-hairline">
        {bundle.headline_stats.kicker}
      </div>
      <CytoscapeBase
        elements={elements}
        onNodeClick={(id) => {
          const node = bundle.nodes.find((n) => n.id === id);
          if (node) router.push(node.route);
        }}
        className="h-full w-full"
      />
      <div
        className="absolute bottom-4 left-5 z-10 text-body"
        style={{ fontFamily: "var(--font-vt323)", fontSize: "16px", letterSpacing: "0.04em" }}
      >
        {bundle.headline_stats.caption}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests — expect pass**

- [ ] **Step 6: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/components/home/signature-subgraph.tsx app/src/tests/components/signature-subgraph.test.tsx app/src/lib/types.ts
git commit -m "$(cat <<'EOF'
add SignatureSubgraph component

Spec §3.5 + §5.5. Fetches manifest, picks one slug at random on session load, fetches its bundle, transforms to Cytoscape elements with Obsidian Glow data attributes, renders with CytoscapeBase. VT323 caption + kicker overlayed. Click-to-navigate per bundle route (deep-links to /graph?focus={id}).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 25: Tracking threads component

Spec §3.6. Reads the hand-curated YAML at build time (server component reads file).

**Files:**
- Create: `app/src/components/home/tracking-threads.tsx`
- Install: `yaml` package

- [ ] **Step 1: Install YAML parser**

```bash
cd app && npm install yaml
```

- [ ] **Step 2: Implement**

```tsx
// app/src/components/home/tracking-threads.tsx
// Server component — reads registry file at build/request time.

import { readFile } from "node:fs/promises";
import path from "node:path";
import Link from "next/link";
import YAML from "yaml";

type Thread = { title: string; meta: string; stat: string; href: string };

async function loadThreads(): Promise<Thread[]> {
  const file = path.resolve(process.cwd(), "..", "registry", "currently-tracking.yaml");
  try {
    const content = await readFile(file, "utf-8");
    const parsed = YAML.parse(content) as { threads: Thread[] };
    return parsed.threads ?? [];
  } catch {
    return [];
  }
}

export async function TrackingThreads() {
  const threads = await loadThreads();
  if (threads.length === 0) {
    return <div className="p-[18px] text-dim">no threads configured</div>;
  }
  return (
    <div className="p-[18px]">
      <h2 className="mb-3 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-dim">
        Currently tracking
      </h2>
      {threads.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          className="block border-b border-border-hairline py-3 last:border-b-0 hover:bg-surface"
        >
          <div className="text-[13px] font-medium" style={{ color: "#e6e8ec" }}>
            {t.title}
          </div>
          <div className="mt-0.5 font-mono text-[10.5px] tracking-[0.02em] text-dim">{t.meta}</div>
          <div
            className="mt-1 text-[#f2c77a]"
            style={{ fontFamily: "var(--font-vt323)", fontSize: "15px", letterSpacing: "0.05em", textShadow: "0 0 4px rgba(242, 199, 122, 0.4)" }}
          >
            {t.stat}
          </div>
        </Link>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/components/home/tracking-threads.tsx app/package.json app/package-lock.json
git commit -m "$(cat <<'EOF'
add TrackingThreads server component

Spec §3.6. Server-renders the hand-curated registry/currently-tracking.yaml. Title (Plex Sans 500 13px white), meta (Plex Mono dim), stat (VT323 amber with subtle glow). Cards link to entity pages.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 26: Wire up the homepage

**Files:**
- Modify: `app/src/app/page.tsx`
- Modify: `app/src/app/layout.tsx` (no changes but verify)

- [ ] **Step 1: Replace `page.tsx` with the hybrid-B layout**

```tsx
// app/src/app/page.tsx
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { PromptSearch } from "@/components/layout/prompt-search";
import { CatalogList } from "@/components/home/catalog-list";
import { SignatureSubgraph } from "@/components/home/signature-subgraph";
import { TrackingThreads } from "@/components/home/tracking-threads";
import type { NodeType } from "@/lib/type-display";
import { ALL_TYPES } from "@/lib/type-display";

type StatusResponse = {
  connected: boolean;
  node_count: number;
  edge_count: number;
  jurisdiction_count: number;
  ingest_at: string | null;
  subgraphs_built_at: string | null;
};

type CatalogResponse = {
  built_at: string;
  counts: Partial<Record<NodeType, number>>;
};

function blankCounts(): Record<NodeType, number> {
  return Object.fromEntries(ALL_TYPES.map((t) => [t, 0])) as Record<NodeType, number>;
}

async function fetchStatus(): Promise<StatusResponse> {
  try {
    const res = await fetch(`${process.env.APP_URL ?? "http://localhost:3000"}/api/status`, {
      cache: "no-store",
    });
    return (await res.json()) as StatusResponse;
  } catch {
    return {
      connected: false,
      node_count: 0,
      edge_count: 0,
      jurisdiction_count: 0,
      ingest_at: null,
      subgraphs_built_at: null,
    };
  }
}

async function fetchCatalog(): Promise<CatalogResponse> {
  try {
    const res = await fetch(`${process.env.APP_URL ?? "http://localhost:3000"}/api/catalog`, {
      cache: "no-store",
    });
    return (await res.json()) as CatalogResponse;
  } catch {
    return { built_at: new Date().toISOString(), counts: {} };
  }
}

export default async function Home() {
  const [status, catalog] = await Promise.all([fetchStatus(), fetchCatalog()]);
  const counts = { ...blankCounts(), ...catalog.counts };

  return (
    <div className="min-h-screen bg-bg">
      <StatusBar
        connected={status.connected}
        nodeCount={status.node_count}
        edgeCount={status.edge_count}
        jurisdictionCount={status.jurisdiction_count}
        ingestAt={status.ingest_at}
        subgraphsBuiltAt={status.subgraphs_built_at}
      />
      <NavHeader currentPath="/" />
      <PromptSearch />
      <div className="mx-[18px] mt-4 grid grid-cols-[25%_50%_25%] border border-border-primary bg-bg">
        <div className="border-r border-border-hairline">
          <CatalogList counts={counts} />
        </div>
        <div className="min-h-[420px] bg-[radial-gradient(ellipse_at_center,#121821_0%,#05070a_90%)]">
          <SignatureSubgraph />
        </div>
        <div className="border-l border-border-hairline">
          <TrackingThreads />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify dev server renders homepage with live data**

```bash
cd app && npm run dev
```

Open http://localhost:3000. Expected:
- Status bar: green dot, real counts, real INGEST/SUBGRAPHS dates.
- Nav: OPEN MARIN cursor, Home highlighted.
- Prompt row: `>` chevron, placeholder.
- Left column: catalog with live counts per type.
- Center: a randomly-rotated signature subgraph, caption visible.
- Right: 4 tracking-thread cards.

If any of these fail, diagnose before continuing. Common issues:
- `@/` alias not resolved: check `tsconfig.json` has `"paths": { "@/*": ["./src/*"] }`.
- Fonts not loading: network tab shows `fonts.googleapis.com` requests; if blocked, fall back to system fonts for now.
- AuraDB errors: check `.env.local` values.

Stop dev server.

- [ ] **Step 3: Build to verify prod compiles**

```bash
cd app && npm run build
```

Expected: no TypeScript errors, no ESLint blockers, successful Next.js build.

- [ ] **Step 4: Commit**

```bash
cd /Users/tammypais/projects/marin-civic-graph
git add app/src/app/page.tsx
git commit -m "$(cat <<'EOF'
wire up Open Marin homepage

Spec §3. Hybrid-B three-column hero (25 / 50 / 25) under the status bar, nav header, and prompt-styled search. Live catalog counts + live signature subgraph with random rotation + server-rendered tracking threads. First production build passes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 27: Smoke-test everything end to end

No code changes — verification that Plan 1 is complete.

- [ ] **Step 1: Clean build + run**

```bash
cd app
rm -rf .next
npm run verify
npm run build
npm run start &
SERVER_PID=$!
sleep 3
```

- [ ] **Step 2: Hit each endpoint**

```bash
curl -s http://localhost:3000/api/status | python3 -m json.tool
curl -s http://localhost:3000/api/catalog | python3 -m json.tool | head -40
curl -s http://localhost:3000/subgraphs/manifest.json | python3 -m json.tool | head
curl -s 'http://localhost:3000/api/search?q=kate+colin' | python3 -m json.tool | head -40
curl -s 'http://localhost:3000/api/search?q=merrydale&include_records=true' | python3 -m json.tool | head -40
```

Expected: each returns valid JSON with expected shape and live data.

- [ ] **Step 3: Open the homepage in a real browser**

```bash
open http://localhost:3000
```

Expected: terminal-mainframe aesthetic, all three columns populated, signature subgraph visible and rotating on reload. Click a node on the graph — should navigate to `/graph?focus=…` which 404s for now (Plan 3 adds the explorer route).

- [ ] **Step 4: Stop the server**

```bash
kill $SERVER_PID
```

- [ ] **Step 5: Commit (if any tweaks needed — otherwise skip)**

Plan 1 is complete when everything above works. Proceed to the follow-up Codex review on the code.

---

## Plan 1 completion checklist

- [ ] All 27 tasks have green tests and commits.
- [ ] `npm run verify` is green.
- [ ] Homepage renders live catalog, live signature subgraph, real timestamps in status bar.
- [ ] `/api/search?q=kate+colin` returns Kate Colin first.
- [ ] Production build (`npm run build`) succeeds.
- [ ] `data/projected/graph-v1/signature-subgraphs/` is committed with at least 4 working bundles.
- [ ] New ingestion scripts applied against AuraDB and spot-checked in the console.

Next plans:
- **Plan 2** — Entity pages: slug routing, Tier 1 + Tier 2 page composition, radial hero with Query 1 + Query 2, timeline ribbon, evidence drawer, facts panel, connections.
- **Plan 3** — Explorer (`/graph`) with fcose + expand contract + pathfinding + time slider; data explorer (`/data`); `/search?q=` results page; `/browse/{type}` list pages.
- **Plan 4** — Command palette (⌘K) + keyboard shortcuts + `?` overlay; invite-only auth; Vercel deploy; `/about`.
