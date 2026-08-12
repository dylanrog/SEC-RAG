"use client";

import type { TabState } from "@/lib/tabs";

export function FilingTabs({
  tabs,
  labels,
  onActivate,
  onClose,
}: {
  tabs: TabState;
  labels: Record<string, string>;
  onActivate: (accession: string) => void;
  onClose: (accession: string) => void;
}) {
  if (tabs.open.length === 0) return null;

  return (
    <div className="flex border-b border-slate-800 bg-slate-900 font-mono text-[11px]">
      {tabs.open.map((accession) => {
        const active = accession === tabs.active;
        return (
          <div
            key={accession}
            className={
              active
                ? "flex items-center gap-2 border-b-2 border-blue-500 bg-slate-950 px-3 py-2 text-slate-100"
                : "flex items-center gap-2 px-3 py-2 text-slate-500 hover:text-slate-300"
            }
          >
            <button type="button" onClick={() => onActivate(accession)}>
              {labels[accession] ?? accession}
            </button>
            <button
              type="button"
              aria-label={`Close ${labels[accession] ?? accession}`}
              onClick={() => onClose(accession)}
              className="text-slate-600 hover:text-slate-300"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
