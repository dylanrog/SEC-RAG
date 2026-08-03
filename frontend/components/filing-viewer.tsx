"use client";

import { useEffect, useRef, useState } from "react";

import { fetchFiling } from "@/lib/api";
import { applyHighlight } from "@/lib/highlight";
import type { Filing } from "@/lib/types";

export function FilingViewer({
  accession,
  sids,
}: {
  accession: string | null;
  sids: number[];
}) {
  const [filing, setFiling] = useState<Filing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fetch keyed on accession only, so clicking a second citation in the same
  // filing does not re-download or re-inject ~818 KB of HTML.
  //
  // There is deliberately no setFiling(null)/setError(null) reset here: the
  // parent gives this component `key={accession}`, so switching filings
  // remounts it with fresh state. Resetting inside the effect instead would
  // trip react-hooks/set-state-in-effect and cost an extra render pass.
  useEffect(() => {
    if (accession === null) return;
    let cancelled = false;
    fetchFiling(accession)
      .then((next) => {
        if (!cancelled) setFiling(next);
      })
      .catch(() => {
        if (!cancelled) setError("Filing not available.");
      });
    return () => {
      cancelled = true;
    };
  }, [accession]);

  // Highlight keyed on sids. React leaves the injected HTML alone when the
  // __html string is unchanged, so the classes we set imperatively survive.
  useEffect(() => {
    if (filing !== null && containerRef.current !== null) {
      applyHighlight(containerRef.current, sids);
    }
  }, [filing, sids]);

  if (accession === null) {
    return (
      <p className="p-6 text-slate-500">
        Click a citation to open the filing here.
      </p>
    );
  }
  if (error !== null) return <p className="p-6 text-red-700">{error}</p>;
  if (filing === null) return <p className="p-6 text-slate-500">Loading filing…</p>;

  return (
    <div className="p-6">
      <h2 className="mb-4 text-sm font-semibold text-slate-600">
        {filing.ticker} {filing.form_type} · filed {filing.filing_date}
      </h2>
      {/* Safe here and only here: this HTML was sanitized by the
          canonicalizer at ingestion, so the server is the sanitizer. */}
      <div ref={containerRef} dangerouslySetInnerHTML={{ __html: filing.viewer_html }} />
    </div>
  );
}
