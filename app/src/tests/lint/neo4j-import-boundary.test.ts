// The public app serves the baked SQLite substrate; Aura is gone. No NEW
// public module may import Neo4j. The legacy live-branch modules are an
// explicit, shrinking allowlist in eslint.config.mjs (deleted in T2).
import { describe, it, expect } from "vitest";
import { ESLint } from "eslint";

const eslint = new ESLint({ cwd: process.cwd() });

async function restrictedImportErrors(filePath: string, code: string) {
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.filter((m) => m.ruleId === "no-restricted-imports");
}

describe("neo4j import boundary", () => {
  it.each([
    ['import { runQuery } from "@/lib/neo4j";'],
    ['import neo4j from "neo4j-driver";'],
  ])("rejects %s in a new public module", async (code) => {
    const src = `${code}\nexport {};\n`;
    expect(await restrictedImportErrors("src/lib/server/brand-new-loader.ts", src)).toHaveLength(1);
    expect(await restrictedImportErrors("src/app/api/brand-new/route.ts", src)).toHaveLength(1);
  });

  it("still allows the allowlisted legacy live-branch modules", async () => {
    const code = 'import { runQuery } from "@/lib/neo4j";\nexport const x = runQuery;\n';
    expect(await restrictedImportErrors("src/lib/server/entity-loader.ts", code)).toHaveLength(0);
  });

  it("keeps the vendor-SDK ban in force alongside the neo4j ban", async () => {
    const code = 'import OpenAI from "openai";\nexport const x = OpenAI;\n';
    expect(await restrictedImportErrors("src/lib/server/brand-new-loader.ts", code)).toHaveLength(1);
  });
});
