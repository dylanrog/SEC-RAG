from datetime import date

from api.generate import AnswerSplitter, build_user_message, parse_citations
from api.retrieval import RetrievedChunk


def chunk(chunk_id: int, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        accession="0000320193-24-000123",
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        ticker="AAPL",
        section="item7",
        sid_start=0,
        sid_end=1,
        text=text,
        filing_id=1,
        score=0.5,
    )


def test_user_message_labels_each_chunk_with_its_id_and_provenance():
    message = build_user_message("What were net sales?", [chunk(42, "Net sales rose.")])
    assert "chunk_id=42" in message
    assert "AAPL" in message and "10-K" in message
    assert "Net sales rose." in message
    assert "What were net sales?" in message


def test_splitter_emits_prose_and_withholds_the_fence():
    splitter = AnswerSplitter()
    parts = ["Net sales ", "rose [1].\n\n", "```json\n", '{"citations": []}', "\n```"]
    emitted = "".join(splitter.feed(part) for part in parts)
    emitted += splitter.finish()
    assert emitted == "Net sales rose [1].\n\n"
    assert "```json" in splitter.raw


def test_splitter_never_emits_a_partial_fence_opener():
    splitter = AnswerSplitter()
    first = splitter.feed("Answer.\n\n`")
    assert "`" not in first


def test_splitter_with_no_fence_emits_everything_on_finish():
    splitter = AnswerSplitter()
    emitted = splitter.feed("Just prose, no citations.") + splitter.finish()
    assert emitted == "Just prose, no citations."


def test_parse_citations_reads_the_fenced_block():
    raw = (
        "Answer [1].\n\n```json\n"
        '{"citations": [{"marker": 1, "chunk_id": 8, "quote": "hi"}]}\n```'
    )
    citations = parse_citations(raw)
    assert len(citations) == 1
    assert citations[0].marker == 1
    assert citations[0].chunk_id == 8
    assert citations[0].quote == "hi"


def test_parse_citations_accepts_a_bare_json_fence():
    assert parse_citations('Answer.\n```\n{"citations": []}\n```') == []


def test_parse_citations_returns_none_when_no_block_is_present():
    assert parse_citations("Answer with no block at all.") is None


def test_parse_citations_returns_none_on_malformed_json():
    assert parse_citations('Answer.\n```json\n{"citations": [oops}\n```') is None


def test_parse_citations_skips_entries_missing_required_fields():
    raw = (
        '```json\n{"citations": [{"marker": 1},'
        ' {"marker": 2, "chunk_id": 3, "quote": "q"}]}\n```'
    )
    citations = parse_citations(raw)
    assert [c.marker for c in citations] == [2]


def test_system_prompt_asks_for_every_supporting_filing():
    from api.generate import SYSTEM_PROMPT

    assert "more than one filing" in SYSTEM_PROMPT
