# EDGAR Answers Phase 2: Chunk → Embed → Hybrid Retrieval → Retrieval Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chunks with embeddings in Postgres for every ingested filing, a hybrid (vector + full-text, RRF-fused) retrieval function, and a retrieval eval harness scoring recall@k against a hand-authored golden set — exiting at recall@10 ≥ 0.8 on ~15 real AAPL questions (design §12, Phase 2).

**Architecture:** Chunking and embedding are pipeline stages (`backend/src/pipeline/`) run via a new `python -m pipeline embed` CLI subcommand that backfills any filing without chunks. Retrieval lives in a new `backend/src/api/` package (design §3: retrieval is the API's job — FastAPI itself arrives in Phase 3). The eval harness is a separate `backend/evals/` package run via `python -m evals run`.

**Tech Stack:** Everything from Phase 0–1 plus fastembed (ONNX bge-small-en-v1.5), tiktoken (chunk sizing), PyYAML (golden set).

**Spec:** `docs/design.md` §4.3–4.4 (chunk/embed), §6.1 (hybrid retrieval), §8 (evals), §12 (Phase 2 exit criterion). Prior work: `docs/superpowers/plans/2026-07-19-phase0-1-ingestion.md` (Tasks 1–7, complete).

## Prerequisites

- The Phase 0–1 code must be present. If the `phase0-1-ingestion` PR has been merged, branch from `main`; otherwise branch from `phase0-1-ingestion`. Create branch `phase2-retrieval`.
- Postgres running (`docker compose up -d` at repo root) with the 12 AAPL filings ingested. If the DB is fresh, re-run: `python -m pipeline migrate` then `python -m pipeline ingest --ticker AAPL` (with `DATABASE_URL` and `EDGAR_USER_AGENT` set — see Phase 0–1 plan Task 7 step 12).
- Test database `edgar_answers_test` exists (Phase 0–1 plan Task 2 step 4).

## Global Constraints

- Python 3.11+; run all backend commands from `backend/` (`pip install -e ".[dev]"` after editing pyproject).
- `ruff check .` and `pytest -v` must pass before every commit (matches CI).
- Commit messages: imperative mood, **no AI attribution of any kind** — no Co-Authored-By, no Claude-Session trailers, no tool names.
- DB-dependent tests carry `@pytest.mark.db` (skip without `TEST_DATABASE_URL`); the one real-model embedding test carries `@pytest.mark.slow` (skip without `RUN_SLOW_TESTS=1`). CI runs neither — that's intentional.
- **Design amendment (chunk size):** design §4.3 says ~600 tokens, but `bge-small-en-v1.5` truncates input at 512 of its own tokens — a 600-token chunk would have its tail silently excluded from vector search. This plan targets **450 tiktoken tokens** per chunk to stay safely under that limit. Do not "restore" 600.
- Embedding dimension stays `vector(384)` (already in migration 001 — **no new migration is needed in this phase**).
- The first real-model run downloads ~100 MB of ONNX weights to the local fastembed cache (one-time, needs network).

## File Structure

```
backend/
  pyproject.toml                     # MODIFY: add fastembed, tiktoken, pyyaml; slow marker; pythonpath
  src/pipeline/chunk.py              # NEW: Chunk dataclass, chunk_sentences()
  src/pipeline/embed.py              # NEW: Embedder (lazy fastembed wrapper), QUERY_PREFIX
  src/pipeline/store.py              # MODIFY: to_pgvector, load_sentences, store_chunks, filing_ids_without_chunks
  src/pipeline/ingest.py             # MODIFY: add embed_filings() stage
  src/pipeline/__main__.py           # MODIFY: add `embed` subcommand
  src/api/__init__.py                # NEW: empty package marker
  src/api/retrieval.py               # NEW: vector_search, lexical_search, retrieve (RRF)
  evals/__init__.py                  # NEW: empty package marker
  evals/__main__.py                  # NEW: CLI (run / verify subcommands)
  evals/harness.py                   # NEW: GoldenQuestion, load_golden, hit, run_retrieval_eval, append_results
  evals/golden.yaml                  # NEW: ≥15 hand-authored questions (Task 6)
  evals/results.jsonl                # NEW: first committed eval result (Task 6)
  tests/conftest.py                  # MODIFY: add slow-marker auto-skip
  tests/test_chunk.py                # NEW
  tests/test_embed.py                # NEW
  tests/test_store_chunks.py         # NEW (db marker)
  tests/test_retrieval.py            # NEW (db marker)
  tests/test_evals.py                # NEW (unit + one db test)
  tests/fakes.py                     # NEW: FakeEmbedder shared by db tests
```

---

### Task 1: Chunker

**Files:**
- Modify: `backend/pyproject.toml` (add `tiktoken`)
- Create: `backend/src/pipeline/chunk.py`
- Test: `backend/tests/test_chunk.py`

**Interfaces:**
- Consumes: `Sentence(sid, section, text, char_start, char_end)` from `pipeline.canonicalize` (Phase 0–1).
- Produces: `Chunk` frozen dataclass `(section: str, sid_start: int, sid_end: int, text: str, token_count: int)`; `chunk_sentences(sentences: list[Sentence], *, max_tokens: int = 450) -> list[Chunk]`; `count_tokens(text: str) -> int`. Invariants later tasks rely on: chunks are contiguous, disjoint sid ranges in document order; every sentence belongs to exactly one chunk; a chunk never spans two sections.

- [ ] **Step 1: Add tiktoken to pyproject**

In `backend/pyproject.toml`, `dependencies`, add:

```toml
    "tiktoken>=0.7",
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_chunk.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_chunk.py -v`
Expected: FAIL — `No module named 'pipeline.chunk'`.

- [ ] **Step 4: Write `backend/src/pipeline/chunk.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_chunk.py -v` then `python -m ruff check .`
Expected: 5 PASS; ruff clean. (First run downloads the tiktoken encoding file — needs network once.)

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/src/pipeline/chunk.py backend/tests/test_chunk.py
git commit -m "feat: add sentence chunker with section-bounded token budget"
```

---

### Task 2: Embedder

**Files:**
- Modify: `backend/pyproject.toml` (add `fastembed`; add `slow` marker)
- Modify: `backend/tests/conftest.py` (slow-marker auto-skip)
- Create: `backend/src/pipeline/embed.py`
- Test: `backend/tests/test_embed.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `QUERY_PREFIX` (the exact BGE query instruction string), `DIMENSIONS = 384`, and `Embedder(model_name="BAAI/bge-small-en-v1.5")` with `embed_texts(texts: list[str]) -> list[list[float]]` (passages, no prefix) and `embed_query(question: str) -> list[float]` (prepends `QUERY_PREFIX`, design §4.4). fastembed loads lazily so importing the module (and every test that doesn't embed) stays fast and offline. Tasks 3–6 and Phase 3 depend on this exact interface; test fakes must implement both methods.

- [ ] **Step 1: Add fastembed and the slow marker to pyproject**

In `dependencies`: add `"fastembed>=0.3",`. In `[tool.pytest.ini_options]`, replace the `markers` list with:

```toml
markers = [
    "db: requires a running Postgres; set TEST_DATABASE_URL to enable",
    "slow: downloads the embedding model; set RUN_SLOW_TESTS=1 to enable",
]
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Extend the conftest auto-skip**

Replace the body of `pytest_collection_modifyitems` in `backend/tests/conftest.py`:

```python
import os

import pytest


def pytest_collection_modifyitems(config, items):
    skip_db = (
        None
        if os.environ.get("TEST_DATABASE_URL")
        else pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    )
    skip_slow = (
        None
        if os.environ.get("RUN_SLOW_TESTS")
        else pytest.mark.skip(reason="RUN_SLOW_TESTS not set")
    )
    for item in items:
        if skip_db and "db" in item.keywords:
            item.add_marker(skip_db)
        if skip_slow and "slow" in item.keywords:
            item.add_marker(skip_slow)
```

- [ ] **Step 3: Write the failing tests**

`backend/tests/test_embed.py`:

```python
import pytest

from pipeline.embed import DIMENSIONS, QUERY_PREFIX, Embedder


class RecordingEmbedder(Embedder):
    def __init__(self):
        super().__init__()
        self.seen: list[list[str]] = []

    def embed_texts(self, texts):
        self.seen.append(list(texts))
        return [[0.0] * DIMENSIONS for _ in texts]


def test_embed_query_applies_bge_prefix():
    embedder = RecordingEmbedder()
    embedder.embed_query("What were net sales in 2024?")
    assert embedder.seen == [[QUERY_PREFIX + "What were net sales in 2024?"]]


@pytest.mark.slow
def test_real_model_embeds_at_384_dims_with_sane_similarity():
    embedder = Embedder()
    vectors = embedder.embed_texts(
        [
            "Total net sales increased during fiscal 2024.",
            "The weather in Paris is rainy in November.",
        ]
    )
    assert [len(v) for v in vectors] == [DIMENSIONS, DIMENSIONS]
    query = embedder.embed_query("How did revenue change in 2024?")

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b))  # fastembed vectors are L2-normalized

    assert cosine(query, vectors[0]) > cosine(query, vectors[1])
```

- [ ] **Step 4: Run tests to verify the unit test fails**

Run: `python -m pytest tests/test_embed.py -v`
Expected: FAIL — `No module named 'pipeline.embed'` (the slow test will skip without `RUN_SLOW_TESTS`).

- [ ] **Step 5: Write `backend/src/pipeline/embed.py`**

```python
from __future__ import annotations

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


class Embedder:
    """Lazy wrapper around fastembed so importing this module stays cheap
    and tests that never embed stay offline."""

    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._load().embed(texts)]

    def embed_query(self, question: str) -> list[float]:
        # BGE models need the query-side instruction prefix (design §4.4)
        return self.embed_texts([QUERY_PREFIX + question])[0]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_embed.py -v` — unit test PASS, slow test SKIP.
Then run the slow test once for real: `$env:RUN_SLOW_TESTS = "1"; python -m pytest tests/test_embed.py -v -m slow` (PowerShell; downloads the model on first run, ~1–3 min). Expected: PASS. Unset afterwards: `Remove-Item Env:RUN_SLOW_TESTS`.
Then: `python -m ruff check .` — clean.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/tests/conftest.py backend/src/pipeline/embed.py backend/tests/test_embed.py
git commit -m "feat: add lazy fastembed embedder with BGE query prefix"
```

---

### Task 3: Chunk + embed persistence and the `embed` CLI stage

**Files:**
- Modify: `backend/pyproject.toml` (add `pythonpath = ["."]` to pytest options)
- Modify: `backend/src/pipeline/store.py` (add `to_pgvector`, `load_sentences`, `filing_ids_without_chunks`, `store_chunks`)
- Modify: `backend/src/pipeline/ingest.py` (add `embed_filings`)
- Modify: `backend/src/pipeline/__main__.py` (add `embed` subcommand)
- Create: `backend/tests/fakes.py`
- Test: `backend/tests/test_store_chunks.py`

**Interfaces:**
- Consumes: `Chunk`/`chunk_sentences` (Task 1), `Embedder` interface (Task 2), existing `store.store_filing`, `db.connect`.
- Produces: `store.to_pgvector(vector: list[float]) -> str` (pgvector text literal, e.g. `"[0.1,0.2]"`); `store.load_sentences(conn, filing_id: int) -> list[Sentence]` (ordered by sid); `store.filing_ids_without_chunks(conn, *, ticker: str | None = None) -> list[int]`; `store.store_chunks(conn, filing_id: int, chunks: list[Chunk], vectors: list[list[float]]) -> int` (row count, single transaction); `ingest.embed_filings(conn, embedder, *, ticker: str | None = None) -> tuple[int, int]` (filings processed, chunks stored — idempotent: only touches filings with zero chunks); CLI `python -m pipeline embed [--ticker T]`. `tests/fakes.py` provides `FakeEmbedder` (deterministic crc32 bag-of-words vectors, no prefix in `embed_query` so a query equal to a chunk's text produces the identical vector) — Task 4 and 5 tests reuse it.

- [ ] **Step 1: Make `backend/` importable in tests, then write the shared fake**

In `backend/pyproject.toml`, under `[tool.pytest.ini_options]`, add:

```toml
pythonpath = ["."]
```

(This lets tests import `tests.fakes` here, and the `evals` package in Task 5.)

`backend/tests/fakes.py`:

```python
import zlib

from pipeline.embed import DIMENSIONS


class FakeEmbedder:
    """Deterministic bag-of-words vectors: same text -> same vector, shared
    tokens -> nonzero cosine. embed_query applies no prefix, so a query equal
    to a stored chunk's text produces the identical vector (distance 0)."""

    def embed_texts(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, question):
        return self._vector(question)

    def _vector(self, text):
        vector = [0.0] * DIMENSIONS
        for token in text.lower().split():
            vector[zlib.crc32(token.encode()) % DIMENSIONS] += 1.0
        norm = sum(x * x for x in vector) ** 0.5 or 1.0
        return [x / norm for x in vector]
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_store_chunks.py`:

```python
import os
from datetime import date

import psycopg
import pytest

from pipeline import db, ingest, store
from pipeline.canonicalize import CanonicalFiling, Sentence
from pipeline.companies import Company
from pipeline.edgar import FilingRef
from tests.fakes import FakeEmbedder

COMPANY = Company(999999002, "TSTB", "Test Co B")


def make_ref(accession):
    return FilingRef(
        cik=999999002,
        accession=accession,
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        period_end=None,
        primary_document="test.htm",
    )


def make_canonical(texts, section="item1"):
    sentences, cursor = [], 0
    for i, text in enumerate(texts):
        sentences.append(Sentence(i, section, text, cursor, cursor + len(text)))
        cursor += len(text) + 1
    spans = " ".join(f'<span data-sid="{s.sid}">{s.text}</span>' for s in sentences)
    return CanonicalFiling("\n".join(texts), sentences, f"<p>{spans}</p>")


def wipe(conn, accession):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM chunks WHERE filing_id IN"
            " (SELECT id FROM filings WHERE accession = %s)",
            (accession,),
        )
        cur.execute(
            "DELETE FROM sentences WHERE filing_id IN"
            " (SELECT id FROM filings WHERE accession = %s)",
            (accession,),
        )
        cur.execute("DELETE FROM filings WHERE accession = %s", (accession,))
    conn.commit()


@pytest.mark.db
def test_embed_filings_chunks_and_stores_vectors():
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        wipe(conn, "TESTB-24-000001")
        canonical = make_canonical(
            ["Revenue grew ten percent this year.", "Margins were stable across segments."]
        )
        filing_id = store.store_filing(conn, COMPANY, make_ref("TESTB-24-000001"), canonical)

        assert filing_id in store.filing_ids_without_chunks(conn, ticker="TSTB")
        filings_done, chunks_stored = ingest.embed_filings(
            conn, FakeEmbedder(), ticker="TSTB"
        )
        assert filings_done == 1
        assert chunks_stored >= 1
        assert store.filing_ids_without_chunks(conn, ticker="TSTB") == []

        # idempotent: second run touches nothing
        assert ingest.embed_filings(conn, FakeEmbedder(), ticker="TSTB") == (0, 0)

        # vector round-trip: the stored embedding matches what the fake produced
        chunk_text_vector = store.to_pgvector(
            FakeEmbedder().embed_texts(
                ["Revenue grew ten percent this year. Margins were stable across segments."]
            )[0]
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding <=> %s::vector FROM chunks WHERE filing_id = %s",
                (chunk_text_vector, filing_id),
            )
            assert cur.fetchone()[0] == pytest.approx(0.0, abs=1e-6)
```

- [ ] **Step 3: Run it to verify it fails**

Run (with `TEST_DATABASE_URL` set): `python -m pytest tests/test_store_chunks.py -v`
Expected: FAIL — `module 'pipeline.store' has no attribute 'filing_ids_without_chunks'` (or AttributeError on `ingest.embed_filings`).

- [ ] **Step 4: Extend `backend/src/pipeline/store.py`**

Append (and add `from .chunk import Chunk` plus `Sentence` to the existing imports from `.canonicalize`):

```python
def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"


def load_sentences(conn: psycopg.Connection, filing_id: int) -> list[Sentence]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sid, section, text, char_start, char_end"
            " FROM sentences WHERE filing_id = %s ORDER BY sid",
            (filing_id,),
        )
        return [Sentence(*row) for row in cur.fetchall()]


def filing_ids_without_chunks(
    conn: psycopg.Connection, *, ticker: str | None = None
) -> list[int]:
    sql = (
        "SELECT f.id FROM filings f JOIN companies c ON c.cik = f.cik"
        " WHERE NOT EXISTS (SELECT 1 FROM chunks ch WHERE ch.filing_id = f.id)"
    )
    params: list[object] = []
    if ticker:
        sql += " AND c.ticker = %s"
        params.append(ticker.upper())
    sql += " ORDER BY f.id"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


def store_chunks(
    conn: psycopg.Connection,
    filing_id: int,
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> int:
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (filing_id, section, sid_start, sid_end, text,"
                " token_count, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s::vector)",
                [
                    (
                        filing_id,
                        chunk.section,
                        chunk.sid_start,
                        chunk.sid_end,
                        chunk.text,
                        chunk.token_count,
                        to_pgvector(vector),
                    )
                    for chunk, vector in zip(chunks, vectors)
                ],
            )
    return len(chunks)
```

Note: `Sentence(*row)` relies on the SELECT column order matching the dataclass field order `(sid, section, text, char_start, char_end)` — keep them in sync.

- [ ] **Step 5: Add the stage to `backend/src/pipeline/ingest.py`**

Append (add `from .chunk import chunk_sentences` to imports):

```python
def embed_filings(
    conn,
    embedder,
    *,
    ticker: str | None = None,
) -> tuple[int, int]:
    """Chunk + embed every filing that has no chunks yet (design §4.3-4.4)."""
    filings_done = 0
    chunks_stored = 0
    for filing_id in store.filing_ids_without_chunks(conn, ticker=ticker):
        sentences = store.load_sentences(conn, filing_id)
        chunks = chunk_sentences(sentences)
        vectors = embedder.embed_texts([c.text for c in chunks])
        chunks_stored += store.store_chunks(conn, filing_id, chunks, vectors)
        filings_done += 1
    return filings_done, chunks_stored
```

- [ ] **Step 6: Add the `embed` subcommand to `backend/src/pipeline/__main__.py`**

After the `ingest` subparser definition, add:

```python
    p_embed = sub.add_parser("embed", help="chunk + embed filings that have no chunks yet")
    p_embed.add_argument("--ticker", help="restrict to one curated ticker")
```

And after the `migrate` branch, add:

```python
    if args.cmd == "embed":
        from .embed import Embedder

        with db.connect() as conn:
            filings_done, chunks_stored = ingest.embed_filings(
                conn, Embedder(), ticker=args.ticker
            )
        print(f"embedded {chunks_stored} chunks across {filings_done} filings")
        return
```

(The import is local so `migrate`/`ingest` never pay the fastembed import cost.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_store_chunks.py -v` (with `TEST_DATABASE_URL`), then the full `python -m pytest -v` and `python -m ruff check .`.
Expected: all PASS/SKIP as appropriate; ruff clean.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/src/pipeline/store.py backend/src/pipeline/ingest.py backend/src/pipeline/__main__.py backend/tests/fakes.py backend/tests/test_store_chunks.py
git commit -m "feat: add chunk-embed pipeline stage with idempotent backfill CLI"
```

---

### Task 4: Hybrid retrieval

**Files:**
- Create: `backend/src/api/__init__.py` (empty)
- Create: `backend/src/api/retrieval.py`
- Test: `backend/tests/test_retrieval.py`

**Interfaces:**
- Consumes: `store.to_pgvector` (Task 3), an embedder implementing `embed_query` (Task 2 interface), the `chunks`/`filings`/`companies` tables.
- Produces: `RetrievedChunk` frozen dataclass `(chunk_id: int, accession: str, form_type: str, ticker: str, section: str, sid_start: int, sid_end: int, text: str, score: float)`; `retrieve(conn, embedder, question: str, *, k_each: int = 20, k_final: int = 8, ticker: str | None = None, form_type: str | None = None) -> list[RetrievedChunk]` — vector top-`k_each` + lexical top-`k_each`, RRF-fused (k=60, design §6.1), top `k_final` by fused score. Also exposes `vector_search` and `lexical_search` for eval debugging. Phase 3's `/ask` will call `retrieve` exactly as specified here.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_retrieval.py`:

```python
import os
from datetime import date

import psycopg
import pytest

from api.retrieval import retrieve
from pipeline import db, store
from pipeline.canonicalize import CanonicalFiling, Sentence
from pipeline.chunk import Chunk
from pipeline.companies import Company
from pipeline.edgar import FilingRef
from tests.fakes import FakeEmbedder

ALPHA = Company(999999003, "TSTC", "Test Co C")
BETA = Company(999999004, "TSTD", "Test Co D")

# One chunk per filing; distinctive vocabularies so vectors are far apart.
ALPHA_TEXT = "The escrow covenant restricts zebra imports during fiscal 2024."
BETA_TEXT = "Cloud subscription revenue accelerated in the fourth quarter."
LEXICAL_ONLY_TEXT = "A zebra logistics subsidiary was divested for cash proceeds."


def seed_filing(conn, company, accession, text):
    sentence = Sentence(0, "item1", text, 0, len(text))
    canonical = CanonicalFiling(
        text, [sentence], f'<p><span data-sid="0">{text}</span></p>'
    )
    ref = FilingRef(
        cik=company.cik,
        accession=accession,
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        period_end=None,
        primary_document="t.htm",
    )
    filing_id = store.store_filing(conn, company, ref, canonical)
    chunk = Chunk("item1", 0, 0, text, 10)
    store.store_chunks(conn, filing_id, [chunk], FakeEmbedder().embed_texts([text]))
    return filing_id


@pytest.fixture()
def seeded_conn():
    conn = psycopg.connect(os.environ["TEST_DATABASE_URL"])
    db.migrate(conn)
    with conn.cursor() as cur:
        for accession in ("TESTC-24-000001", "TESTD-24-000001", "TESTC-24-000002"):
            cur.execute(
                "DELETE FROM chunks WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = %s)",
                (accession,),
            )
            cur.execute(
                "DELETE FROM sentences WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = %s)",
                (accession,),
            )
            cur.execute("DELETE FROM filings WHERE accession = %s", (accession,))
    conn.commit()
    seed_filing(conn, ALPHA, "TESTC-24-000001", ALPHA_TEXT)
    seed_filing(conn, BETA, "TESTD-24-000001", BETA_TEXT)
    seed_filing(conn, ALPHA, "TESTC-24-000002", LEXICAL_ONLY_TEXT)
    yield conn
    conn.close()


@pytest.mark.db
def test_exact_text_question_ranks_its_chunk_first(seeded_conn):
    results = retrieve(seeded_conn, FakeEmbedder(), ALPHA_TEXT)
    assert results[0].accession == "TESTC-24-000001"
    assert results[0].text == ALPHA_TEXT
    assert results[0].score > 0


@pytest.mark.db
def test_lexical_match_surfaces_vector_far_chunk(seeded_conn):
    # "zebra" appears in the lexical-only chunk; its fake vector shares little
    # with the full ALPHA_TEXT query, so fusion must bring it in via FTS.
    results = retrieve(seeded_conn, FakeEmbedder(), ALPHA_TEXT, k_final=3)
    accessions = {r.accession for r in results}
    assert "TESTC-24-000002" in accessions


@pytest.mark.db
def test_ticker_filter_excludes_other_companies(seeded_conn):
    results = retrieve(seeded_conn, FakeEmbedder(), "revenue quarter", ticker="TSTD")
    assert results  # BETA's chunk matches
    assert {r.ticker for r in results} == {"TSTD"}


@pytest.mark.db
def test_k_final_caps_results(seeded_conn):
    results = retrieve(seeded_conn, FakeEmbedder(), "zebra revenue escrow", k_final=1)
    assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_retrieval.py -v` (with `TEST_DATABASE_URL`)
Expected: FAIL — `No module named 'api'`.

- [ ] **Step 3: Write `backend/src/api/__init__.py`** (empty file) **and `backend/src/api/retrieval.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from pipeline.store import to_pgvector

RRF_K = 60

_BASE = (
    "SELECT ch.id, f.accession, f.form_type, c.ticker, ch.section,"
    " ch.sid_start, ch.sid_end, ch.text"
    " FROM chunks ch"
    " JOIN filings f ON f.id = ch.filing_id"
    " JOIN companies c ON c.cik = f.cik"
)


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
    score: float


def _filters(ticker: str | None, form_type: str | None) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if ticker:
        clauses.append("c.ticker = %s")
        params.append(ticker.upper())
    if form_type:
        clauses.append("f.form_type = %s")
        params.append(form_type)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def vector_search(
    conn: psycopg.Connection,
    query_vector: list[float],
    *,
    k: int = 20,
    ticker: str | None = None,
    form_type: str | None = None,
) -> list[tuple]:
    where, params = _filters(ticker, form_type)
    sql = _BASE + where + " ORDER BY ch.embedding <=> %s::vector LIMIT %s"
    with conn.cursor() as cur:
        cur.execute(sql, [*params, to_pgvector(query_vector), k])
        return cur.fetchall()


def lexical_search(
    conn: psycopg.Connection,
    question: str,
    *,
    k: int = 20,
    ticker: str | None = None,
    form_type: str | None = None,
) -> list[tuple]:
    where, params = _filters(ticker, form_type)
    match = "to_tsvector('english', ch.text) @@ websearch_to_tsquery('english', %s)"
    where = where + (" AND " if where else " WHERE ") + match
    sql = (
        _BASE
        + where
        + " ORDER BY ts_rank_cd(to_tsvector('english', ch.text),"
        " websearch_to_tsquery('english', %s)) DESC LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, [*params, question, question, k])
        return cur.fetchall()


def retrieve(
    conn: psycopg.Connection,
    embedder,
    question: str,
    *,
    k_each: int = 20,
    k_final: int = 8,
    ticker: str | None = None,
    form_type: str | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieval per design §6.1: vector + lexical arms fused with RRF."""
    query_vector = embedder.embed_query(question)
    vector_rows = vector_search(
        conn, query_vector, k=k_each, ticker=ticker, form_type=form_type
    )
    lexical_rows = lexical_search(
        conn, question, k=k_each, ticker=ticker, form_type=form_type
    )

    scores: dict[int, float] = {}
    rows_by_id: dict[int, tuple] = {}
    for rows in (vector_rows, lexical_rows):
        for rank, row in enumerate(rows):
            chunk_id = row[0]
            rows_by_id[chunk_id] = row
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k_final]
    return [RetrievedChunk(*rows_by_id[chunk_id], score) for chunk_id, score in ranked]
```

Note: `RetrievedChunk(*row, score)` relies on the SELECT column order matching the first eight dataclass fields — keep them in sync.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_retrieval.py -v`, then full `python -m pytest -v` and `python -m ruff check .`.
Expected: all PASS; ruff clean. If `test_lexical_match_surfaces_vector_far_chunk` is flaky on ranking, that indicates an RRF bug — the lexical-only chunk must appear via the FTS arm regardless of vector distance; debug the arms individually with `vector_search`/`lexical_search`, don't loosen the test.

- [ ] **Step 5: Commit**

```bash
git add backend/src/api/__init__.py backend/src/api/retrieval.py backend/tests/test_retrieval.py
git commit -m "feat: add hybrid vector plus lexical retrieval with RRF fusion"
```

---

### Task 5: Retrieval eval harness

**Files:**
- Modify: `backend/pyproject.toml` (add `pyyaml`; add `pythonpath = ["."]` to pytest options)
- Create: `backend/evals/__init__.py` (empty), `backend/evals/harness.py`, `backend/evals/__main__.py`
- Test: `backend/tests/test_evals.py`

**Interfaces:**
- Consumes: `retrieve`/`RetrievedChunk` (Task 4), `Embedder` (Task 2), `db.connect`.
- Produces: `GoldenQuestion` frozen dataclass `(id: str, question: str, ticker: str, accession: str, section: str, gold_sids: list[int])`; `load_golden(path) -> list[GoldenQuestion]` (raises `ValueError` naming the entry id on a missing/invalid field); `hit(chunks: list[RetrievedChunk], accession: str, gold_sids: list[int]) -> bool` (any chunk from that accession whose `[sid_start, sid_end]` contains any gold sid); `run_retrieval_eval(conn, embedder, questions, *, ks=(5, 10)) -> dict` returning `{"questions": N, "recall@5": float, "recall@10": float, "misses@10": [ids]}`; `append_results(path, metrics) -> None` (JSON line with `git_sha`, `timestamp`, metrics — design §8). CLI: `python -m evals run [--retrieval-only] [--debug]` and `python -m evals verify`.

- [ ] **Step 1: pyproject changes**

Add `"pyyaml>=6.0",` to `dependencies` (`pythonpath = ["."]` was already added in Task 3, which is what makes `from evals import harness` resolve in tests). Run `pip install -e ".[dev]"`.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_evals.py`:

```python
import json
import os

import psycopg
import pytest

from api.retrieval import RetrievedChunk
from evals import harness
from tests.fakes import FakeEmbedder


def chunk(accession, sid_start, sid_end):
    return RetrievedChunk(1, accession, "10-K", "TSTC", "item1", sid_start, sid_end, "t", 1.0)


def test_hit_requires_matching_accession_and_sid_overlap():
    chunks = [chunk("ACC-1", 10, 20)]
    assert harness.hit(chunks, "ACC-1", [15]) is True
    assert harness.hit(chunks, "ACC-1", [21]) is False
    assert harness.hit(chunks, "ACC-2", [15]) is False


def test_load_golden_validates_fields(tmp_path):
    good = tmp_path / "golden.yaml"
    good.write_text(
        "- id: q001\n"
        "  question: What were net sales?\n"
        "  ticker: AAPL\n"
        '  accession: "0000320193-24-000123"\n'
        "  section: item7\n"
        "  gold_sids: [612, 613]\n",
        encoding="utf-8",
    )
    questions = harness.load_golden(good)
    assert questions[0].id == "q001"
    assert questions[0].gold_sids == [612, 613]

    bad = tmp_path / "bad.yaml"
    bad.write_text("- id: q002\n  question: Missing everything else\n", encoding="utf-8")
    with pytest.raises(ValueError, match="q002"):
        harness.load_golden(bad)


def test_append_results_writes_json_line(tmp_path):
    path = tmp_path / "results.jsonl"
    harness.append_results(path, {"recall@10": 0.9})
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["recall@10"] == 0.9
    assert "git_sha" in record and "timestamp" in record


@pytest.mark.db
def test_run_retrieval_eval_end_to_end():
    from datetime import date

    from pipeline import db, store
    from pipeline.canonicalize import CanonicalFiling, Sentence
    from pipeline.chunk import Chunk
    from pipeline.companies import Company
    from pipeline.edgar import FilingRef

    text = "The board approved a quarterly dividend increase of four percent."
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chunks WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = 'TESTE-24-000001')"
            )
            cur.execute(
                "DELETE FROM sentences WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = 'TESTE-24-000001')"
            )
            cur.execute("DELETE FROM filings WHERE accession = 'TESTE-24-000001'")
        conn.commit()
        company = Company(999999005, "TSTE", "Test Co E")
        sentence = Sentence(0, "item1", text, 0, len(text))
        canonical = CanonicalFiling(
            text, [sentence], f'<p><span data-sid="0">{text}</span></p>'
        )
        ref = FilingRef(
            cik=999999005,
            accession="TESTE-24-000001",
            form_type="10-K",
            filing_date=date(2024, 11, 1),
            period_end=None,
            primary_document="t.htm",
        )
        filing_id = store.store_filing(conn, company, ref, canonical)
        store.store_chunks(
            conn, filing_id, [Chunk("item1", 0, 0, text, 10)],
            FakeEmbedder().embed_texts([text]),
        )

        questions = [
            harness.GoldenQuestion(
                "q001", text, "TSTE", "TESTE-24-000001", "item1", [0]
            ),
            harness.GoldenQuestion(
                "q002", "entirely unrelated basket weaving query", "TSTE",
                "TESTE-24-000001", "item1", [99],  # sid that no chunk covers
            ),
        ]
        metrics = harness.run_retrieval_eval(conn, FakeEmbedder(), questions)
        assert metrics["questions"] == 2
        assert metrics["recall@10"] == 0.5
        assert metrics["misses@10"] == ["q002"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_evals.py -v`
Expected: FAIL — `No module named 'evals'` (create `backend/evals/__init__.py` as an empty file first if the error is different).

- [ ] **Step 4: Write `backend/evals/harness.py`**

```python
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from api.retrieval import RetrievedChunk, retrieve

GOLDEN_PATH = Path(__file__).parent / "golden.yaml"
RESULTS_PATH = Path(__file__).parent / "results.jsonl"
_REQUIRED = ("id", "question", "ticker", "accession", "section", "gold_sids")


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    question: str
    ticker: str
    accession: str
    section: str
    gold_sids: list[int]


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenQuestion]:
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    questions = []
    for entry in entries:
        entry_id = entry.get("id", "<missing id>")
        for field in _REQUIRED:
            if field not in entry:
                raise ValueError(f"golden entry {entry_id}: missing field {field!r}")
        if not isinstance(entry["gold_sids"], list) or not all(
            isinstance(s, int) for s in entry["gold_sids"]
        ):
            raise ValueError(f"golden entry {entry_id}: gold_sids must be a list of ints")
        questions.append(GoldenQuestion(*(entry[f] for f in _REQUIRED)))
    return questions


def hit(chunks: list[RetrievedChunk], accession: str, gold_sids: list[int]) -> bool:
    return any(
        chunk.accession == accession
        and any(chunk.sid_start <= sid <= chunk.sid_end for sid in gold_sids)
        for chunk in chunks
    )


def run_retrieval_eval(conn, embedder, questions, *, ks=(5, 10)) -> dict:
    top_k = max(ks)
    hits_at = {k: 0 for k in ks}
    misses_at_top: list[str] = []
    for question in questions:
        chunks = retrieve(conn, embedder, question.question, k_final=top_k)
        for k in ks:
            if hit(chunks[:k], question.accession, question.gold_sids):
                hits_at[k] += 1
        if not hit(chunks, question.accession, question.gold_sids):
            misses_at_top.append(question.id)
    n = len(questions)
    metrics: dict = {"questions": n}
    for k in ks:
        metrics[f"recall@{k}"] = round(hits_at[k] / n, 4) if n else 0.0
    metrics[f"misses@{top_k}"] = misses_at_top
    return metrics


def append_results(path: Path, metrics: dict) -> None:
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    record = {
        "git_sha": sha or "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **metrics,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
```

- [ ] **Step 5: Write `backend/evals/__main__.py`**

```python
from __future__ import annotations

import argparse

from pipeline import db
from pipeline.embed import Embedder

from . import harness


def cmd_run(args) -> None:
    if not args.retrieval_only:
        print("note: faithfulness eval arrives in Phase 3; running retrieval only")
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
        metrics = harness.run_retrieval_eval(conn, Embedder(), questions)
    for key, value in metrics.items():
        print(f"{key}: {value}")
    harness.append_results(harness.RESULTS_PATH, metrics)
    print(f"appended to {harness.RESULTS_PATH}")


def cmd_verify(args) -> None:
    """Check every golden entry against the DB: accession exists, sids exist."""
    questions = harness.load_golden()
    failures = 0
    with db.connect() as conn, conn.cursor() as cur:
        for question in questions:
            cur.execute(
                "SELECT id FROM filings WHERE accession = %s", (question.accession,)
            )
            row = cur.fetchone()
            if row is None:
                print(f"FAIL {question.id}: accession {question.accession} not in DB")
                failures += 1
                continue
            filing_id = row[0]
            for sid in question.gold_sids:
                cur.execute(
                    "SELECT text FROM sentences WHERE filing_id = %s AND sid = %s",
                    (filing_id, sid),
                )
                sentence = cur.fetchone()
                if sentence is None:
                    print(f"FAIL {question.id}: sid {sid} not in {question.accession}")
                    failures += 1
                else:
                    print(f"ok  {question.id} sid {sid}: {sentence[0][:90]}")
    if failures:
        raise SystemExit(f"{failures} golden-set problems")
    print(f"all {len(questions)} entries verified")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="evals")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="run the eval harness against DATABASE_URL")
    p_run.add_argument("--retrieval-only", action="store_true")
    p_run.add_argument("--debug", action="store_true", help="print per-arm top results")
    sub.add_parser("verify", help="validate golden entries against the DB")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        cmd_run(args)
    else:
        cmd_verify(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_evals.py -v` (with `TEST_DATABASE_URL`), full `python -m pytest -v`, `python -m ruff check .`.
Expected: all PASS; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/evals/__init__.py backend/evals/harness.py backend/evals/__main__.py backend/tests/test_evals.py
git commit -m "feat: add retrieval eval harness with golden-set loader and recall metrics"
```

---

### Task 6: Embed the real corpus, author the golden set, hit the exit criterion

This task works against real data and requires judgment — there is no fixed code to copy. Follow the procedure; do not fabricate golden entries.

**Files:**
- Create: `backend/evals/golden.yaml` (≥15 real questions)
- Create: `backend/evals/results.jsonl` (first committed run)

- [ ] **Step 1: Backfill embeddings for the ingested AAPL corpus**

From `backend/` (PowerShell):

```powershell
$env:DATABASE_URL = "postgresql://user:password@localhost:5432/edgar_answers"
python -m pipeline embed --ticker AAPL
```

Expected: `embedded N chunks across 12 filings` (N roughly 400–900 given ~7,500 sentences at ~450-token chunks). First run downloads the ONNX model (~1–3 min). Spot-check:

```powershell
docker compose exec db psql -U user -d edgar_answers -c "SELECT count(*), min(token_count), max(token_count) FROM chunks; SELECT f.accession, count(ch.id) FROM filings f JOIN chunks ch ON ch.filing_id = f.id GROUP BY f.accession ORDER BY f.accession;"
```

Every filing must have chunks; `max(token_count)` should not wildly exceed 450 (only over-long single sentences may exceed it).

- [ ] **Step 2: Author ≥15 golden questions from real filing content**

Procedure per question:

1. List the corpus: `docker compose exec db psql -U user -d edgar_answers -c "SELECT f.id, f.accession, f.form_type, f.filing_date FROM filings f ORDER BY f.filing_date DESC;"`
2. Read a section's sentences, e.g.: `docker compose exec db psql -U user -d edgar_answers -c "SELECT sid, left(text, 140) FROM sentences WHERE filing_id = <id> AND section = 'item7' ORDER BY sid LIMIT 120;"`
3. Pick a sentence (or adjacent pair) stating a concrete fact. Write a question **a user would actually ask** — paraphrase, don't copy the sentence verbatim. Record the accession and the sid(s) as `gold_sids`.

Coverage requirements: ≥15 questions total; ≥3 different filings (mix 10-K and 10-Q); ≥4 distinct sections (e.g. `item1`, `item1a`, `item7`, `item8`, `part1.item2`); at least 2 questions whose natural phrasing uses finance-specific exact terms (e.g. "RSUs", "share repurchase", "effective tax rate") — those exercise the lexical arm. Entry format (values here are ILLUSTRATIVE — every committed entry must use accessions and sids read from your DB in steps 1–2):

```yaml
- id: q001
  question: "How much did Apple's total net sales grow in fiscal 2024?"
  ticker: AAPL
  accession: "0000320193-24-000123"
  section: "item7"
  gold_sids: [637]
```

- [ ] **Step 3: Verify the golden set against the DB**

```powershell
python -m evals verify
```

Expected: one `ok` line per gold sid showing the sentence text (read them — each printed sentence must actually answer its question), ending `all 15 entries verified`. Fix any FAIL before proceeding.

- [ ] **Step 4: Run the eval — exit criterion recall@10 ≥ 0.8**

```powershell
python -m evals run --retrieval-only
```

Expected output shape: `questions: 15`, `recall@5: …`, `recall@10: …`, `misses@10: […]`, `appended to …results.jsonl`.

**If recall@10 < 0.8**, diagnose before touching anything: run `python -m evals run --debug` and for each missed question check (a) does either arm return the gold chunk at all? (b) is the gold sentence inside a chunk (`SELECT * FROM chunks WHERE filing_id = <id> AND <sid> BETWEEN sid_start AND sid_end`)? Remedies, in order: add a `k_each: int = 20` parameter to `run_retrieval_eval` that passes through to `retrieve`, and try 40 (helps when gold chunks appear in an arm but rank below the fused top-10); fix a genuinely malformed question (ambiguous, or asks about content not in the corpus). **Never** edit `gold_sids` to whatever was retrieved, and never delete a question just because it misses — that games the metric the phase exists to establish. Re-run until ≥ 0.8, keeping every intermediate result line in `results.jsonl` (the history is the point).

- [ ] **Step 5: Final full verification and commit**

```powershell
python -m pytest -v          # with TEST_DATABASE_URL set: all pass
python -m ruff check .
```

```bash
git add backend/evals/golden.yaml backend/evals/results.jsonl
git commit -m "feat: add golden retrieval set with first eval results"
```

---

## Exit criteria (design §12, Phase 2)

- `pytest -v` and `ruff check .` green (db tests included).
- All 12 AAPL filings have chunks with 384-dim embeddings in Postgres.
- `python -m evals run --retrieval-only` reports **recall@10 ≥ 0.8** on ≥15 verified golden questions, with the run recorded in `backend/evals/results.jsonl`.

## Follow-on plans (not in this document)

1. **Phase 3:** FastAPI `/ask` — generation (Claude Haiku), deterministic quote verification, SSE streaming, faithfulness eval.
2. **Phase 4:** Next.js frontend — ask page, filing viewer, citation highlighting.
3. **Phase 5:** full 10-company corpus, 40-question golden set, deployment.
