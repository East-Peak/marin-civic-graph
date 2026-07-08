"use client";

import { useState } from "react";
import type { IdentityLink } from "@/lib/server/entity-loader";

type KeyKind = {
  prefix: string;
  label: string;
};

const KEY_KINDS: KeyKind[] = [
  { prefix: "org-bmf-ein-", label: "EIN" },
  { prefix: "org-casos-", label: "CA SOS" },
  { prefix: "org-fppc-", label: "FPPC" },
];

function keyLabel(peerId: string): string {
  const kind = KEY_KINDS.find((item) => peerId.startsWith(item.prefix));
  if (!kind) return peerId;
  const rawKey = peerId.slice(kind.prefix.length);
  const digits = rawKey.match(/\d+/g)?.join("") ?? rawKey;
  return `${kind.label} ${digits}`;
}

export function IdentityChipRow({ links }: { links?: IdentityLink[] }) {
  const [active, setActive] = useState<string | null>(null);
  if (!links || links.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="verified-identity-row">
      <span
        className="font-mono uppercase text-hairline"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
      >
        VERIFIED IDENTITY
      </span>
      {links.map((link) => {
        const chipLabel = keyLabel(link.peer_id);
        const open = active === link.assertion_id;
        return (
          <span key={link.assertion_id} className="relative inline-flex">
            <button
              type="button"
              onClick={() => setActive(open ? null : link.assertion_id)}
              className="border border-border-hairline bg-panel px-2 py-1 font-mono uppercase text-dim hover:border-border-primary hover:text-body"
              style={{ fontSize: "10px", letterSpacing: "0.1em" }}
            >
              {chipLabel}
            </button>
            {open && (
              <div
                className="absolute left-0 top-full z-10 mt-1 min-w-[260px] border border-border-hairline bg-bg px-3 py-2 font-mono text-dim shadow-lg"
                style={{ fontSize: "11px", lineHeight: 1.45 }}
                data-testid="verified-identity-popover"
              >
                <div>{link.basis ?? "no basis captured"}</div>
                <div>{link.decided_at ?? "no decision date"}</div>
                <div className="select-all text-hairline">{link.assertion_id}</div>
              </div>
            )}
          </span>
        );
      })}
    </div>
  );
}
