import os
from datetime import date

import psycopg
import pytest

from pipeline import db, ingest, store
from pipeline.canonicalize import CanonicalFiling, Sentence
from pipeline.companies import Company
from pipeline.edgar import FilingRef
from tests.fakes import FakeEmbedder

COMPANY = Company(999999002, "TSTB", "Test Co B")


def make_ref(accession):
    return FilingRef(
        cik=999999002,
        accession=accession,
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        period_end=None,
        primary_document="test.htm",
    )


def make_canonical(texts, section="item1"):
    sentences, cursor = [], 0
    for i, text in enumerate(texts):
        sentences.append(Sentence(i, section, text, cursor, cursor + len(text)))
        cursor += len(text) + 1
    spans = " ".join(f'<span data-sid="{s.sid}">{s.text}</span>' for s in sentences)
    return CanonicalFiling("\n".join(texts), sentences, f"<p>{spans}</p>")


def wipe(conn, accession):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM chunks WHERE filing_id IN"
            " (SELECT id FROM filings WHERE accession = %s)",
            (accession,),
        )
        cur.execute(
            "DELETE FROM sentences WHERE filing_id IN"
            " (SELECT id FROM filings WHERE accession = %s)",
            (accession,),
        )
        cur.execute("DELETE FROM filings WHERE accession = %s", (accession,))
    conn.commit()


@pytest.mark.db
def test_embed_filings_chunks_and_stores_vectors():
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        wipe(conn, "TESTB-24-000001")
        canonical = make_canonical(
            ["Revenue grew ten percent this year.", "Margins were stable across segments."]
        )
        filing_id = store.store_filing(conn, COMPANY, make_ref("TESTB-24-000001"), canonical)

        assert filing_id in store.filing_ids_without_chunks(conn, ticker="TSTB")
        filings_done, chunks_stored = ingest.embed_filings(
            conn, FakeEmbedder(), ticker="TSTB"
        )
        assert filings_done == 1
        assert chunks_stored >= 1
        assert store.filing_ids_without_chunks(conn, ticker="TSTB") == []

        # idempotent: second run touches nothing
        assert ingest.embed_filings(conn, FakeEmbedder(), ticker="TSTB") == (0, 0)

        # vector round-trip: the stored embedding matches what the fake produced
        chunk_text_vector = store.to_pgvector(
            FakeEmbedder().embed_texts(
                ["Revenue grew ten percent this year. Margins were stable across segments."]
            )[0]
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding <=> %s::vector FROM chunks WHERE filing_id = %s",
                (chunk_text_vector, filing_id),
            )
            assert cur.fetchone()[0] == pytest.approx(0.0, abs=1e-6)
