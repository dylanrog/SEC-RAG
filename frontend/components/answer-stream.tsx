"use client";

import { CitationChip } from "@/components/citation-chip";
import type { AnswerState } from "@/lib/answer";
import { splitOnMarkers } from "@/lib/markers";
import type { Citation } from "@/lib/types";

export function AnswerStream({
  state,
  onSelect,
}: {
  state: AnswerState;
  onSelect: (citation: Citation) => void;
}) {
  if (state.status === "idle") {
    return <p className="text-slate-500">Ask a question about a filing.</p>;
  }
  if (state.status === "done" && state.chunksRetrieved === 0) {
    return <p className="text-slate-500">No matching filings.</p>;
  }

  return (
    <div>
      {state.errorMessage && (
        <p className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">
          {state.errorMessage}
        </p>
      )}
      {state.notice && (
        <p className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-800">
          {state.notice}
        </p>
      )}
      <p className="leading-7 whitespace-pre-wrap">
        {splitOnMarkers(state.prose).map((segment, index) =>
          typeof segment === "string" ? (
            <span key={index}>{segment}</span>
          ) : (
            <CitationChip
              key={index}
              marker={segment.marker}
              citation={state.citations.get(segment.marker)}
              onSelect={onSelect}
            />
          ),
        )}
      </p>
    </div>
  );
}
