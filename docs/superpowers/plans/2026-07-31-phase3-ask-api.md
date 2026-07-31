# EDGAR Answers Phase 3: `/ask` — Generation → Verification → SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI service exposing `POST /ask` that retrieves chunks, generates an answer with Claude Haiku, verifies every citation quote against the cited chunk's canonical text server-side, resolves verified quotes to sentence ids, and streams the whole thing over SSE — exiting at "stubbed-LLM integration test passes; live answers cite verified quotes" (design §12, Phase 3).

**Architecture:** The query path is a pure generator function, `api.answer.answer_stream()`, which yields typed events (`token` / `citation` / `done` / `error`). FastAPI is a thin adapter that renders those events as SSE; the faithfulness eval consumes the same generator directly, with no HTTP. The LLM sits behind a one-method `Generator` protocol so every test below the eval runs with a stub and costs nothing. Verification is split into two pure modules — `api.normalize` (text → normalized text + offset map) and `api.verify` (substring match → original offsets → sids) — neither of which touches the database or the network.

**Tech Stack:** Everything from Phase 0–2 plus FastAPI (HTTP + SSE), uvicorn (dev server), and the `anthropic` SDK (Claude Haiku 4.5).

**Spec:** `docs/design.md` §6 (query path: retrieve/generate/verify/SSE), §9 (testing: stubbed-LLM integration), §10 (error handling), §12 (Phase 3 exit criterion). Prior work: `docs/superpowers/plans/2026-07-19-phase2-retrieval.md` (complete).

## Prerequisites

- **Phase 2 must be merged to `main` first.** Branch `phase3-ask` from `main` after the `phase2-retrieval` PR lands. Phase 3 consumes `api.retrieval.retrieve()` and `pipeline.embed.Embedder` as-is.
- Postgres running (`docker compose up -d` at repo root) with the 12 AAPL filings ingested **and chunked** — `python -m evals run --retrieval-only` should reproduce recall@10 = 1.0 before you start. If it doesn't, fix that first; a broken retrieval floor makes every Phase 3 failure ambiguous.
- Test database `edgar_answers_test` exists and `TEST_DATABASE_URL` points at it.
- `ANTHROPIC_API_KEY` exported in the shell. Only Task 8 and the Task 6 live smoke step spend money; everything else runs on the stub.
- Upgrade the SDK first: `pip install -U anthropic`. The currently installed 0.40.0 predates the Haiku 4.5 release.

## Global Constraints

- Python 3.11+; run all backend commands from `backend/` (`pip install -e ".[dev]"` after editing pyproject).
- `ruff check .` and `pytest -v` must pass before every commit (matches CI). `ruff` is not on PATH as a bare command in this environment — use `python -m ruff check .`.
- Commit messages: imperative mood, **no AI attribution of any kind** — no Co-Authored-By, no Claude-Session trailers, no tool names.
- DB-dependent tests carry `@pytest.mark.db` (skip without `TEST_DATABASE_URL`). CI runs no DB — that's intentional. **No test in this phase may call the real Anthropic API.** The faithfulness eval (Task 8) is a CLI command, not a test.
- **Model is `claude-haiku-4-5`** (design §2). Do not set `thinking` (Haiku 4.5 has no adaptive thinking; omitting it means no thinking, which is what we want) and do not set `output_config.effort` (errors on Haiku 4.5). `temperature=0` for reproducibility.
- **Do not add prompt caching.** Haiku 4.5's minimum cacheable prefix is 4096 tokens; our system prompt is a few hundred. A `cache_control` marker would pay the ~1.25× write premium for zero reads.
- **Do not use `output_config.format` (structured outputs) for citations.** It constrains the *entire* response to JSON, which is incompatible with design §6.2's streaming-prose-then-trailing-block contract. The trailing fenced block is deliberate — it keeps perceived latency low and costs one call instead of two.
- Failed verification renders `verified: false` with a visible badge. **Never silently drop a citation** (design §6.3). This is the product.
- Scope note: design §6 lists an optional `year` filter. `api.retrieval.retrieve()` has no year parameter and Phase 3 does not add one — `/ask` accepts `ticker` and `form_type` only. Year filtering goes to the §14 backlog.

## File Structure

```
backend/
  pyproject.toml                     # MODIFY: add fastapi, uvicorn, anthropic
  src/api/retrieval.py               # MODIFY: add filing_id to SELECT + RetrievedChunk
  src/api/normalize.py               # NEW: normalize() -> (text, offset_map)
  src/api/verify.py                  # NEW: Citation, VerifiedCitation, sentence_spans, verify_citation
  src/api/queries.py                 # NEW: non-retrieval DB reads (chunk sentences, filing, companies)
  src/api/generate.py                # NEW: Generator protocol, prompts, AnswerSplitter, parse_citations
  src/api/answer.py                  # NEW: answer_stream() — the query path, HTTP-free
  src/api/app.py                     # NEW: FastAPI app, SSE rendering, all endpoints
  evals/faithfulness.py              # NEW: run_faithfulness_eval()
  evals/__main__.py                  # MODIFY: wire up the full (non retrieval-only) path
  tests/test_normalize.py            # NEW (pure)
  tests/test_verify.py               # NEW (pure)
  tests/test_generate.py             # NEW (pure)
  tests/test_answer.py               # NEW (db marker, stubbed generator)
  tests/test_app.py                  # NEW (mixed: /healthz pure, /ask + /filings db marker)
  tests/fakes.py                     # MODIFY: add StubGenerator
```

---

### Task 1: Dependencies and the app skeleton

Establishes the FastAPI package and closes the CI gap: `fastapi`, `uvicorn`, and `anthropic` are currently installed in the local environment but absent from `pyproject.toml`, so the first commit importing FastAPI would turn CI red on a clean runner.

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/src/api/app.py`
- Test: `backend/tests/test_app.py`

**Interfaces:**
- Produces: `api.app.app` (a `fastapi.FastAPI` instance). Tasks 6 and 7 add routes to this same object.

- [ ] **Step 1: Add the dependencies**

In `backend/pyproject.toml`, `[project].dependencies`, append:

```toml
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "anthropic>=0.40",
```

- [ ] **Step 2: Install**

Run: `pip install -e ".[dev]"`
Expected: succeeds; `python -c "import fastapi, uvicorn, anthropic"` prints nothing.

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_app.py`:

```python
from fastapi.testclient import TestClient

from api.app import app


def test_healthz_reports_ok():
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 4: Run it to verify it fails**

Run: `pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.app'`

- [ ] **Step 5: Write the minimal app**

Create `backend/src/api/app.py`:

```python
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="EDGAR Answers", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 7: Confirm the server actually boots**

Run: `uvicorn api.app:app --port 8000` (from `backend/`), then in another shell `curl localhost:8000/healthz`. Expected: `{"status":"ok"}`. Ctrl-C to stop.

- [ ] **Step 8: Lint and commit**

```bash
python -m ruff check .
pytest -v
git add pyproject.toml src/api/app.py tests/test_app.py
git commit -m "feat: add FastAPI app skeleton with healthz endpoint"
```

---

### Task 2: Normalization with an offset map

Design §6.3 step 1. This is the foundation of verification: both the LLM's quote and the chunk's canonical text are normalized identically, but we must be able to map a match position in the *normalized* chunk back to a position in the *original* chunk, or we cannot resolve sids.

**Files:**
- Create: `backend/src/api/normalize.py`
- Test: `backend/tests/test_normalize.py`

**Interfaces:**
- Produces: `normalize(text: str) -> tuple[str, list[int]]`. The second element is the offset map: `offset_map[i]` is the index in the *original* `text` of the character that produced `normalized[i]`. `len(offset_map) == len(normalized)` always.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_normalize.py`:

```python
from api.normalize import normalize


def test_casefolds_and_collapses_whitespace():
    text, _ = normalize("Total  Net\n\tSales")
    assert text == "total net sales"


def test_straightens_curly_quotes_and_dashes():
    text, _ = normalize("“Apple’s” year—over–year")
    assert text == '"apple\'s" year-over-year'


def test_offset_map_has_one_entry_per_normalized_char():
    original = "The  “Quick” Brown"
    text, offsets = normalize(original)
    assert len(offsets) == len(text)


def test_offset_map_points_at_the_producing_character():
    original = "Net   sales"
    text, offsets = normalize(original)
    # "sales" starts at index 6 in the normalized text, index 6 in the original
    assert text == "net sales"
    assert offsets[text.index("sales")] == original.index("sales")


def test_collapsed_whitespace_run_maps_to_its_first_character():
    original = "a \n b"
    text, offsets = normalize(original)
    assert text == "a b"
    assert offsets[1] == 1  # the single space maps to the run's first char


def test_multi_character_expansion_maps_every_char_to_one_source_index():
    # NFKC expands the ligature; casefold expands the eszett.
    text, offsets = normalize("ﬁnß")
    assert text == "finss"
    assert offsets == [0, 0, 1, 2, 2]


def test_empty_text_is_stable():
    assert normalize("") == ("", [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.normalize'`

- [ ] **Step 3: Implement**

Create `backend/src/api/normalize.py`:

```python
from __future__ import annotations

import unicodedata

# Design §6.3: curly quotes -> straight, en/em dashes -> hyphen. LLMs
# routinely "improve" typography when quoting, and EDGAR HTML is full of
# both forms; without this a verbatim quote fails an exact substring match
# for reasons that have nothing to do with faithfulness.
_REPLACEMENTS = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",
    "—": "-",
    "−": "-",
}


def normalize(text: str) -> tuple[str, list[int]]:
    """Normalize for citation matching, returning a normalized->original offset map.

    `offset_map[i]` is the index in `text` of the character that produced
    `normalized[i]`. A character may produce zero characters (a whitespace
    run after the first) or several (NFKC expands ligatures, casefold expands
    the eszett), so the map is built per source character rather than derived
    from lengths.

    NFKC is applied per character, not to the whole string. That loses
    composition across character boundaries (an "e" followed by a combining
    acute stays two characters instead of becoming a single "e-acute"), which
    is the price of an exact offset map. It is safe here because both the
    quote and the chunk text pass through this same function: a sequence that
    fails to compose fails to compose identically on both sides, so the match
    still succeeds.
    """
    out: list[str] = []
    offsets: list[int] = []
    in_space_run = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_space_run:
                out.append(" ")
                offsets.append(index)
                in_space_run = True
            continue
        in_space_run = False
        piece = unicodedata.normalize("NFKC", _REPLACEMENTS.get(char, char)).casefold()
        for produced in piece:
            out.append(produced)
            offsets.append(index)
    return "".join(out), offsets
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_normalize.py -v`
Expected: 7 passed

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check .
git add src/api/normalize.py tests/test_normalize.py
git commit -m "feat: add citation text normalizer with normalized-to-original offset map"
```

---

### Task 3: Quote verification and sid resolution

Design §6.3 steps 2–3. Deterministic substring match, then map the matched span onto sentence boundaries.

The chunk-local sentence spans are reconstructed from the sentence rows using the same `" ".join(...)` the chunker used (`pipeline/chunk.py:45`), *not* from `sentences.char_start`. Those canonical-text offsets happen to work today only because `canonicalize.py` advances its cursor by `len(text) + 1` for a `"\n"` join while the chunker joins with a single space — an undocumented coincidence between two files. Step 7 pins the real invariant with a test.

**Files:**
- Modify: `backend/src/api/retrieval.py`
- Create: `backend/src/api/verify.py`, `backend/src/api/queries.py`
- Test: `backend/tests/test_verify.py`

**Interfaces:**
- Consumes: `pipeline.canonicalize.Sentence`, `api.normalize.normalize`.
- Produces:
  - `RetrievedChunk` gains a `filing_id: int` field, positioned **immediately before** `score`.
  - `Citation` frozen dataclass `(marker: int, chunk_id: int, quote: str)`.
  - `VerifiedCitation` frozen dataclass `(marker: int, chunk_id: int, quote: str, verified: bool, accession: str, sids: list[int])`.
  - `sentence_spans(sentences: list[Sentence]) -> list[tuple[int, int, int]]` — `(sid, start, end)` in chunk-text coordinates.
  - `find_quote(chunk_text: str, quote: str) -> tuple[int, int] | None` — original chunk-text offsets.
  - `resolve_sids(spans, start, end) -> list[int]`.
  - `verify_citation(citation, chunk, sentences) -> VerifiedCitation`.
  - `api.queries.load_chunk_sentences(conn, filing_id, sid_start, sid_end) -> list[Sentence]`.

- [ ] **Step 1: Add `filing_id` to retrieval**

In `backend/src/api/retrieval.py`, extend `_BASE`'s SELECT list — **append at the end** so no existing positional index shifts (`evals/__main__.py` reads `r[1]`, `r[5]`, `r[6]`):

```python
_BASE = (
    "SELECT ch.id, f.accession, f.form_type, c.ticker, ch.section,"
    " ch.sid_start, ch.sid_end, ch.text, ch.filing_id"
    " FROM chunks ch"
    " JOIN filings f ON f.id = ch.filing_id"
    " JOIN companies c ON c.cik = f.cik"
)
```

And add the matching field to `RetrievedChunk`, immediately before `score` (construction is positional — `RetrievedChunk(*rows_by_id[chunk_id], score)`):

```python
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
    filing_id: int
    score: float
```

- [ ] **Step 2: Confirm nothing regressed**

Run: `pytest tests/test_retrieval.py tests/test_evals.py -v`
Expected: existing tests pass (db-marked ones skip unless `TEST_DATABASE_URL` is set — set it and re-run to actually exercise this).

- [ ] **Step 3: Write the failing tests**

Create `backend/tests/test_verify.py`:

```python
import pytest

from api.retrieval import RetrievedChunk
from api.verify import (
    Citation,
    find_quote,
    resolve_sids,
    sentence_spans,
    verify_citation,
)
from pipeline.canonicalize import Sentence

SENTENCES = [
    Sentence(10, "item7", "Total net sales were $391.0 billion.", 0, 36),
    Sentence(11, "item7", "That is an increase of two percent.", 37, 71),
    Sentence(12, "item7", "Services set an all-time revenue record.", 72, 111),
]
CHUNK_TEXT = " ".join(s.text for s in SENTENCES)


def chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        accession="0000320193-24-000123",
        form_type="10-K",
        ticker="AAPL",
        section="item7",
        sid_start=10,
        sid_end=12,
        text=CHUNK_TEXT,
        filing_id=7,
        score=0.5,
    )


def test_sentence_spans_reconstruct_chunk_text_coordinates():
    spans = sentence_spans(SENTENCES)
    assert [sid for sid, _, _ in spans] == [10, 11, 12]
    for _, start, end in spans:
        assert CHUNK_TEXT[start:end] in [s.text for s in SENTENCES]


def test_find_quote_matches_verbatim_text():
    assert find_quote(CHUNK_TEXT, "Total net sales were $391.0 billion.") == (0, 36)


def test_find_quote_tolerates_typography_and_whitespace_drift():
    # Curly apostrophe, em dash spacing, and a collapsed newline all normalize away.
    assert find_quote(CHUNK_TEXT, "Total net   sales\nwere $391.0 billion") is not None


def test_find_quote_returns_none_for_absent_text():
    assert find_quote(CHUNK_TEXT, "Revenue declined sharply.") is None


def test_find_quote_returns_none_for_whitespace_only_quote():
    assert find_quote(CHUNK_TEXT, "   \n  ") is None


def test_resolve_sids_returns_every_overlapped_sentence():
    spans = sentence_spans(SENTENCES)
    # A span covering the tail of sid 10 and the head of sid 11.
    assert resolve_sids(spans, 30, 45) == [10, 11]


def test_resolve_sids_returns_a_single_sentence_for_an_inner_span():
    spans = sentence_spans(SENTENCES)
    assert resolve_sids(spans, 5, 12) == [10]


def test_verify_citation_marks_a_real_quote_verified_with_sids():
    result = verify_citation(
        Citation(marker=1, chunk_id=1, quote="an increase of two percent"),
        chunk(),
        SENTENCES,
    )
    assert result.verified is True
    assert result.sids == [11]
    assert result.accession == "0000320193-24-000123"


def test_verify_citation_marks_a_fabricated_quote_unverified_with_no_sids():
    result = verify_citation(
        Citation(marker=2, chunk_id=1, quote="net sales fell by half"),
        chunk(),
        SENTENCES,
    )
    assert result.verified is False
    assert result.sids == []
    assert result.marker == 2


def test_verify_citation_spanning_two_sentences_reports_both():
    result = verify_citation(
        Citation(marker=1, chunk_id=1, quote="billion. That is an increase"),
        chunk(),
        SENTENCES,
    )
    assert result.verified is True
    assert result.sids == [10, 11]


@pytest.mark.parametrize("quote", ["", "   "])
def test_verify_citation_rejects_empty_quotes(quote):
    result = verify_citation(Citation(1, 1, quote), chunk(), SENTENCES)
    assert result.verified is False
```

- [ ] **Step 4: Run to verify they fail**

Run: `pytest tests/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.verify'`

- [ ] **Step 5: Implement verification**

Create `backend/src/api/verify.py`:

```python
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

    No fuzzy matching (design §6.3) — determinism is the whole point. A quote
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


def resolve_sids(
    spans: list[tuple[int, int, int]], start: int, end: int
) -> list[int]:
    """Every sid whose span overlaps [start, end)."""
    return [
        sid
        for sid, span_start, span_end in spans
        if span_start < end and start < span_end
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
    )
```

- [ ] **Step 6: Run to verify they pass**

Run: `pytest tests/test_verify.py -v`
Expected: 11 passed

- [ ] **Step 7: Pin the chunk-text invariant with a db test**

Verification's correctness rests on `" ".join(sentence.text) == chunk.text` for real stored data. First add these to the **import block at the top** of `backend/tests/test_verify.py` — ruff's default rules include E402, so a mid-file import fails lint:

```python
import os

import psycopg

from api import queries
```

Then append the test to the end of the file:

```python
@pytest.mark.db
def test_stored_chunk_text_is_the_space_join_of_its_sentences():
    """If this fails, sentence_spans() is computing the wrong coordinates and
    every citation highlight will be silently offset."""
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT filing_id, sid_start, sid_end, text FROM chunks"
                " ORDER BY id LIMIT 25"
            )
            rows = cur.fetchall()
        if not rows:
            pytest.skip("no chunks in the test database")
        for filing_id, sid_start, sid_end, text in rows:
            sentences = queries.load_chunk_sentences(
                conn, filing_id, sid_start, sid_end
            )
            assert " ".join(s.text for s in sentences) == text
```

- [ ] **Step 8: Implement the query module**

Create `backend/src/api/queries.py`:

```python
from __future__ import annotations

import psycopg

from pipeline.canonicalize import Sentence


def load_chunk_sentences(
    conn: psycopg.Connection, filing_id: int, sid_start: int, sid_end: int
) -> list[Sentence]:
    """The sentences a chunk covers, in document order."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sid, section, text, char_start, char_end FROM sentences"
            " WHERE filing_id = %s AND sid BETWEEN %s AND %s ORDER BY sid",
            (filing_id, sid_start, sid_end),
        )
        return [Sentence(*row) for row in cur.fetchall()]
```

- [ ] **Step 9: Run the full suite**

Run: `pytest -v` (with `TEST_DATABASE_URL` set, so the db test actually runs)
Expected: all pass, including `test_stored_chunk_text_is_the_space_join_of_its_sentences`.

- [ ] **Step 10: Lint and commit**

```bash
python -m ruff check .
git add src/api/retrieval.py src/api/verify.py src/api/queries.py tests/test_verify.py
git commit -m "feat: verify citation quotes against chunk text and resolve them to sids"
```

---

### Task 4: Prompt, generator protocol, and response parsing

Design §6.2. Three separable pieces: how we ask, how we abstract the LLM for testing, and how we split the streamed response into prose and the trailing JSON block.

**Files:**
- Create: `backend/src/api/generate.py`
- Modify: `backend/tests/fakes.py`
- Test: `backend/tests/test_generate.py`

**Interfaces:**
- Consumes: `api.retrieval.RetrievedChunk`, `api.verify.Citation`.
- Produces:
  - `Generator` protocol with `stream(system: str, user: str) -> Iterator[str]`.
  - `AnthropicGenerator(model=MODEL, max_tokens=MAX_OUTPUT_TOKENS)`.
  - `SYSTEM_PROMPT: str`, `build_user_message(question, chunks) -> str`.
  - `AnswerSplitter` — `feed(delta) -> str`, `finish() -> str`, `.raw` property.
  - `parse_citations(raw: str) -> list[Citation] | None` (`None` means unparseable → caller retries once).
  - `MODEL = "claude-haiku-4-5"`, `MAX_OUTPUT_TOKENS = 1500`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_generate.py`:

```python
from api.generate import (
    AnswerSplitter,
    build_user_message,
    parse_citations,
)
from api.retrieval import RetrievedChunk


def chunk(chunk_id: int, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        accession="0000320193-24-000123",
        form_type="10-K",
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
    emitted = "".join(
        splitter.feed(part)
        for part in ["Net sales ", "rose [1].\n\n", "```json\n", '{"citations": []}', "\n```"]
    )
    emitted += splitter.finish()
    assert emitted == "Net sales rose [1].\n\n"
    assert "```json" in splitter.raw


def test_splitter_never_emits_a_partial_fence_opener():
    splitter = AnswerSplitter()
    # A backtick arrives that turns out to be the start of the fence.
    first = splitter.feed("Answer.\n\n`")
    assert "`" not in first


def test_splitter_with_no_fence_emits_everything_on_finish():
    splitter = AnswerSplitter()
    emitted = splitter.feed("Just prose, no citations.") + splitter.finish()
    assert emitted == "Just prose, no citations."


def test_parse_citations_reads_the_fenced_block():
    raw = 'Answer [1].\n\n```json\n{"citations": [{"marker": 1, "chunk_id": 8, "quote": "hi"}]}\n```'
    citations = parse_citations(raw)
    assert len(citations) == 1
    assert citations[0].marker == 1
    assert citations[0].chunk_id == 8
    assert citations[0].quote == "hi"


def test_parse_citations_accepts_a_bare_json_fence():
    raw = 'Answer.\n```\n{"citations": []}\n```'
    assert parse_citations(raw) == []


def test_parse_citations_returns_none_when_no_block_is_present():
    assert parse_citations("Answer with no block at all.") is None


def test_parse_citations_returns_none_on_malformed_json():
    assert parse_citations('Answer.\n```json\n{"citations": [oops}\n```') is None


def test_parse_citations_skips_entries_missing_required_fields():
    raw = '```json\n{"citations": [{"marker": 1}, {"marker": 2, "chunk_id": 3, "quote": "q"}]}\n```'
    citations = parse_citations(raw)
    assert [c.marker for c in citations] == [2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_generate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.generate'`

- [ ] **Step 3: Implement**

Create `backend/src/api/generate.py`:

```python
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterator, Protocol

from .retrieval import RetrievedChunk
from .verify import Citation

# Design §2: low-volume, pennies per answer. Small local models are unreliable
# at verbatim structured quoting, which is the entire product.
MODEL = "claude-haiku-4-5"
# Design §11: a hard output cap keeps per-answer spend bounded.
MAX_OUTPUT_TOKENS = 1500
FENCE = "```"

SYSTEM_PROMPT = """You answer questions about SEC filings using only the excerpts provided.

Rules:
1. Answer ONLY from the provided excerpts. If they do not contain the answer, say
   so plainly and stop — do not fall back on general knowledge about the company.
2. Attach an inline marker to every factual claim: [1], [2], and so on, numbered
   from 1 in the order they first appear.
3. After the answer, emit a fenced JSON block and nothing after it:

```json
{"citations": [{"marker": 1, "chunk_id": 8123, "quote": "verbatim text from that chunk"}]}
```

Every quote must be copied character-for-character from the excerpt whose
chunk_id you cite, and must be 300 characters or fewer. Do not paraphrase,
reformat, join sentences with an ellipsis, or fix typography inside a quote —
quotes are checked against the source text and a mismatch is shown to the user
as unverified. Prefer a short exact quote over a long approximate one."""


class Generator(Protocol):
    """The LLM, narrowed to the one thing the query path needs."""

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield answer text deltas in order."""
        ...


@dataclass
class AnthropicGenerator:
    model: str = MODEL
    max_tokens: int = MAX_OUTPUT_TOKENS
    api_key: str | None = None

    def stream(self, system: str, user: str) -> Iterator[str]:
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key or os.environ["ANTHROPIC_API_KEY"]
        )
        # No `thinking` (Haiku 4.5 does not do adaptive thinking, and omitting
        # the parameter means none) and no `output_config.effort` (rejected on
        # Haiku 4.5). temperature=0 so the eval is reproducible run to run.
        with client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            yield from stream.text_stream


def build_user_message(question: str, chunks: list[RetrievedChunk]) -> str:
    blocks = [
        f"[chunk_id={c.chunk_id}] {c.ticker} {c.form_type} {c.accession} ({c.section})\n{c.text}"
        for c in chunks
    ]
    excerpts = "\n\n".join(blocks) if blocks else "(no excerpts were retrieved)"
    return f"Excerpts:\n\n{excerpts}\n\nQuestion: {question}"


class AnswerSplitter:
    """Splits a streamed response into user-visible prose and a trailing block.

    The answer streams token-by-token while the JSON block must not — it is
    machinery, not prose. Until the fence appears we hold back the last
    len(FENCE) - 1 characters so a fence opener can never be emitted one
    backtick at a time; once it appears, emission stops there for good.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._emitted = 0
        self._fence_at: int | None = None

    @property
    def raw(self) -> str:
        return self._buffer

    def feed(self, delta: str) -> str:
        self._buffer += delta
        if self._fence_at is None:
            index = self._buffer.find(FENCE)
            if index != -1:
                self._fence_at = index
        limit = (
            self._fence_at
            if self._fence_at is not None
            else max(0, len(self._buffer) - (len(FENCE) - 1))
        )
        return self._take(limit)

    def finish(self) -> str:
        limit = self._fence_at if self._fence_at is not None else len(self._buffer)
        return self._take(limit)

    def _take(self, limit: int) -> str:
        if limit <= self._emitted:
            return ""
        out = self._buffer[self._emitted : limit]
        self._emitted = limit
        return out


_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_citations(raw: str) -> list[Citation] | None:
    """Parse the trailing JSON block. None means unparseable — retry, then degrade."""
    match = _BLOCK.search(raw)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    entries = payload.get("citations")
    if not isinstance(entries, list):
        return None
    citations = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        marker, chunk_id, quote = (
            entry.get("marker"),
            entry.get("chunk_id"),
            entry.get("quote"),
        )
        if isinstance(marker, int) and isinstance(chunk_id, int) and isinstance(quote, str):
            citations.append(Citation(marker=marker, chunk_id=chunk_id, quote=quote))
    return citations
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_generate.py -v`
Expected: 9 passed

- [ ] **Step 5: Add the stub generator**

Append to `backend/tests/fakes.py`:

```python
class StubGenerator:
    """Replays a canned response in small deltas — exercises the streaming
    split without an API key or a cent of spend (design §9)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def stream(self, system, user):
        self.calls += 1
        index = min(self.calls - 1, len(self.responses) - 1)
        text = self.responses[index]
        for start in range(0, len(text), 7):
            yield text[start : start + 7]
```

- [ ] **Step 6: Lint and commit**

```bash
python -m ruff check .
pytest -v
git add src/api/generate.py tests/test_generate.py tests/fakes.py
git commit -m "feat: add Haiku generator, prompt contract, and streamed answer splitter"
```

---

### Task 5: The query path

Wires retrieve → generate → verify into one HTTP-free generator. Design §6 end to end, plus the §10 error rows: unparseable output retries once then degrades; an LLM outage becomes an `error` event.

**Files:**
- Create: `backend/src/api/answer.py`
- Test: `backend/tests/test_answer.py`

**Interfaces:**
- Consumes: `api.retrieval.retrieve`, `api.generate.*`, `api.verify.*`, `api.queries.load_chunk_sentences`.
- Produces: `AnswerEvent` frozen dataclass `(name: str, data: dict)` where `name` is one of `token` / `citation` / `done` / `error`; `answer_stream(conn, embedder, generator, question, *, ticker=None, form_type=None, k_final=8) -> Iterator[AnswerEvent]`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_answer.py`:

```python
import os
from datetime import date

import psycopg
import pytest

from api.answer import answer_stream
from pipeline import db, store
from pipeline.canonicalize import CanonicalFiling, Sentence
from pipeline.chunk import Chunk
from pipeline.companies import Company
from pipeline.edgar import FilingRef
from tests.fakes import FakeEmbedder, StubGenerator

COMPANY = Company(999999005, "TSTE", "Test Co E")
ACCESSION = "9999999999-24-000005"
SENTENCES = [
    "Total net sales were 391.0 billion dollars in fiscal 2024.",
    "Services revenue reached an all-time record.",
]
CHUNK_TEXT = " ".join(SENTENCES)


@pytest.fixture()
def seeded_conn():
    conn = psycopg.connect(os.environ["TEST_DATABASE_URL"])
    db.migrate(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks")
        cur.execute("DELETE FROM sentences")
        cur.execute("DELETE FROM filings")
        cur.execute("DELETE FROM companies")
    conn.commit()
    sentences = []
    cursor = 0
    for sid, text in enumerate(SENTENCES):
        sentences.append(Sentence(sid, "item7", text, cursor, cursor + len(text)))
        cursor += len(text) + 1
    canonical = CanonicalFiling(
        "\n".join(SENTENCES),
        sentences,
        "".join(f'<p><span data-sid="{s.sid}">{s.text}</span></p>' for s in sentences),
    )
    ref = FilingRef(
        cik=COMPANY.cik,
        accession=ACCESSION,
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        period_end=date(2024, 9, 28),
        primary_document="t.htm",
    )
    filing_id = store.store_filing(conn, COMPANY, ref, canonical)
    store.store_chunks(
        conn,
        filing_id,
        [Chunk("item7", 0, 1, CHUNK_TEXT, 20)],
        FakeEmbedder().embed_texts([CHUNK_TEXT]),
    )
    conn.commit()
    yield conn
    conn.close()


def response_with(quote: str, chunk_id_source) -> str:
    return (
        "Total net sales were $391.0 billion [1].\n\n"
        "```json\n"
        '{"citations": [{"marker": 1, "chunk_id": CHUNK_ID, "quote": "QUOTE"}]}\n'
        "```"
    ).replace("CHUNK_ID", str(chunk_id_source)).replace("QUOTE", quote)


def chunk_id_of(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM chunks LIMIT 1")
        return cur.fetchone()[0]


def collect(conn, *responses):
    generator = StubGenerator(*responses)
    events = list(
        answer_stream(conn, FakeEmbedder(), generator, "What were total net sales?")
    )
    return events, generator


@pytest.mark.db
def test_streams_tokens_then_a_verified_citation_then_done(seeded_conn):
    quote = "Total net sales were 391.0 billion dollars"
    events, _ = collect(seeded_conn, response_with(quote, chunk_id_of(seeded_conn)))
    names = [e.name for e in events]
    assert names[0] == "token"
    assert names[-1] == "done"
    answer = "".join(e.data["text"] for e in events if e.name == "token")
    assert "391.0 billion" in answer
    assert "```" not in answer
    citations = [e for e in events if e.name == "citation"]
    assert len(citations) == 1
    assert citations[0].data["verified"] is True
    assert citations[0].data["sids"] == [0]
    assert citations[0].data["accession"] == ACCESSION


@pytest.mark.db
def test_fabricated_quote_is_reported_unverified_not_dropped(seeded_conn):
    events, _ = collect(
        seeded_conn,
        response_with("Net sales collapsed by half", chunk_id_of(seeded_conn)),
    )
    citations = [e for e in events if e.name == "citation"]
    assert len(citations) == 1
    assert citations[0].data["verified"] is False
    assert citations[0].data["sids"] == []


@pytest.mark.db
def test_citation_naming_an_unretrieved_chunk_is_unverified(seeded_conn):
    events, _ = collect(seeded_conn, response_with("Total net sales", 987654))
    citations = [e for e in events if e.name == "citation"]
    assert citations[0].data["verified"] is False


@pytest.mark.db
def test_unparseable_block_retries_once_then_succeeds(seeded_conn):
    good = response_with("Services revenue reached", chunk_id_of(seeded_conn))
    events, generator = collect(seeded_conn, "No block here at all.", good)
    assert generator.calls == 2
    assert [e for e in events if e.name == "citation"]
    assert next(e for e in events if e.name == "done").data["citations_total"] == 1


@pytest.mark.db
def test_unparseable_block_twice_degrades_without_erroring(seeded_conn):
    events, generator = collect(seeded_conn, "Nope.", "Still nope.")
    assert generator.calls == 2
    done = next(e for e in events if e.name == "done")
    assert done.data["citations_total"] == 0
    assert done.data["unverified_answer"] is True
    assert not [e for e in events if e.name == "error"]


@pytest.mark.db
def test_done_event_carries_the_counts(seeded_conn):
    quote = "Services revenue reached an all-time record."
    events, _ = collect(seeded_conn, response_with(quote, chunk_id_of(seeded_conn)))
    done = next(e for e in events if e.name == "done").data
    assert done["chunks_retrieved"] == 1
    assert done["citations_total"] == 1
    assert done["citations_verified"] == 1


@pytest.mark.db
def test_generator_failure_becomes_an_error_event(seeded_conn):
    class Boom:
        def stream(self, system, user):
            raise RuntimeError("upstream is down")
            yield  # pragma: no cover

    events = list(
        answer_stream(seeded_conn, FakeEmbedder(), Boom(), "What were net sales?")
    )
    assert events[-1].name == "error"
    assert "message" in events[-1].data
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_answer.py -v` (with `TEST_DATABASE_URL` set)
Expected: FAIL — `ModuleNotFoundError: No module named 'api.answer'`

- [ ] **Step 3: Implement**

Create `backend/src/api/answer.py`:

```python
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
            conn, embedder, question, k_final=k_final, ticker=ticker, form_type=form_type
        )
        user_message = build_user_message(question, chunks)

        # Design §6.2: one retry if the trailing block does not parse, then
        # render the answer with an "unverified answer" notice rather than
        # failing the request outright.
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
            # The retry's prose is discarded: the first attempt's answer has
            # already streamed to the client, and replacing it mid-stream would
            # be worse than keeping it. We are re-rolling only for the block.

        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        verified: list[VerifiedCitation] = []
        for citation in citations or []:
            chunk = by_id.get(citation.chunk_id)
            if chunk is None:
                # The model cited a chunk it was never shown. Unverifiable by
                # construction — surface it rather than dropping it.
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_answer.py -v`
Expected: 7 passed

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check .
pytest -v
git add src/api/answer.py tests/test_answer.py
git commit -m "feat: add answer query path with retry and citation verification"
```

---

### Task 6: SSE and `POST /ask`

Design §6.4. FastAPI becomes a thin adapter over Task 5's generator.

**Files:**
- Modify: `backend/src/api/app.py`, `backend/tests/test_app.py`

**Interfaces:**
- Consumes: `api.answer.answer_stream`, `pipeline.db.connect`, `pipeline.embed.Embedder`.
- Produces: `sse(event: AnswerEvent) -> str`; `get_generator()` and `get_embedder()` FastAPI dependencies (overridable in tests via `app.dependency_overrides`); `POST /ask`.

- [ ] **Step 1: Write the failing tests**

Add these to the **import block at the top** of `backend/tests/test_app.py`, alongside the existing `TestClient` and `app` imports (ruff's E402 rejects mid-file imports). The `seeded_conn` fixture is reused by importing it — pytest picks it up as a fixture, and the `noqa: F401` is needed because ruff otherwise sees it as unused:

```python
import json
import os

import pytest

from api import app as app_module
from tests.fakes import FakeEmbedder, StubGenerator
from tests.test_answer import ACCESSION, chunk_id_of, response_with, seeded_conn  # noqa: F401
```

Then append the tests to the end of the file:

```python
def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture()
def stubbed_client(seeded_conn):  # noqa: F811
    quote = "Total net sales were 391.0 billion dollars"
    generator = StubGenerator(response_with(quote, chunk_id_of(seeded_conn)))
    app_module.app.dependency_overrides[app_module.get_generator] = lambda: generator
    app_module.app.dependency_overrides[app_module.get_embedder] = lambda: FakeEmbedder()
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    with TestClient(app_module.app) as client:
        yield client
    app_module.app.dependency_overrides.clear()


@pytest.mark.db
def test_ask_streams_sse_events_in_order(stubbed_client):
    response = stubbed_client.post("/ask", json={"question": "What were net sales?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "token"
    assert "citation" in names
    assert names[-1] == "done"


@pytest.mark.db
def test_ask_citation_event_matches_the_design_shape(stubbed_client):
    response = stubbed_client.post("/ask", json={"question": "What were net sales?"})
    citation = next(data for name, data in parse_sse(response.text) if name == "citation")
    assert set(citation) == {"marker", "verified", "accession", "sids", "quote"}
    assert citation["verified"] is True
    assert citation["accession"] == ACCESSION


@pytest.mark.db
def test_ask_passes_filters_through(stubbed_client):
    response = stubbed_client.post(
        "/ask",
        json={"question": "What were net sales?", "filters": {"ticker": "NOPE"}},
    )
    done = next(data for name, data in parse_sse(response.text) if name == "done")
    assert done["chunks_retrieved"] == 0


def test_ask_rejects_an_empty_question():
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "   "})
    assert response.status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_app.py -v`
Expected: FAIL — `AttributeError: module 'api.app' has no attribute 'get_generator'`

- [ ] **Step 3: Implement**

Rewrite `backend/src/api/app.py`:

```python
from __future__ import annotations

import json
from functools import lru_cache
from typing import Iterator

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from pipeline import db
from pipeline.embed import Embedder

from .answer import AnswerEvent, answer_stream
from .generate import AnthropicGenerator, Generator

app = FastAPI(title="EDGAR Answers", version="0.1.0")


class Filters(BaseModel):
    ticker: str | None = None
    form_type: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    filters: Filters = Field(default_factory=Filters)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()


@lru_cache(maxsize=1)
def _embedder() -> Embedder:
    """One process-wide embedder: loading the ONNX weights per request would
    dominate latency."""
    return Embedder()


def get_embedder() -> Embedder:
    return _embedder()


def get_generator() -> Generator:
    return AnthropicGenerator()


def sse(event: AnswerEvent) -> str:
    payload = json.dumps(event.data, separators=(",", ":"))
    return f"event: {event.name}\ndata: {payload}\n\n"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask")
def ask(
    request: AskRequest,
    embedder: Embedder = Depends(get_embedder),
    generator: Generator = Depends(get_generator),
) -> StreamingResponse:
    def events() -> Iterator[str]:
        # A connection per request; pooling is a Phase 5 concern.
        with db.connect() as conn:
            for event in answer_stream(
                conn,
                embedder,
                generator,
                request.question,
                ticker=request.filters.ticker,
                form_type=request.filters.form_type,
            ):
                yield sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: all pass (the non-db `test_healthz_...` and `test_ask_rejects_an_empty_question` run unconditionally).

- [ ] **Step 5: Live smoke test — the first real spend**

With `DATABASE_URL` and `ANTHROPIC_API_KEY` set and the AAPL corpus loaded, run `uvicorn api.app:app --port 8000` and:

```bash
curl -N -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"What were Apple total net sales in fiscal 2024?","filters":{"ticker":"AAPL"}}'
```

Expected: `token` events stream visibly one at a time (not one buffered dump), no backticks in the prose, then at least one `citation` event with `"verified": true` and a non-empty `sids` array, then `done`. **This is the Phase 3 exit criterion — "live answers cite verified quotes."** Cost is a fraction of a cent.

If citations come back `verified: false`, read the actual quote out of the event and diff it against the chunk text before touching the normalizer — the usual cause is the model paraphrasing or joining sentences, which is a prompt problem, not a matching problem.

- [ ] **Step 6: Lint and commit**

```bash
python -m ruff check .
pytest -v
git add src/api/app.py tests/test_app.py
git commit -m "feat: stream verified answers over SSE from the ask endpoint"
```

---

### Task 7: Filing and company endpoints

Design §6.5. Small, and Phase 4's viewer cannot be built without `/filings/{accession}` — landing them here keeps §6 complete.

**Files:**
- Modify: `backend/src/api/queries.py`, `backend/src/api/app.py`, `backend/tests/test_app.py`

**Interfaces:**
- Produces: `queries.load_filing(conn, accession) -> dict | None`; `queries.load_companies(conn) -> list[dict]`; `GET /filings/{accession}`, `GET /companies`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_app.py`:

```python
@pytest.mark.db
def test_filings_endpoint_returns_viewer_html_and_metadata(stubbed_client):
    response = stubbed_client.get(f"/filings/{ACCESSION}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "accession",
        "viewer_html",
        "ticker",
        "form_type",
        "filing_date",
        "period_end",
    }
    assert 'data-sid="0"' in body["viewer_html"]
    assert body["ticker"] == "TSTE"


@pytest.mark.db
def test_filings_endpoint_404s_for_an_unknown_accession(stubbed_client):
    assert stubbed_client.get("/filings/0000000000-00-000000").status_code == 404


@pytest.mark.db
def test_companies_endpoint_lists_companies_with_filings(stubbed_client):
    body = stubbed_client.get("/companies").json()
    assert {"cik": 999999005, "ticker": "TSTE", "name": "Test Co E", "filings": 1} in body
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_app.py -v`
Expected: FAIL — 404 on `/filings/...` (route not registered).

- [ ] **Step 3: Add the queries**

Append to `backend/src/api/queries.py`:

```python
def load_filing(conn: psycopg.Connection, accession: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT f.accession, f.viewer_html, c.ticker, f.form_type,"
            " f.filing_date, f.period_end"
            " FROM filings f JOIN companies c ON c.cik = f.cik"
            " WHERE f.accession = %s",
            (accession,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "accession": row[0],
        "viewer_html": row[1],
        "ticker": row[2],
        "form_type": row[3],
        "filing_date": row[4].isoformat(),
        "period_end": row[5].isoformat() if row[5] else None,
    }


def load_companies(conn: psycopg.Connection) -> list[dict]:
    """Only companies that actually have filings — the filter UI should not
    offer a ticker that returns nothing."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.cik, c.ticker, c.name, count(f.id) FROM companies c"
            " JOIN filings f ON f.cik = c.cik"
            " GROUP BY c.cik, c.ticker, c.name ORDER BY c.ticker"
        )
        return [
            {"cik": cik, "ticker": ticker, "name": name, "filings": count}
            for cik, ticker, name, count in cur.fetchall()
        ]
```

- [ ] **Step 4: Add the routes**

Append to `backend/src/api/app.py`:

```python
@app.get("/filings/{accession}")
def get_filing(accession: str) -> dict:
    with db.connect() as conn:
        filing = queries.load_filing(conn, accession)
    if filing is None:
        raise HTTPException(status_code=404, detail="filing not found")
    return filing


@app.get("/companies")
def get_companies() -> list[dict]:
    with db.connect() as conn:
        return queries.load_companies(conn)
```

Add the imports at the top of the file: `from fastapi import Depends, FastAPI, HTTPException` and `from . import queries`.

- [ ] **Step 5: Run to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: all pass.

- [ ] **Step 6: Lint and commit**

```bash
python -m ruff check .
pytest -v
git add src/api/queries.py src/api/app.py tests/test_app.py
git commit -m "feat: add filing viewer and company list endpoints"
```

---

### Task 8: Faithfulness eval

Design §8.2 and the `evals/__main__.py:11` promise that "faithfulness eval arrives in Phase 3." Reuses the golden set from Phase 2 — the questions already pin answers to sids, so we can score citation accuracy, not just verification rate.

**Files:**
- Create: `backend/evals/faithfulness.py`
- Modify: `backend/evals/__main__.py`
- Test: `backend/tests/test_evals.py`

**Interfaces:**
- Consumes: `evals.harness.GoldenQuestion`, `api.answer.answer_stream`.
- Produces: `run_faithfulness_eval(conn, embedder, generator, questions) -> dict` with keys `questions`, `answered_rate`, `citations_total`, `verified_rate`, `gold_sid_hit_rate`, `unverified_answers`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_evals.py`:

```python
from evals.faithfulness import run_faithfulness_eval
from evals.harness import GoldenQuestion


def test_faithfulness_metrics_are_computed_from_the_event_stream(monkeypatch):
    question = GoldenQuestion(
        id="q001",
        question="What were total net sales?",
        ticker="AAPL",
        accession="0000320193-24-000123",
        section="item7",
        gold_sids=[41],
    )
    events = [
        ("token", {"text": "Net sales rose [1]."}),
        (
            "citation",
            {
                "marker": 1,
                "verified": True,
                "accession": "0000320193-24-000123",
                "sids": [41, 42],
                "quote": "q",
            },
        ),
        (
            "citation",
            {"marker": 2, "verified": False, "accession": "", "sids": [], "quote": "x"},
        ),
        (
            "done",
            {
                "chunks_retrieved": 8,
                "citations_total": 2,
                "citations_verified": 1,
                "unverified_answer": False,
            },
        ),
    ]

    class FakeEvent:
        def __init__(self, name, data):
            self.name, self.data = name, data

    monkeypatch.setattr(
        "evals.faithfulness.answer_stream",
        lambda *a, **k: (FakeEvent(n, d) for n, d in events),
    )

    metrics = run_faithfulness_eval(None, None, None, [question])
    assert metrics["questions"] == 1
    assert metrics["citations_total"] == 2
    assert metrics["verified_rate"] == 0.5
    assert metrics["gold_sid_hit_rate"] == 1.0
    assert metrics["answered_rate"] == 1.0
    assert metrics["unverified_answers"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_evals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.faithfulness'`

- [ ] **Step 3: Implement**

Create `backend/evals/faithfulness.py`:

```python
from __future__ import annotations

from api.answer import answer_stream

from .harness import GoldenQuestion

# A refusal is a correct answer when the corpus does not cover the question
# (design §10), so "answered" is measured, never assumed to be the goal.
_REFUSALS = ("do not contain", "does not contain", "not covered", "cannot answer")


def run_faithfulness_eval(
    conn, embedder, generator, questions: list[GoldenQuestion]
) -> dict:
    """Full /ask path per golden question: % citations verified, % answered,
    and whether verified citations actually land on the gold sentences."""
    answered = 0
    unverified_answers = 0
    total = 0
    verified = 0
    gold_hits = 0
    for question in questions:
        text_parts: list[str] = []
        citations: list[dict] = []
        for event in answer_stream(
            conn,
            embedder,
            generator,
            question.question,
            ticker=question.ticker,
        ):
            if event.name == "token":
                text_parts.append(event.data["text"])
            elif event.name == "citation":
                citations.append(event.data)
            elif event.name == "done":
                unverified_answers += int(event.data["unverified_answer"])
            elif event.name == "error":
                citations = []
                break
        answer = "".join(text_parts).lower()
        if answer and not any(phrase in answer for phrase in _REFUSALS):
            answered += 1
        total += len(citations)
        verified += sum(c["verified"] for c in citations)
        gold_hits += any(
            c["verified"]
            and c["accession"] == question.accession
            and set(c["sids"]) & set(question.gold_sids)
            for c in citations
        )
    n = len(questions) or 1
    return {
        "questions": len(questions),
        "answered_rate": round(answered / n, 4),
        "citations_total": total,
        "verified_rate": round(verified / total, 4) if total else 0.0,
        "gold_sid_hit_rate": round(gold_hits / n, 4),
        "unverified_answers": unverified_answers,
    }
```

- [ ] **Step 4: Wire up the CLI**

In `backend/evals/__main__.py`, replace the `if not args.retrieval_only:` note block in `cmd_run` so the full path actually runs. The function becomes:

```python
def cmd_run(args) -> None:
    questions = harness.load_golden()
    with db.connect() as conn:
        if args.debug:
            from api.retrieval import lexical_search, vector_search

            embedder = Embedder()
            for question in questions:
                vec = vector_search(conn, embedder.embed_query(question.question), k=5)
                lex = lexical_search(conn, question.question, k=5)
                print(f"\n{question.id}: {question.question}")
                print("  vector:", [(r[1], r[5], r[6]) for r in vec])
                print("  lexical:", [(r[1], r[5], r[6]) for r in lex])
            return
        embedder = Embedder()
        metrics = harness.run_retrieval_eval(conn, embedder, questions)
        if not args.retrieval_only:
            from api.generate import AnthropicGenerator

            from . import faithfulness

            metrics |= faithfulness.run_faithfulness_eval(
                conn, embedder, AnthropicGenerator(), questions
            )
    for key, value in metrics.items():
        print(f"{key}: {value}")
    harness.append_results(harness.RESULTS_PATH, metrics)
    print(f"appended to {harness.RESULTS_PATH}")
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_evals.py -v`
Expected: all pass.

Also confirm the retrieval-only path did not regress:

Run: `python -m evals run --retrieval-only`
Expected: recall@10 = 1.0, unchanged from the last `results.jsonl` line.

- [ ] **Step 6: Run the real faithfulness eval**

Commit everything first so `git_dirty` is `false` in the recorded result — an eval run against a dirty tree is not reproducible from its sha, which is exactly why `harness.append_results` records the flag.

```bash
python -m ruff check .
pytest -v
git add evals/faithfulness.py evals/__main__.py tests/test_evals.py
git commit -m "feat: add faithfulness eval over the full ask path"
python -m evals run
```

Expected: 16 questions, a handful of cents. Record whatever comes out — **do not tune the prompt to make the number look better before committing the first honest baseline.** Design §12 sets ≥90% citations verified as the *Phase 5* bar, not this one.

- [ ] **Step 7: Commit the eval result**

```bash
git add evals/results.jsonl
git commit -m "chore: record first faithfulness eval baseline"
```

---

## Wrap-up

- [ ] **Update `CLAUDE.md`'s "Current state" section:** Phase 3 complete on `phase3-ask`; note the faithfulness numbers and that `frontend/` is still a placeholder. Phase 4 is next.
- [ ] **Amend `docs/design.md`** while the context is fresh — §6.1's `websearch_to_tsquery` and §4.3's ~600 tokens are both stale relative to the shipped code, and §6 should note that the `year` filter is deferred. design.md is the authoritative spec; letting it drift defeats the point.
- [ ] **Open the PR** for `phase3-ask` → `main`.

## Verification

The phase is done when all of these hold:

1. `python -m ruff check .` clean and `pytest -v` green with `TEST_DATABASE_URL` set (no db tests skipped).
2. `pytest -v` green with `TEST_DATABASE_URL` unset — the db tests skip, nothing errors. This is what CI runs.
3. `uvicorn api.app:app` boots; `curl localhost:8000/healthz` returns `{"status":"ok"}`.
4. A live `curl -N -X POST localhost:8000/ask ...` against the AAPL corpus streams `token` events incrementally, then at least one `citation` with `"verified": true` and non-empty `sids`, then `done`. (Phase 3 exit criterion.)
5. `GET /filings/{accession}` returns viewer HTML containing `data-sid=` attributes matching sids from step 4 — this is the end-to-end proof that click-to-highlight will work in Phase 4.
6. `python -m evals run --retrieval-only` still reports recall@10 = 1.0.
7. `evals/results.jsonl` has a new line with `git_dirty: false` carrying the faithfulness baseline.
