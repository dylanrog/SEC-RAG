from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import psycopg

from . import queries
from .generate import (
    SYSTEM_PROMPT,
    AnswerSplitter,
    Generator,
    build_user_message,
    parse_citations,
)
from .retrieval import retrieve
from .verify import VerifiedCitation, verify_citation


@dataclass(frozen=True)
class AnswerEvent:
    name: str  # token | citation | done | error
    data: dict


def answer_stream(
    conn: psycopg.Connection,
    embedder,
    generator: Generator,
    question: str,
    *,
    ticker: str | None = None,
    form_type: str | None = None,
    k_final: int = 8,
) -> Iterator[AnswerEvent]:
    """The query path (design §6): retrieve -> generate -> verify -> stream."""
    try:
        chunks = retrieve(
            conn,
            embedder,
            question,
            k_final=k_final,
            ticker=ticker,
            form_type=form_type,
        )
        user_message = build_user_message(question, chunks)

        # Design §6.2: one retry if the trailing block does not parse, then
        # render the answer with an "unverified answer" notice rather than
        # failing the request outright. The retry's prose is discarded -- the
        # first attempt's answer has already streamed to the client, and
        # replacing it mid-stream would be worse than keeping it. We are
        # re-rolling only for the citation block.
        splitter = AnswerSplitter()
        citations = None
        for attempt in range(2):
            splitter = AnswerSplitter()
            for delta in generator.stream(SYSTEM_PROMPT, user_message):
                text = splitter.feed(delta)
                if text and attempt == 0:
                    yield AnswerEvent("token", {"text": text})
            tail = splitter.finish()
            if tail and attempt == 0:
                yield AnswerEvent("token", {"text": tail})
            citations = parse_citations(splitter.raw)
            if citations is not None:
                break

        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        verified: list[VerifiedCitation] = []
        for citation in citations or []:
            chunk = by_id.get(citation.chunk_id)
            if chunk is None:
                # The model cited a chunk it was never shown. Unverifiable by
                # construction -- surface it rather than dropping it.
                verified.append(
                    VerifiedCitation(
                        marker=citation.marker,
                        chunk_id=citation.chunk_id,
                        quote=citation.quote,
                        verified=False,
                        accession="",
                        sids=[],
                    )
                )
                continue
            sentences = queries.load_chunk_sentences(
                conn, chunk.filing_id, chunk.sid_start, chunk.sid_end
            )
            verified.append(verify_citation(citation, chunk, sentences))

        for citation in verified:
            yield AnswerEvent(
                "citation",
                {
                    "marker": citation.marker,
                    "verified": citation.verified,
                    "accession": citation.accession,
                    "sids": citation.sids,
                    "quote": citation.quote,
                },
            )

        yield AnswerEvent(
            "done",
            {
                "chunks_retrieved": len(chunks),
                "citations_total": len(verified),
                "citations_verified": sum(c.verified for c in verified),
                "unverified_answer": citations is None,
            },
        )
    except Exception as exc:
        # Design §10: an LLM outage becomes an `error` event, not a 500. By the
        # time generation starts the response headers are already sent, so
        # raising here would truncate the stream with no explanation.
        yield AnswerEvent("error", {"message": f"{type(exc).__name__}: {exc}"})
