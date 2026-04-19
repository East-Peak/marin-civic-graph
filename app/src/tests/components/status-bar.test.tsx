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
