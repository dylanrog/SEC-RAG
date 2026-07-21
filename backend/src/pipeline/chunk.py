from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from .canonicalize import Sentence

# bge-small-en-v1.5 truncates input at 512 of its own tokens; 450 tiktoken
# tokens keeps chunks safely under that limit (amends design §4.3's ~600).
MAX_TOKENS = 450


@dataclass(frozen=True)
class Chunk:
    section: str
    sid_start: int
    sid_end: int
    text: str
    token_count: int


@lru_cache(maxsize=1)
def _encoding():
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def chunk_sentences(sentences: list[Sentence], *, max_tokens: int = MAX_TOKENS) -> list[Chunk]:
    """Greedy grouping of consecutive sentences within a section (design §4.3).

    Chunks are contiguous, disjoint sid ranges; an over-long single sentence
    becomes its own chunk rather than being split mid-sentence."""
    chunks: list[Chunk] = []
    current: list[Sentence] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if current:
            text = " ".join(s.text for s in current)
            chunks.append(
                Chunk(
                    section=current[0].section,
                    sid_start=current[0].sid,
                    sid_end=current[-1].sid,
                    text=text,
                    token_count=count_tokens(text),
                )
            )
            current, current_tokens = [], 0

    for sentence in sentences:
        n = count_tokens(sentence.text)
        new_section = current and sentence.section != current[0].section
        over_budget = current and current_tokens + n > max_tokens
        if new_section or over_budget:
            flush()
        current.append(sentence)
        current_tokens += n
    flush()
    return chunks
