from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass
class RecanonicalizeStats:
    updated: int = 0
    missing: int = 0
    mismatched: list[str] = field(default_factory=list)


def recanonicalize_filings(
    conn,
    *,
    cache_dir: Path,
    ticker: str | None = None,
) -> RecanonicalizeStats:
    """Rebuild viewer_html from cached raw HTML. Writes nothing else.

    Sentence extraction reads block text, which an inline style attribute
    cannot affect, so sids are invariant across this change -- meaning no
    re-chunk and no re-embed. That invariance is *verified per filing* rather
    than assumed: if the freshly computed sentences disagree with the stored
    rows in any field, the filing is left untouched and reported. A silent
    rewrite here would break every stored citation and the golden set's
    pinned sids at once.
    """
    stats = RecanonicalizeStats()
    for filing_id, cik, accession, form_type in store.filings_to_recanonicalize(
        conn, ticker=ticker
    ):
        path = Path(cache_dir) / str(cik) / f"{accession}.html"
        if not path.exists():
            stats.missing += 1
            continue
        canonical = canonicalize(path.read_text(encoding="utf-8"), form_type)
        if canonical.sentences != store.load_sentences(conn, filing_id):
            stats.mismatched.append(accession)
            continue
        store.update_viewer_html(conn, filing_id, canonical.viewer_html)
        stats.updated += 1
    return stats
