from __future__ import annotations

from dataclasses import dataclass

from . import store
from .canonicalize import canonicalize
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
