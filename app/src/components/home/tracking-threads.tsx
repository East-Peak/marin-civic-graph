// Server component — reads registry file at build/request time.

import { readFile } from "node:fs/promises";
import path from "node:path";
import Link from "next/link";
import YAML from "yaml";

type Thread = { title: string; meta: string; stat: string; href: string };

async function loadThreads(): Promise<Thread[]> {
  const file = path.join(process.cwd(), "public", "currently-tracking.yaml");
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
