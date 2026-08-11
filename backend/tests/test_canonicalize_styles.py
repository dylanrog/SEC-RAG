import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from pipeline.canonicalize import canonicalize, strip_color_declarations

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def styled():
    raw = (FIXTURES / "styled_filing.html").read_text(encoding="utf-8")
    return canonicalize(raw, "10-K")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("color:#000000;font-weight:700", "font-weight:700"),
        ("width:40%;background-color:#cceeff", "width:40%"),
        ("background:#f2f2f2;text-align:right", "text-align:right"),
        ("COLOR: #000000; TEXT-ALIGN: center", "TEXT-ALIGN: center"),
        ("color:#000000", ""),
        ("  color:#000 ;  ", ""),
        ("text-align:left", "text-align:left"),
        ("", ""),
    ],
)
def test_strip_color_declarations(value, expected):
    assert strip_color_declarations(value) == expected


def test_border_color_is_not_a_color_declaration():
    # 'border-bottom' carries geometry as well as colour. Dropping the whole
    # declaration would lose the rule line, so it stays.
    assert (
        strip_color_declarations("border-bottom:1px solid #000000")
        == "border-bottom:1px solid #000000"
    )


def test_viewer_html_has_no_color_declarations(styled):
    assert "color:#000000" not in styled.viewer_html
    assert "color:#ff0000" not in styled.viewer_html
    assert "background-color:#cceeff" not in styled.viewer_html
    assert "background:#f2f2f2" not in styled.viewer_html


def test_viewer_html_keeps_layout_declarations(styled):
    assert "text-align:justify" in styled.viewer_html
    assert "width:40%" in styled.viewer_html
    assert "border-collapse:collapse" in styled.viewer_html
    assert "font-weight:700" in styled.viewer_html


def test_emptied_style_attributes_are_removed(styled):
    soup = BeautifulSoup(styled.viewer_html, "lxml")
    for el in soup.find_all(style=True):
        assert el["style"].strip() != ""


def test_sentences_are_invariant_under_style_attributes():
    """The load-bearing claim: a style attribute contributes no text, so
    stripping one cannot move a sid. Guards click-to-highlight."""
    raw = (FIXTURES / "styled_filing.html").read_text(encoding="utf-8")
    without_styles = re.sub(r'\s+style="[^"]*"', "", raw)
    assert canonicalize(raw, "10-K").sentences == canonicalize(without_styles, "10-K").sentences
