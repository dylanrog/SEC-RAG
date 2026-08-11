/** One decoded SSE frame from POST /ask. */
export type SSEEvent = { event: string; data: unknown };

/** A citation event, post-verification (design §6.4). */
export type Citation = {
  marker: number;
  verified: boolean;
  /** Empty when the model cited a chunk it was never shown — unattributable. */
  accession: string;
  ticker: string;
  form_type: string;
  filing_date: string;
  sids: number[];
  quote: string;
};

/** GET /filings/{accession} */
export type Filing = {
  accession: string;
  viewer_html: string;
  ticker: string;
  form_type: string;
  filing_date: string;
  period_end: string | null;
};

/** GET /companies */
export type Company = {
  cik: number;
  ticker: string;
  name: string;
  filings: number;
};
