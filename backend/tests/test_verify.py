import os
from datetime import date

import psycopg
import pytest

from api import queries
from api.retrieval import RetrievedChunk
from api.verify import (
    Citation,
    find_quote,
    resolve_sids,
    sentence_spans,
    verify_citation,
)
from pipeline.canonicalize import Sentence

SENTENCES = [
    Sentence(10, "item7", "Total net sales were $391.0 billion.", 0, 36),
    Sentence(11, "item7", "That is an increase of two percent.", 37, 71),
    Sentence(12, "item7", "Services set an all-time revenue record.", 72, 111),
]
CHUNK_TEXT = " ".join(s.text for s in SENTENCES)


def chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        accession="0000320193-24-000123",
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        ticker="AAPL",
        section="item7",
        sid_start=10,
        sid_end=12,
        text=CHUNK_TEXT,
        filing_id=7,
        score=0.5,
    )


def test_sentence_spans_reconstruct_chunk_text_coordinates():
    spans = sentence_spans(SENTENCES)
    assert [sid for sid, _, _ in spans] == [10, 11, 12]
    for _, start, end in spans:
        assert CHUNK_TEXT[start:end] in [s.text for s in SENTENCES]


def test_find_quote_matches_verbatim_text():
    assert find_quote(CHUNK_TEXT, "Total net sales were $391.0 billion.") == (0, 36)


def test_find_quote_tolerates_typography_and_whitespace_drift():
    assert find_quote(CHUNK_TEXT, "Total net   sales\nwere $391.0 billion") is not None


def test_find_quote_returns_none_for_absent_text():
    assert find_quote(CHUNK_TEXT, "Revenue declined sharply.") is None


def test_find_quote_returns_none_for_whitespace_only_quote():
    assert find_quote(CHUNK_TEXT, "   \n  ") is None


def test_resolve_sids_returns_every_overlapped_sentence():
    spans = sentence_spans(SENTENCES)
    assert resolve_sids(spans, 30, 45) == [10, 11]


def test_resolve_sids_returns_a_single_sentence_for_an_inner_span():
    spans = sentence_spans(SENTENCES)
    assert resolve_sids(spans, 5, 12) == [10]


def test_verify_citation_marks_a_real_quote_verified_with_sids():
    result = verify_citation(
        Citation(marker=1, chunk_id=1, quote="an increase of two percent"),
        chunk(),
        SENTENCES,
    )
    assert result.verified is True
    assert result.sids == [11]
    assert result.accession == "0000320193-24-000123"


def test_verify_citation_marks_a_fabricated_quote_unverified_with_no_sids():
    result = verify_citation(
        Citation(marker=2, chunk_id=1, quote="net sales fell by half"),
        chunk(),
        SENTENCES,
    )
    assert result.verified is False
    assert result.sids == []
    assert result.marker == 2


def test_verify_citation_spanning_two_sentences_reports_both():
    result = verify_citation(
        Citation(marker=1, chunk_id=1, quote="billion. That is an increase"),
        chunk(),
        SENTENCES,
    )
    assert result.verified is True
    assert result.sids == [10, 11]


@pytest.mark.parametrize("quote", ["", "   "])
def test_verify_citation_rejects_empty_quotes(quote):
    result = verify_citation(Citation(1, 1, quote), chunk(), SENTENCES)
    assert result.verified is False


def test_verified_citation_carries_filing_metadata():
    from datetime import date

    from api.retrieval import RetrievedChunk
    from api.verify import Citation, verify_citation
    from pipeline.canonicalize import Sentence

    chunk = RetrievedChunk(
        chunk_id=1,
        accession="0000320193-24-000123",
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        ticker="AAPL",
        section="item7",
        sid_start=0,
        sid_end=0,
        text="Total net sales were 391,035 million.",
        filing_id=5,
        score=0.5,
    )
    sentences = [Sentence(0, "item7", chunk.text, 0, len(chunk.text))]
    result = verify_citation(
        Citation(marker=1, chunk_id=1, quote="Total net sales"), chunk, sentences
    )
    assert result.verified is True
    assert result.ticker == "AAPL"
    assert result.form_type == "10-K"
    assert result.filing_date == "2024-11-01"


@pytest.mark.db
def test_stored_chunk_text_is_the_space_join_of_its_sentences():
    """If this fails, sentence_spans() is computing the wrong coordinates and
    every citation highlight will be silently offset."""
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT filing_id, sid_start, sid_end, text FROM chunks"
                " ORDER BY id LIMIT 25"
            )
            rows = cur.fetchall()
        if not rows:
            pytest.skip("no chunks in the test database")
        for filing_id, sid_start, sid_end, text in rows:
            sentences = queries.load_chunk_sentences(conn, filing_id, sid_start, sid_end)
            assert " ".join(s.text for s in sentences) == text
