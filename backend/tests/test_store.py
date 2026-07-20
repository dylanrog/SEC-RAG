import os
from datetime import date

import psycopg
import pytest

from pipeline import db, store
from pipeline.canonicalize import CanonicalFiling, Sentence
from pipeline.companies import Company
from pipeline.edgar import FilingRef

COMPANY = Company(999999001, "TSTA", "Test Co A")
REF = FilingRef(
    cik=999999001,
    accession="TEST-24-000001",
    form_type="10-K",
    filing_date=date(2024, 11, 1),
    period_end=date(2024, 9, 28),
    primary_document="test.htm",
)
CANONICAL = CanonicalFiling(
    canonical_text="First sentence.\nSecond sentence.",
    sentences=[
        Sentence(0, "item1", "First sentence.", 0, 15),
        Sentence(1, "item1", "Second sentence.", 16, 32),
    ],
    viewer_html=(
        '<p><span data-sid="0">First sentence.</span>'
        ' <span data-sid="1">Second sentence.</span></p>'
    ),
)


@pytest.mark.db
def test_store_filing_roundtrip():
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        with conn.cursor() as cur:  # clean slate for reruns
            cur.execute(
                "DELETE FROM sentences WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = %s)",
                (REF.accession,),
            )
            cur.execute("DELETE FROM filings WHERE accession = %s", (REF.accession,))
        conn.commit()

        assert store.filing_exists(conn, REF.accession) is False
        filing_id = store.store_filing(conn, COMPANY, REF, CANONICAL)
        assert store.filing_exists(conn, REF.accession) is True
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sentences WHERE filing_id = %s", (filing_id,))
            assert cur.fetchone()[0] == 2
