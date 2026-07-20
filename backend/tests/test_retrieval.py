import os
from datetime import date

import psycopg
import pytest

from api.retrieval import retrieve
from pipeline import db, store
from pipeline.canonicalize import CanonicalFiling, Sentence
from pipeline.chunk import Chunk
from pipeline.companies import Company
from pipeline.edgar import FilingRef
from tests.fakes import FakeEmbedder

ALPHA = Company(999999003, "TSTC", "Test Co C")
BETA = Company(999999004, "TSTD", "Test Co D")

# One chunk per filing; distinctive vocabularies so vectors are far apart.
ALPHA_TEXT = "The escrow covenant restricts zebra imports during fiscal 2024."
BETA_TEXT = "Cloud subscription revenue accelerated in the fourth quarter."
LEXICAL_ONLY_TEXT = "A zebra logistics subsidiary was divested for cash proceeds."


def seed_filing(conn, company, accession, text):
    sentence = Sentence(0, "item1", text, 0, len(text))
    canonical = CanonicalFiling(
        text, [sentence], f'<p><span data-sid="0">{text}</span></p>'
    )
    ref = FilingRef(
        cik=company.cik,
        accession=accession,
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        period_end=None,
        primary_document="t.htm",
    )
    filing_id = store.store_filing(conn, company, ref, canonical)
    chunk = Chunk("item1", 0, 0, text, 10)
    store.store_chunks(conn, filing_id, [chunk], FakeEmbedder().embed_texts([text]))
    return filing_id


@pytest.fixture()
def seeded_conn():
    conn = psycopg.connect(os.environ["TEST_DATABASE_URL"])
    db.migrate(conn)
    with conn.cursor() as cur:
        for accession in ("TESTC-24-000001", "TESTD-24-000001", "TESTC-24-000002"):
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
    seed_filing(conn, ALPHA, "TESTC-24-000001", ALPHA_TEXT)
    seed_filing(conn, BETA, "TESTD-24-000001", BETA_TEXT)
    seed_filing(conn, ALPHA, "TESTC-24-000002", LEXICAL_ONLY_TEXT)
    yield conn
    conn.close()


@pytest.mark.db
def test_exact_text_question_ranks_its_chunk_first(seeded_conn):
    results = retrieve(seeded_conn, FakeEmbedder(), ALPHA_TEXT)
    assert results[0].accession == "TESTC-24-000001"
    assert results[0].text == ALPHA_TEXT
    assert results[0].score > 0


@pytest.mark.db
def test_lexical_match_surfaces_vector_far_chunk(seeded_conn):
    # "zebra" appears in the lexical-only chunk; its fake vector shares little
    # with the full ALPHA_TEXT query, so fusion must bring it in via FTS.
    results = retrieve(seeded_conn, FakeEmbedder(), ALPHA_TEXT, k_final=3)
    accessions = {r.accession for r in results}
    assert "TESTC-24-000002" in accessions


@pytest.mark.db
def test_lexical_search_matches_on_partial_term_overlap(seeded_conn):
    from api.retrieval import lexical_search

    # "reporting" appears nowhere in the seeded corpus. A naive AND-tsquery
    # (websearch_to_tsquery's default) requires every stemmed term to be
    # present and would match zero rows here, even though most of the
    # question's terms hit the ALPHA chunk directly. Full natural-language
    # questions must degrade to "most terms matched, ranked by overlap" or
    # the lexical arm silently starves on realistic queries.
    question = "What does the escrow covenant restrict about zebra imports for reporting purposes?"
    results = lexical_search(seeded_conn, question, k=10)
    assert results
    assert results[0][1] == "TESTC-24-000001"


@pytest.mark.db
def test_ticker_filter_excludes_other_companies(seeded_conn):
    results = retrieve(seeded_conn, FakeEmbedder(), "revenue quarter", ticker="TSTD")
    assert results  # BETA's chunk matches
    assert {r.ticker for r in results} == {"TSTD"}


@pytest.mark.db
def test_k_final_caps_results(seeded_conn):
    results = retrieve(seeded_conn, FakeEmbedder(), "zebra revenue escrow", k_final=1)
    assert len(results) == 1
