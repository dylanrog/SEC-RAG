# EDGAR Answers

**A RAG-based Q&A system over SEC filings, with server-verified, click-to-highlight citations.**

> Every answer is grounded in SEC filings, and every citation is verified against the
> source text before it renders — click any citation to see the exact sentence
> highlighted in the original filing.

Built by Dylan Rogers

## Status

Phases 0–4 complete: EDGAR ingestion, sentence-aligned canonicalization, hybrid
retrieval, the `/ask` API with server-side citation verification, and the
frontend with click-to-highlight. Phase 5 — full corpus and deploy — is next.
See `docs/design.md` §12 for the phase plan.

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
                                     (answer pane + canonical filing viewer,
                                      click-to-highlight citations)
```

XBRL is deliberately out of scope for v1, along with 8-Ks and on-demand ticker
ingestion — see `docs/design.md` §2 and the §14 backlog.

## Repo layout

```
backend/        Python ingestion pipeline + FastAPI service
  src/pipeline/   EDGAR fetch → canonicalize → chunk → embed
  src/api/        FastAPI app: query routing, retrieval, generation, verification
  tests/          Unit tests + canonicalizer fixtures (real messy filing HTML samples)
  evals/          Golden question set + retrieval/faithfulness eval harness
frontend/       Next.js app: answer UI + filing viewer with citation highlighting
docs/
  design.md            Full technical design document — the authoritative spec
  superpowers/specs/   Design specs written before a phase starts
  superpowers/plans/   Per-phase implementation plans
```

## Running it locally

```bash
docker compose up -d --wait          # Postgres + pgvector
cd backend && pip install -e ".[dev]"
python -m pipeline migrate
python -m pipeline ingest --ticker AAPL --all   # needs EDGAR_USER_AGENT
python -m uvicorn api.app:app --port 8000

cd ../frontend && npm install
cp .env.local.example .env.local
npm run dev                          # http://localhost:3000
```

Answering questions needs `ANTHROPIC_API_KEY`; ingestion and retrieval do not.

## License

MIT
