from __future__ import annotations

from dataclasses import dataclass

from pipeline.canonicalize import Sentence

from .normalize import normalize
from .retrieval import RetrievedChunk


@dataclass(frozen=True)
class Citation:
    """A citation as the model claimed it, before verification."""

    marker: int
    chunk_id: int
    quote: str


@dataclass(frozen=True)
class VerifiedCitation:
    marker: int
    chunk_id: int
    quote: str
    verified: bool
    accession: str
    sids: list[int]
    ticker: str = ""
    form_type: str = ""
    filing_date: str = ""


def sentence_spans(sentences: list[Sentence]) -> list[tuple[int, int, int]]:
    """(sid, start, end) half-open spans in *chunk-text* coordinates.

    This reconstructs the ' '.join(...) that pipeline.chunk.chunk_sentences
    used to build chunk.text. It deliberately does not use Sentence.char_start,
    which is an offset into the filing's canonical text (a '\\n'-joined string).
    Those two coordinate systems agree today only because both joins happen to
    use exactly one separator character; depending on that coincidence would
    make verification break silently if either join ever changed.
    """
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    for sentence in sentences:
        spans.append((sentence.sid, cursor, cursor + len(sentence.text)))
        cursor += len(sentence.text) + 1  # the single space from " ".join
    return spans


def find_quote(chunk_text: str, quote: str) -> tuple[int, int] | None:
    """Normalized substring match; returns original chunk_text offsets.

    No fuzzy matching (design §6.3) -- determinism is the whole point. A quote
    that does not appear verbatim modulo normalization is unverified, full stop.
    """
    normalized_quote, _ = normalize(quote)
    normalized_quote = normalized_quote.strip()
    if not normalized_quote:
        return None
    normalized_chunk, offsets = normalize(chunk_text)
    index = normalized_chunk.find(normalized_quote)
    if index == -1:
        return None
    start = offsets[index]
    end = offsets[index + len(normalized_quote) - 1] + 1
    return start, end


def resolve_sids(spans: list[tuple[int, int, int]], start: int, end: int) -> list[int]:
    """Every sid whose span overlaps [start, end)."""
    return [
        sid for sid, span_start, span_end in spans if span_start < end and start < span_end
    ]


def verify_citation(
    citation: Citation, chunk: RetrievedChunk, sentences: list[Sentence]
) -> VerifiedCitation:
    match = find_quote(chunk.text, citation.quote)
    sids = resolve_sids(sentence_spans(sentences), *match) if match else []
    return VerifiedCitation(
        marker=citation.marker,
        chunk_id=citation.chunk_id,
        quote=citation.quote,
        verified=bool(sids),
        accession=chunk.accession,
        sids=sids,
        ticker=chunk.ticker,
        form_type=chunk.form_type,
        filing_date=chunk.filing_date.isoformat(),
    )
