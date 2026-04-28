import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

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
      "no-restricted-imports": ["error", {
        paths: [
          { name: "openai", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
          { name: "@anthropic-ai/sdk", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
          { name: "voyageai", message: "Use scripts/outbound_policy.py for vendor calls (server-side only)." },
        ],
      }],
    },
  },
]);

export default eslintConfig;
