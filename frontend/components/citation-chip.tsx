"use client";

import type { Citation } from "@/lib/types";

/**
 * Three states, because the backend sends every token before any citation:
 *  - undefined citation -> inert text, the answer is still streaming
 *  - verified           -> clickable
 *  - unverified         -> visible badge, deliberately NOT clickable
 * A failed citation is never dropped silently (design §6.3).
 */
export function CitationChip({
  marker,
  citation,
  onSelect,
}: {
  marker: number;
  citation: Citation | undefined;
  onSelect: (citation: Citation) => void;
}) {
  if (citation === undefined) {
    return <span className="text-slate-400">[{marker}]</span>;
  }
  if (!citation.verified) {
    return (
      <span
        className="mx-0.5 rounded bg-amber-100 px-1 text-xs text-amber-800"
        title={`Unverified: "${citation.quote}"`}
      >
        [{marker}] unverified
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onSelect(citation)}
      className="mx-0.5 rounded bg-blue-100 px-1 text-xs text-blue-800 hover:bg-blue-200"
      title={citation.quote}
    >
      [{marker}]
    </button>
  );
}
