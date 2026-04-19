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
