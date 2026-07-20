# EDGAR Answers

**A RAG-based Q&A system over SEC filings, with server-verified, click-to-highlight citations.**

> Every answer is grounded in SEC filings, and every citation is verified against the
> source text before it renders — click any citation to see the exact sentence
> highlighted in the original filing.

Built by Dylan Rogers

## Status

🚧 Early development

## Demo

_link goes here once demoable_

## Why this project

Looking to gain experience with RAG. Highlighting the source seemed interesting since AI 
hallucinations are annoying to deal with.

## Architecture

```
EDGAR (submissions, filings, XBRL) ─▶ Python ingestion pipeline ─▶ Postgres/pgvector
                                                                         │
                                    Next.js frontend  ◀── FastAPI ───────┘
                                    (answer pane + canonical filing viewer,
                                     click-to-highlight citations)
```
XBRL in Phase 2
## Repo layout

```
backend/        Python ingestion pipeline + FastAPI service
  src/pipeline/   EDGAR fetch → canonicalize → chunk → embed
  src/api/        FastAPI app: query routing, retrieval, generation, verification
  tests/          Unit tests + canonicalizer fixtures (real messy filing HTML samples)
  evals/          Golden question set + retrieval/faithfulness eval harness
frontend/       Next.js app: answer UI + filing viewer with citation highlighting
docs/
  design.md       Full technical design document
  decisions/      Short ADRs for notable technical choices
  roadmap.md      Phase-by-phase build plan and current status
```

## License

MIT
