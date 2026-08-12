"use client";

import type { SourceGroup } from "@/lib/sources";
import type { Citation } from "@/lib/types";

export function SourcesPanel({
  groups,
  onSelect,
}: {
  groups: SourceGroup[];
  onSelect: (citation: Citation) => void;
}) {
  if (groups.length === 0) return null;

  const citationCount = groups.reduce((n, g) => n + g.citations.length, 0);

  return (
    <section className="mt-6">
      <h2 className="font-mono text-[10px] tracking-[0.09em] text-slate-500 uppercase">
        Sources · {groups.length} {groups.length === 1 ? "filing" : "filings"} ·{" "}
        {citationCount} {citationCount === 1 ? "citation" : "citations"}
      </h2>

      <ul className="mt-2 space-y-1">
        {groups.map((group) => (
          <li
            key={group.accession || "unattributable"}
            className={
              group.openable
                ? "border-l-2 border-blue-500 bg-slate-900 px-3 py-2"
                : "border-l-2 border-red-500 bg-slate-900 px-3 py-2"
            }
          >
            <div className="flex items-baseline justify-between text-xs">
              {group.accession === "" ? (
                <span className="font-mono font-bold text-slate-300">
                  unattributable
                </span>
              ) : (
                <span className="font-mono font-bold text-slate-200">
                  {group.ticker}{" "}
                  <span className="font-normal text-slate-500">
                    {group.form_type} {group.filing_date}
                  </span>
                </span>
              )}
              <span
                className={group.verifiedCount > 0 ? "text-green-500" : "text-red-400"}
              >
                {group.verifiedCount > 0 ? `${group.verifiedCount} ✓` : "unverified"}
              </span>
            </div>

            <ul className="mt-1.5 space-y-1 border-l border-slate-800 pl-2">
              {group.citations.map((citation) => (
                <li key={citation.marker} className="text-[11px] leading-snug">
                  {citation.verified ? (
                    <button
                      type="button"
                      onClick={() => onSelect(citation)}
                      className="text-left hover:text-slate-100"
                    >
                      <span className="mr-1 rounded bg-blue-900 px-1 font-mono text-blue-200">
                        {citation.marker}
                      </span>
                      <span className="text-slate-400">“{citation.quote}”</span>
                    </button>
                  ) : (
                    <span>
                      <span className="mr-1 rounded bg-red-950 px-1 font-mono text-red-300">
                        {citation.marker}
                      </span>
                      <span className="text-slate-500">
                        quote did not match source text
                      </span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}
