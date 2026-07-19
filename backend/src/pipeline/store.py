from __future__ import annotations

import psycopg

from .canonicalize import CanonicalFiling
from .companies import Company
from .edgar import FilingRef


def filing_exists(conn: psycopg.Connection, accession: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM filings WHERE accession = %s", (accession,))
        return cur.fetchone() is not None


def store_filing(
    conn: psycopg.Connection,
    company: Company,
    ref: FilingRef,
    canonical: CanonicalFiling,
    *,
    replace: bool = False,
) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO companies (cik, ticker, name) VALUES (%s, %s, %s)"
                " ON CONFLICT (cik) DO NOTHING",
                (company.cik, company.ticker, company.name),
            )
            if replace:
                cur.execute(
                    "DELETE FROM sentences WHERE filing_id IN"
                    " (SELECT id FROM filings WHERE accession = %s)",
                    (ref.accession,),
                )
                cur.execute("DELETE FROM filings WHERE accession = %s", (ref.accession,))
            cur.execute(
                "INSERT INTO filings (cik, accession, form_type, filing_date, period_end,"
                " viewer_html) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    company.cik,
                    ref.accession,
                    ref.form_type,
                    ref.filing_date,
                    ref.period_end,
                    canonical.viewer_html,
                ),
            )
            filing_id = cur.fetchone()[0]
            with cur.copy(
                "COPY sentences (filing_id, sid, section, text, char_start, char_end)"
                " FROM STDIN"
            ) as copy:
                for s in canonical.sentences:
                    copy.write_row((filing_id, s.sid, s.section, s.text, s.char_start, s.char_end))
    return filing_id
