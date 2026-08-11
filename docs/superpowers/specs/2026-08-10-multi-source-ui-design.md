# Multi-Source Answers + Viewer UI — Design

**Status:** approved, pre-implementation
**Date:** 2026-08-10
**Author:** Dylan Rogers

---

## 1. What this is

An answer that draws on several filings should *say so*, and the reader should be
able to hold two filings open at once while checking it. Today the frontend
collapses every answer to a single filing: the ask page's state is literally
`{accession, sids}` (`app/ask/page.tsx:16-19`) and `FilingViewer` is keyed on one
accession, so opening a second source discards the first.

This project makes multi-filing answers legible. It changes no retrieval
*behavior* — one `SELECT` column is added (§4), but no query, filter, fusion, or
ranking rule moves.

## 2. Scope

| Decision | Choice | Rationale |
|---|---|---|
| Retrieval ranking | **Unchanged** | Keeps a clean baseline for the decomposition work that follows (§8) |
| Sources panel | Grouped by filing | Only place the UI states "this answer rests on N filings" |
| Viewer | Tabs, cap 3, LRU | Two filings genuinely open at once is the point of the feature |
| Theme | Dense utilitarian, dark | Chosen from three mockups; see §5 |
| Filing colors | Selective strip at ingestion | Makes a dark viewer possible without mangling tables (§4) |
| On-demand ingestion | **Out** | Its own spec |
| Golden-set expansion, deploy | **Out** | Phase 5 work, tracked separately |

### 2.1 Why retrieval is deliberately untouched

The tempting adjacent change is to make cross-filing retrieval better. The
evidence says it would be the wrong change *here*:

- The observed failure is not too little filing diversity but too much of the
  wrong kind. Eval `q009` reported excerpts spanning Q1 2024, Q3 2024, Q2 2025,
  Q1 2025, Q1 2026 and Q3 2026 — six-plus distinct filings inside one top-8.
  A per-filing cap or round-robin would not have helped, and would hurt the
  single-filing questions that legitimately want eight chunks from one 10-K.
- `unfiltered_recall@10` sits at 0.75 because *other filers'* boilerplate
  outranks the right chunk. That is a precision problem, not a spread problem.

Both are real, and both are better attacked by the sequence in §8 — where the
eval can attribute the movement — than by entangling them with a UI redesign.

## 3. Backend — pipeline

### 3.1 Selective color strip

`canonicalize.py` currently strips `<style>` **elements** and `on*` handlers
(lines 33-39) but leaves inline `style=` **attributes** intact. One cached
Amazon 10-K carries 9,316 of them, with 6,574 `color:` declarations, nearly all
`color:#000000`. Rendered on a dark pane that is invisible text.

Add one step inside the existing traversal, beside the `on*` removal: for each
element with a `style` attribute, drop the `color`, `background`, and
`background-color` declarations and keep the rest; delete the attribute if
nothing survives.

Colors only — not the whole attribute. EDGAR tables lean on inline
`text-align`, `width`, and `border` for their geometry, and a blanket strip
leaves financial tables as unstyled grids. Losing `background` does cost the
tables their row shading; the viewer supplies its own banding instead (§5).

The step goes in the **existing** pass. A second traversal is exactly the drift
risk design.md §4.2 forbids.

### 3.2 `python -m pipeline recanonicalize`

Re-runs `canonicalize()` over the cached raw HTML in `data/raw/` and issues
`UPDATE filings SET viewer_html = …`. Nothing else is written. Operates on every
stored filing by default, with an optional `--ticker` to narrow it, matching the
`embed` subcommand's shape. A filing whose raw HTML is missing from the cache is
skipped and reported — the command never re-fetches from EDGAR.

This is not a re-ingest. Sentence extraction reads
`block.get_text(" ", strip=True)` over leaf blocks (`canonicalize.py:47`), and a
`style` attribute contributes no text — so sentence strings, `sid` assignment and
`char_start`/`char_end` are invariant under the strip. Therefore: no re-chunking,
no re-embedding of 13,725 chunks, no sid churn (every stored citation and every
pinned `gold_sids` keeps resolving), and no EDGAR traffic, since all 120 filings
are already on disk.

**The command enforces that invariance rather than assuming it.** Per filing it
compares freshly-computed sentences against the stored rows — count, `sid`,
`text`, `char_start`, `char_end` — and on any difference skips the filing and
reports it. Safe to re-run; a mismatch is a loud signal, never a silent
corruption of the anchor the product rests on.

## 4. Backend — API

`retrieval.py` `_BASE` gains `f.filing_date`, carried onto `RetrievedChunk`,
through `VerifiedCitation`, into the SSE event:

```
citation: {marker, verified, accession, ticker, form_type, filing_date, sids, quote}
```

`ticker` and `form_type` already exist on `RetrievedChunk`; only `filing_date` is
new. Without these fields the frontend would issue a `GET /filings/{accession}`
per source purely to draw a label — fetching ~800 KB of HTML to render a date.

One rule added to `SYSTEM_PROMPT`: when excerpts from more than one filing
support the answer, cite each rather than collapsing to whichever ranked first.

This is a change to a measured variable, and should be treated as one. Run the
faithfulness eval before and after the prompt edit, in that order and with no
other change in the tree, so any movement in `verified_rate` or `answered_rate`
is attributable to this single rule. Record both rows in `evals/results.jsonl`.

## 5. Frontend

Logic stays framework-free in `lib/`, components stay thin renderers.

**`lib/sources.ts`** — pure: `Map<marker, Citation>` → ordered source groups
`{accession, ticker, form_type, filing_date, citations[], verifiedCount}`,
ordered by first marker appearance.

**`lib/tabs.ts`** — pure reducer over `{open: accession[], active: accession | null}`
with open / activate / close and **LRU eviction at a cap of 3**. Three filings is
~2.4 MB of live HTML; past that we evict and refetch on reopen.

**Components** — `sources-panel.tsx` (grouped cards), `filing-tabs.tsx` (tab
strip). `filing-viewer.tsx` renders every open tab with inactive ones
`display:none`, which is what preserves per-tab scroll position — the reason for
tabs at all. The `key={accession}` remount in `app/ask/page.tsx:54` is replaced by
tab state.

**Theme** — dense utilitarian dark: tight grid, small type, monospace for tickers
and dates, muted slate, one accent. Applies to the viewer too, which §3.1 makes
possible. The viewer restores table row banding via `nth-child`, replacing the
`background` shading the strip removes.

Inline `[n]` chips in the prose stay exactly as they are — they remain the
direct route from a claim to its sentences.

## 6. Error handling

| Case | Behavior |
|---|---|
| Quote failed to match, chunk known (`verify.py:84`) | Groups under its real filing, badged unverified, not clickable |
| Model cited an unseen chunk (`answer.py:76`, `accession: ""`) | Separate "unattributable" card; opens nothing |
| Filing has only unverified citations | Card still renders — visible failure per design §6.3 — but does not open |
| `GET /filings/{accession}` fails | That tab shows the error; other tabs unaffected |
| Tab cap reached | LRU evict; reopening refetches |

The two unverified cases are distinct in the current code and the panel must not
conflate them: one points at a real filing, the other points nowhere.

## 7. Testing

| Layer | Test |
|---|---|
| Canonicalizer | Fixture: colors stripped, `text-align`/`width`/`border` preserved, emptied `style` attributes removed |
| Canonicalizer | **Invariance fixture**: same input with and without the strip yields equal `Sentence` lists — the test that protects click-to-highlight |
| `recanonicalize` | `@pytest.mark.db`: updates `viewer_html`, leaves chunks untouched, aborts a filing on sentence mismatch |
| `lib/sources.ts` | vitest: two citations one filing, unverified-only filing, empty accession |
| `lib/tabs.ts` | vitest: open, activate, LRU evict, reopen after eviction |
| e2e | Existing two specs stay green; new spec stubs `/ask` with citations across two accessions → two source cards, two tabs, scroll preserved across a switch |

The e2e spec extends the existing `page.route` stubbing in
`e2e/highlight.spec.ts` — no live API, no LLM cost.

## 8. What follows this

1. **This spec** — multi-source UI.
2. **Golden set 16 → 40** (already owed by Phase 5), deliberately including
   comparison and period-specific questions, with `gold_sids` allowed to span
   accessions. Today's metrics all ask "did top-k contain *the* gold sid",
   singular, and so cannot score a multi-filing answer at all.
3. **Query decomposition** — scored against that set.

Ordering matters: decomposition's entire output is a multi-filing answer, so
building it before this spec means not being able to see what it produced, and
before step 2 means not being able to measure it.

## 9. Risk

`recanonicalize`'s invariance check is where time could go: if BeautifulSoup's
serialization of a stripped attribute perturbs whitespace in a way that reaches
`get_text()`, some filings will refuse to update. That is the check working, but
it may need investigation per filing.
