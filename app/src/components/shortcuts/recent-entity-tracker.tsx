"use client";

import { useEffect } from "react";

const RECENT_KEY = "openmarin_recent_entities";
const MAX_RECENTS = 10;

type Recent = {
  id: string;
  type: string;
  label: string;
  viewed_at: number;
};

type Props = {
  entity: { id: string; type: string; search_label?: string | null };
};

export function RecentEntityTracker({ entity }: Props) {
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(RECENT_KEY);
      let existing: Recent[] = [];
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) existing = parsed as Recent[];
        } catch {
          existing = [];
        }
      }
      const entry: Recent = {
        id: entity.id,
        type: entity.type,
        label: entity.search_label ?? entity.id,
        viewed_at: Date.now(),
      };
      const deduped = [entry, ...existing.filter((r) => r && r.id !== entity.id)];
      const trimmed = deduped.slice(0, MAX_RECENTS);
      sessionStorage.setItem(RECENT_KEY, JSON.stringify(trimmed));
    } catch {
      /* sessionStorage unavailable or quota; tracker is best-effort */
    }
  }, [entity.id, entity.type, entity.search_label]);

  return null;
}
