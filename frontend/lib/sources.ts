import type { Citation } from "./types";

export type SourceGroup = {
  accession: string;
  ticker: string;
  form_type: string;
  filing_date: string;
  citations: Citation[];
  verifiedCount: number;
  /** False for an unattributable group, or one whose citations all failed. */
  openable: boolean;
};

/**
 * Collapse citations into one group per filing, ordered by the first marker
 * appearing in each. Grouping is the only place the UI states "this answer
 * rests on N filings", which is the claim the feature exists to make.
 */
export function groupSources(citations: Map<number, Citation>): SourceGroup[] {
  const byAccession = new Map<string, SourceGroup>();

  for (const citation of [...citations.values()].sort((a, b) => a.marker - b.marker)) {
    const existing = byAccession.get(citation.accession);
    if (existing === undefined) {
      byAccession.set(citation.accession, {
        accession: citation.accession,
        ticker: citation.ticker,
        form_type: citation.form_type,
        filing_date: citation.filing_date,
        citations: [citation],
        verifiedCount: citation.verified ? 1 : 0,
        openable: citation.accession !== "" && citation.verified,
      });
      continue;
    }
    existing.citations.push(citation);
    if (citation.verified) {
      existing.verifiedCount += 1;
      existing.openable = existing.accession !== "";
    }
  }

  return [...byAccession.values()];
}
