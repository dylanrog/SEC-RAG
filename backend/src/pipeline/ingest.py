from __future__ import annotations

from dataclasses import dataclass

from . import store
from .canonicalize import canonicalize
from .chunk import chunk_sentences
from .companies import Company


@dataclass
class IngestStats:
    ingested: int = 0
    skipped: int = 0


def ingest_company(
    company: Company,
    *,
    edgar,
    conn,
    force: bool = False,
    accession: str | None = None,
) -> IngestStats:
    stats = IngestStats()
    for ref in edgar.list_filings(company.cik):
        if accession is not None and ref.accession != accession:
            continue
        if not force and store.filing_exists(conn, ref.accession):
            stats.skipped += 1
            continue
        path = edgar.download_filing(ref, force=force)
        canonical = canonicalize(path.read_text(encoding="utf-8"), ref.form_type)
        store.store_filing(conn, company, ref, canonical, replace=force)
        stats.ingested += 1
    return stats


def embed_filings(
    conn,
    embedder,
    *,
    ticker: str | None = None,
) -> tuple[int, int]:
    """Chunk + embed every filing that has no chunks yet (design §4.3-4.4)."""
    filings_done = 0
    chunks_stored = 0
    for filing_id in store.filing_ids_without_chunks(conn, ticker=ticker):
        sentences = store.load_sentences(conn, filing_id)
        chunks = chunk_sentences(sentences)
        vectors = embedder.embed_texts([c.text for c in chunks])
        chunks_stored += store.store_chunks(conn, filing_id, chunks, vectors)
        filings_done += 1
    return filings_done, chunks_stored
