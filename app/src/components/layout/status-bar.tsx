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
