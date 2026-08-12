import os
from datetime import date
from pathlib import Path

import psycopg
import pytest

from pipeline import db, ingest, store
from pipeline.canonicalize import canonicalize
from pipeline.companies import Company
from pipeline.edgar import FilingRef

FIXTURES = Path(__file__).parent / "fixtures"
COMPANY = Company(999999002, "TSTB", "Test Co B")
REF = FilingRef(
    cik=999999002,
    accession="TEST-24-000002",
    form_type="10-K",
    filing_date=date(2024, 11, 1),
    period_end=date(2024, 9, 28),
    primary_document="styled_filing.html",
)


@pytest.fixture(autouse=True)
def _wipe_after():
    """Every test here shares REF.accession under ticker TSTB with
    test_store_chunks.py's own TSTB fixture. store_filing(replace=True)
    keeps this file's own tests isolated from each other, but nothing
    removes the row once the last test in this file finishes -- and a
    filing left with no chunks is exactly what test_store_chunks.py's
    ticker-scoped filing_ids_without_chunks query counts. Clean up on the
    way out so unscoped `pytest -q` doesn't depend on file collection
    order.
    """
    yield
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM chunks WHERE filing_id IN"
            " (SELECT id FROM filings WHERE accession = %s)",
            (REF.accession,),
        )
        cur.execute(
            "DELETE FROM sentences WHERE filing_id IN"
            " (SELECT id FROM filings WHERE accession = %s)",
            (REF.accession,),
        )
        cur.execute("DELETE FROM filings WHERE accession = %s", (REF.accession,))


def _seed(conn, cache_dir: Path, *, viewer_html: str | None = None) -> int:
    """Store the styled fixture as a filing, optionally with a stale viewer_html."""
    raw = (FIXTURES / "styled_filing.html").read_text(encoding="utf-8")
    cached = cache_dir / str(REF.cik) / f"{REF.accession}.html"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(raw, encoding="utf-8")

    canonical = canonicalize(raw, REF.form_type)
    if viewer_html is not None:
        canonical = type(canonical)(
            canonical_text=canonical.canonical_text,
            sentences=canonical.sentences,
            viewer_html=viewer_html,
        )
    return store.store_filing(conn, COMPANY, REF, canonical, replace=True)


@pytest.mark.db
def test_recanonicalize_updates_viewer_html_only(tmp_path):
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        filing_id = _seed(conn, tmp_path, viewer_html="<p>stale</p>")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sentences WHERE filing_id = %s", (filing_id,))
            sentences_before = cur.fetchone()[0]

        stats = ingest.recanonicalize_filings(conn, cache_dir=tmp_path, ticker="TSTB")
        conn.commit()

        assert stats.updated == 1
        assert stats.mismatched == []
        with conn.cursor() as cur:
            cur.execute("SELECT viewer_html FROM filings WHERE id = %s", (filing_id,))
            viewer_html = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM sentences WHERE filing_id = %s", (filing_id,))
            assert cur.fetchone()[0] == sentences_before

        assert "stale" not in viewer_html
        assert "color:#000000" not in viewer_html
        assert 'data-sid="0"' in viewer_html


@pytest.mark.db
def test_recanonicalize_aborts_a_filing_whose_sentences_moved(tmp_path):
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        filing_id = _seed(conn, tmp_path)
        conn.commit()

        # Corrupt one stored sentence so the freshly computed list disagrees.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentences SET text = 'tampered' WHERE filing_id = %s AND sid = 0",
                (filing_id,),
            )
            cur.execute(
                "UPDATE filings SET viewer_html = '<p>stale</p>' WHERE id = %s", (filing_id,)
            )
        conn.commit()

        stats = ingest.recanonicalize_filings(conn, cache_dir=tmp_path, ticker="TSTB")
        conn.commit()

        assert stats.updated == 0
        assert stats.mismatched == [REF.accession]
        with conn.cursor() as cur:
            cur.execute("SELECT viewer_html FROM filings WHERE id = %s", (filing_id,))
            assert cur.fetchone()[0] == "<p>stale</p>"


@pytest.mark.db
def test_recanonicalize_skips_a_filing_missing_from_the_cache(tmp_path):
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        _seed(conn, tmp_path)
        conn.commit()
        (tmp_path / str(REF.cik) / f"{REF.accession}.html").unlink()

        stats = ingest.recanonicalize_filings(conn, cache_dir=tmp_path, ticker="TSTB")
        conn.commit()

        assert stats.updated == 0
        assert stats.missing == 1
