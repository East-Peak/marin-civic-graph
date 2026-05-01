import Link from "next/link";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/graph", label: "Graph" },
  { href: "/data", label: "Data" },
  { href: "/about", label: "About" },
];

export type NavHeaderProps = {
  currentPath: string;
};

export function NavHeader({ currentPath }: NavHeaderProps) {
  return (
    <div className="flex items-center gap-[22px] border-b border-border-hairline px-[18px] py-3.5">
      <div
        className="flex items-center text-body"
        style={{ fontFamily: "var(--font-vt323)", fontSize: "22px", letterSpacing: "0.08em" }}
      >
        OPEN MARIN
        <span className="ml-1 inline-block h-[18px] w-2 animate-[blink_1.1s_steps(1)_infinite] bg-[#a4e8bf] shadow-[0_0_4px_rgba(164,232,191,0.7)]" />
      </div>
      <nav className="flex gap-1 font-mono text-xs">
        {NAV_ITEMS.map((item) => {
          const isActive = currentPath === item.href || (item.href !== "/" && currentPath.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                isActive
                  ? "rounded border border-[#262b35] bg-surface px-2.5 py-1 text-body"
                  : "rounded border border-transparent px-2.5 py-1 text-dim hover:text-body"
              }
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="ml-auto flex items-center gap-1.5 font-mono text-[11px] text-hairline">
        <span>open palette</span>
        <kbd className="rounded border border-[#262b35] bg-surface px-1.5 py-0.5 text-[10px] text-dim">⌘</kbd>
        <kbd className="rounded border border-[#262b35] bg-surface px-1.5 py-0.5 text-[10px] text-dim">K</kbd>
      </div>
    </div>
  );
}
