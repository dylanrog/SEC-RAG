# EDGAR Answers

**A RAG-based Q&A system over SEC filings, with server-verified, click-to-highlight citations.**

> Every answer is grounded in SEC filings, and every citation is verified against the
> source text before it renders — click any citation to see the exact sentence
> highlighted in the original filing.

Built by Dylan Rogers

## Status

Phases 0–4 complete: EDGAR ingestion, sentence-aligned canonicalization, hybrid
retrieval, the `/ask` API with server-side citation verification, and the
frontend with click-to-highlight.

Phase 5 is in progress. The corpus is built — ten large filers (AAPL, MSFT,
AMZN, GOOGL, META, NVDA, TSLA, JPM, JNJ, WMT), 120 filings, 13,725 chunks,
188,074 sentences — and answers draw on several filings at once: citations are
grouped by filing in a sources panel, and the viewer holds up to three filings
open as tabs. Growing the golden set from 16 to 40 questions and deploying are
the remaining Phase 5 work. See `docs/design.md` §12 for the phase plan.

On the 16-question golden set, citation verification sits at **1.0** (every
quote the model produced matched its source text) against the design's ≥90%
bar. Retrieval recall@10 is 1.0 when scoped to a ticker and 0.75 unscoped —
comparison questions naming two companies still retrieve from one, which is
tracked in `docs/design.md` §14 as query decomposition.

## Demo

_link goes here once demoable_

## Why this project

Looking to gain experience with RAG. Highlighting the source seemed interesting since AI 
hallucinations are annoying to deal with.

## Architecture

```
EDGAR (submissions, 10-K/10-Q HTML) ─▶ Python ingestion pipeline ─▶ Postgres/pgvector
                                                                          │
                                     Next.js frontend ◀── FastAPI ────────┘
                                     (answer pane + sources panel,
                                      tabbed filing viewer,
                                      click-to-highlight citations)
```

The load-bearing idea is that the canonicalizer emits two **aligned** outputs in
a single DOM traversal: canonical text split into sentences with stable integer
ids, and sanitized viewer HTML where each sentence is wrapped in a span carrying
that same id. Verification is then a plain substring match of the model's quote
against the cited chunk's canonical text — no fuzzy matching — and the id it
resolves to is the id the frontend scrolls to. A citation that fails
verification renders a visible "unverified" badge; it is never silently
dropped.

XBRL is deliberately out of scope for v1, along with 8-Ks and on-demand ticker
ingestion — see `docs/design.md` §2 and the §14 backlog.

## Repo layout

```
backend/        Python ingestion pipeline + FastAPI service
  src/pipeline/   EDGAR fetch → canonicalize → chunk → embed
  src/api/        FastAPI app: query routing, retrieval, generation, verification
  migrations/     Numbered plain-SQL migrations, applied in filename order
  tests/          Unit tests + canonicalizer fixtures (real messy filing HTML samples)
  evals/          Golden question set + retrieval/faithfulness eval harness
frontend/       Next.js app: answer UI + filing viewer with citation highlighting
  lib/            Framework-free logic: SSE parsing, answer reducer, grouping, tab state
  components/     Thin renderers over lib/
  e2e/            Playwright specs, including click-to-highlight and multi-source
docs/
  design.md            Full technical design document — the authoritative spec
  superpowers/specs/   Design specs written before a phase starts
  superpowers/plans/   Per-phase implementation plans
```

## Running it locally

Requires Python 3.13, Node 22, and Docker. Those are the versions CI runs
(`.github/workflows/ci.yml`); `requires-python` is pinned to `>=3.13`, and the
old 3.11/3.13 matrix was removed deliberately.

### 1. Configure

```bash
cp .env.example backend/.env         # then fill it in — it is gitignored
```

At minimum set `EDGAR_USER_AGENT` (the SEC rejects requests without an
identifying User-Agent) and, if you want to ask questions, `ANTHROPIC_API_KEY`.
The `DATABASE_URL` default matches `docker-compose.yml`, so it works as shipped.

Backend entry points read `backend/.env` (see `src/pipeline/env.py`); a real
environment variable always wins over a value in the file. Keep
`ANTHROPIC_API_KEY` in that file rather than exporting it — an exported key is
visible to every process on the machine.

### 2. Database

```bash
docker compose up -d --wait          # Postgres + pgvector; --wait blocks until it accepts connections
cd backend
pip install -e ".[dev]"
python -m pipeline migrate
```

### 3. Build the corpus

```bash
python -m pipeline ingest --ticker AAPL    # one company, or --all for all ten
python -m pipeline embed                   # chunk + embed; retrieval returns nothing without this
```

`ingest` fetches and canonicalizes; `embed` is a **separate, required step** —
it chunks the stored filings and writes the vectors that the search half of
retrieval reads. `--ticker` and `--all` are alternatives, not a pair: passing
`--all` ingests every curated company and ignores `--ticker`.

Expect ingestion to take a while and to be polite about it — EDGAR is rate
limited to 5 requests/second. Raw HTML is cached under `backend/data/raw/`, so
re-runs never re-download a filing you already have. Filing *lists* are fetched
live every run; only documents are cached.

### 4. Run it

```bash
python -m uvicorn api.app:app --port 8000   # from backend/

cd ../frontend && npm install
cp .env.local.example .env.local
npm run dev                                 # http://localhost:3000/ask
```

Only answering questions costs money. Ingestion, embedding, and retrieval are
free: embeddings run locally via `fastembed`, so you can build the whole
pipeline and exercise retrieval without an Anthropic key at all.

## Running the tests

```bash
# backend/ — CI runs lint first, and a lint failure skips the tests entirely
ruff check .
pytest -q

# frontend/
npm test          # vitest unit specs
npm run lint
npm run test:e2e  # Playwright; builds the app first, so it typechecks too
```

Database-backed tests are marked `@pytest.mark.db` and **skip silently** unless
`TEST_DATABASE_URL` is set — a skip is not a pass. Point it at a separate
database, which `docker-compose.yml` does not create for you:

```bash
docker compose exec db createdb -U user edgar_answers_test
```

The tests apply migrations themselves, so nothing further is needed. If
Postgres is down while `TEST_DATABASE_URL` is set, pytest blocks in
`psycopg.connect` with no timeout — a hung suite usually means the container
isn't up, not a bad test.

## Evals

```bash
python -m evals run              # retrieval + faithfulness, appends to evals/results.jsonl
python -m evals run --retrieval-only   # skips the model, costs nothing
python -m evals verify           # checks every golden entry still resolves in the DB
```

Run these before and after any change to chunking, retrieval, or the prompt.
Each row records the git sha it ran at and whether the tree was dirty, so run
them on a clean tree or the row can't be replayed. Note that `gold_sid_hit_rate`
and `citations_total` vary between runs on identical code — don't read a single
run's movement as a regression.

## Maintenance commands

```bash
python -m pipeline recanonicalize            # rebuild viewer_html from cached HTML
python -m pipeline recanonicalize --ticker AAPL
```

Re-runs the canonicalizer over already-cached raw HTML and updates the stored
viewer HTML only — no re-chunk, no re-embed, no EDGAR traffic. Use it after a
canonicalizer change that affects rendering but not sentence splitting. It
verifies per filing that the recomputed sentences still match the stored rows
and skips any filing that disagrees, because silently rewriting one would
invalidate every citation already anchored to it.

## License

MIT
