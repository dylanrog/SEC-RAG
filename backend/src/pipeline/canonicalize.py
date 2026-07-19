from __future__ import annotations

from dataclasses import dataclass

import pysbd
from bs4 import BeautifulSoup

from .sections import SectionTracker

_STRIP_TAGS = ["script", "style", "iframe", "object", "embed", "ix:header", "ix:hidden"]
_BLOCK_TAGS = ["p", "li", "div"]


@dataclass(frozen=True)
class Sentence:
    sid: int
    section: str
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class CanonicalFiling:
    canonical_text: str
    sentences: list[Sentence]
    viewer_html: str


def canonicalize(raw_html: str, form_type: str) -> CanonicalFiling:
    """One DOM traversal producing aligned canonical text and sid-annotated viewer HTML."""
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    for tag in soup.find_all(lambda t: t.name is not None and t.name.startswith("ix:")):
        tag.unwrap()
    for el in soup.find_all(True):
        for attr in [a for a in el.attrs if a.lower().startswith("on")]:
            del el.attrs[attr]

    segmenter = pysbd.Segmenter(language="en", clean=False, char_span=True)
    tracker = SectionTracker(form_type)
    sentences: list[Sentence] = []
    cursor = 0

    for block in _leaf_blocks(soup):
        text = " ".join(block.get_text(" ", strip=True).split())
        if not text:
            continue
        section = tracker.update(text)
        block_sentences: list[Sentence] = []
        for span in segmenter.segment(text):
            sent_text = span.sent.strip()
            if not sent_text:
                continue
            start = cursor
            end = start + len(sent_text)
            sid = len(sentences) + len(block_sentences)
            block_sentences.append(Sentence(sid, section, sent_text, start, end))
            cursor = end + 1  # sentences join with "\n" in canonical_text
        if block_sentences:
            _rewrite_block(soup, block, block_sentences)
            sentences.extend(block_sentences)

    canonical_text = "\n".join(s.text for s in sentences)
    body = soup.body if soup.body is not None else soup
    viewer_html = "".join(str(child) for child in body.children)
    return CanonicalFiling(canonical_text, sentences, viewer_html)


def _leaf_blocks(soup: BeautifulSoup):
    for el in soup.find_all(_BLOCK_TAGS):
        if el.find(_BLOCK_TAGS) is not None:
            continue  # container block; its leaf descendants are visited on their own
        if el.find_parent("table") is not None:
            continue  # tables stay viewer-only in v1 (spec §4.2)
        yield el


def _rewrite_block(soup: BeautifulSoup, block, block_sentences: list[Sentence]) -> None:
    """Replace block content with sid-tagged spans. Inline formatting inside a
    paragraph is flattened in v1; block structure and tables are preserved."""
    block.clear()
    for i, s in enumerate(block_sentences):
        span = soup.new_tag("span")
        span["data-sid"] = str(s.sid)
        span.string = s.text
        block.append(span)
        if i < len(block_sentences) - 1:
            block.append(" ")
