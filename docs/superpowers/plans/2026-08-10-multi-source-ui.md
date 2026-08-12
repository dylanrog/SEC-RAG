# Multi-Source Answers + Tabbed Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an answer that draws on several filings say so — a sources panel grouped by filing, and a tabbed viewer that holds up to three filings open at once.

**Architecture:** The canonicalizer gains a selective strip of color-bearing inline CSS so the filing viewer can be themed dark; a new `recanonicalize` CLI backfills `viewer_html` only, verifying that sentence anchoring is unchanged rather than assuming it. The API carries `filing_date` onto the citation SSE event so source cards render without a second fetch. The frontend gains two pure `lib/` modules (grouping, tab state) and thin components over them.

**Tech Stack:** Python 3.13, psycopg 3, BeautifulSoup + lxml, FastAPI. Next.js 16.2.12, React 19.2.4, Tailwind 4, vitest 4, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-10-multi-source-ui-design.md`

## Global Constraints

- Python **3.13** everywhere. `requires-python = ">=3.13"`; do not reintroduce a version matrix.
- **ruff is pinned exactly** at `ruff==0.16.1` with an explicit `[tool.ruff.lint] select`. Do not bump it in this work.
- Every commit must leave `ruff check .` and `pytest -q` green, run from `backend/`. CI runs lint before tests, so a lint failure silently skips the whole test suite.
- Frontend commands run from `frontend/` **in PowerShell** — node is not on the git-bash PATH on this machine.
- `frontend/AGENTS.md`: this Next.js version has breaking changes versus training data. Read the relevant guide in `frontend/node_modules/next/dist/docs/` before writing Next-specific code.
- DB-dependent tests are marked `@pytest.mark.db` and auto-skip unless `TEST_DATABASE_URL` is set. CI has no Postgres; that is intentional.
- **Commit messages must contain no AI attribution of any kind** — no Co-Authored-By, no session trailers, no tool names.
- **Do not change retrieval ranking.** No query, filter, fusion, or ranking rule moves in this plan. One `SELECT` column is added in Task 3 and nothing else.
- Chunk size stays **450 tiktoken tokens**. Do not touch chunking or embedding.
- Canonicalizer correctness is defined by fixtures in `backend/tests/fixtures/`. Add a fixture before changing extraction behavior.

## File Structure

**Backend — pipeline**
- `backend/src/pipeline/canonicalize.py` — gains `strip_color_declarations()` and calls it in the existing single traversal.
- `backend/src/pipeline/store.py` — gains `filings_to_recanonicalize()` and `update_viewer_html()`.
- `backend/src/pipeline/ingest.py` — gains `recanonicalize_filings()` and `RecanonicalizeStats`.
- `backend/src/pipeline/__main__.py` — gains the `recanonicalize` subcommand.

**Backend — API**
- `backend/src/api/retrieval.py` — `_BASE` gains `f.filing_date`; `RetrievedChunk` gains the field.
- `backend/src/api/verify.py` — `VerifiedCitation` gains `ticker`, `form_type`, `filing_date`.
- `backend/src/api/answer.py` — citation event payload gains those three fields.
- `backend/src/api/generate.py` — one added `SYSTEM_PROMPT` rule.

**Frontend**
- `frontend/lib/types.ts` — `Citation` gains three fields.
- `frontend/lib/sources.ts` — **new**, pure grouping.
- `frontend/lib/tabs.ts` — **new**, pure tab reducer.
- `frontend/components/sources-panel.tsx` — **new**.
- `frontend/components/filing-tabs.tsx` — **new**.
- `frontend/components/filing-viewer.tsx` — rewritten for multiple panes.
- `frontend/app/ask/page.tsx` — tab state replaces `{accession, sids}`.
- `frontend/app/globals.css` — dark theme, viewer rules, table banding.

---

### Task 1: Selective color strip in the canonicalizer

**Files:**
- Create: `backend/tests/fixtures/styled_filing.html`
- Modify: `backend/src/pipeline/canonicalize.py`
- Test: `backend/tests/test_canonicalize_styles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `strip_color_declarations(style: str) -> str` in `pipeline.canonicalize`. Returns the style attribute value with `color`, `background`, and `background-color` declarations removed; returns `""` when nothing survives. `canonicalize()` keeps its existing signature and return type.

- [ ] **Step 1: Create the fixture**

The existing `mini_10k.html` has no inline styles, so the strip needs its own fixture. These attribute values are shaped like real EDGAR output — `color:#000000` alongside layout properties on the same element.

Create `backend/tests/fixtures/styled_filing.html`:

```html
<html>
<head><title>FORM 10-K</title></head>
<body>
<div><p style="color:#000000;font-weight:700"><b>Item 1. Business</b></p></div>
<div>
  <p style="color:#000000;font-family:'Times New Roman',sans-serif;font-size:10pt;text-align:justify">The Company designs smartphones and related services. It sells its products worldwide.</p>
</div>
<table style="border-collapse:collapse;width:100%">
  <tr style="background-color:#cceeff">
    <td style="width:40%;text-align:left;color:#000000;border-bottom:1px solid #000000">Net sales</td>
    <td style="width:60%;text-align:right;background:#f2f2f2">$ 391,035</td>
  </tr>
</table>
<p style="color:#ff0000">Loss figures appear in red.</p>
<p style="COLOR: #000000; TEXT-ALIGN: center">Mixed-case declarations occur in real filings.</p>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_canonicalize_styles.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run from `backend/`: `pytest tests/test_canonicalize_styles.py -v`
Expected: FAIL — `ImportError: cannot import name 'strip_color_declarations'`

- [ ] **Step 4: Implement the strip**

In `backend/src/pipeline/canonicalize.py`, add `re` to the imports and this constant beside `_STRIP_TAGS`:

```python
# Declarations whose *only* job is colour. 'border-bottom: 1px solid #000'
# deliberately does not match: it carries geometry too, and dropping it would
# lose the rule line from every financial table.
_COLOR_PROPERTIES = ("color", "background", "background-color")
```

Then add the function:

```python
def strip_color_declarations(style: str) -> str:
    """Remove colour-bearing declarations from one inline style attribute.

    EDGAR filings arrive with colour baked into thousands of inline styles
    (one cached AMZN 10-K: 9,316 style attributes, 6,574 colour declarations,
    nearly all '#000000'). Those render as invisible text on a dark viewer.
    Layout properties are kept -- EDGAR tables rely on width, alignment and
    borders for their geometry, so a blanket strip mangles them.
    """
    kept = []
    for declaration in style.split(";"):
        if not declaration.strip():
            continue
        prop, _, _value = declaration.partition(":")
        if prop.strip().lower() in _COLOR_PROPERTIES:
            continue
        kept.append(declaration.strip())
    return "; ".join(kept)
```

In `canonicalize()`, extend the existing attribute-cleaning loop (currently lines 37-39) so it becomes:

```python
    for el in soup.find_all(True):
        for attr in [a for a in el.attrs if a.lower().startswith("on")]:
            del el.attrs[attr]
        style = el.attrs.get("style")
        if style is not None:
            cleaned = strip_color_declarations(style)
            if cleaned:
                el["style"] = cleaned
            else:
                del el.attrs["style"]
```

Keeping this inside the existing traversal matters: design.md §4.2 forbids a second pass, because separate passes are how canonical text and viewer HTML drift apart.

- [ ] **Step 5: Run the tests to verify they pass**

Run from `backend/`: `pytest tests/test_canonicalize_styles.py -v`
Expected: PASS, 13 tests (8 parametrized cases plus 5 others).

- [ ] **Step 6: Run the full suite and lint**

Run from `backend/`: `pytest -q` then `ruff check .`
Expected: all green. `test_canonicalize.py` must still pass — `mini_10k.html` has no inline styles, so nothing there changes.

- [ ] **Step 7: Commit**

```bash
git add backend/src/pipeline/canonicalize.py backend/tests/test_canonicalize_styles.py backend/tests/fixtures/styled_filing.html
git commit -m "feat: strip colour declarations from inline filing styles

EDGAR bakes colour into inline style attributes that survive ingestion,
so filing text renders invisibly on a dark viewer pane. Drop the
colour-bearing declarations and keep the layout ones tables need for
geometry. A fixture pins that sentence extraction is unchanged."
```

---

### Task 2: `recanonicalize` — the viewer_html-only backfill

**Files:**
- Modify: `backend/src/pipeline/store.py`
- Modify: `backend/src/pipeline/ingest.py`
- Modify: `backend/src/pipeline/__main__.py`
- Test: `backend/tests/test_recanonicalize.py`

**Interfaces:**
- Consumes: `strip_color_declarations` behaviour from Task 1 (indirectly, via `canonicalize()`); existing `store.load_sentences(conn, filing_id) -> list[Sentence]`.
- Produces:
  - `store.filings_to_recanonicalize(conn, *, ticker=None) -> list[tuple[int, int, str, str]]` — `(filing_id, cik, accession, form_type)`, ordered by `filing_id`.
  - `store.update_viewer_html(conn, filing_id: int, viewer_html: str) -> None`
  - `ingest.RecanonicalizeStats(updated: int, missing: int, mismatched: list[str])`
  - `ingest.recanonicalize_filings(conn, *, cache_dir: Path, ticker: str | None = None) -> RecanonicalizeStats`

- [ ] **Step 1: Write the failing unit test for the mismatch guard**

Create `backend/tests/test_recanonicalize.py`:

```python
import os
from datetime import date
from pathlib import Path

import psycopg
import pytest

from pipeline import db, ingest, store
from pipeline.canonicalize import canonicalize
from pipeline.companies import Company
from pipeline.edgar import FilingRef

FIXTURES = Path(__file__).parent / "fixtures"
COMPANY = Company(999999002, "TSTB", "Test Co B")
REF = FilingRef(
    cik=999999002,
    accession="TEST-24-000002",
    form_type="10-K",
    filing_date=date(2024, 11, 1),
    period_end=date(2024, 9, 28),
    primary_document="styled_filing.html",
)


def _seed(conn, cache_dir: Path, *, viewer_html: str | None = None) -> int:
    """Store the styled fixture as a filing, optionally with a stale viewer_html."""
    raw = (FIXTURES / "styled_filing.html").read_text(encoding="utf-8")
    cached = cache_dir / str(REF.cik) / f"{REF.accession}.html"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(raw, encoding="utf-8")

    canonical = canonicalize(raw, REF.form_type)
    if viewer_html is not None:
        canonical = type(canonical)(
            canonical_text=canonical.canonical_text,
            sentences=canonical.sentences,
            viewer_html=viewer_html,
        )
    return store.store_filing(conn, COMPANY, REF, canonical, replace=True)


@pytest.mark.db
def test_recanonicalize_updates_viewer_html_only(tmp_path):
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        filing_id = _seed(conn, tmp_path, viewer_html="<p>stale</p>")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sentences WHERE filing_id = %s", (filing_id,))
            sentences_before = cur.fetchone()[0]

        stats = ingest.recanonicalize_filings(conn, cache_dir=tmp_path, ticker="TSTB")
        conn.commit()

        assert stats.updated == 1
        assert stats.mismatched == []
        with conn.cursor() as cur:
            cur.execute("SELECT viewer_html FROM filings WHERE id = %s", (filing_id,))
            viewer_html = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM sentences WHERE filing_id = %s", (filing_id,))
            assert cur.fetchone()[0] == sentences_before

        assert "stale" not in viewer_html
        assert "color:#000000" not in viewer_html
        assert 'data-sid="0"' in viewer_html


@pytest.mark.db
def test_recanonicalize_aborts_a_filing_whose_sentences_moved(tmp_path):
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        filing_id = _seed(conn, tmp_path)
        conn.commit()

        # Corrupt one stored sentence so the freshly computed list disagrees.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentences SET text = 'tampered' WHERE filing_id = %s AND sid = 0",
                (filing_id,),
            )
            cur.execute("UPDATE filings SET viewer_html = '<p>stale</p>' WHERE id = %s", (filing_id,))
        conn.commit()

        stats = ingest.recanonicalize_filings(conn, cache_dir=tmp_path, ticker="TSTB")
        conn.commit()

        assert stats.updated == 0
        assert stats.mismatched == [REF.accession]
        with conn.cursor() as cur:
            cur.execute("SELECT viewer_html FROM filings WHERE id = %s", (filing_id,))
            assert cur.fetchone()[0] == "<p>stale</p>"


@pytest.mark.db
def test_recanonicalize_skips_a_filing_missing_from_the_cache(tmp_path):
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        _seed(conn, tmp_path)
        conn.commit()
        (tmp_path / str(REF.cik) / f"{REF.accession}.html").unlink()

        stats = ingest.recanonicalize_filings(conn, cache_dir=tmp_path, ticker="TSTB")
        conn.commit()

        assert stats.updated == 0
        assert stats.missing == 1
```

- [ ] **Step 2: Run to verify it fails**

Run from `backend/`: `pytest tests/test_recanonicalize.py -v`
Expected: FAIL — `AttributeError: module 'pipeline.ingest' has no attribute 'recanonicalize_filings'`

(If it reports "skipped", `TEST_DATABASE_URL` is unset. Set it to the `edgar_answers_test` database and re-run — a skip is not a pass.)

- [ ] **Step 3: Add the store functions**

Append to `backend/src/pipeline/store.py`:

```python
def filings_to_recanonicalize(
    conn: psycopg.Connection, *, ticker: str | None = None
) -> list[tuple[int, int, str, str]]:
    """(filing_id, cik, accession, form_type) for every stored filing."""
    sql = (
        "SELECT f.id, f.cik, f.accession, f.form_type FROM filings f"
        " JOIN companies c ON c.cik = f.cik"
    )
    params: list[object] = []
    if ticker:
        sql += " WHERE c.ticker = %s"
        params.append(ticker.upper())
    sql += " ORDER BY f.id"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def update_viewer_html(conn: psycopg.Connection, filing_id: int, viewer_html: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE filings SET viewer_html = %s WHERE id = %s", (viewer_html, filing_id)
        )
```

- [ ] **Step 4: Add the backfill to ingest.py**

Add `from pathlib import Path` to the imports in `backend/src/pipeline/ingest.py`, then append:

```python
@dataclass
class RecanonicalizeStats:
    updated: int = 0
    missing: int = 0
    mismatched: list[str] = field(default_factory=list)


def recanonicalize_filings(
    conn,
    *,
    cache_dir: Path,
    ticker: str | None = None,
) -> RecanonicalizeStats:
    """Rebuild viewer_html from cached raw HTML. Writes nothing else.

    Sentence extraction reads block text, which an inline style attribute
    cannot affect, so sids are invariant across this change -- meaning no
    re-chunk and no re-embed. That invariance is *verified per filing* rather
    than assumed: if the freshly computed sentences disagree with the stored
    rows in any field, the filing is left untouched and reported. A silent
    rewrite here would break every stored citation and the golden set's
    pinned sids at once.
    """
    stats = RecanonicalizeStats()
    for filing_id, cik, accession, form_type in store.filings_to_recanonicalize(
        conn, ticker=ticker
    ):
        path = Path(cache_dir) / str(cik) / f"{accession}.html"
        if not path.exists():
            stats.missing += 1
            continue
        canonical = canonicalize(path.read_text(encoding="utf-8"), form_type)
        if canonical.sentences != store.load_sentences(conn, filing_id):
            stats.mismatched.append(accession)
            continue
        store.update_viewer_html(conn, filing_id, canonical.viewer_html)
        stats.updated += 1
    return stats
```

Update the dataclass import at the top of the file to `from dataclasses import dataclass, field`.

- [ ] **Step 5: Run the tests to verify they pass**

Run from `backend/`: `pytest tests/test_recanonicalize.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Add the CLI subcommand**

In `backend/src/pipeline/__main__.py`, register the parser next to `p_embed`:

```python
    p_recanon = sub.add_parser(
        "recanonicalize",
        help="rebuild viewer_html from cached raw HTML (no re-embed, no EDGAR traffic)",
    )
    p_recanon.add_argument("--ticker", help="restrict to one curated ticker")
```

and handle it beside the `embed` branch:

```python
    if args.cmd == "recanonicalize":
        with db.connect() as conn:
            stats = ingest.recanonicalize_filings(conn, cache_dir=Path("data/raw"), ticker=args.ticker)
        print(f"updated {stats.updated} filings, {stats.missing} missing from cache")
        if stats.mismatched:
            print(f"SENTENCE MISMATCH, left untouched: {', '.join(stats.mismatched)}")
        return
```

- [ ] **Step 7: Verify the command runs against the real database**

Run from `backend/`: `python -m pipeline recanonicalize --ticker AAPL`
Expected: `updated 13 filings, 0 missing from cache` and no mismatch line.

If any filing reports a mismatch, **stop and investigate before continuing** — that is the invariance claim failing, and §9 of the spec flags it as the likeliest place for the work to go sideways.

- [ ] **Step 8: Backfill the whole corpus**

Run from `backend/`: `python -m pipeline recanonicalize`
Expected: `updated 120 filings, 0 missing from cache`.

- [ ] **Step 9: Run the full suite and lint, then commit**

Run from `backend/`: `pytest -q` then `ruff check .`

```bash
git add backend/src/pipeline/store.py backend/src/pipeline/ingest.py backend/src/pipeline/__main__.py backend/tests/test_recanonicalize.py
git commit -m "feat: add recanonicalize to rebuild viewer_html in place

Re-runs the canonicalizer over cached raw HTML and updates viewer_html
only -- no re-chunk, no re-embed, no EDGAR traffic. Verifies per filing
that the recomputed sentences match the stored rows before writing, so a
change that did move a sid is reported instead of silently breaking every
stored citation."
```

---

### Task 3: Carry filing metadata onto the citation event

**Files:**
- Modify: `backend/src/api/retrieval.py`
- Modify: `backend/src/api/verify.py`
- Modify: `backend/src/api/answer.py`
- Test: `backend/tests/test_verify.py`, `backend/tests/test_answer.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces: `RetrievedChunk` gains `filing_date: date` as the **fourth** field (after `form_type`). `VerifiedCitation` gains `ticker: str`, `form_type: str`, `filing_date: str` (ISO). The `citation` SSE event payload becomes `{marker, verified, accession, ticker, form_type, filing_date, sids, quote}`.

**Critical ordering note:** `retrieve()` builds chunks with `RetrievedChunk(*rows_by_id[chunk_id], score)` — positional expansion. The `_BASE` column order and the dataclass field order **must** move together or every field silently shifts.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_verify.py`, add:

```python
def test_verified_citation_carries_filing_metadata():
    from datetime import date

    from api.retrieval import RetrievedChunk
    from api.verify import Citation, verify_citation
    from pipeline.canonicalize import Sentence

    chunk = RetrievedChunk(
        chunk_id=1,
        accession="0000320193-24-000123",
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        ticker="AAPL",
        section="item7",
        sid_start=0,
        sid_end=0,
        text="Total net sales were 391,035 million.",
        filing_id=5,
        score=0.5,
    )
    sentences = [Sentence(0, "item7", chunk.text, 0, len(chunk.text))]
    result = verify_citation(
        Citation(marker=1, chunk_id=1, quote="Total net sales"), chunk, sentences
    )
    assert result.verified is True
    assert result.ticker == "AAPL"
    assert result.form_type == "10-K"
    assert result.filing_date == "2024-11-01"
```

- [ ] **Step 2: Run to verify it fails**

Run from `backend/`: `pytest tests/test_verify.py -v`
Expected: FAIL — `TypeError: RetrievedChunk.__init__() got an unexpected keyword argument 'filing_date'`

- [ ] **Step 3: Add the column and fields**

In `backend/src/api/retrieval.py`, change `_BASE` to (note `f.filing_date` inserted after `f.form_type`):

```python
_BASE = (
    "SELECT ch.id, f.accession, f.form_type, f.filing_date, c.ticker, ch.section,"
    " ch.sid_start, ch.sid_end, ch.text, ch.filing_id"
    " FROM chunks ch"
    " JOIN filings f ON f.id = ch.filing_id"
    " JOIN companies c ON c.cik = f.cik"
)
```

and `RetrievedChunk` to match, in the same position:

```python
@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    accession: str
    form_type: str
    filing_date: date
    ticker: str
    section: str
    sid_start: int
    sid_end: int
    text: str
    filing_id: int
    score: float
```

Add `from datetime import date` to the imports.

In `backend/src/api/verify.py`, extend `VerifiedCitation`:

```python
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
```

Defaults are empty strings so the `answer.py` "model cited a chunk it was never shown" path keeps constructing this without them — that citation genuinely has no filing.

Extend the return in `verify_citation`:

```python
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
```

In `backend/src/api/answer.py`, extend the citation event payload:

```python
        for citation in verified:
            yield AnswerEvent(
                "citation",
                {
                    "marker": citation.marker,
                    "verified": citation.verified,
                    "accession": citation.accession,
                    "ticker": citation.ticker,
                    "form_type": citation.form_type,
                    "filing_date": citation.filing_date,
                    "sids": citation.sids,
                    "quote": citation.quote,
                },
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`: `pytest tests/test_verify.py tests/test_answer.py tests/test_retrieval.py -v`
Expected: PASS. Any test constructing `RetrievedChunk` positionally will need `filing_date` added in the fourth position — fix those as they surface; that is the ordering hazard doing its job.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run from `backend/`: `pytest -q` then `ruff check .`

```bash
git add backend/src/api/retrieval.py backend/src/api/verify.py backend/src/api/answer.py backend/tests/test_verify.py
git commit -m "feat: carry ticker, form type and filing date onto citations

Source cards need a label. Without these fields the frontend would fetch
GET /filings/{accession} per source -- ~800 KB of viewer HTML -- purely to
render a date. Ranking is untouched: one SELECT column is added."
```

---

### Task 4: Prompt rule for multi-filing citation

**Files:**
- Modify: `backend/src/api/generate.py`
- Test: `backend/tests/test_generate.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no new symbols. `SYSTEM_PROMPT` gains rule 4.

This task changes a measured variable, so it is bracketed by eval runs. Tasks 1-3 do not touch generation, so a baseline taken now is still a clean comparison.

- [ ] **Step 1: Record the pre-change faithfulness baseline**

Ensure the tree is clean (`git status` shows nothing uncommitted), then run from `backend/`:

```
python -m evals run
```

Note the `verified_rate` and `answered_rate` of the appended row in `evals/results.jsonl`.

- [ ] **Step 2: Write the failing test**

In `backend/tests/test_generate.py`, add:

```python
def test_system_prompt_asks_for_every_supporting_filing():
    from api.generate import SYSTEM_PROMPT

    assert "more than one filing" in SYSTEM_PROMPT
```

- [ ] **Step 3: Run to verify it fails**

Run from `backend/`: `pytest tests/test_generate.py -v`
Expected: FAIL — assertion error.

- [ ] **Step 4: Add the rule**

In `backend/src/api/generate.py`, insert a fourth numbered rule into `SYSTEM_PROMPT`, after rule 3's fenced example and before the "Every quote must be copied" paragraph:

```
4. When excerpts from more than one filing support the answer, cite each of
   them. Do not collapse several filings into a single citation, and do not
   answer only from whichever excerpt appeared first.
```

- [ ] **Step 5: Run the test to verify it passes**

Run from `backend/`: `pytest tests/test_generate.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite and lint, then commit**

Run from `backend/`: `pytest -q` then `ruff check .`

```bash
git add backend/src/api/generate.py backend/tests/test_generate.py
git commit -m "feat: ask the model to cite every filing that supports an answer"
```

- [ ] **Step 7: Record the post-change faithfulness run**

Run from `backend/`: `python -m evals run`

Compare against Step 1. Because this commit is the only change between the two runs, any movement in `verified_rate` or `answered_rate` is attributable to this rule. Commit the new results rows:

```bash
git add backend/evals/results.jsonl
git commit -m "chore: record faithfulness either side of the multi-filing prompt rule"
```

Note: `gold_sid_hit_rate` varies run to run on identical code — do not read a single-run change in it as a regression.

---

### Task 5: `lib/sources.ts` — grouping citations by filing

**Files:**
- Modify: `frontend/lib/types.ts`
- Create: `frontend/lib/sources.ts`
- Test: `frontend/lib/__tests__/sources.test.ts`

**Interfaces:**
- Consumes: the citation event shape from Task 3.
- Produces:
  - `Citation` gains `ticker: string`, `form_type: string`, `filing_date: string`.
  - `type SourceGroup = {accession, ticker, form_type, filing_date, citations: Citation[], verifiedCount: number, openable: boolean}`
  - `groupSources(citations: Map<number, Citation>): SourceGroup[]`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/sources.test.ts`:

```ts
import { expect, test } from "vitest";

import { groupSources } from "../sources";
import type { Citation } from "../types";

function citation(marker: number, over: Partial<Citation> = {}): Citation {
  return {
    marker,
    verified: true,
    accession: "AAPL-1",
    ticker: "AAPL",
    form_type: "10-K",
    filing_date: "2024-11-01",
    sids: [marker],
    quote: `quote ${marker}`,
    ...over,
  };
}

function map(...citations: Citation[]): Map<number, Citation> {
  return new Map(citations.map((c) => [c.marker, c]));
}

test("citations from one filing collapse into a single group", () => {
  const groups = groupSources(map(citation(1), citation(3)));
  expect(groups).toHaveLength(1);
  expect(groups[0].citations.map((c) => c.marker)).toEqual([1, 3]);
  expect(groups[0].verifiedCount).toBe(2);
});

test("groups are ordered by the first marker that appears in each", () => {
  const groups = groupSources(
    map(
      citation(1, { accession: "MSFT-1", ticker: "MSFT" }),
      citation(2, { accession: "AAPL-1" }),
      citation(3, { accession: "MSFT-1", ticker: "MSFT" }),
    ),
  );
  expect(groups.map((g) => g.accession)).toEqual(["MSFT-1", "AAPL-1"]);
});

test("a filing whose citations all failed still renders but does not open", () => {
  const groups = groupSources(map(citation(1, { verified: false, sids: [] })));
  expect(groups).toHaveLength(1);
  expect(groups[0].verifiedCount).toBe(0);
  expect(groups[0].openable).toBe(false);
});

test("a citation with no accession is unattributable and does not open", () => {
  const groups = groupSources(
    map(citation(1, { verified: false, accession: "", ticker: "", sids: [] })),
  );
  expect(groups[0].accession).toBe("");
  expect(groups[0].openable).toBe(false);
});

test("a partially verified filing is openable", () => {
  const groups = groupSources(map(citation(1), citation(2, { verified: false, sids: [] })));
  expect(groups[0].verifiedCount).toBe(1);
  expect(groups[0].openable).toBe(true);
});

test("no citations yields no groups", () => {
  expect(groupSources(new Map())).toEqual([]);
});
```

- [ ] **Step 2: Run to verify it fails**

Run from `frontend/` in PowerShell: `npm test -- sources`
Expected: FAIL — cannot resolve `../sources`.

- [ ] **Step 3: Extend the Citation type**

In `frontend/lib/types.ts`, replace the `Citation` type with:

```ts
/** A citation event, post-verification (design §6.4). */
export type Citation = {
  marker: number;
  verified: boolean;
  /** Empty when the model cited a chunk it was never shown — unattributable. */
  accession: string;
  ticker: string;
  form_type: string;
  filing_date: string;
  sids: number[];
  quote: string;
};
```

- [ ] **Step 4: Implement the grouping**

Create `frontend/lib/sources.ts`:

```ts
import type { Citation } from "./types";

export type SourceGroup = {
  accession: string;
  ticker: string;
  form_type: string;
  filing_date: string;
  citations: Citation[];
  verifiedCount: number;
  /** False for an unattributable group, or one whose citations all failed. */
  openable: boolean;
};

/**
 * Collapse citations into one group per filing, ordered by the first marker
 * appearing in each. Grouping is the only place the UI states "this answer
 * rests on N filings", which is the claim the feature exists to make.
 */
export function groupSources(citations: Map<number, Citation>): SourceGroup[] {
  const byAccession = new Map<string, SourceGroup>();

  for (const citation of [...citations.values()].sort((a, b) => a.marker - b.marker)) {
    const existing = byAccession.get(citation.accession);
    if (existing === undefined) {
      byAccession.set(citation.accession, {
        accession: citation.accession,
        ticker: citation.ticker,
        form_type: citation.form_type,
        filing_date: citation.filing_date,
        citations: [citation],
        verifiedCount: citation.verified ? 1 : 0,
        openable: citation.accession !== "" && citation.verified,
      });
      continue;
    }
    existing.citations.push(citation);
    if (citation.verified) {
      existing.verifiedCount += 1;
      existing.openable = existing.accession !== "";
    }
  }

  return [...byAccession.values()];
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run from `frontend/`: `npm test -- sources`
Expected: PASS, 6 tests.

- [ ] **Step 6: Run the full frontend suite and lint, then commit**

Run from `frontend/`: `npm test` then `npm run lint`
Expected: green. `answer.test.ts` constructs citations without the new fields; TypeScript will flag those object literals — add `ticker: "AAPL"`, `form_type: "10-K"`, `filing_date: "2024-11-01"` to them.

```bash
git add frontend/lib/sources.ts frontend/lib/types.ts frontend/lib/__tests__/sources.test.ts frontend/lib/__tests__/answer.test.ts
git commit -m "feat: group citations by filing for the sources panel"
```

---

### Task 6: `lib/tabs.ts` — tab state with LRU eviction

**Files:**
- Create: `frontend/lib/tabs.ts`
- Test: `frontend/lib/__tests__/tabs.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `type TabState = {open: string[]; active: string | null; recency: string[]}`
  - `MAX_TABS = 3`
  - `initialTabState: TabState`
  - `openTab(state: TabState, accession: string): TabState`
  - `closeTab(state: TabState, accession: string): TabState`

`open` is display order and stays stable so the tab strip does not reshuffle under the cursor; `recency` is most-recently-active first and drives eviction.

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/tabs.test.ts`:

```ts
import { expect, test } from "vitest";

import { closeTab, initialTabState, MAX_TABS, openTab } from "../tabs";

function openAll(...accessions: string[]) {
  return accessions.reduce(openTab, initialTabState);
}

test("opening a filing adds it and makes it active", () => {
  const state = openTab(initialTabState, "A");
  expect(state.open).toEqual(["A"]);
  expect(state.active).toBe("A");
});

test("reopening an open filing activates it without duplicating or reordering", () => {
  const state = openTab(openAll("A", "B"), "A");
  expect(state.open).toEqual(["A", "B"]);
  expect(state.active).toBe("A");
});

test("opening beyond the cap evicts the least recently active tab", () => {
  // A opened first, then B, then C, then A re-activated -> B is least recent.
  const state = openTab(openTab(openAll("A", "B", "C"), "A"), "D");
  expect(state.open).toHaveLength(MAX_TABS);
  expect(state.open).toEqual(["A", "C", "D"]);
  expect(state.active).toBe("D");
});

test("an evicted filing can be reopened", () => {
  const evicted = openTab(openTab(openAll("A", "B", "C"), "A"), "D");
  const state = openTab(evicted, "B");
  expect(state.open).toContain("B");
  expect(state.active).toBe("B");
  expect(state.open).toHaveLength(MAX_TABS);
});

test("closing the active tab activates the next most recent", () => {
  const state = closeTab(openAll("A", "B"), "B");
  expect(state.open).toEqual(["A"]);
  expect(state.active).toBe("A");
});

test("closing the last tab leaves nothing active", () => {
  const state = closeTab(openAll("A"), "A");
  expect(state.open).toEqual([]);
  expect(state.active).toBeNull();
});

test("closing an inactive tab leaves the active one alone", () => {
  const state = closeTab(openAll("A", "B"), "A");
  expect(state.active).toBe("B");
});

test("openTab does not mutate the state it was given", () => {
  const before = openAll("A");
  const after = openTab(before, "B");
  expect(before.open).toEqual(["A"]);
  expect(after).not.toBe(before);
});
```

- [ ] **Step 2: Run to verify it fails**

Run from `frontend/`: `npm test -- tabs`
Expected: FAIL — cannot resolve `../tabs`.

- [ ] **Step 3: Implement the reducer**

Create `frontend/lib/tabs.ts`:

```ts
export type TabState = {
  /** Display order. Deliberately stable so the tab strip never reshuffles. */
  open: string[];
  active: string | null;
  /** Most-recently-active first. Drives eviction only. */
  recency: string[];
};

/**
 * A real 10-K's viewer_html is ~800 KB, and open tabs stay mounted so each
 * keeps its scroll position. Three is the point where that stops being free.
 */
export const MAX_TABS = 3;

export const initialTabState: TabState = { open: [], active: null, recency: [] };

export function openTab(state: TabState, accession: string): TabState {
  const recency = [accession, ...state.recency.filter((a) => a !== accession)];

  if (state.open.includes(accession)) {
    return { open: state.open, active: accession, recency };
  }

  let open = [...state.open, accession];
  if (open.length > MAX_TABS) {
    const evicted = [...recency].reverse().find((a) => open.includes(a));
    if (evicted !== undefined) {
      open = open.filter((a) => a !== evicted);
      return { open, active: accession, recency: recency.filter((a) => a !== evicted) };
    }
  }
  return { open, active: accession, recency };
}

export function closeTab(state: TabState, accession: string): TabState {
  const open = state.open.filter((a) => a !== accession);
  const recency = state.recency.filter((a) => a !== accession);
  const active = state.active === accession ? (recency[0] ?? null) : state.active;
  return { open, active, recency };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run from `frontend/`: `npm test -- tabs`
Expected: PASS, 8 tests.

- [ ] **Step 5: Run the full frontend suite and lint, then commit**

Run from `frontend/`: `npm test` then `npm run lint`

```bash
git add frontend/lib/tabs.ts frontend/lib/__tests__/tabs.test.ts
git commit -m "feat: add tab state with LRU eviction at three filings"
```

---

### Task 7: Tab strip, multi-pane viewer, sources panel, and page wiring

**Files:**
- Create: `frontend/components/filing-tabs.tsx`
- Create: `frontend/components/sources-panel.tsx`
- Modify: `frontend/components/filing-viewer.tsx` (full rewrite)
- Modify: `frontend/app/ask/page.tsx` (full rewrite)

**Interfaces:**
- Consumes: `groupSources`/`SourceGroup` (Task 5); `TabState`/`openTab`/`closeTab`/`initialTabState` (Task 6); existing `fetchFiling`, `applyHighlight`, `Filing`.
- Produces:
  - `<FilingTabs tabs={TabState} labels={Record<string, string>} onActivate={(a: string) => void} onClose={(a: string) => void} />`
  - `<FilingViewer tabs={TabState} sids={Record<string, number[]>} />`
  - `<SourcesPanel groups={SourceGroup[]} onSelect={(c: Citation) => void} />`

Every open filing stays mounted; inactive panes are hidden with `display:none` rather than unmounted. That is what preserves per-tab scroll position, which is the entire reason for tabs.

**This is one task and not two on purpose.** `FilingViewer`'s props change, and `app/ask/page.tsx` is its only caller. Splitting them would land a commit that does not compile — and `playwright.config.ts` runs `npm run build` before the e2e suite, so that commit could not run its own tests.

- [ ] **Step 1: Write the tab strip**

Create `frontend/components/filing-tabs.tsx`:

```tsx
"use client";

import type { TabState } from "@/lib/tabs";

export function FilingTabs({
  tabs,
  labels,
  onActivate,
  onClose,
}: {
  tabs: TabState;
  labels: Record<string, string>;
  onActivate: (accession: string) => void;
  onClose: (accession: string) => void;
}) {
  if (tabs.open.length === 0) return null;

  return (
    <div className="flex border-b border-slate-800 bg-slate-900 font-mono text-[11px]">
      {tabs.open.map((accession) => {
        const active = accession === tabs.active;
        return (
          <div
            key={accession}
            className={
              active
                ? "flex items-center gap-2 border-b-2 border-blue-500 bg-slate-950 px-3 py-2 text-slate-100"
                : "flex items-center gap-2 px-3 py-2 text-slate-500 hover:text-slate-300"
            }
          >
            <button type="button" onClick={() => onActivate(accession)}>
              {labels[accession] ?? accession}
            </button>
            <button
              type="button"
              aria-label={`Close ${labels[accession] ?? accession}`}
              onClick={() => onClose(accession)}
              className="text-slate-600 hover:text-slate-300"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Rewrite the viewer**

Replace `frontend/components/filing-viewer.tsx` entirely:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

import { fetchFiling } from "@/lib/api";
import { applyHighlight } from "@/lib/highlight";
import type { TabState } from "@/lib/tabs";
import type { Filing } from "@/lib/types";

/**
 * One mounted filing. Kept in the DOM while its tab is open even when
 * inactive -- hidden with display:none rather than unmounted -- so that its
 * scroll position survives a tab switch. Unmounting would also mean
 * re-fetching and re-parsing ~800 KB of HTML on every switch.
 */
function FilingPane({
  accession,
  sids,
  active,
}: {
  accession: string;
  sids: number[];
  active: boolean;
}) {
  const [filing, setFiling] = useState<Filing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchFiling(accession)
      .then((next) => {
        if (!cancelled) setFiling(next);
      })
      .catch(() => {
        if (!cancelled) setError("Filing not available.");
      });
    return () => {
      cancelled = true;
    };
  }, [accession]);

  // Highlighting scrolls the cited sentence into view, so it must not run
  // while the pane is hidden -- display:none elements have no layout box and
  // scrollIntoView would do nothing.
  useEffect(() => {
    if (active && filing !== null && containerRef.current !== null) {
      applyHighlight(containerRef.current, sids);
    }
  }, [active, filing, sids]);

  return (
    // data-accession gives each pane a stable handle regardless of which is
    // active — the e2e scroll-persistence spec needs to address a *specific*
    // pane, and a class selector would resolve to whichever is visible.
    <div
      data-accession={accession}
      className={active ? "h-full overflow-y-auto p-5" : "hidden"}
    >
      {error !== null && <p className="text-red-400">{error}</p>}
      {error === null && filing === null && (
        <p className="text-slate-500">Loading filing…</p>
      )}
      {filing !== null && (
        // Safe here and only here: this HTML was sanitized by the
        // canonicalizer at ingestion, so the server is the sanitizer.
        <div
          ref={containerRef}
          className="filing-html"
          dangerouslySetInnerHTML={{ __html: filing.viewer_html }}
        />
      )}
    </div>
  );
}

export function FilingViewer({
  tabs,
  sids,
}: {
  tabs: TabState;
  sids: Record<string, number[]>;
}) {
  if (tabs.open.length === 0) {
    return (
      <p className="p-5 text-slate-500">Click a source to open the filing here.</p>
    );
  }

  return (
    <>
      {tabs.open.map((accession) => (
        <FilingPane
          key={accession}
          accession={accession}
          sids={sids[accession] ?? []}
          active={accession === tabs.active}
        />
      ))}
    </>
  );
}
```

- [ ] **Step 3: Write the sources panel**

Create `frontend/components/sources-panel.tsx`:

```tsx
"use client";

import type { SourceGroup } from "@/lib/sources";
import type { Citation } from "@/lib/types";

export function SourcesPanel({
  groups,
  onSelect,
}: {
  groups: SourceGroup[];
  onSelect: (citation: Citation) => void;
}) {
  if (groups.length === 0) return null;

  const citationCount = groups.reduce((n, g) => n + g.citations.length, 0);

  return (
    <section className="mt-6">
      <h2 className="font-mono text-[10px] tracking-[0.09em] text-slate-500 uppercase">
        Sources · {groups.length} {groups.length === 1 ? "filing" : "filings"} ·{" "}
        {citationCount} {citationCount === 1 ? "citation" : "citations"}
      </h2>

      <ul className="mt-2 space-y-1">
        {groups.map((group) => (
          <li
            key={group.accession || "unattributable"}
            className={
              group.openable
                ? "border-l-2 border-blue-500 bg-slate-900 px-3 py-2"
                : "border-l-2 border-red-500 bg-slate-900 px-3 py-2"
            }
          >
            <div className="flex items-baseline justify-between text-xs">
              {group.accession === "" ? (
                <span className="font-mono font-bold text-slate-300">
                  unattributable
                </span>
              ) : (
                <span className="font-mono font-bold text-slate-200">
                  {group.ticker}{" "}
                  <span className="font-normal text-slate-500">
                    {group.form_type} {group.filing_date}
                  </span>
                </span>
              )}
              <span
                className={group.verifiedCount > 0 ? "text-green-500" : "text-red-400"}
              >
                {group.verifiedCount > 0
                  ? `${group.verifiedCount} ✓`
                  : "unverified"}
              </span>
            </div>

            <ul className="mt-1.5 space-y-1 border-l border-slate-800 pl-2">
              {group.citations.map((citation) => (
                <li key={citation.marker} className="text-[11px] leading-snug">
                  {citation.verified ? (
                    <button
                      type="button"
                      onClick={() => onSelect(citation)}
                      className="text-left hover:text-slate-100"
                    >
                      <span className="mr-1 rounded bg-blue-900 px-1 font-mono text-blue-200">
                        {citation.marker}
                      </span>
                      <span className="text-slate-400">“{citation.quote}”</span>
                    </button>
                  ) : (
                    <span>
                      <span className="mr-1 rounded bg-red-950 px-1 font-mono text-red-300">
                        {citation.marker}
                      </span>
                      <span className="text-slate-500">
                        quote did not match source text
                      </span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Rewrite the page**

Replace `frontend/app/ask/page.tsx` entirely:

```tsx
"use client";

import { useMemo, useState } from "react";

import { AnswerStream } from "@/components/answer-stream";
import { AskForm } from "@/components/ask-form";
import { FilingTabs } from "@/components/filing-tabs";
import { FilingViewer } from "@/components/filing-viewer";
import { SourcesPanel } from "@/components/sources-panel";
import { initialAnswerState, reduceAnswer } from "@/lib/answer";
import type { AnswerState } from "@/lib/answer";
import { askStream } from "@/lib/api";
import type { AskFilters } from "@/lib/api";
import { groupSources } from "@/lib/sources";
import { closeTab, initialTabState, openTab } from "@/lib/tabs";
import type { Citation } from "@/lib/types";

export default function AskPage() {
  const [answer, setAnswer] = useState<AnswerState>(initialAnswerState);
  const [tabs, setTabs] = useState(initialTabState);
  const [sids, setSids] = useState<Record<string, number[]>>({});

  const groups = useMemo(() => groupSources(answer.citations), [answer.citations]);
  const labels = useMemo(
    () =>
      Object.fromEntries(
        groups.map((g) => [g.accession, `${g.ticker} ${g.form_type}`]),
      ),
    [groups],
  );

  async function ask(question: string, filters: AskFilters) {
    setAnswer({ ...initialAnswerState, status: "streaming" });
    setTabs(initialTabState);
    setSids({});
    try {
      for await (const event of askStream(question, filters)) {
        setAnswer((previous) => reduceAnswer(previous, event));
      }
    } catch (error) {
      setAnswer((previous) => ({
        ...previous,
        status: "error",
        errorMessage:
          error instanceof Error ? error.message : "Could not reach the API.",
      }));
    }
  }

  function select(citation: Citation) {
    // Unverified and unattributable citations are inert by design (§6.3):
    // there is nothing trustworthy to scroll to.
    if (!citation.verified || citation.accession === "") return;
    setTabs((previous) => openTab(previous, citation.accession));
    setSids((previous) => ({ ...previous, [citation.accession]: citation.sids }));
  }

  return (
    <main className="grid h-screen grid-cols-[minmax(0,5fr)_minmax(0,7fr)] bg-slate-950 text-slate-200">
      <section className="overflow-y-auto border-r border-slate-800 p-5">
        <h1 className="mb-4 font-mono text-sm font-bold tracking-wide text-slate-100">
          EDGAR ANSWERS
        </h1>
        <AskForm disabled={answer.status === "streaming"} onSubmit={ask} />
        <AnswerStream state={answer} onSelect={select} />
        <SourcesPanel groups={groups} onSelect={select} />
      </section>

      <section className="flex flex-col overflow-hidden">
        <FilingTabs
          tabs={tabs}
          labels={labels}
          onActivate={(accession) =>
            setTabs((previous) => openTab(previous, accession))
          }
          onClose={(accession) =>
            setTabs((previous) => closeTab(previous, accession))
          }
        />
        <div className="min-h-0 flex-1 bg-white">
          <FilingViewer tabs={tabs} sids={sids} />
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 5: Run the full frontend suite and lint**

Run from `frontend/`: `npm test` then `npm run lint`
Expected: green.

- [ ] **Step 6: Run the existing e2e specs**

Run from `frontend/`: `npm run test:e2e`
Expected: both existing specs pass. This also proves the tree builds — the Playwright webServer runs `npm run build`, which typechecks. The first spec clicks an inline `[1]` chip, which now opens a tab instead of setting a single accession; its assertion is on `data-sid` classes and is unaffected. The existing stubs send citations without `ticker`/`form_type`/`filing_date`, so those render as blanks in the tab label — harmless, and Task 9 adds a spec with the full payload.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/filing-tabs.tsx frontend/components/filing-viewer.tsx frontend/components/sources-panel.tsx frontend/app/ask/page.tsx
git commit -m "feat: grouped sources panel over a tabbed filing viewer

Open panes stay mounted and hidden rather than unmounting, so each tab
keeps its scroll position and switching does not re-fetch ~800 KB of HTML.
Highlighting is gated on the pane being active: scrollIntoView does
nothing inside a display:none subtree. Page state moves from a single
{accession, sids} to tab state plus sids keyed by accession."
```

---

### Task 8: Dark utilitarian theme

**Files:**
- Modify: `frontend/app/globals.css`
- Modify: `frontend/components/citation-chip.tsx`
- Modify: `frontend/components/answer-stream.tsx`
- Modify: `frontend/components/ask-form.tsx`

**Interfaces:**
- Consumes: the `filing-html` class applied by `FilingPane` in Task 7.
- Produces: no new symbols.

The viewer keeps a **white** background under dark chrome only where filing HTML sets its own; with colours stripped in Task 1 the filing text now inherits, so the pane goes dark and the `filing-html` rules below supply readable defaults plus table banding to replace the `background` shading the strip removed.

- [ ] **Step 1: Rewrite globals.css**

Replace `frontend/app/globals.css` entirely:

```css
@import "tailwindcss";

:root {
  --background: #020617;
  --foreground: #e2e8f0;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);
}

/* Dark is now viable because the canonicalizer strips colour-bearing inline
   declarations at ingestion (pipeline/canonicalize.py strip_color_declarations),
   so filing text inherits instead of arriving hardcoded to #000000. Filings
   ingested before that change must be backfilled with
   `python -m pipeline recanonicalize` or they will render invisibly here. */

body {
  background: var(--background);
  color: var(--foreground);
}

/* Injected filing HTML. Tailwind never sees this markup, so these are plain
   global rules. */
.filing-html {
  color: #cbd5e1;
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.75;
}

.filing-html table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
  font-family: var(--font-geist-mono), ui-monospace, monospace;
  font-size: 0.8rem;
}

/* Replaces the row shading that stripping `background` removed. */
.filing-html tr:nth-child(even) {
  background-color: #0f172a;
}

.filing-html td,
.filing-html th {
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid #1e293b;
}

.filing-html b,
.filing-html strong {
  color: #f1f5f9;
}

/* Applied imperatively by lib/highlight.ts to spans inside injected viewer
   HTML. */
.cited-sentence {
  background-color: #78350f;
  color: #fef3c7;
  box-shadow: 0 0 0 3px #78350f;
  scroll-margin-top: 4rem;
}
```

- [ ] **Step 2: Darken the viewer pane background in the page**

In `frontend/app/ask/page.tsx`, change the viewer wrapper from `bg-white` to `bg-slate-950`:

```tsx
        <div className="min-h-0 flex-1 bg-slate-950">
```

- [ ] **Step 3: Restyle the citation chip**

In `frontend/components/citation-chip.tsx`, replace the three `className` values:

- undefined citation: `"text-slate-600"`
- unverified span: `"mx-0.5 rounded bg-red-950 px-1 font-mono text-[10px] text-red-300"`
- verified button: `"mx-0.5 rounded bg-blue-900 px-1 font-mono text-[10px] text-blue-200 hover:bg-blue-800"`

- [ ] **Step 4: Restyle the answer stream notices**

In `frontend/components/answer-stream.tsx`, replace:

- idle text: `"text-slate-500"` (unchanged)
- error paragraph: `"mb-3 rounded bg-red-950 p-2 text-sm text-red-300"`
- notice paragraph: `"mb-3 rounded bg-amber-950 p-2 text-sm text-amber-300"`
- answer paragraph: `"text-sm leading-7 whitespace-pre-wrap"`

- [ ] **Step 5: Restyle the ask form**

In `frontend/components/ask-form.tsx`, replace only the four `className` strings on the controls. Leave every `aria-label`, `value`, and handler untouched — the e2e specs locate these with `getByLabel("Question")` and `getByRole("button", { name: "Ask" })`, and renaming or dropping an `aria-label` breaks all three specs.

```tsx
      <input
        aria-label="Question"
        className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-600 focus:outline-none"
        placeholder="What were Apple's total net sales in fiscal 2024?"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
```

Both `<select>` elements take the same class string:

```tsx
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-slate-300"
```

And the submit button:

```tsx
          className="rounded bg-blue-700 px-4 py-1 text-sm text-white hover:bg-blue-600 disabled:bg-slate-800 disabled:text-slate-500"
```

- [ ] **Step 6: Verify in the browser**

Start the API (from `backend/`: `uvicorn api.app:app --reload`) and the frontend (from `frontend/`: `npm run dev`), then open `http://localhost:3000/ask` and ask a question that spans filers, e.g. "How do Apple and Microsoft describe supply chain risk?".

Confirm: the sources panel lists more than one filing; clicking two sources opens two tabs; switching tabs preserves scroll position; the filing text is legible on the dark pane; tables show banding.

- [ ] **Step 7: Run tests and lint, then commit**

Run from `frontend/`: `npm test`, `npm run lint`, `npm run test:e2e`

```bash
git add frontend/app/globals.css frontend/app/ask/page.tsx frontend/components/citation-chip.tsx frontend/components/answer-stream.tsx frontend/components/ask-form.tsx
git commit -m "feat: dark utilitarian theme across chrome and filing viewer

The viewer can go dark now that colour declarations are stripped at
ingestion. Table row banding is restored in CSS, replacing the background
shading the strip removes."
```

---

### Task 9: End-to-end multi-source spec

**Files:**
- Create: `frontend/e2e/multi-source.spec.ts`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Write the spec**

Create `frontend/e2e/multi-source.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const AAPL = "0000320193-24-000123";
const MSFT = "0000789019-24-000078";
const API = "http://localhost:8000";

const SSE_BODY = [
  'event: token\ndata: {"text":"Apple cites single-source suppliers [1]. ',
  'Microsoft cites datacenter hardware [2]."}\n\n',
  `event: citation\ndata: {"marker":1,"verified":true,"accession":"${AAPL}",`,
  '"ticker":"AAPL","form_type":"10-K","filing_date":"2024-11-01",',
  '"sids":[2],"quote":"single-source suppliers"}\n\n',
  `event: citation\ndata: {"marker":2,"verified":true,"accession":"${MSFT}",`,
  '"ticker":"MSFT","form_type":"10-K","filing_date":"2024-07-30",',
  '"sids":[1],"quote":"a limited number of suppliers"}\n\n',
  'event: done\ndata: {"chunks_retrieved":8,"citations_total":2,',
  '"citations_verified":2,"unverified_answer":false}\n\n',
].join("");

// Long enough that the pane scrolls, so a preserved scroll position is
// actually observable.
const filler = Array.from(
  { length: 60 },
  (_, i) => `<p><span data-sid="${100 + i}">Filler sentence ${i}.</span></p>`,
).join("");

const AAPL_HTML = `
  <p><span data-sid="1">Apple risk intro.</span></p>
  <p><span data-sid="2">single-source suppliers concentrate our exposure</span></p>
  ${filler}`;

const MSFT_HTML = `
  <p><span data-sid="1">a limited number of suppliers serve our datacenters</span></p>
  ${filler}`;

function filing(accession: string, ticker: string, html: string, filed: string) {
  return {
    accession,
    viewer_html: html,
    ticker,
    form_type: "10-K",
    filing_date: filed,
    period_end: null,
  };
}

test("an answer spanning two filings opens two tabs that keep their scroll", async ({
  page,
}) => {
  await page.route(`${API}/companies`, (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.route(`${API}/ask`, (route) =>
    route.fulfill({ contentType: "text/event-stream", body: SSE_BODY }),
  );
  await page.route(`${API}/filings/${AAPL}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(filing(AAPL, "AAPL", AAPL_HTML, "2024-11-01")),
    }),
  );
  await page.route(`${API}/filings/${MSFT}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(filing(MSFT, "MSFT", MSFT_HTML, "2024-07-30")),
    }),
  );

  await page.goto("/ask");
  await page.getByLabel("Question").fill("How do Apple and Microsoft describe supply chain risk?");
  await page.getByRole("button", { name: "Ask" }).click();

  // Both filings appear as sources, and the panel says so.
  await expect(page.getByText("Sources · 2 filings · 2 citations")).toBeVisible();

  // Open Apple, then Microsoft.
  await page.getByRole("button", { name: "[1]" }).click();
  await expect(page.locator(`[data-sid="2"]`).first()).toHaveClass(/cited-sentence/);

  await page.getByRole("button", { name: "[2]" }).click();
  await expect(page.getByRole("button", { name: "MSFT 10-K" })).toBeVisible();
  await expect(page.getByRole("button", { name: "AAPL 10-K" })).toBeVisible();

  // Scroll the Microsoft pane, switch away, switch back: position survives.
  // Addressed by data-accession, not by a class: a ".overflow-y-auto" selector
  // would resolve to whichever pane is currently visible, so after switching
  // to Apple it would silently read Apple's scrollTop instead.
  const msftPane = page.locator(`[data-accession="${MSFT}"]`);
  await msftPane.evaluate((el) => el.scrollTo(0, 800));
  const scrolled = await msftPane.evaluate((el) => el.scrollTop);
  expect(scrolled).toBeGreaterThan(0);

  await page.getByRole("button", { name: "AAPL 10-K" }).click();
  await page.getByRole("button", { name: "MSFT 10-K" }).click();
  await expect
    .poll(() => msftPane.evaluate((el) => el.scrollTop))
    .toBe(scrolled);
});
```

- [ ] **Step 2: Run the spec**

Run from `frontend/`: `npm run test:e2e -- multi-source`
Expected: PASS.

If the scroll assertion fails, the cause is a pane being unmounted rather than hidden — check that `FilingViewer` maps over `tabs.open` and that `FilingPane` uses `className="hidden"` rather than returning `null` when inactive.

- [ ] **Step 3: Run the whole e2e suite, then commit**

Run from `frontend/`: `npm run test:e2e`
Expected: 3 specs pass.

```bash
git add frontend/e2e/multi-source.spec.ts
git commit -m "test: cover a two-filing answer end to end

Asserts both filings surface as sources, both open as tabs, and a tab's
scroll position survives switching away and back -- the behaviour that
distinguishes tabs from a single swapped pane."
```

---

### Task 10: Update project documentation

**Files:**
- Modify: `docs/design.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

`CLAUDE.md` is gitignored — update it locally, and do not stage it.

- [ ] **Step 1: Record the spec deviations in design.md**

In `docs/design.md` §4.2, after the "Tables" bullet, add:

```markdown
- **Inline styles:** colour-bearing declarations (`color`, `background`,
  `background-color`) are stripped from inline `style` attributes during the
  same traversal; layout declarations are kept, because EDGAR tables rely on
  width, alignment and borders for their geometry. Filings arrive with colour
  hardcoded to `#000000` on thousands of elements, which is unreadable on the
  dark viewer. `python -m pipeline recanonicalize` backfills `viewer_html` for
  already-ingested filings without re-chunking or re-embedding.
```

In §6.4, replace the `citation` event line with:

```
citation: {"marker": 1, "verified": true,
           "accession": "0000320193-24-000123",
           "ticker": "AAPL", "form_type": "10-K",
           "filing_date": "2024-11-01",
           "sids": [1042, 1043], "quote": "…"}
```

In §7, replace the two bullets describing the panes with:

```markdown
- **Left — answer pane:** question input, optional company/form filters, streamed
  answer. Markers render as citation chips; verified chips are clickable,
  unverified chips show the badge and are not. Below the answer, a **sources
  panel** groups every citation under its filing, so an answer drawing on
  several filings says so.
- **Right — filing viewer:** a tab strip over up to three open filings (LRU
  eviction beyond that). Inactive panes stay mounted and hidden so each keeps
  its scroll position. Clicking a citation opens or activates its filing's tab
  and highlights the cited sids.
```

In §14, remove "multi-filing comparison questions" from the backlog list — the rendering half is now built; the retrieval half is tracked as query decomposition.

- [ ] **Step 2: Update CLAUDE.md's current state**

In `CLAUDE.md`, under "Current state", add a bullet after the Phase 5 one:

```markdown
- **Multi-source UI complete** (spec `docs/superpowers/specs/2026-08-10-multi-source-ui-design.md`):
  sources panel grouped by filing, tabbed viewer capped at 3 with LRU
  eviction, dark utilitarian theme. The canonicalizer now strips colour
  declarations from inline styles; `python -m pipeline recanonicalize`
  backfills `viewer_html` only, verifying per filing that sentences and sids
  are unchanged before writing. Retrieval ranking is deliberately untouched —
  the next steps are the golden set 16 → 40 with comparison and period
  questions, then query decomposition scored against it.
```

Also correct the stale note in the same file: the `gold_sid_hit_rate` paragraph recommends "a fixed seed / temperature 0", but `api/generate.py` already sets `temperature=0`. Reword to say the variance persists at temperature 0 and its source is not yet identified.

- [ ] **Step 3: Commit**

```bash
git add docs/design.md
git commit -m "docs: record the sources panel, tabbed viewer and style strip"
```

---

## Verification

Before opening a PR, from a clean tree:

```
cd backend && ruff check . && pytest -q
cd ../frontend && npm test && npm run lint && npm run test:e2e
```

Expected: ruff clean; backend tests pass with db tests running (not skipped — set `TEST_DATABASE_URL`); 42+ vitest specs pass; 3 Playwright specs pass.

Then confirm the corpus was actually backfilled. `recanonicalize` rewrites unconditionally, so its own output cannot tell you whether Task 2 Step 8 ran — query the data instead. From `backend/`:

```
python -c "from pipeline import db; c=db.connect(); cur=c.execute(\"select count(*) from filings where viewer_html like '%color:#000000%'\"); print(cur.fetchone()[0])"
```

Expected: `0`. Any non-zero count is filings that were never backfilled; they will render as invisible text on the dark viewer. Re-run `python -m pipeline recanonicalize` and check for a reported sentence mismatch.
