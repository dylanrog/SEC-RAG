from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from pipeline.canonicalize import canonicalize

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def result():
    raw = (FIXTURES / "mini_10k.html").read_text(encoding="utf-8")
    return canonicalize(raw, "10-K")


def test_sentences_extracted_with_sections(result):
    texts = [s.text for s in result.sentences]
    assert "The Company designs smartphones and related services." in texts
    assert "It sells its products worldwide." in texts
    by_text = {s.text: s for s in result.sentences}
    assert by_text["The Company designs smartphones and related services."].section == "item1"
    assert by_text["Demand could differ from expectations."].section == "item1a"


def test_sids_sequential_and_offsets_align(result):
    assert [s.sid for s in result.sentences] == list(range(len(result.sentences)))
    for s in result.sentences:
        assert result.canonical_text[s.char_start:s.char_end] == s.text


def test_viewer_html_spans_align_with_sentences(result):
    viewer = BeautifulSoup(result.viewer_html, "lxml")
    span_tags = viewer.find_all("span", attrs={"data-sid": True})
    spans = {int(el["data-sid"]): el.get_text() for el in span_tags}
    assert len(spans) == len(result.sentences)
    for s in result.sentences:
        assert spans[s.sid] == s.text


def test_tables_are_viewer_only(result):
    assert "table text must stay viewer-only" not in result.canonical_text
    assert "table text must stay viewer-only" in result.viewer_html


def test_scripts_and_xbrl_header_are_stripped(result):
    assert "alert(" not in result.viewer_html
    assert "dei:DocumentType" not in result.viewer_html
    assert "10-K" not in result.canonical_text  # ix:hidden content must not leak into text
