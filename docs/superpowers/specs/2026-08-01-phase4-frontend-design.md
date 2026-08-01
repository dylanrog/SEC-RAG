# EDGAR Answers Phase 4: Frontend — Ask Page, Filing Viewer, Click-to-Highlight

**Status:** approved design, not yet planned or implemented.
**Spec authority:** `docs/design.md` §3 (unit boundaries), §6.4 (SSE contract),
§7 (frontend), §10 (error handling), §12 (Phase 4 exit criterion), §13 (risks),
§14 (backlog). Where this document and design.md disagree, design.md is amended
as part of this phase rather than silently diverged from.

**Exit criterion (design §12):** click a citation → the exact cited sentences
highlight in the filing viewer.

## 1. Goal and boundaries

Phase 4 builds the only user-facing surface in the product: a single `/ask`
page with a split pane. The left pane takes a question and renders a streamed,
citation-marked answer. The right pane renders the original filing and
highlights the exact sentences a citation resolves to.

Everything the frontend needs already exists and is verified working against
real data as of `a7e45f4`:

- `POST /ask` streams `token` / `citation` / `done` / `error` over SSE.
- `GET /filings/{accession}` returns stored, server-sanitized viewer HTML whose
  sentences are wrapped in `<span data-sid="...">`.
- `GET /companies` returns the curated list for the filter UI.

The frontend is a pure consumer of that HTTP contract (design §3). It contains
no retrieval, no verification, and no knowledge of the database.

**Out of scope**, per design §2 and §14: authentication, chat history, the
`year` filter, XBRL, on-demand ticker ingestion, viewer virtualization, dark
mode, and mobile-specific layouts. New ideas go to §14, not into this phase.

## 2. Stack

| Concern | Choice |
|---|---|
| Framework | Next.js App Router, TypeScript |
| Styling | Tailwind, plus one global CSS rule for injected HTML |
| Unit tests | Vitest (`node` env; `jsdom` only where a DOM is required) |
| E2E | Playwright, one spec covering the exit criterion |
| API access | Direct `fetch` to FastAPI; CORS enabled server-side |

Node 22.18 and npm 10.8 are already installed locally.

## 3. Architecture

### 3.1 Shape: pure core, thin React

The tricky logic lives in framework-free TypeScript modules under `lib/`.
React components are renderers over the state those modules produce.

This deliberately mirrors the backend, which is the same shape and is the
reason its tests are fast and boring: `api/normalize.py` and `api/verify.py`
are pure — no database, no network, no framework — and `api/app.py` is a thin
adapter over them. Three of the four `lib/` modules below need no DOM at all,
so their tests run in milliseconds without jsdom.

| Module | Export | Needs DOM |
|---|---|---|
| `lib/sse.ts` | `parseSSE(buffer) → {events, rest}` | no |
| `lib/answer.ts` | `reduce(state, event) → AnswerState` | no |
| `lib/markers.ts` | `splitOnMarkers(text) → Segment[]` | no |
| `lib/highlight.ts` | `applyHighlight(container, sids)` | yes |
| `lib/api.ts` | `askStream()`, `fetchFiling()`, `fetchCompanies()` | no |

`parseSSE` returns the unconsumed `rest` of the buffer rather than assuming
each network chunk contains whole events. A chunk boundary can fall mid-frame,
and the caller must prepend the remainder to the next chunk. This is the most
likely source of a defect that passes locally and fails on a slow connection,
so the remainder is part of the return value where a test can assert on it.

### 3.2 Components

```
frontend/
  app/ask/page.tsx              layout, owns both pieces of state
  app/globals.css               Tailwind + .cited-sentence
  components/ask-form.tsx       question input, ticker/form_type filters
  components/answer-stream.tsx  prose with inline markers
  components/citation-chip.tsx  pending | verified | unverified
  components/filing-viewer.tsx  injects HTML once, highlights on sid change
  lib/                          the five modules above
```

`/ask` is a client component: the entire page is driven by a live stream, so
there is nothing meaningful to render on the server.

### 3.3 State

Two `useState` objects, no state library (design §7):

```ts
answer: {
  prose: string
  citations: Map<number, Citation>   // keyed by marker
  status: "idle" | "streaming" | "done" | "error"
  notice: string | null              // set only when unverified_answer is true
  errorMessage: string | null        // set only when status is "error"
}
active: { accession: string | null; sids: number[] }
```

`active` is exactly design §7's `{activeAccession, activeSids}`: a chip click
sets it, the viewer reacts to it.

## 4. Data flow

1. Submit → `POST /ask` with `{question, filters:{ticker?, form_type?}}`.
2. Read `response.body` as a stream; each chunk goes through `parseSSE`, each
   event through `reduce`.
3. `token` appends to `prose`. `splitOnMarkers` renders `[1]` as **inert
   styled text** — citation data does not exist yet (see §4.1).
4. `citation` inserts into the `citations` Map. Markers already on screen
   **upgrade in place** to a chip: clickable if `verified`, badged if not.
5. `done` sets `status`. `unverified_answer: true` raises a notice.
6. Chip click → `setActive({accession, sids})`.
7. Viewer: if `accession` changed, fetch and inject the HTML **once**; then
   call `applyHighlight(container, sids)`.

### 4.1 Why markers stream inert

The backend emits every `token` event before any `citation` event — the whole
answer streams, then citations arrive. Confirmed live: a real `/ask` call
produced three `token` events, then one `citation`, then `done`.

Design §7 says "markers render as citation chips", which is only reachable
after the stream ends. Rather than buffering the answer (which would discard
the streaming behaviour the SSE path was built for), markers render inert
during streaming and upgrade when their citation lands. This makes marker
rendering and citation resolution two independently testable concerns.

### 4.2 Why highlighting is a DOM operation, not a string rewrite

A real AAPL 10-K's `viewer_html` is **818 KB**. Injecting highlight classes by
rewriting that HTML string would re-parse 818 KB on every citation click and
would mean running a regex over HTML, which is fragile.

Instead the HTML is injected once per filing, and `applyHighlight` operates on
the already-mounted container:

```ts
container.querySelectorAll(".cited-sentence")
  .forEach(el => el.classList.remove("cited-sentence"))
for (const sid of sids)
  container.querySelectorAll(`[data-sid="${sid}"]`)
    .forEach(el => el.classList.add("cited-sentence"))
first?.scrollIntoView({ behavior: "smooth", block: "center" })
```

Injection is keyed on `accession`, highlighting on `sids`. Clicking a second
citation within the same filing is therefore a class toggle, not a re-parse.

Because the HTML is injected via `dangerouslySetInnerHTML`, the highlight
cannot be a Tailwind utility class — Tailwind cannot reach markup React did not
author. It is a plain global rule in `globals.css`:

```css
.cited-sentence { background: #fef08a; scroll-margin-top: 4rem; }
```

`dangerouslySetInnerHTML` is acceptable here and only here: the canonicalizer
sanitized this HTML at ingestion, so the server is the sanitizer (design §7).
The frontend must never inject HTML from any other source.

## 5. Error handling (design §10)

| Condition | Behaviour |
|---|---|
| `error` event mid-stream | Banner; the partial answer stays on screen |
| Network / fetch failure | Banner with retry; form re-enabled |
| `done.unverified_answer: true` | Notice above the answer |
| Citation `verified: false` | Visible badge; chip is **not** clickable |
| `done.chunks_retrieved: 0` | "No matching filings" empty state |
| `GET /filings` 404 | Viewer pane shows unavailable; answer untouched |
| Marker with no matching citation | Stays inert text; never a dead chip |

A failed citation is never silently dropped — that is the product (design §6.3).

## 6. Backend changes

Two small changes, both in service of this phase:

1. **CORS.** `api/app.py` gains `CORSMiddleware` allowing the frontend origin,
   read from an env var (default `http://localhost:3000`) so Phase 5 can point
   it at the deployed domain. Without this, the browser preflight on a
   JSON `POST /ask` fails and the frontend cannot make a single request.
   Methods `GET`/`POST`, header `content-type`; no credentials. Covered by a
   backend test asserting the `OPTIONS /ask` preflight returns the
   `access-control-allow-origin` header for the configured origin — this needs
   no database and runs in CI.

2. **Spec amendment.** design.md §6.4 documents `input_tokens` and
   `output_tokens` on the `done` event, which the code has never emitted, and
   omits `unverified_answer`, which it does emit. The frontend consumes this
   payload, so §6.4 is corrected to the shipped shape:
   `{chunks_retrieved, citations_total, citations_verified, unverified_answer}`.

No other backend behaviour changes in Phase 4.

## 7. Testing

| Layer | Env | Covers |
|---|---|---|
| `lib/sse.ts` | node | frames split across chunks, multi-line `data`, unknown event names, trailing partial frame |
| `lib/answer.ts` | node | each event type's state transition; error mid-stream keeps prose |
| `lib/markers.ts` | node | `[1]`, `[10]`, adjacent markers, literal brackets that are not markers |
| `lib/highlight.ts` | jsdom | class applied to every cited sid, cleared before reapply, `scrollIntoView` on the first |
| Playwright | browser | the exit criterion, end to end |

The Playwright spec stubs `/ask` and `/filings` at the network layer so it is
deterministic and spends no API credit: ask a question, watch tokens stream,
click the chip, assert the element carrying the cited `data-sid` has class
`cited-sentence` and is scrolled into view.

CI gains a `frontend` job (lint, vitest, playwright) beside the existing
`backend` job. As with the backend, lint and unit tests must pass per commit.

## 8. Verification

Phase 4 is done when all of these hold:

1. `npm run lint` and `npm test` (vitest) pass in `frontend/`.
2. `npx playwright test` passes, including the exit-criterion spec.
3. Backend `pytest -v` and `ruff check .` still pass, with a new test covering
   the CORS preflight on `/ask`.
4. Against the live stack (`docker compose up -d`, uvicorn, `npm run dev`):
   asking "What were Apple's total net sales in fiscal 2024?" streams a visible
   token-by-token answer, the marker upgrades to a verified chip, and clicking
   it loads the 10-K and highlights the cited sentence.
5. A deliberately unverifiable citation renders a visible unverified badge and
   is not clickable.
6. design.md §6.4 matches the shipped `done` payload.
