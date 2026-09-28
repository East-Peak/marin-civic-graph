import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const VENDOR_SDK_PATHS = [
  { name: "openai", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
  { name: "@anthropic-ai/sdk", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
  { name: "voyageai", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
];

const NEO4J_BOUNDARY_MESSAGE =
  "Public code reads the SQLite substrate (@/lib/server/substrate), not Neo4j. Aura is gone; " +
  "local Neo4j is operator-only.";
const NEO4J_PATHS = [
  { name: "@/lib/neo4j", message: NEO4J_BOUNDARY_MESSAGE },
  { name: "neo4j-driver", message: NEO4J_BOUNDARY_MESSAGE },
];

// Legacy live-Cypher modules still behind the SERVING_BACKEND=live switch.
// This list only shrinks: tranche T2 deletes these branches and this list.
const LEGACY_NEO4J_IMPORTERS = [
  "src/lib/neo4j.ts",
  "src/app/api/constellation-manifest/route.ts",
  "src/app/api/expand/route.ts",
  "src/lib/server/about-data.ts",
  "src/lib/server/browse-queries.ts",
  "src/lib/server/data-queries-dispatch.ts",
  "src/lib/server/entity-evidence.ts",
  "src/lib/server/entity-loader.ts",
  "src/lib/server/explorer-queries.ts",
  "src/lib/server/homepage-data.ts",
  "src/lib/server/path-finder.ts",
  "src/lib/server/search-backend.ts",
];

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  // Block direct vendor SDK imports in TypeScript/JS code.
  // All OpenAI/Anthropic calls must go through scripts/outbound_policy.py.
  {
    rules: {
      "no-restricted-imports": ["error", { paths: VENDOR_SDK_PATHS }],
    },
  },
  // Public code serves the baked SQLite substrate; Aura was deleted 2026-07-08.
  // No NEW public module may import Neo4j. (A later block's options replace an
  // earlier block's for the same rule, so the vendor paths are repeated here.)
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: [...LEGACY_NEO4J_IMPORTERS, "src/tests/**", "src/app/(operator-workbench)/**"],
    rules: {
      "no-restricted-imports": ["error", { paths: [...VENDOR_SDK_PATHS, ...NEO4J_PATHS] }],
    },
  },
]);

export default eslintConfig;
