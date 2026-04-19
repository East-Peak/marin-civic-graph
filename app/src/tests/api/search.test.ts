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
