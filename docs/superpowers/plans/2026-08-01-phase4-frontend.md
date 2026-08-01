# EDGAR Answers Phase 4: Frontend — Ask Page, Viewer, Click-to-Highlight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Next.js `/ask` page with a split pane — streamed answer with citation
chips on the left, the original filing on the right — where clicking a verified
citation highlights the exact cited sentences (design §12, Phase 4 exit criterion).

**Architecture:** All non-trivial logic lives in framework-free modules under
`frontend/lib/` (SSE parsing, event reduction, marker splitting, highlighting).
React components are thin renderers over the state those modules produce. This
mirrors the backend's own shape — pure `api.normalize` / `api.verify` behind a
thin FastAPI adapter — and means three of the four logic modules test with no DOM.

**Tech Stack:** Next.js App Router, TypeScript, Tailwind, Vitest (node + jsdom),
Playwright. Backend gains only `CORSMiddleware`.

**Spec:** `docs/superpowers/specs/2026-08-01-phase4-frontend-design.md`.
Prior work: `docs/superpowers/plans/2026-07-31-phase3-ask-api.md` (complete).

## Prerequisites

- **Phase 3 must be merged to `main` first.** This branch (`phase4-frontend`)
  was cut from `phase3-ask`; once PR #3 lands, rebase onto `main`.
- Backend running: `docker compose up -d` at repo root, then
  `python -m uvicorn api.app:app --port 8000` from `backend/`, with the 12 AAPL
  filings ingested. `curl localhost:8000/companies` must return AAPL with 12
  filings before you start.
- Node 22.18+ and npm 10.8+ (both already installed).
- No `ANTHROPIC_API_KEY` is needed except in Task 11's live check. Every test in
  this plan runs against stubs and costs nothing.

## Global Constraints

- All frontend commands run from `frontend/`. All backend commands from `backend/`.
- `npm run lint` and `npm test` must pass before every commit (matches CI).
- Commit messages: imperative mood, **no AI attribution of any kind** — no
  Co-Authored-By, no session trailers, no tool names.
- **No test may call the real Anthropic API or hit EDGAR.**
- TypeScript `strict` stays on. Do not add `any` to silence an error.
- `dangerouslySetInnerHTML` is permitted for `viewer_html` **only** — the server
  sanitized it at ingestion (design §7). Never use it for any other value.
- Do not add a state management library. Two `useState` objects (design §7).
- Do not add React Testing Library. Components are covered by Playwright;
  adding a third test tool for them is unnecessary.
- Scope: no auth, no chat history, no `year` filter, no virtualization, no dark
  mode. New ideas go to design.md §14.

## File Structure

```
.github/workflows/ci.yml              MODIFY: add a frontend job
backend/src/api/app.py                MODIFY: CORSMiddleware
backend/tests/test_app.py             MODIFY: preflight test
docs/design.md                        MODIFY: §6.4 done-event shape
frontend/
  package.json                        NEW (scaffold): scripts + deps
  vitest.config.ts                    NEW: node default env
  playwright.config.ts                NEW: webServer + testDir
  app/globals.css                     MODIFY: .cited-sentence
  app/page.tsx                        MODIFY: redirect to /ask
  app/ask/page.tsx                    NEW: layout, owns state
  components/ask-form.tsx             NEW
  components/answer-stream.tsx        NEW
  components/citation-chip.tsx        NEW
  components/filing-viewer.tsx        NEW
  lib/types.ts                        NEW: shared types
  lib/sse.ts                          NEW: parseSSE
  lib/answer.ts                       NEW: reduce
  lib/markers.ts                      NEW: splitOnMarkers
  lib/highlight.ts                    NEW: applyHighlight
  lib/api.ts                          NEW: askStream, fetchFiling, fetchCompanies
  lib/__tests__/*.test.ts             NEW: vitest specs
  e2e/highlight.spec.ts               NEW: the exit criterion
```

---

### Task 1: Scaffold the app and its test harness

Everything else depends on this existing. Folded together because none of it is
independently reviewable: a scaffold with no test runner and no CI job is not a
deliverable.

**Files:**
- Delete: `frontend/README.md` (placeholder; `create-next-app` writes its own)
- Create: `frontend/` (scaffold), `frontend/vitest.config.ts`,
  `frontend/lib/types.ts`, `frontend/lib/__tests__/smoke.test.ts`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `npm test` (vitest), `npm run lint`, `npm run test:e2e` scripts;
  the shared types every later task imports.

- [ ] **Step 1: Remove the placeholder README**

`create-next-app` refuses to scaffold into a directory containing files it
would write, and `README.md` is one of them.

```bash
git rm frontend/README.md
```

- [ ] **Step 2: Scaffold**

From the **repo root** (not `frontend/`):

```bash
npx create-next-app@latest frontend --typescript --tailwind --app \
  --no-src-dir --eslint --import-alias "@/*" --use-npm
```

Note: `npx --version` is not a valid command — if you were checking npx exists,
run the real command. Answer "No" to Turbopack if prompted; it is not needed.

Expected: `frontend/package.json`, `frontend/app/`, `frontend/next.config.ts`.

- [ ] **Step 3: Add the test dependencies**

From `frontend/`:

```bash
npm install -D vitest jsdom @playwright/test
npx playwright install chromium
```

`jsdom` is only for `lib/highlight.ts`; every other spec runs in node.

- [ ] **Step 4: Configure vitest**

Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // node by default — only highlight.test.ts opts into jsdom, via a
    // `@vitest-environment jsdom` docblock at the top of that file. Running
    // every spec in jsdom would slow the suite down for no benefit.
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
```

- [ ] **Step 5: Add the scripts**

In `frontend/package.json`, set `"scripts"` to:

```json
{
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "next lint",
  "test": "vitest run",
  "test:e2e": "playwright test"
}
```

- [ ] **Step 6: Add the shared types**

Create `frontend/lib/types.ts`:

```ts
/** One decoded SSE frame from POST /ask. */
export type SSEEvent = { event: string; data: unknown };

/** A citation event, post-verification (design §6.4). */
export type Citation = {
  marker: number;
  verified: boolean;
  accession: string;
  sids: number[];
  quote: string;
};

/** GET /filings/{accession} */
export type Filing = {
  accession: string;
  viewer_html: string;
  ticker: string;
  form_type: string;
  filing_date: string;
  period_end: string | null;
};

/** GET /companies */
export type Company = {
  cik: number;
  ticker: string;
  name: string;
  filings: number;
};
```

- [ ] **Step 7: Write a smoke test**

Create `frontend/lib/__tests__/smoke.test.ts`:

```ts
import { expect, test } from "vitest";

test("vitest runs", () => {
  expect(1 + 1).toBe(2);
});
```

- [ ] **Step 8: Verify the harness**

```bash
npm test
npm run lint
```

Expected: 1 test passes; lint clean.

- [ ] **Step 9: Add the CI job**

In `.github/workflows/ci.yml`, add a second job at the same indentation as
`backend:`:

```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Lint
        run: npm run lint

      - name: Unit tests (vitest)
        run: npm test
```

Stop there. The Playwright steps are added in Task 10, alongside the spec they
run — adding them now would leave CI red on every commit until Task 10 lands.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: scaffold Next.js frontend with vitest, playwright, and CI job"
```

---

### Task 2: CORS on the backend

Without this the browser's preflight on a JSON `POST /ask` fails and the
frontend cannot make a single request. Done early so every later task can talk
to a real backend. Also carries the design.md §6.4 correction, because the
frontend consumes that payload and the spec currently misdescribes it.

**Files:**
- Modify: `backend/src/api/app.py`, `backend/tests/test_app.py`, `docs/design.md`

**Interfaces:**
- Produces: `OPTIONS /ask` answering with `access-control-allow-origin` for the
  configured origin. No Python symbol other tasks import.

- [ ] **Step 1: Write the failing test**

No new imports are needed — `TestClient` and `app` are already imported at the
top of `backend/tests/test_app.py`. Append this to the end of the file:

```python
def test_ask_preflight_allows_the_frontend_origin():
    """The browser sends OPTIONS before a JSON POST cross-origin. Without CORS
    the frontend cannot call /ask at all, and the failure surfaces only in a
    browser — never in pytest — so it is pinned here."""
    with TestClient(app) as client:
        response = client.options(
            "/ask",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
```

This test needs no database, so it runs in CI.

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_app.py::test_ask_preflight_allows_the_frontend_origin -v`
Expected: FAIL — status 405, because no CORS middleware answers OPTIONS.

- [ ] **Step 3: Implement**

In `backend/src/api/app.py`, add to the imports:

```python
import os

from fastapi.middleware.cors import CORSMiddleware
```

and immediately after `app = FastAPI(...)`:

```python
# The browser preflights a JSON POST from another origin. Phase 5 sets
# FRONTEND_ORIGIN to the deployed domain; there is no wildcard here because
# a wildcard plus credentials is rejected by browsers and we may want
# credentials later.
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_app.py -v`
Expected: all pass.

- [ ] **Step 5: Correct design.md §6.4**

In `docs/design.md` §6.4, replace the `done:` line with the shipped shape:

```
done:     {"chunks_retrieved": 8, "citations_total": 3,
           "citations_verified": 3, "unverified_answer": false}
```

`input_tokens` / `output_tokens` were never emitted; `unverified_answer` is.

- [ ] **Step 6: Lint and commit**

```bash
python -m ruff check .
pytest -v
git add src/api/app.py tests/test_app.py ../docs/design.md
git commit -m "feat: allow the frontend origin through CORS"
```

---

### Task 3: `lib/sse.ts` — the SSE frame parser

The single most defect-prone piece in this phase. A TCP chunk boundary can fall
anywhere, including the middle of a `data:` line, so the parser must hand back
whatever it could not consume.

**Files:**
- Create: `frontend/lib/sse.ts`, `frontend/lib/__tests__/sse.test.ts`
- Delete: `frontend/lib/__tests__/smoke.test.ts`

**Interfaces:**
- Consumes: `SSEEvent` from `lib/types.ts`.
- Produces: `parseSSE(buffer: string) → { events: SSEEvent[]; rest: string }`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/__tests__/sse.test.ts`:

```ts
import { expect, test } from "vitest";

import { parseSSE } from "../sse";

test("parses one complete frame", () => {
  const { events, rest } = parseSSE('event: token\ndata: {"text":"hi"}\n\n');
  expect(events).toEqual([{ event: "token", data: { text: "hi" } }]);
  expect(rest).toBe("");
});

test("parses two frames from one buffer", () => {
  const buffer =
    'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n';
  const { events } = parseSSE(buffer);
  expect(events.map((e) => (e.data as { text: string }).text)).toEqual(["a", "b"]);
});

test("returns an incomplete trailing frame as rest", () => {
  const { events, rest } = parseSSE('event: token\ndata: {"text":"a"}\n\nevent: tok');
  expect(events).toHaveLength(1);
  expect(rest).toBe("event: tok");
});

test("a frame split across two chunks parses once rejoined", () => {
  const first = parseSSE('event: citation\ndata: {"marker":1,');
  expect(first.events).toEqual([]);
  const second = parseSSE(first.rest + '"verified":true}\n\n');
  expect(second.events).toEqual([
    { event: "citation", data: { marker: 1, verified: true } },
  ]);
});

test("joins multi-line data before parsing", () => {
  const { events } = parseSSE('event: token\ndata: {"text":\ndata: "hi"}\n\n');
  expect(events[0].data).toEqual({ text: "hi" });
});

test("preserves an unknown event name", () => {
  const { events } = parseSSE('event: heartbeat\ndata: {}\n\n');
  expect(events[0].event).toBe("heartbeat");
});

test("drops a frame whose data is not JSON without losing later frames", () => {
  const { events } = parseSSE('event: token\ndata: not json\n\nevent: done\ndata: {}\n\n');
  expect(events).toEqual([{ event: "done", data: {} }]);
});

test("tolerates CRLF line endings", () => {
  const { events } = parseSSE('event: token\r\ndata: {"text":"hi"}\r\n\r\n');
  expect(events[0].data).toEqual({ text: "hi" });
});

test("an empty buffer yields nothing", () => {
  expect(parseSSE("")).toEqual({ events: [], rest: "" });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test`
Expected: FAIL — cannot resolve `../sse`.

- [ ] **Step 3: Implement**

Create `frontend/lib/sse.ts`:

```ts
import type { SSEEvent } from "./types";

/**
 * Decode as many whole SSE frames as `buffer` contains.
 *
 * Returns the unconsumed remainder as `rest`. The caller must prepend it to
 * the next network chunk: a chunk boundary can fall anywhere, including
 * mid-JSON, and a parser that assumed whole frames would work on localhost
 * and corrupt answers on a slow connection.
 */
export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const segments = normalized.split("\n\n");
  // The last segment is whatever follows the final blank line — either "" or
  // a partial frame. Either way it is not ours to decode yet.
  const rest = segments.pop() ?? "";
  const events: SSEEvent[] = [];

  for (const segment of segments) {
    if (!segment.trim()) continue;
    let name = "message";
    const dataLines: string[] = [];
    for (const line of segment.split("\n")) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) continue;
    try {
      events.push({ event: name, data: JSON.parse(dataLines.join("\n")) });
    } catch {
      // Our server always sends JSON, so this is a corrupt frame. Skipping it
      // beats throwing away every later frame in the same chunk.
    }
  }
  return { events, rest };
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `npm test`
Expected: 9 passed.

- [ ] **Step 5: Remove the smoke test and commit**

```bash
rm lib/__tests__/smoke.test.ts
npm test && npm run lint
git add -A
git commit -m "feat: add SSE frame parser that survives chunk boundaries"
```

---

### Task 4: `lib/answer.ts` — event reduction

Turns the event stream into the one object the left pane renders.

**Files:**
- Create: `frontend/lib/answer.ts`, `frontend/lib/__tests__/answer.test.ts`

**Interfaces:**
- Consumes: `SSEEvent`, `Citation` from `lib/types.ts`.
- Produces: `AnswerState` type, `initialAnswerState`, and
  `reduceAnswer(state: AnswerState, event: SSEEvent) → AnswerState`.

Note: `AnswerState` carries `chunksRetrieved`, which the design doc's §3.3 state
sketch omitted but its §5 error table requires (the "no matching filings" empty
state keys off `chunks_retrieved === 0`).

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/__tests__/answer.test.ts`:

```ts
import { expect, test } from "vitest";

import { initialAnswerState, reduceAnswer } from "../answer";
import type { AnswerState } from "../answer";

function feed(events: Array<[string, unknown]>): AnswerState {
  return events.reduce(
    (state, [event, data]) => reduceAnswer(state, { event, data }),
    initialAnswerState,
  );
}

test("token events concatenate into prose and mark it streaming", () => {
  const state = feed([
    ["token", { text: "Net sales " }],
    ["token", { text: "rose [1]." }],
  ]);
  expect(state.prose).toBe("Net sales rose [1].");
  expect(state.status).toBe("streaming");
});

test("a citation event is stored under its marker", () => {
  const state = feed([
    ["citation", { marker: 1, verified: true, accession: "A", sids: [7], quote: "q" }],
  ]);
  expect(state.citations.get(1)?.sids).toEqual([7]);
});

test("done records counts and finishes", () => {
  const state = feed([
    ["done", {
      chunks_retrieved: 8, citations_total: 1,
      citations_verified: 1, unverified_answer: false,
    }],
  ]);
  expect(state.status).toBe("done");
  expect(state.chunksRetrieved).toBe(8);
  expect(state.notice).toBeNull();
});

test("unverified_answer raises a notice", () => {
  const state = feed([
    ["done", {
      chunks_retrieved: 8, citations_total: 0,
      citations_verified: 0, unverified_answer: true,
    }],
  ]);
  expect(state.notice).not.toBeNull();
});

test("an error keeps the prose already streamed", () => {
  const state = feed([
    ["token", { text: "Partial answer" }],
    ["error", { message: "upstream is down" }],
  ]);
  expect(state.status).toBe("error");
  expect(state.prose).toBe("Partial answer");
  expect(state.errorMessage).toContain("upstream is down");
});

test("an unknown event leaves state untouched", () => {
  const state = feed([["heartbeat", {}]]);
  expect(state).toEqual(initialAnswerState);
});

test("reduce does not mutate the state it was given", () => {
  const next = reduceAnswer(initialAnswerState, { event: "token", data: { text: "x" } });
  expect(initialAnswerState.prose).toBe("");
  expect(next).not.toBe(initialAnswerState);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test`
Expected: FAIL — cannot resolve `../answer`.

- [ ] **Step 3: Implement**

Create `frontend/lib/answer.ts`:

```ts
import type { Citation, SSEEvent } from "./types";

export type AnswerState = {
  prose: string;
  citations: Map<number, Citation>;
  status: "idle" | "streaming" | "done" | "error";
  /** Set only when the model's citation block never parsed (design §10). */
  notice: string | null;
  /** Set only when status is "error". */
  errorMessage: string | null;
  chunksRetrieved: number | null;
};

export const initialAnswerState: AnswerState = {
  prose: "",
  citations: new Map(),
  status: "idle",
  notice: null,
  errorMessage: null,
  chunksRetrieved: null,
};

const UNVERIFIED_NOTICE =
  "The model did not return a usable citation block, so this answer is unverified.";

/** Pure state transition for one SSE event. Never mutates `state`. */
export function reduceAnswer(state: AnswerState, event: SSEEvent): AnswerState {
  switch (event.event) {
    case "token": {
      const { text } = event.data as { text: string };
      return { ...state, prose: state.prose + text, status: "streaming" };
    }
    case "citation": {
      const citation = event.data as Citation;
      // A fresh Map, because React compares by reference to decide re-renders.
      const citations = new Map(state.citations);
      citations.set(citation.marker, citation);
      return { ...state, citations };
    }
    case "done": {
      const data = event.data as {
        chunks_retrieved: number;
        unverified_answer: boolean;
      };
      return {
        ...state,
        status: "done",
        chunksRetrieved: data.chunks_retrieved,
        notice: data.unverified_answer ? UNVERIFIED_NOTICE : null,
      };
    }
    case "error": {
      const { message } = event.data as { message: string };
      // Deliberately keeps `prose`: a partial answer is more useful than a
      // blank pane, and design §10 says an outage is reported, not hidden.
      return { ...state, status: "error", errorMessage: message };
    }
    default:
      return state;
  }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `npm test`
Expected: 16 passed (9 sse + 7 answer).

- [ ] **Step 5: Lint and commit**

```bash
npm run lint
git add lib/answer.ts lib/__tests__/answer.test.ts
git commit -m "feat: reduce ask events into answer state"
```

---

### Task 5: `lib/markers.ts` — splitting prose on citation markers

**Files:**
- Create: `frontend/lib/markers.ts`, `frontend/lib/__tests__/markers.test.ts`

**Interfaces:**
- Produces: `Segment = string | { marker: number }`;
  `splitOnMarkers(text: string) → Segment[]`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/__tests__/markers.test.ts`:

```ts
import { expect, test } from "vitest";

import { splitOnMarkers } from "../markers";

test("text with no marker is one segment", () => {
  expect(splitOnMarkers("Just prose.")).toEqual(["Just prose."]);
});

test("splits around a single marker", () => {
  expect(splitOnMarkers("Sales rose [1].")).toEqual([
    "Sales rose ",
    { marker: 1 },
    ".",
  ]);
});

test("handles a multi-digit marker", () => {
  expect(splitOnMarkers("see [10]")).toEqual(["see ", { marker: 10 }]);
});

test("handles adjacent markers", () => {
  expect(splitOnMarkers("both [1][2] agree")).toEqual([
    "both ",
    { marker: 1 },
    { marker: 2 },
    " agree",
  ]);
});

test("leaves non-numeric brackets alone", () => {
  expect(splitOnMarkers("see Item [1A] here")).toEqual(["see Item [1A] here"]);
});

test("handles a marker at the very start", () => {
  expect(splitOnMarkers("[3] leads")).toEqual([{ marker: 3 }, " leads"]);
});

test("an empty string yields no segments", () => {
  expect(splitOnMarkers("")).toEqual([]);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test`
Expected: FAIL — cannot resolve `../markers`.

- [ ] **Step 3: Implement**

Create `frontend/lib/markers.ts`:

```ts
export type Segment = string | { marker: number };

/**
 * Split answer prose into literal text and citation markers.
 *
 * Markers are `[1]`-style and digits only, so `[1A]` (an Item reference, which
 * appears constantly in filings) stays literal text. The regex is built inside
 * the function so its `lastIndex` can never leak between calls.
 */
export function splitOnMarkers(text: string): Segment[] {
  const pattern = /\[(\d{1,3})\]/g;
  const segments: Segment[] = [];
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) segments.push(text.slice(cursor, index));
    segments.push({ marker: Number(match[1]) });
    cursor = index + match[0].length;
  }
  if (cursor < text.length) segments.push(text.slice(cursor));
  return segments;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `npm test`
Expected: 23 passed.

- [ ] **Step 5: Lint and commit**

```bash
npm run lint
git add lib/markers.ts lib/__tests__/markers.test.ts
git commit -m "feat: split answer prose on citation markers"
```

---

### Task 6: `lib/highlight.ts` — highlighting cited sentences

The only module that touches the DOM, and the reason it does is performance: a
real AAPL 10-K's `viewer_html` is 818 KB, so highlighting must not re-render it.

**Files:**
- Create: `frontend/lib/highlight.ts`, `frontend/lib/__tests__/highlight.test.ts`

**Interfaces:**
- Produces: `HIGHLIGHT_CLASS = "cited-sentence"`;
  `applyHighlight(container: HTMLElement, sids: number[]) → void`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/__tests__/highlight.test.ts`. The docblock on line 1 is
what switches this one file to jsdom:

```ts
/**
 * @vitest-environment jsdom
 */
import { beforeAll, beforeEach, expect, test, vi } from "vitest";

import { HIGHLIGHT_CLASS, applyHighlight } from "../highlight";

beforeAll(() => {
  // jsdom implements no layout, so scrollIntoView does not exist on Element.
  // Without this stub every test here throws TypeError.
  Element.prototype.scrollIntoView = vi.fn();
});

let container: HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  container.innerHTML = `
    <p><span data-sid="10">First.</span></p>
    <p><span data-sid="11">Second.</span></p>
    <p><span data-sid="12">Third.</span></p>`;
});

test("adds the class to every cited sid", () => {
  applyHighlight(container, [10, 12]);
  expect(container.querySelector('[data-sid="10"]')?.className).toBe(HIGHLIGHT_CLASS);
  expect(container.querySelector('[data-sid="12"]')?.className).toBe(HIGHLIGHT_CLASS);
  expect(container.querySelector('[data-sid="11"]')?.className).toBe("");
});

test("clears the previous highlight before applying the next", () => {
  applyHighlight(container, [10]);
  applyHighlight(container, [11]);
  expect(container.querySelector('[data-sid="10"]')?.className).toBe("");
  expect(container.querySelector('[data-sid="11"]')?.className).toBe(HIGHLIGHT_CLASS);
});

test("scrolls the first cited sentence into view", () => {
  applyHighlight(container, [11, 12]);
  const first = container.querySelector('[data-sid="11"]');
  expect(first?.scrollIntoView).toHaveBeenCalledTimes(1);
});

test("an unknown sid highlights nothing and does not throw", () => {
  expect(() => applyHighlight(container, [999])).not.toThrow();
  expect(container.querySelectorAll(`.${HIGHLIGHT_CLASS}`)).toHaveLength(0);
});

test("an empty sid list clears everything", () => {
  applyHighlight(container, [10]);
  applyHighlight(container, []);
  expect(container.querySelectorAll(`.${HIGHLIGHT_CLASS}`)).toHaveLength(0);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npm test`
Expected: FAIL — cannot resolve `../highlight`.

- [ ] **Step 3: Implement**

Create `frontend/lib/highlight.ts`:

```ts
/** Plain global class, defined in app/globals.css. It cannot be a Tailwind
 *  utility: these spans come from dangerouslySetInnerHTML, so Tailwind never
 *  sees them at build time. */
export const HIGHLIGHT_CLASS = "cited-sentence";

/**
 * Highlight the sentences a citation resolves to, inside already-mounted HTML.
 *
 * Operates on the live container rather than rewriting the HTML string,
 * because a real 10-K's viewer_html is ~818 KB — re-parsing that on every
 * citation click would be visibly slow, and regex-over-HTML is fragile.
 * Injection happens once per filing; this runs on every sid change.
 */
export function applyHighlight(container: HTMLElement, sids: number[]): void {
  container
    .querySelectorAll(`.${HIGHLIGHT_CLASS}`)
    .forEach((el) => el.classList.remove(HIGHLIGHT_CLASS));

  // Collected into an array rather than tracked in a `let` that a callback
  // assigns: TypeScript narrows such a variable to `null` at the use site and
  // reports `scrollIntoView` on type `never`.
  const cited: Element[] = [];
  for (const sid of sids) {
    container.querySelectorAll(`[data-sid="${sid}"]`).forEach((el) => {
      el.classList.add(HIGHLIGHT_CLASS);
      cited.push(el);
    });
  }
  cited[0]?.scrollIntoView({ behavior: "smooth", block: "center" });
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `npm test`
Expected: 28 passed.

- [ ] **Step 5: Add the CSS rule**

Append to `frontend/app/globals.css`:

```css
/* Applied imperatively by lib/highlight.ts to spans inside injected viewer
   HTML. Tailwind cannot reach markup React did not author, so this is a
   plain global rule. */
.cited-sentence {
  background-color: #fef08a;
  scroll-margin-top: 4rem;
}
```

- [ ] **Step 6: Lint and commit**

```bash
npm run lint
git add lib/highlight.ts lib/__tests__/highlight.test.ts app/globals.css
git commit -m "feat: highlight cited sentences in mounted viewer HTML"
```

---

### Task 7: `lib/api.ts` — the HTTP client

**Files:**
- Create: `frontend/lib/api.ts`, `frontend/.env.local.example`

**Interfaces:**
- Consumes: `parseSSE`, and `SSEEvent` / `Filing` / `Company` from `lib/types.ts`.
- Produces:
  - `askStream(question, filters?, signal?) → AsyncGenerator<SSEEvent>`
  - `fetchFiling(accession: string) → Promise<Filing>`
  - `fetchCompanies() → Promise<Company[]>`

No unit test here: this module is a thin wrapper whose only logic is the
read-loop, and mocking `fetch` well enough to test it would test the mock. It is
covered end-to-end by Task 10.

- [ ] **Step 1: Record the env var**

Create `frontend/.env.local.example`:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- [ ] **Step 2: Implement**

Create `frontend/lib/api.ts`:

```ts
import { parseSSE } from "./sse";
import type { Company, Filing, SSEEvent } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type AskFilters = { ticker?: string; form_type?: string };

/**
 * Stream POST /ask as decoded SSE events.
 *
 * The browser's built-in EventSource cannot do this: it is GET-only, and /ask
 * takes a JSON body. So we read response.body ourselves and hand each chunk to
 * parseSSE, carrying its unconsumed remainder into the next iteration.
 */
export async function* askStream(
  question: string,
  filters: AskFilters = {},
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const response = await fetch(`${API_URL}/ask`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question, filters }),
    signal,
  });
  if (!response.ok || response.body === null) {
    throw new Error(`Ask failed with status ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // stream: true so a multi-byte character split across chunks survives.
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSSE(buffer);
    buffer = rest;
    for (const event of events) yield event;
  }
}

export async function fetchFiling(accession: string): Promise<Filing> {
  const response = await fetch(`${API_URL}/filings/${accession}`);
  if (!response.ok) throw new Error(`Filing ${accession} unavailable`);
  return (await response.json()) as Filing;
}

export async function fetchCompanies(): Promise<Company[]> {
  const response = await fetch(`${API_URL}/companies`);
  if (!response.ok) throw new Error("Could not load companies");
  return (await response.json()) as Company[];
}
```

- [ ] **Step 3: Verify it compiles**

```bash
npx tsc --noEmit
npm run lint
```

Expected: both clean.

- [ ] **Step 4: Commit**

```bash
git add lib/api.ts .env.local.example
git commit -m "feat: add ask stream and filing HTTP client"
```

---

### Task 8: The answer pane

Left half: the form, the streamed prose, and the chips.

**Files:**
- Create: `frontend/components/citation-chip.tsx`,
  `frontend/components/answer-stream.tsx`, `frontend/components/ask-form.tsx`

**Interfaces:**
- Consumes: `splitOnMarkers`, `AnswerState`, `Citation`, `Company`,
  `fetchCompanies`.
- Produces:
  - `<CitationChip citation={Citation | undefined} marker={number} onSelect={(c: Citation) => void} />`
  - `<AnswerStream state={AnswerState} onSelect={(c: Citation) => void} />`
  - `<AskForm disabled={boolean} onSubmit={(q: string, f: AskFilters) => void} />`

- [ ] **Step 1: The chip**

Create `frontend/components/citation-chip.tsx`:

```tsx
"use client";

import type { Citation } from "@/lib/types";

/**
 * Three states, because the backend sends every token before any citation:
 *  - undefined citation -> inert text, the answer is still streaming
 *  - verified           -> clickable
 *  - unverified         -> visible badge, deliberately NOT clickable
 * A failed citation is never dropped silently (design §6.3).
 */
export function CitationChip({
  marker,
  citation,
  onSelect,
}: {
  marker: number;
  citation: Citation | undefined;
  onSelect: (citation: Citation) => void;
}) {
  if (citation === undefined) {
    return <span className="text-slate-400">[{marker}]</span>;
  }
  if (!citation.verified) {
    return (
      <span
        className="mx-0.5 rounded bg-amber-100 px-1 text-xs text-amber-800"
        title={`Unverified: "${citation.quote}"`}
      >
        [{marker}] unverified
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onSelect(citation)}
      className="mx-0.5 rounded bg-blue-100 px-1 text-xs text-blue-800 hover:bg-blue-200"
      title={citation.quote}
    >
      [{marker}]
    </button>
  );
}
```

- [ ] **Step 2: The answer stream**

Create `frontend/components/answer-stream.tsx`:

```tsx
"use client";

import { CitationChip } from "@/components/citation-chip";
import type { AnswerState } from "@/lib/answer";
import { splitOnMarkers } from "@/lib/markers";
import type { Citation } from "@/lib/types";

export function AnswerStream({
  state,
  onSelect,
}: {
  state: AnswerState;
  onSelect: (citation: Citation) => void;
}) {
  if (state.status === "idle") {
    return <p className="text-slate-500">Ask a question about a filing.</p>;
  }
  if (state.status === "done" && state.chunksRetrieved === 0) {
    return <p className="text-slate-500">No matching filings.</p>;
  }

  return (
    <div>
      {state.errorMessage && (
        <p className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">
          {state.errorMessage}
        </p>
      )}
      {state.notice && (
        <p className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-800">
          {state.notice}
        </p>
      )}
      <p className="whitespace-pre-wrap leading-7">
        {splitOnMarkers(state.prose).map((segment, index) =>
          typeof segment === "string" ? (
            <span key={index}>{segment}</span>
          ) : (
            <CitationChip
              key={index}
              marker={segment.marker}
              citation={state.citations.get(segment.marker)}
              onSelect={onSelect}
            />
          ),
        )}
      </p>
    </div>
  );
}
```

- [ ] **Step 3: The form**

Create `frontend/components/ask-form.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

import { fetchCompanies } from "@/lib/api";
import type { AskFilters } from "@/lib/api";
import type { Company } from "@/lib/types";

export function AskForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (question: string, filters: AskFilters) => void;
}) {
  const [question, setQuestion] = useState("");
  const [ticker, setTicker] = useState("");
  const [formType, setFormType] = useState("");
  const [companies, setCompanies] = useState<Company[]>([]);

  useEffect(() => {
    // A failed company list only costs the filter dropdown, so it must not
    // block asking questions.
    fetchCompanies()
      .then(setCompanies)
      .catch(() => setCompanies([]));
  }, []);

  return (
    <form
      className="mb-6 flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!question.trim()) return;
        onSubmit(question.trim(), {
          ticker: ticker || undefined,
          form_type: formType || undefined,
        });
      }}
    >
      <input
        aria-label="Question"
        className="rounded border px-3 py-2"
        placeholder="What were Apple's total net sales in fiscal 2024?"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      <div className="flex gap-2">
        <select
          aria-label="Company"
          className="rounded border px-2 py-1 text-sm"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
        >
          <option value="">All companies</option>
          {companies.map((company) => (
            <option key={company.cik} value={company.ticker}>
              {company.ticker}
            </option>
          ))}
        </select>
        <select
          aria-label="Form type"
          className="rounded border px-2 py-1 text-sm"
          value={formType}
          onChange={(event) => setFormType(event.target.value)}
        >
          <option value="">All forms</option>
          <option value="10-K">10-K</option>
          <option value="10-Q">10-Q</option>
        </select>
        <button
          type="submit"
          disabled={disabled}
          className="rounded bg-blue-600 px-4 py-1 text-sm text-white disabled:bg-slate-300"
        >
          {disabled ? "Asking…" : "Ask"}
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 4: Verify it compiles and lints**

```bash
npx tsc --noEmit
npm run lint
```

Expected: both clean. (These components are exercised by Task 10, not by unit
tests — see the Global Constraints note on React Testing Library.)

- [ ] **Step 5: Commit**

```bash
git add components/
git commit -m "feat: add ask form, streamed answer, and citation chips"
```

---

### Task 9: The viewer pane and the page

**Files:**
- Create: `frontend/components/filing-viewer.tsx`, `frontend/app/ask/page.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: everything from Tasks 4, 6, 7, 8.
- Produces: the `/ask` route.

- [ ] **Step 1: The viewer**

Create `frontend/components/filing-viewer.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

import { fetchFiling } from "@/lib/api";
import { applyHighlight } from "@/lib/highlight";
import type { Filing } from "@/lib/types";

export function FilingViewer({
  accession,
  sids,
}: {
  accession: string | null;
  sids: number[];
}) {
  const [filing, setFiling] = useState<Filing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fetch keyed on accession only, so clicking a second citation in the same
  // filing does not re-download or re-inject ~818 KB of HTML.
  useEffect(() => {
    if (accession === null) return;
    let cancelled = false;
    setFiling(null);
    setError(null);
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

  // Highlight keyed on sids. React leaves the injected HTML alone when the
  // __html string is unchanged, so the classes we set imperatively survive.
  useEffect(() => {
    if (filing !== null && containerRef.current !== null) {
      applyHighlight(containerRef.current, sids);
    }
  }, [filing, sids]);

  if (accession === null) {
    return (
      <p className="p-6 text-slate-500">
        Click a citation to open the filing here.
      </p>
    );
  }
  if (error !== null) return <p className="p-6 text-red-700">{error}</p>;
  if (filing === null) return <p className="p-6 text-slate-500">Loading filing…</p>;

  return (
    <div className="p-6">
      <h2 className="mb-4 text-sm font-semibold text-slate-600">
        {filing.ticker} {filing.form_type} · filed {filing.filing_date}
      </h2>
      {/* Safe here and only here: this HTML was sanitized by the
          canonicalizer at ingestion, so the server is the sanitizer. */}
      <div ref={containerRef} dangerouslySetInnerHTML={{ __html: filing.viewer_html }} />
    </div>
  );
}
```

- [ ] **Step 2: The page**

Create `frontend/app/ask/page.tsx`:

```tsx
"use client";

import { useState } from "react";

import { AnswerStream } from "@/components/answer-stream";
import { AskForm } from "@/components/ask-form";
import { FilingViewer } from "@/components/filing-viewer";
import { initialAnswerState, reduceAnswer } from "@/lib/answer";
import type { AnswerState } from "@/lib/answer";
import { askStream } from "@/lib/api";
import type { AskFilters } from "@/lib/api";
import type { Citation } from "@/lib/types";

export default function AskPage() {
  const [answer, setAnswer] = useState<AnswerState>(initialAnswerState);
  const [active, setActive] = useState<{
    accession: string | null;
    sids: number[];
  }>({ accession: null, sids: [] });

  async function ask(question: string, filters: AskFilters) {
    setAnswer({ ...initialAnswerState, status: "streaming" });
    setActive({ accession: null, sids: [] });
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
    setActive({ accession: citation.accession, sids: citation.sids });
  }

  return (
    <main className="grid h-screen grid-cols-2">
      <section className="overflow-y-auto p-6">
        <h1 className="mb-4 text-xl font-semibold">EDGAR Answers</h1>
        <AskForm disabled={answer.status === "streaming"} onSubmit={ask} />
        <AnswerStream state={answer} onSelect={select} />
      </section>
      <section className="overflow-y-auto border-l bg-white">
        <FilingViewer accession={active.accession} sids={active.sids} />
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Redirect the root**

Replace the whole contents of `frontend/app/page.tsx` with:

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/ask");
}
```

- [ ] **Step 4: Verify it compiles and runs**

```bash
npx tsc --noEmit
npm run lint
npm run dev
```

With the backend running, open `http://localhost:3000` — it should land on
`/ask` with the company dropdown populated with AAPL. Ctrl-C to stop.

- [ ] **Step 5: Commit**

```bash
git add components/filing-viewer.tsx app/ask/page.tsx app/page.tsx
git commit -m "feat: wire the ask page to the filing viewer"
```

---

### Task 10: The exit-criterion e2e test

Design §12's Phase 4 exit criterion, automated. Stubs both endpoints so the
spec is deterministic and spends nothing.

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/highlight.spec.ts`

**Interfaces:**
- Consumes: the running app. No exports.

- [ ] **Step 1: Configure Playwright**

Create `frontend/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:3000" },
  webServer: {
    // Production build: `next dev` recompiles on first hit and the extra
    // seconds make the first assertion flaky in CI.
    command: "npm run build && npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

- [ ] **Step 2: Write the spec**

Create `frontend/e2e/highlight.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const ACCESSION = "0000320193-24-000123";

const SSE_BODY = [
  'event: token\ndata: {"text":"Total net sales were $391,035 million [1]."}\n\n',
  `event: citation\ndata: {"marker":1,"verified":true,"accession":"${ACCESSION}",`,
  '"sids":[647],"quote":"Total net sales $ 391,035"}\n\n',
  'event: done\ndata: {"chunks_retrieved":8,"citations_total":1,',
  '"citations_verified":1,"unverified_answer":false}\n\n',
].join("");

const VIEWER_HTML = `
  <p><span data-sid="646">Segment information follows.</span></p>
  <p><span data-sid="647">Total net sales $ 391,035 2 % $ 383,285</span></p>
  <p><span data-sid="648">Services set a record.</span></p>`;

test("clicking a verified citation highlights the cited sentence", async ({ page }) => {
  await page.route("**/companies", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        { cik: 320193, ticker: "AAPL", name: "Apple Inc.", filings: 12 },
      ]),
    }),
  );
  await page.route("**/ask", (route) =>
    route.fulfill({ contentType: "text/event-stream", body: SSE_BODY }),
  );
  await page.route(`**/filings/${ACCESSION}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        accession: ACCESSION,
        viewer_html: VIEWER_HTML,
        ticker: "AAPL",
        form_type: "10-K",
        filing_date: "2024-11-01",
        period_end: "2024-09-28",
      }),
    }),
  );

  await page.goto("/ask");
  await page.getByLabel("Question").fill("What were total net sales?");
  await page.getByRole("button", { name: "Ask" }).click();

  // The marker becomes a real button only once its citation event lands.
  const chip = page.getByRole("button", { name: "[1]" });
  await expect(chip).toBeVisible();
  await chip.click();

  const cited = page.locator('[data-sid="647"]');
  await expect(cited).toHaveClass(/cited-sentence/);
  await expect(page.locator('[data-sid="646"]')).not.toHaveClass(/cited-sentence/);
});

test("an unverified citation is badged and not clickable", async ({ page }) => {
  await page.route("**/companies", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.route("**/ask", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body:
        'event: token\ndata: {"text":"Sales fell [1]."}\n\n' +
        'event: citation\ndata: {"marker":1,"verified":false,"accession":"",' +
        '"sids":[],"quote":"fabricated"}\n\n' +
        'event: done\ndata: {"chunks_retrieved":8,"citations_total":1,' +
        '"citations_verified":0,"unverified_answer":false}\n\n',
    }),
  );

  await page.goto("/ask");
  await page.getByLabel("Question").fill("Did sales fall?");
  await page.getByRole("button", { name: "Ask" }).click();

  await expect(page.getByText("[1] unverified")).toBeVisible();
  await expect(page.getByRole("button", { name: "[1]" })).toHaveCount(0);
});
```

- [ ] **Step 3: Run it**

```bash
npm run test:e2e
```

Expected: 2 passed. If the first assertion times out, check that the chip is a
`<button>` — `getByRole("button")` will not match the inert `<span>` state.

- [ ] **Step 4: Add the Playwright steps to CI**

In `.github/workflows/ci.yml`, append to the `frontend` job's `steps`, after
the vitest step:

```yaml
      - name: Install Playwright browser
        run: npx playwright install --with-deps chromium

      - name: E2E (playwright)
        run: npm run test:e2e
```

- [ ] **Step 5: Commit**

```bash
git add playwright.config.ts e2e/ ../.github/workflows/ci.yml
git commit -m "feat: cover click-to-highlight with an end-to-end test"
```

---

### Task 11: Live verification and wrap-up

**Files:**
- Create: `frontend/README.md`
- Modify: `CLAUDE.md` (local only, gitignored — not committed)

- [ ] **Step 1: Run everything**

```bash
# backend/
python -m ruff check . && pytest -v
# frontend/
npm run lint && npm test && npm run test:e2e
```

Expected: all green.

- [ ] **Step 2: Live check against the real stack**

With `docker compose up -d`, uvicorn on 8000, `ANTHROPIC_API_KEY` set, and
`npm run dev` on 3000, open `http://localhost:3000` and ask
"What were Apple's total net sales in fiscal 2024?" with ticker AAPL.

Expected: prose appears incrementally; `[1]` is grey while streaming and turns
into a blue button at the end; clicking it loads the 10-K in the right pane,
scrolls to the cited sentence, and paints it yellow. **This is the Phase 4 exit
criterion.** Cost is a fraction of a cent.

If the chip never turns blue, open devtools and check the `citation` event's
`verified` field before touching the frontend — an unverified citation is a
backend/prompt outcome, not a UI bug.

- [ ] **Step 3: Write the README**

Create `frontend/README.md`:

```markdown
# Frontend

Next.js (App Router) + TypeScript. One page, `/ask`: streamed answer with
citation chips on the left, the original filing with highlighted cited
sentences on the right.

## Running

The backend must be up first (see the repo root README):

    docker compose up -d          # repo root
    python -m uvicorn api.app:app --port 8000   # backend/

Then:

    npm install
    cp .env.local.example .env.local
    npm run dev

## Testing

    npm test          # vitest — lib/ logic, no browser
    npm run test:e2e  # playwright — the click-to-highlight exit criterion

`lib/` holds the logic (SSE parsing, event reduction, marker splitting,
highlighting); components are thin renderers over it. Only `lib/highlight.ts`
touches the DOM.
```

- [ ] **Step 4: Update CLAUDE.md's "Current state"**

Mark Phase 4 complete on `phase4-frontend`, note Phase 5 (full corpus + deploy)
is next. `CLAUDE.md` is gitignored, so this is a local edit with no commit.

- [ ] **Step 5: Commit and open the PR**

```bash
git add README.md
git commit -m "docs: document frontend setup and testing"
git push -u origin phase4-frontend
```

Open the PR against `main` (after Phase 3 has landed).

---

## Verification

Phase 4 is done when all of these hold:

1. `npm run lint` and `npm test` pass in `frontend/`.
2. `npm run test:e2e` passes, including the click-to-highlight spec.
3. Backend `pytest -v` and `ruff check .` still pass, including the new CORS
   preflight test.
4. Live: asking a question streams a visible token-by-token answer, the marker
   upgrades from grey text to a blue chip, and clicking it loads the filing and
   highlights the cited sentence. (Phase 4 exit criterion.)
5. A citation with `verified: false` renders a visible badge and is not
   clickable.
6. `docs/design.md` §6.4 matches the shipped `done` payload.
7. CI is green on both the `backend` and `frontend` jobs.
