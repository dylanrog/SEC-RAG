from pipeline.canonicalize import Sentence
from pipeline.chunk import chunk_sentences, count_tokens


def sent(sid, section, text):
    return Sentence(sid, section, text, 0, len(text))


def test_groups_consecutive_sentences_within_budget():
    sentences = [sent(i, "item1", f"Sentence number {i} talks about products.") for i in range(5)]
    chunks = chunk_sentences(sentences, max_tokens=1000)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert (chunk.sid_start, chunk.sid_end) == (0, 4)
    assert chunk.section == "item1"
    assert "Sentence number 3" in chunk.text
    assert chunk.token_count == count_tokens(chunk.text)


def test_splits_on_token_budget():
    sentences = [sent(i, "item1", "word " * 50) for i in range(4)]  # ~50 tokens each
    chunks = chunk_sentences(sentences, max_tokens=120)
    assert len(chunks) == 2
    assert (chunks[0].sid_start, chunks[0].sid_end) == (0, 1)
    assert (chunks[1].sid_start, chunks[1].sid_end) == (2, 3)


def test_never_spans_sections():
    sentences = [sent(0, "item1", "About the business."), sent(1, "item1a", "About the risks.")]
    chunks = chunk_sentences(sentences, max_tokens=1000)
    assert [c.section for c in chunks] == ["item1", "item1a"]


def test_sid_ranges_are_contiguous_and_disjoint():
    sentences = [sent(i, "item7" if i < 7 else "item8", "word " * 30) for i in range(10)]
    chunks = chunk_sentences(sentences, max_tokens=100)
    covered = []
    for c in chunks:
        covered.extend(range(c.sid_start, c.sid_end + 1))
    assert covered == list(range(10))  # every sid exactly once, in order


def test_overlong_single_sentence_gets_own_chunk():
    sentences = [sent(0, "item1", "word " * 600), sent(1, "item1", "Short one.")]
    chunks = chunk_sentences(sentences, max_tokens=450)
    assert (chunks[0].sid_start, chunks[0].sid_end) == (0, 0)
    assert (chunks[1].sid_start, chunks[1].sid_end) == (1, 1)
