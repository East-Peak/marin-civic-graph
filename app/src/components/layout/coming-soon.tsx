import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import Link from "next/link";

export type ComingSoonProps = {
  currentPath: string;
  heading: string;
  body: string;
  planName: string;
};

export function ComingSoon({ currentPath, heading, body, planName }: ComingSoonProps) {
  return (
    <div className="min-h-screen bg-bg">
      <StatusBar connected={true} nodeCount={0} edgeCount={0} jurisdictionCount={0} ingestAt={null} subgraphsBuiltAt={null} />
      <NavHeader currentPath={currentPath} />
      <div className="mx-[18px] mt-24 flex flex-col items-center gap-3 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-hairline">{planName}</div>
        <h1 className="text-body" style={{ fontFamily: "var(--font-vt323)", fontSize: "40px", lineHeight: "1.1" }}>
          {heading}
        </h1>
        <p className="max-w-md font-mono text-sm text-dim">{body}</p>
        <Link href="/" className="mt-6 font-mono text-xs text-dim underline hover:text-body">
          ← back to home
        </Link>
      </div>
    </div>
  );
}
