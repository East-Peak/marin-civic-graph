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
    // No options → third arg is undefined (so no TransactionConfig is sent).
    expect(mockRun).toHaveBeenCalledWith("RETURN 42 AS x", {}, undefined);
    expect(mockSession.close).toHaveBeenCalled();
  });

  it("runQuery threads a per-transaction timeout into TransactionConfig", async () => {
    const { runQuery } = await import("@/lib/neo4j");
    const mockRun = vi.fn().mockResolvedValue({ records: [] });
    const mockSession = { run: mockRun, close: vi.fn() };
    const { getDriver } = await import("@/lib/neo4j");
    vi.spyOn(getDriver(), "session").mockReturnValue(mockSession as never);

    await runQuery("RETURN 1", {}, { timeoutMs: 500 });
    expect(mockRun).toHaveBeenCalledWith("RETURN 1", {}, { timeout: 500 });
  });
});
