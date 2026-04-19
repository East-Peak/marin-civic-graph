"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export function PromptSearch() {
  const ref = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        ref.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const q = (data.get("q") ?? "").toString().trim();
    if (q) router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <form
      onSubmit={onSubmit}
      className="mx-[18px] mt-3.5 flex items-center gap-2.5 rounded-md border border-[#262b35] bg-panel px-3 py-2.5 font-mono text-xs"
    >
      <span
        className="text-[#a4e8bf]"
        style={{ fontFamily: "var(--font-vt323)", fontSize: "16px", letterSpacing: "0.08em" }}
      >
        &gt;
      </span>
      <input
        ref={ref}
        name="q"
        placeholder="search any person, decision, project, money flow, filing, case…"
        className="flex-1 bg-transparent text-body placeholder:text-hairline focus:outline-none"
        aria-label="Search"
      />
    </form>
  );
}
