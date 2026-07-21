# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

EDGAR Answers: RAG Q&A over SEC filings (10-K/10-Q) where every citation is
**verified server-side against source text before rendering**, and clicking a
citation highlights the exact sentences in the original filing. Postgres +
pgvector, Python ingestion pipeline + FastAPI backend, Next.js frontend.

**`docs/design.md` is the authoritative spec.** Scope is deliberately locked
(§2): no XBRL, no 8-Ks, no on-demand tickers, no auth/chat-history in v1.
Do not expand scope; new ideas go to the §14 backlog.

## Working mode (important)

- This is Dylan's learning project. Dylan writes the implementation code;
  Claude reviews, explains, and unblocks. **Do not implement plan tasks
  wholesale unless explicitly asked.** The active plan is
  `docs/superpowers/plans/2026-07-19-phase0-1-ingestion.md`.
- **Commit messages must contain no AI attribution of any kind** — no
  Co-Authored-By, no Claude-Session trailers, no tool names.

## Commands

All backend work runs from `backend/` (Python 3.11, src layout, package name
`pipeline`):

```
pip install -e ".[dev]"            # setup
pytest -v                          # all tests
pytest tests/test_foo.py::test_name -v   # single test
ruff check .                       # lint (CI runs both; keep green per commit)
python -m pipeline migrate         # apply SQL migrations
python -m pipeline ingest --ticker AAPL [--all] [--accession N] [--force]
```

Dev database: `docker compose up -d` at repo root (pgvector Postgres,
URL `postgresql://user:password@localhost:5432/edgar_answers`).
DB-dependent tests are marked `@pytest.mark.db` and auto-skip unless
`TEST_DATABASE_URL` is set (point it at a separate `edgar_answers_test`
database). CI has no Postgres, so db tests never run there — that's
intentional.

Ingestion needs `EDGAR_USER_AGENT` set (SEC requires an identifying
User-Agent); see `.env.example`.

## Architecture

Three units with hard boundaries (design.md §3):

- **Pipeline** (`backend/src/pipeline/`): batch CLI, fetch → canonicalize →
  chunk → embed, writes Postgres. Never called by the API.
- **API** (`backend/src/api/`): FastAPI, retrieve → generate → verify →
  stream SSE. Reads Postgres, calls Claude Haiku. Stateless.
- **Frontend** (`frontend/`): Next.js ask page + filing viewer. Talks only
  to the API.

The pipeline↔API contract is the DB schema (design.md §5); the API↔frontend
contract is the HTTP/SSE interface (§6.4).

### The load-bearing invariant: sentence anchoring

The canonicalizer produces two **aligned** outputs in a single DOM traversal:
canonical text segmented into sentences with stable integer IDs (`sid`), and
sanitized viewer HTML where each sentence is wrapped in
`<span data-sid="...">`. Everything depends on this alignment:

- Citation verification = normalized substring match of the LLM's quote
  against the cited chunk's canonical text (deterministic, no fuzzy match),
  then resolution to sids via character offsets.
- Click-to-highlight = the frontend scrolling to those same sids in the
  stored viewer HTML.
- Chunks are contiguous, **disjoint** sid ranges (no overlap) — every
  sentence belongs to exactly one chunk.

If a change would let canonical text and viewer HTML drift (e.g., separate
extraction passes), it breaks the product. Canonicalizer correctness is
defined by fixtures in `backend/tests/fixtures/` — real messy EDGAR HTML
excerpts; when a real filing breaks extraction, snip the pattern into a new
fixture first.

### Other pinned decisions

- Embeddings: local `bge-small-en-v1.5` via fastembed; **queries need the BGE
  query prefix** ("Represent this sentence for searching relevant passages: ").
  Dimension `vector(384)` is baked into the schema.
- Retrieval is hybrid (pgvector cosine + Postgres FTS, RRF k=60) — financial
  jargon makes lexical search essential, don't "simplify" to vector-only.
- Failed citation verification renders a visible "unverified" badge, never a
  silent drop.
- Migrations are plain numbered SQL files in `backend/migrations/`, applied
  in filename order by `pipeline.db.migrate` (Alembic deliberately deferred).
- EDGAR fetches: ≤5 req/s, raw HTML cached to `backend/data/raw/` (gitignored);
  re-runs must never re-hit EDGAR for cached filings.
- Evals (`backend/evals/`): golden questions pin answers to sids;
  retrieval recall@k and citation-verification rate append to
  `evals/results.jsonl`. Run them before/after chunking or prompt changes.

## Current state (2026-07-20)

Phases: 0 plumbing → 1 ingestion → 2 retrieval+evals → 3 /ask API →
4 frontend → 5 scale+deploy (design.md §12).

- **Phase 0–1 complete**, merged to `main` (PR #1): EDGAR fetch, canonicalize
  (sentences + aligned viewer HTML), Postgres schema, `ingest` CLI. 12 AAPL
  filings ingested locally.
- **Phase 2 complete** on branch `phase2-retrieval`, not yet merged: chunker,
  fastembed embedder, `embed` CLI stage, hybrid RRF retrieval
  (`src/api/retrieval.py`), eval harness + 16-question golden set. Exit
  criterion met at recall@10 = 1.0.
- **Phase 3 next** — FastAPI `/ask`: generation, quote verification, SSE.
  Needs its own plan; it will consume `api.retrieval.retrieve()` as-is.

`frontend/` is still a placeholder. Chunk size is **450 tiktoken tokens**, not
design §4.3's ~600 — `bge-small-en-v1.5` truncates at 512 of its own tokens,
so a 600-token chunk would lose its tail from vector search. Don't "restore" 600.
