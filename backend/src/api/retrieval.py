from __future__ import annotations

from dataclasses import dataclass

import psycopg

from pipeline.store import to_pgvector

RRF_K = 60

_BASE = (
    "SELECT ch.id, f.accession, f.form_type, c.ticker, ch.section,"
    " ch.sid_start, ch.sid_end, ch.text"
    " FROM chunks ch"
    " JOIN filings f ON f.id = ch.filing_id"
    " JOIN companies c ON c.cik = f.cik"
)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    accession: str
    form_type: str
    ticker: str
    section: str
    sid_start: int
    sid_end: int
    text: str
    score: float


def _filters(ticker: str | None, form_type: str | None) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if ticker:
        clauses.append("c.ticker = %s")
        params.append(ticker.upper())
    if form_type:
        clauses.append("f.form_type = %s")
        params.append(form_type)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def vector_search(
    conn: psycopg.Connection,
    query_vector: list[float],
    *,
    k: int = 20,
    ticker: str | None = None,
    form_type: str | None = None,
) -> list[tuple]:
    where, params = _filters(ticker, form_type)
    sql = _BASE + where + " ORDER BY ch.embedding <=> %s::vector LIMIT %s"
    with conn.cursor() as cur:
        cur.execute(sql, [*params, to_pgvector(query_vector), k])
        return cur.fetchall()


def lexical_search(
    conn: psycopg.Connection,
    question: str,
    *,
    k: int = 20,
    ticker: str | None = None,
    form_type: str | None = None,
) -> list[tuple]:
    where, params = _filters(ticker, form_type)
    match = "to_tsvector('english', ch.text) @@ websearch_to_tsquery('english', %s)"
    where = where + (" AND " if where else " WHERE ") + match
    sql = (
        _BASE
        + where
        + " ORDER BY ts_rank_cd(to_tsvector('english', ch.text),"
        " websearch_to_tsquery('english', %s)) DESC LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, [*params, question, question, k])
        return cur.fetchall()


def retrieve(
    conn: psycopg.Connection,
    embedder,
    question: str,
    *,
    k_each: int = 20,
    k_final: int = 8,
    ticker: str | None = None,
    form_type: str | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieval per design §6.1: vector + lexical arms fused with RRF."""
    query_vector = embedder.embed_query(question)
    vector_rows = vector_search(
        conn, query_vector, k=k_each, ticker=ticker, form_type=form_type
    )
    lexical_rows = lexical_search(
        conn, question, k=k_each, ticker=ticker, form_type=form_type
    )

    scores: dict[int, float] = {}
    rows_by_id: dict[int, tuple] = {}
    for rows in (vector_rows, lexical_rows):
        for rank, row in enumerate(rows):
            chunk_id = row[0]
            rows_by_id[chunk_id] = row
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k_final]
    return [RetrievedChunk(*rows_by_id[chunk_id], score) for chunk_id, score in ranked]
