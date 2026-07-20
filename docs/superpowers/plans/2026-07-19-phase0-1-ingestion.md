# EDGAR Answers Phases 0–1: Plumbing + Ingestion (Fetch → Canonicalize → Store) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working ingestion pipeline: `python -m pipeline ingest --ticker AAPL` fetches that company's 10-K/10-Q filings from EDGAR, canonicalizes each into sentence-anchored text + sid-annotated viewer HTML, and stores everything in Postgres.

**Architecture:** Batch CLI (`backend/src/pipeline/`) with four stages — fetch (throttled, disk-cached EDGAR client) → canonicalize (single DOM traversal producing aligned canonical text and viewer HTML) → store (Postgres via plain SQL migrations). Chunking/embedding are Phase 2 (separate plan); the schema for them ships now so migration 001 matches the spec.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup4 + lxml, pysbd, psycopg 3, Postgres 16 + pgvector (Docker), pytest, ruff.

**Spec:** `docs/design.md` (§4 pipeline, §5 data model). This plan covers design phases 0 and 1 only. Retrieval+evals, the `/ask` API, and the frontend get their own plans once this one is done.

## Global Constraints

- Python 3.11; run all backend commands from `backend/` (`pip install -e ".[dev]"` to set up).
- `ruff check .` and `pytest -v` must pass before every commit (matches CI).
- Commit messages: imperative mood, **no AI attribution of any kind** — no Co-Authored-By, no Claude-Session trailers, no tool names.
- EDGAR etiquette (spec §4.1): `User-Agent` from `EDGAR_USER_AGENT` env var on every request; ≤5 req/s; raw HTML cached to `backend/data/raw/{cik}/{accession}.html` (already gitignored).
- Embedding dimension is locked at `vector(384)` (bge-small-en-v1.5, spec §2) — migration 001 must use it.
- DB-dependent tests carry `@pytest.mark.db` and skip automatically unless `TEST_DATABASE_URL` is set (CI has no Postgres; that's intentional for now).
- Dev DB URL (docker-compose): `postgresql://user:password@localhost:5432/edgar_answers` (matches `.env.example`).

## File Structure

```
docker-compose.yml                      # NEW: pgvector Postgres for dev
backend/
  pyproject.toml                        # NEW: package metadata, deps, ruff/pytest config
  migrations/001_init.sql               # NEW: full v1 schema (spec §5)
  src/pipeline/__init__.py              # NEW: empty package marker
  src/pipeline/__main__.py              # NEW: CLI (migrate / ingest subcommands)
  src/pipeline/edgar.py                 # NEW: EdgarClient, FilingRef (fetch stage)
  src/pipeline/sections.py              # NEW: SectionTracker (heading → section labels)
  src/pipeline/canonicalize.py          # NEW: canonicalize(), Sentence, CanonicalFiling
  src/pipeline/companies.py             # NEW: curated 10-company list
  src/pipeline/db.py                    # NEW: connect(), migrate()
  src/pipeline/store.py                 # NEW: filing_exists(), store_filing()
  src/pipeline/ingest.py                # NEW: ingest_company() orchestrator, IngestStats
  tests/conftest.py                     # NEW: db-marker auto-skip
  tests/test_sanity.py                  # NEW: package imports
  tests/test_edgar.py                   # NEW: listing, throttle, retry, cache
  tests/test_sections.py                # NEW: SectionTracker unit tests
  tests/test_canonicalize.py            # NEW: fixture-driven canonicalizer tests
  tests/test_db.py                      # NEW: migration tests (db marker)
  tests/test_store.py                   # NEW: store tests (db marker)
  tests/test_ingest.py                  # NEW: orchestrator unit tests (fakes, no db)
  tests/fixtures/submissions_aapl.json  # NEW: trimmed EDGAR submissions payload
  tests/fixtures/mini_10k.html          # NEW: small EDGAR-style filing HTML
```

---

### Task 1: Backend package scaffolding

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/pipeline/__init__.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_sanity.py`

**Interfaces:**
- Consumes: nothing.
- Produces: installable `pipeline` package (src layout); `db` pytest marker with auto-skip; every later task assumes `pip install -e ".[dev]"` has been run from `backend/`.

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "edgar-answers-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "pysbd>=0.3.4",
    "psycopg[binary]>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.5"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["db: requires a running Postgres; set TEST_DATABASE_URL to enable"]
```

- [ ] **Step 2: Create the package marker and conftest**

`backend/src/pipeline/__init__.py` — empty file.

`backend/tests/conftest.py`:

```python
import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 3: Write the sanity test**

`backend/tests/test_sanity.py`:

```python
def test_pipeline_package_imports():
    import pipeline  # noqa: F401
```

- [ ] **Step 4: Install and run**

Run (from `backend/`): `pip install -e ".[dev]"` then `pytest -v` and `ruff check .`
Expected: 1 test PASS; ruff reports no issues.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/src/pipeline/__init__.py backend/tests/conftest.py backend/tests/test_sanity.py
git commit -m "feat: add backend package scaffolding with pytest and ruff"
```

---

### Task 2: Dev Postgres + schema migration 001 + migration runner

**Files:**
- Create: `docker-compose.yml` (repo root)
- Create: `backend/migrations/001_init.sql`
- Create: `backend/src/pipeline/db.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `db.connect(url: str | None = None) -> psycopg.Connection` (defaults to `DATABASE_URL` env); `db.migrate(conn) -> list[str]` (applies pending `backend/migrations/*.sql` in filename order, returns applied names, idempotent via a `schema_migrations` table). Tables `companies`, `filings`, `sentences`, `chunks` exactly as spec §5.

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: edgar_answers
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

- [ ] **Step 2: Write `backend/migrations/001_init.sql`**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE companies (
  cik    bigint PRIMARY KEY,
  ticker text UNIQUE NOT NULL,
  name   text NOT NULL
);

CREATE TABLE filings (
  id          bigserial PRIMARY KEY,
  cik         bigint NOT NULL REFERENCES companies (cik),
  accession   text UNIQUE NOT NULL,
  form_type   text NOT NULL,
  filing_date date NOT NULL,
  period_end  date,
  viewer_html text NOT NULL
);

CREATE TABLE sentences (
  filing_id  bigint NOT NULL REFERENCES filings (id),
  sid        integer NOT NULL,
  section    text NOT NULL,
  text       text NOT NULL,
  char_start integer NOT NULL,
  char_end   integer NOT NULL,
  PRIMARY KEY (filing_id, sid)
);

CREATE TABLE chunks (
  id          bigserial PRIMARY KEY,
  filing_id   bigint NOT NULL REFERENCES filings (id),
  section     text NOT NULL,
  sid_start   integer NOT NULL,
  sid_end     integer NOT NULL,
  text        text NOT NULL,
  token_count integer NOT NULL,
  embedding   vector(384) NOT NULL
);

CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_text_fts ON chunks USING gin (to_tsvector('english', text));
CREATE INDEX filings_cik_idx ON filings (cik);
```

- [ ] **Step 3: Write the failing test**

`backend/tests/test_db.py`:

```python
import os

import psycopg
import pytest

from pipeline import db


@pytest.mark.db
def test_migrate_creates_schema_and_is_idempotent():
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        assert db.migrate(conn) == []  # second run applies nothing
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('companies'), to_regclass('filings'),"
                " to_regclass('sentences'), to_regclass('chunks')"
            )
            assert all(cur.fetchone())
```

- [ ] **Step 4: Start Postgres, create the test database, verify the test fails**

Run (repo root): `docker compose up -d`
Then: `docker compose exec db psql -U user -d edgar_answers -c "CREATE DATABASE edgar_answers_test"`
Then (from `backend/`, PowerShell):
`$env:TEST_DATABASE_URL = "postgresql://user:password@localhost:5432/edgar_answers_test"; pytest tests/test_db.py -v`
Expected: FAIL — `module 'pipeline.db' has no attribute 'migrate'` (module doesn't exist yet).

- [ ] **Step 5: Write `backend/src/pipeline/db.py`**

```python
from __future__ import annotations

import os
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or os.environ["DATABASE_URL"])


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations in filename order; return the names applied."""
    applied: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations"
            " (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        cur.execute("SELECT name FROM schema_migrations")
        done = {row[0] for row in cur.fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    conn.commit()
    return applied
```

- [ ] **Step 6: Run the test, verify it passes**

Run: `pytest tests/test_db.py -v` (with `TEST_DATABASE_URL` still set)
Expected: PASS. Also run `pytest -v` without the env var in a fresh shell to confirm the db test SKIPS.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml backend/migrations/001_init.sql backend/src/pipeline/db.py backend/tests/test_db.py
git commit -m "feat: add dev Postgres, v1 schema migration, and migration runner"
```

---

### Task 3: EDGAR client — listing filings

**Files:**
- Create: `backend/src/pipeline/edgar.py`
- Create: `backend/tests/fixtures/submissions_aapl.json`
- Test: `backend/tests/test_edgar.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FilingRef` frozen dataclass `(cik: int, accession: str, form_type: str, filing_date: date, period_end: date | None, primary_document: str)`; `EdgarClient(user_agent: str, cache_dir: Path, *, client: httpx.Client | None = None, min_interval: float = 0.2, sleep=time.sleep, clock=time.monotonic)` with `list_filings(cik, *, forms=("10-K", "10-Q"), lookback_days=1095, today: date | None = None) -> list[FilingRef]`. Task 4 adds `download_filing` to this same class.

- [ ] **Step 1: Write the fixture**

`backend/tests/fixtures/submissions_aapl.json` (EDGAR's columnar format, trimmed to three filings):

```json
{
  "cik": "320193",
  "filings": {
    "recent": {
      "accessionNumber": ["0000320193-24-000123", "0000320193-24-000081", "0000320193-19-000119"],
      "form": ["10-K", "10-Q", "10-K"],
      "filingDate": ["2024-11-01", "2024-08-02", "2019-10-31"],
      "reportDate": ["2024-09-28", "2024-06-29", "2019-09-28"],
      "primaryDocument": ["aapl-20240928.htm", "aapl-20240629.htm", "a10-k20199282019.htm"]
    }
  }
}
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_edgar.py`:

```python
import json
from datetime import date
from pathlib import Path

import httpx

from pipeline.edgar import EdgarClient

FIXTURES = Path(__file__).parent / "fixtures"


def make_client(handler, tmp_path, **kwargs):
    transport = httpx.MockTransport(handler)
    return EdgarClient(
        user_agent="Test test@example.com",
        cache_dir=tmp_path,
        client=httpx.Client(transport=transport),
        min_interval=0.0,
        clock=lambda: 0.0,
        **kwargs,
    )


def submissions_handler(request):
    assert request.headers["User-Agent"] == "Test test@example.com"
    payload = json.loads((FIXTURES / "submissions_aapl.json").read_text(encoding="utf-8"))
    return httpx.Response(200, json=payload)


def test_list_filings_filters_forms_and_lookback(tmp_path):
    client = make_client(submissions_handler, tmp_path)
    refs = client.list_filings(320193, today=date(2025, 1, 1))
    assert [r.accession for r in refs] == ["0000320193-24-000123", "0000320193-24-000081"]
    ten_k = refs[0]
    assert ten_k.form_type == "10-K"
    assert ten_k.filing_date == date(2024, 11, 1)
    assert ten_k.period_end == date(2024, 9, 28)
    assert ten_k.primary_document == "aapl-20240928.htm"
    assert ten_k.cik == 320193
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_edgar.py -v`
Expected: FAIL — `No module named 'pipeline.edgar'`.

- [ ] **Step 4: Write `backend/src/pipeline/edgar.py`**

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4


@dataclass(frozen=True)
class FilingRef:
    cik: int
    accession: str
    form_type: str
    filing_date: date
    period_end: date | None
    primary_document: str


class EdgarClient:
    """Fetches EDGAR data politely: identifying UA, throttled, retried, disk-cached."""

    def __init__(
        self,
        user_agent: str,
        cache_dir: Path,
        *,
        client: httpx.Client | None = None,
        min_interval: float = 0.2,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self._client = client or httpx.Client(timeout=30.0)
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def _get(self, url: str) -> httpx.Response:
        for attempt in range(_MAX_ATTEMPTS):
            if self._last_request is not None:
                wait = self._last_request + self.min_interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
            response = self._client.get(url, headers={"User-Agent": self.user_agent})
            self._last_request = self._clock()
            if response.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                self._sleep(2**attempt)
                continue
            response.raise_for_status()
            return response
        raise AssertionError("unreachable")

    def list_filings(
        self,
        cik: int,
        *,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
        lookback_days: int = 1095,
        today: date | None = None,
    ) -> list[FilingRef]:
        cutoff = (today or date.today()) - timedelta(days=lookback_days)
        data = self._get(SUBMISSIONS_URL.format(cik=cik)).json()
        recent = data["filings"]["recent"]
        refs: list[FilingRef] = []
        for i, form in enumerate(recent["form"]):
            if form not in forms:
                continue
            filed = date.fromisoformat(recent["filingDate"][i])
            if filed < cutoff:
                continue
            report = recent["reportDate"][i]
            refs.append(
                FilingRef(
                    cik=cik,
                    accession=recent["accessionNumber"][i],
                    form_type=form,
                    filing_date=filed,
                    period_end=date.fromisoformat(report) if report else None,
                    primary_document=recent["primaryDocument"][i],
                )
            )
        return refs
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_edgar.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/pipeline/edgar.py backend/tests/test_edgar.py backend/tests/fixtures/submissions_aapl.json
git commit -m "feat: add EDGAR client with filing listing"
```

---

### Task 4: EDGAR client — throttled, retried, cached downloads

**Files:**
- Modify: `backend/src/pipeline/edgar.py` (add one method to `EdgarClient`)
- Test: `backend/tests/test_edgar.py` (append)

**Interfaces:**
- Consumes: `EdgarClient` and `FilingRef` from Task 3.
- Produces: `EdgarClient.download_filing(ref: FilingRef, *, force: bool = False) -> Path` — writes to `{cache_dir}/{cik}/{accession}.html`, returns the path, and never re-downloads an existing file unless `force=True`. Throttle and retry live in `_get` (Task 3) and are tested here.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_edgar.py`)

```python
from pipeline.edgar import FilingRef

REF = FilingRef(
    cik=320193,
    accession="0000320193-24-000123",
    form_type="10-K",
    filing_date=date(2024, 11, 1),
    period_end=date(2024, 9, 28),
    primary_document="aapl-20240928.htm",
)


def test_download_filing_caches_to_disk(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>10-K</html>")

    client = make_client(handler, tmp_path)
    path = client.download_filing(REF)
    assert path == tmp_path / "320193" / "0000320193-24-000123.html"
    assert path.read_text(encoding="utf-8") == "<html>10-K</html>"
    expected_url = (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019324000123/aapl-20240928.htm"
    )
    assert calls == [expected_url]

    client.download_filing(REF)  # second call: served from cache
    assert len(calls) == 1


def test_get_retries_on_server_errors(tmp_path):
    sleeps = []
    statuses = iter([503, 503, 200])

    def handler(request):
        return httpx.Response(next(statuses), text="ok")

    client = make_client(handler, tmp_path, sleep=sleeps.append)
    response = client._get("https://data.sec.gov/anything")
    assert response.status_code == 200
    assert sleeps == [1, 2]  # exponential backoff: 2**0, 2**1


def test_get_throttles_between_requests(tmp_path):
    sleeps = []
    clock_values = iter([0.0, 0.05, 1.0])

    def handler(request):
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    client = EdgarClient(
        user_agent="Test test@example.com",
        cache_dir=tmp_path,
        client=httpx.Client(transport=transport),
        min_interval=1.0,
        sleep=sleeps.append,
        clock=lambda: next(clock_values),
    )
    client._get("https://data.sec.gov/a")
    client._get("https://data.sec.gov/b")
    assert len(sleeps) == 1
    assert abs(sleeps[0] - 0.95) < 1e-9  # 0.0 + 1.0 - 0.05
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `pytest tests/test_edgar.py -v`
Expected: `test_download_filing_caches_to_disk` FAILS with `'EdgarClient' object has no attribute 'download_filing'`; the two `_get` tests PASS already (the logic shipped in Task 3 — these tests pin it down).

- [ ] **Step 3: Add `download_filing` to `EdgarClient`**

```python
    def download_filing(self, ref: FilingRef, *, force: bool = False) -> Path:
        path = self.cache_dir / str(ref.cik) / f"{ref.accession}.html"
        if path.exists() and not force:
            return path
        url = DOCUMENT_URL.format(
            cik=ref.cik, acc_nodash=ref.accession.replace("-", ""), doc=ref.primary_document
        )
        response = self._get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
        return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_edgar.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/pipeline/edgar.py backend/tests/test_edgar.py
git commit -m "feat: add cached filing downloads with throttle and retry coverage"
```

---

### Task 5: Section tracker

**Files:**
- Create: `backend/src/pipeline/sections.py`
- Test: `backend/tests/test_sections.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SectionTracker(form_type: str)` with `update(block_text: str) -> str` — feed block texts in document order; returns the section label the block belongs to. Labels: `"item1"`, `"item1a"`, `"item7"` … for 10-Ks; `"part1.item2"` style for 10-Qs; `"other"` before any heading is seen. Heading detection only fires on blocks ≤120 chars (spec §4.2 heuristic).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_sections.py`:

```python
from pipeline.sections import SectionTracker


def test_10k_items_ignore_part_headings():
    t = SectionTracker("10-K")
    assert t.update("Cover page text") == "other"
    assert t.update("PART I") == "other"          # part heading itself precedes any item
    assert t.update("Item 1. Business") == "item1"
    assert t.update("The Company designs products.") == "item1"
    assert t.update("Item 1A. Risk Factors") == "item1a"
    assert t.update("ITEM 7A. Quantitative and Qualitative Disclosures") == "item7a"


def test_10q_items_get_part_prefix():
    t = SectionTracker("10-Q")
    t.update("PART I — FINANCIAL INFORMATION")
    assert t.update("Item 2. Management's Discussion and Analysis") == "part1.item2"
    t.update("PART II — OTHER INFORMATION")
    assert t.update("Item 1. Legal Proceedings") == "part2.item1"


def test_long_blocks_never_change_section():
    t = SectionTracker("10-K")
    t.update("Item 7. Management's Discussion and Analysis")
    long_sentence = "Item 1A described risks that " + "very " * 40 + "materially affect us."
    assert t.update(long_sentence) == "item7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sections.py -v`
Expected: FAIL — `No module named 'pipeline.sections'`.

- [ ] **Step 3: Write `backend/src/pipeline/sections.py`**

```python
from __future__ import annotations

import re

_ITEM_RE = re.compile(r"^\s*item\s+(\d{1,2}[a-c]?)\b", re.IGNORECASE)
_PART_RE = re.compile(r"^\s*part\s+(iv|i{1,3})\b", re.IGNORECASE)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_MAX_HEADING_LEN = 120


class SectionTracker:
    """State machine: feed block texts in document order, get each block's section label."""

    def __init__(self, form_type: str):
        self._is_10q = form_type == "10-Q"
        self._part: int | None = None
        self.current = "other"

    def update(self, block_text: str) -> str:
        text = block_text.strip()
        if len(text) <= _MAX_HEADING_LEN:
            part = _PART_RE.match(text)
            if part:
                self._part = _ROMAN[part.group(1).lower()]
                return self.current
            item = _ITEM_RE.match(text)
            if item:
                label = f"item{item.group(1).lower()}"
                if self._is_10q and self._part:
                    label = f"part{self._part}.{label}"
                self.current = label
        return self.current
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sections.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/pipeline/sections.py backend/tests/test_sections.py
git commit -m "feat: add section tracker for 10-K and 10-Q headings"
```

---

### Task 6: Canonicalizer

**Files:**
- Create: `backend/src/pipeline/canonicalize.py`
- Create: `backend/tests/fixtures/mini_10k.html`
- Test: `backend/tests/test_canonicalize.py`

**Interfaces:**
- Consumes: `SectionTracker` from Task 5.
- Produces: `Sentence` frozen dataclass `(sid: int, section: str, text: str, char_start: int, char_end: int)`; `CanonicalFiling` frozen dataclass `(canonical_text: str, sentences: list[Sentence], viewer_html: str)`; `canonicalize(raw_html: str, form_type: str) -> CanonicalFiling`. Invariants later phases rely on: sids are sequential from 0 in document order; `canonical_text[s.char_start:s.char_end] == s.text` (sentences joined with `"\n"`); every sentence appears in `viewer_html` as `<span data-sid="{sid}">` with exactly the sentence text; table text is never extracted; scripts/styles/inline-XBRL are gone.

- [ ] **Step 1: Write the fixture**

`backend/tests/fixtures/mini_10k.html` — hand-built to mimic real EDGAR patterns (inline XBRL, nested divs, bold headings, a table, a script):

```html
<html>
<head><title>FORM 10-K</title><style>p { margin: 0; }</style></head>
<body>
<ix:header><ix:hidden><ix:nonNumeric name="dei:DocumentType">10-K</ix:nonNumeric></ix:hidden></ix:header>
<div><p><b>PART I</b></p></div>
<div><p><b>Item 1. Business</b></p></div>
<div>
  <p>The Company designs <ix:nonNumeric name="x:Products">smartphones</ix:nonNumeric> and related services. It sells its products worldwide.</p>
</div>
<table>
  <tr><td>Item 7</td><td>table text must stay viewer-only</td></tr>
</table>
<p><b>Item 1A. Risk Factors</b></p>
<p>The Company&#8217;s business can be affected by economic conditions. Demand could differ from expectations.</p>
<script>alert("should be stripped")</script>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_canonicalize.py`:

```python
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from pipeline.canonicalize import canonicalize

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def result():
    raw = (FIXTURES / "mini_10k.html").read_text(encoding="utf-8")
    return canonicalize(raw, "10-K")


def test_sentences_extracted_with_sections(result):
    texts = [s.text for s in result.sentences]
    assert "The Company designs smartphones and related services." in texts
    assert "It sells its products worldwide." in texts
    by_text = {s.text: s for s in result.sentences}
    assert by_text["The Company designs smartphones and related services."].section == "item1"
    assert by_text["Demand could differ from expectations."].section == "item1a"


def test_sids_sequential_and_offsets_align(result):
    assert [s.sid for s in result.sentences] == list(range(len(result.sentences)))
    for s in result.sentences:
        assert result.canonical_text[s.char_start:s.char_end] == s.text


def test_viewer_html_spans_align_with_sentences(result):
    viewer = BeautifulSoup(result.viewer_html, "lxml")
    span_tags = viewer.find_all("span", attrs={"data-sid": True})
    spans = {int(el["data-sid"]): el.get_text() for el in span_tags}
    assert len(spans) == len(result.sentences)
    for s in result.sentences:
        assert spans[s.sid] == s.text


def test_tables_are_viewer_only(result):
    assert "table text must stay viewer-only" not in result.canonical_text
    assert "table text must stay viewer-only" in result.viewer_html


def test_scripts_and_xbrl_header_are_stripped(result):
    assert "alert(" not in result.viewer_html
    assert "dei:DocumentType" not in result.viewer_html
    assert "10-K" not in result.canonical_text  # ix:hidden content must not leak into text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_canonicalize.py -v`
Expected: FAIL — `No module named 'pipeline.canonicalize'`.

- [ ] **Step 4: Write `backend/src/pipeline/canonicalize.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import pysbd
from bs4 import BeautifulSoup

from .sections import SectionTracker

_STRIP_TAGS = ["script", "style", "iframe", "object", "embed", "ix:header", "ix:hidden"]
_BLOCK_TAGS = ["p", "li", "div"]


@dataclass(frozen=True)
class Sentence:
    sid: int
    section: str
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class CanonicalFiling:
    canonical_text: str
    sentences: list[Sentence]
    viewer_html: str


def canonicalize(raw_html: str, form_type: str) -> CanonicalFiling:
    """One DOM traversal producing aligned canonical text and sid-annotated viewer HTML."""
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    for tag in soup.find_all(lambda t: t.name is not None and t.name.startswith("ix:")):
        tag.unwrap()
    for el in soup.find_all(True):
        for attr in [a for a in el.attrs if a.lower().startswith("on")]:
            del el.attrs[attr]

    segmenter = pysbd.Segmenter(language="en", clean=False, char_span=True)
    tracker = SectionTracker(form_type)
    sentences: list[Sentence] = []
    cursor = 0

    for block in _leaf_blocks(soup):
        text = " ".join(block.get_text(" ", strip=True).split())
        if not text:
            continue
        section = tracker.update(text)
        block_sentences: list[Sentence] = []
        for span in segmenter.segment(text):
            sent_text = span.sent.strip()
            if not sent_text:
                continue
            start = cursor
            end = start + len(sent_text)
            sid = len(sentences) + len(block_sentences)
            block_sentences.append(Sentence(sid, section, sent_text, start, end))
            cursor = end + 1  # sentences join with "\n" in canonical_text
        if block_sentences:
            _rewrite_block(soup, block, block_sentences)
            sentences.extend(block_sentences)

    canonical_text = "\n".join(s.text for s in sentences)
    body = soup.body if soup.body is not None else soup
    viewer_html = "".join(str(child) for child in body.children)
    return CanonicalFiling(canonical_text, sentences, viewer_html)


def _leaf_blocks(soup: BeautifulSoup):
    for el in soup.find_all(_BLOCK_TAGS):
        if el.find(_BLOCK_TAGS) is not None:
            continue  # container block; its leaf descendants are visited on their own
        if el.find_parent("table") is not None:
            continue  # tables stay viewer-only in v1 (spec §4.2)
        yield el


def _rewrite_block(soup: BeautifulSoup, block, block_sentences: list[Sentence]) -> None:
    """Replace block content with sid-tagged spans. Inline formatting inside a
    paragraph is flattened in v1; block structure and tables are preserved."""
    block.clear()
    for i, s in enumerate(block_sentences):
        span = soup.new_tag("span")
        span["data-sid"] = str(s.sid)
        span.string = s.text
        block.append(span)
        if i < len(block_sentences) - 1:
            block.append(" ")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_canonicalize.py -v`
Expected: PASS. If a pysbd or lxml quirk breaks an assertion, fix the canonicalizer — the fixture defines correct behavior, per the spec's fixture-driven testing strategy. (Known watch-item: lxml lowercases tag names, so `ix:nonNumeric` arrives as `ix:nonnumeric` — the `startswith("ix:")` checks handle that.)

- [ ] **Step 6: Commit**

```bash
git add backend/src/pipeline/canonicalize.py backend/tests/test_canonicalize.py backend/tests/fixtures/mini_10k.html
git commit -m "feat: add canonicalizer producing sentence-anchored text and viewer HTML"
```

---

### Task 7: Store, ingest orchestrator, and CLI

**Files:**
- Create: `backend/src/pipeline/companies.py`
- Create: `backend/src/pipeline/store.py`
- Create: `backend/src/pipeline/ingest.py`
- Create: `backend/src/pipeline/__main__.py`
- Test: `backend/tests/test_store.py`, `backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `db.connect`/`db.migrate` (Task 2), `EdgarClient`/`FilingRef` (Tasks 3–4), `canonicalize`/`CanonicalFiling`/`Sentence` (Task 6).
- Produces: `companies.Company(cik: int, ticker: str, name: str)`, `companies.CURATED: list[Company]`, `companies.by_ticker(ticker: str) -> Company` (raises `KeyError` on unknown); `store.filing_exists(conn, accession: str) -> bool`; `store.store_filing(conn, company, ref, canonical, *, replace: bool = False) -> int` (filing id); `ingest.IngestStats(ingested: int, skipped: int)`; `ingest.ingest_company(company, *, edgar, conn, force: bool = False, accession: str | None = None) -> IngestStats`; CLI `python -m pipeline migrate` and `python -m pipeline ingest --ticker T | --all [--accession A] [--force]`.

- [ ] **Step 1: Write `backend/src/pipeline/companies.py`**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    cik: int
    ticker: str
    name: str


CURATED: list[Company] = [
    Company(320193, "AAPL", "Apple Inc."),
    Company(789019, "MSFT", "Microsoft Corporation"),
    Company(1018724, "AMZN", "Amazon.com, Inc."),
    Company(1652044, "GOOGL", "Alphabet Inc."),
    Company(1326801, "META", "Meta Platforms, Inc."),
    Company(1045810, "NVDA", "NVIDIA Corporation"),
    Company(1318605, "TSLA", "Tesla, Inc."),
    Company(19617, "JPM", "JPMorgan Chase & Co."),
    Company(200406, "JNJ", "Johnson & Johnson"),
    Company(104169, "WMT", "Walmart Inc."),
]


def by_ticker(ticker: str) -> Company:
    for company in CURATED:
        if company.ticker == ticker.upper():
            return company
    raise KeyError(f"unknown ticker: {ticker}")
```

(CIKs are verified implicitly on first real run — a wrong CIK 404s loudly at the submissions endpoint.)

- [ ] **Step 2: Write the failing store test**

`backend/tests/test_store.py`:

```python
import os
from datetime import date

import psycopg
import pytest

from pipeline import db, store
from pipeline.canonicalize import CanonicalFiling, Sentence
from pipeline.companies import Company
from pipeline.edgar import FilingRef

COMPANY = Company(999999001, "TSTA", "Test Co A")
REF = FilingRef(
    cik=999999001,
    accession="TEST-24-000001",
    form_type="10-K",
    filing_date=date(2024, 11, 1),
    period_end=date(2024, 9, 28),
    primary_document="test.htm",
)
CANONICAL = CanonicalFiling(
    canonical_text="First sentence.\nSecond sentence.",
    sentences=[
        Sentence(0, "item1", "First sentence.", 0, 15),
        Sentence(1, "item1", "Second sentence.", 16, 32),
    ],
    viewer_html=(
        '<p><span data-sid="0">First sentence.</span>'
        ' <span data-sid="1">Second sentence.</span></p>'
    ),
)


@pytest.mark.db
def test_store_filing_roundtrip():
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        with conn.cursor() as cur:  # clean slate for reruns
            cur.execute(
                "DELETE FROM sentences WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = %s)",
                (REF.accession,),
            )
            cur.execute("DELETE FROM filings WHERE accession = %s", (REF.accession,))
        conn.commit()

        assert store.filing_exists(conn, REF.accession) is False
        filing_id = store.store_filing(conn, COMPANY, REF, CANONICAL)
        assert store.filing_exists(conn, REF.accession) is True
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sentences WHERE filing_id = %s", (filing_id,))
            assert cur.fetchone()[0] == 2
```

- [ ] **Step 3: Run it to verify it fails**

Run (with `TEST_DATABASE_URL` set): `pytest tests/test_store.py -v`
Expected: FAIL — `No module named 'pipeline.store'`.

- [ ] **Step 4: Write `backend/src/pipeline/store.py`**

```python
from __future__ import annotations

import psycopg

from .canonicalize import CanonicalFiling
from .companies import Company
from .edgar import FilingRef


def filing_exists(conn: psycopg.Connection, accession: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM filings WHERE accession = %s", (accession,))
        return cur.fetchone() is not None


def store_filing(
    conn: psycopg.Connection,
    company: Company,
    ref: FilingRef,
    canonical: CanonicalFiling,
    *,
    replace: bool = False,
) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO companies (cik, ticker, name) VALUES (%s, %s, %s)"
                " ON CONFLICT (cik) DO NOTHING",
                (company.cik, company.ticker, company.name),
            )
            if replace:
                cur.execute(
                    "DELETE FROM sentences WHERE filing_id IN"
                    " (SELECT id FROM filings WHERE accession = %s)",
                    (ref.accession,),
                )
                cur.execute("DELETE FROM filings WHERE accession = %s", (ref.accession,))
            cur.execute(
                "INSERT INTO filings (cik, accession, form_type, filing_date, period_end,"
                " viewer_html) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    company.cik,
                    ref.accession,
                    ref.form_type,
                    ref.filing_date,
                    ref.period_end,
                    canonical.viewer_html,
                ),
            )
            filing_id = cur.fetchone()[0]
            with cur.copy(
                "COPY sentences (filing_id, sid, section, text, char_start, char_end)"
                " FROM STDIN"
            ) as copy:
                for s in canonical.sentences:
                    copy.write_row((filing_id, s.sid, s.section, s.text, s.char_start, s.char_end))
    return filing_id
```

- [ ] **Step 5: Run the store test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 6: Write the failing orchestrator test** (no db needed — fakes only)

`backend/tests/test_ingest.py`:

```python
from datetime import date

from pipeline import ingest
from pipeline.companies import Company
from pipeline.edgar import FilingRef


def ref(accession):
    return FilingRef(
        cik=320193,
        accession=accession,
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        period_end=None,
        primary_document="doc.htm",
    )


class FakeEdgar:
    def __init__(self, refs, filing_path):
        self.refs = refs
        self.filing_path = filing_path
        self.downloads = 0

    def list_filings(self, cik):
        return self.refs

    def download_filing(self, ref, *, force=False):
        self.downloads += 1
        return self.filing_path


def test_ingest_skips_existing_and_stores_new(tmp_path, monkeypatch):
    filing_path = tmp_path / "f.html"
    filing_path.write_text("<html><body><p>One sentence here.</p></body></html>", encoding="utf-8")
    edgar = FakeEdgar([ref("ACC-1"), ref("ACC-2")], filing_path)
    stored = []
    monkeypatch.setattr("pipeline.ingest.store.filing_exists", lambda conn, acc: acc == "ACC-1")
    monkeypatch.setattr(
        "pipeline.ingest.store.store_filing",
        lambda conn, company, ref, canonical, **kw: stored.append(ref.accession) or 1,
    )

    stats = ingest.ingest_company(
        Company(320193, "AAPL", "Apple Inc."), edgar=edgar, conn=None
    )
    assert stats.skipped == 1
    assert stats.ingested == 1
    assert stored == ["ACC-2"]
    assert edgar.downloads == 1
```

- [ ] **Step 7: Run it to verify it fails**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL — `No module named 'pipeline.ingest'`.

- [ ] **Step 8: Write `backend/src/pipeline/ingest.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from . import store
from .canonicalize import canonicalize
from .companies import Company


@dataclass
class IngestStats:
    ingested: int = 0
    skipped: int = 0


def ingest_company(
    company: Company,
    *,
    edgar,
    conn,
    force: bool = False,
    accession: str | None = None,
) -> IngestStats:
    stats = IngestStats()
    for ref in edgar.list_filings(company.cik):
        if accession is not None and ref.accession != accession:
            continue
        if not force and store.filing_exists(conn, ref.accession):
            stats.skipped += 1
            continue
        path = edgar.download_filing(ref, force=force)
        canonical = canonicalize(path.read_text(encoding="utf-8"), ref.form_type)
        store.store_filing(conn, company, ref, canonical, replace=force)
        stats.ingested += 1
    return stats
```

- [ ] **Step 9: Run it to verify it passes**

Run: `pytest tests/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 10: Write `backend/src/pipeline/__main__.py`**

```python
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import companies, db, ingest
from .edgar import EdgarClient


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply pending database migrations")
    p_ingest = sub.add_parser("ingest", help="fetch, canonicalize, and store filings")
    p_ingest.add_argument("--ticker", help="one curated ticker, e.g. AAPL")
    p_ingest.add_argument("--all", action="store_true", help="ingest every curated company")
    p_ingest.add_argument("--accession", help="restrict to a single accession number")
    p_ingest.add_argument("--force", action="store_true", help="re-download and re-store")
    args = parser.parse_args(argv)

    if args.cmd == "migrate":
        with db.connect() as conn:
            applied = db.migrate(conn)
        print(f"applied: {applied if applied else 'nothing to do'}")
        return

    if not args.all and not args.ticker:
        sys.exit("ingest requires --ticker or --all")
    user_agent = os.environ.get("EDGAR_USER_AGENT")
    if not user_agent:
        sys.exit("EDGAR_USER_AGENT is not set (SEC requires an identifying User-Agent)")
    edgar = EdgarClient(user_agent=user_agent, cache_dir=Path("data/raw"))
    targets = companies.CURATED if args.all else [companies.by_ticker(args.ticker)]
    with db.connect() as conn:
        for company in targets:
            stats = ingest.ingest_company(
                company, edgar=edgar, conn=conn, force=args.force, accession=args.accession
            )
            print(f"{company.ticker}: ingested={stats.ingested} skipped={stats.skipped}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 11: Full test suite + lint**

Run: `pytest -v` and `ruff check .`
Expected: all tests PASS (db-marked ones require `TEST_DATABASE_URL`); ruff clean.

- [ ] **Step 12: Real-world smoke run** (manual, PowerShell, from `backend/`)

```powershell
docker compose up -d          # from repo root if not already running
$env:DATABASE_URL = "postgresql://user:password@localhost:5432/edgar_answers"
$env:EDGAR_USER_AGENT = "Dylan Rogers dylanjrogers@proton.me"
python -m pipeline migrate
python -m pipeline ingest --ticker AAPL
```

Expected: `migrate` prints `applied: ['001_init.sql']` (first run); `ingest` prints roughly `AAPL: ingested=12 skipped=0` (10-K/10-Q count over 3 years varies). Spot-check:

```powershell
docker compose exec db psql -U user -d edgar_answers -c "SELECT form_type, count(*) FROM filings GROUP BY 1; SELECT count(*) FROM sentences;"
```

Expected: a few 10-Ks, more 10-Qs, and tens of thousands of sentences. Skim one filing's sentences for garbage (`SELECT text FROM sentences WHERE filing_id = 1 ORDER BY sid LIMIT 20`) — if extraction quality is poor on a real filing, snip the offending HTML pattern into a new fixture and fix the canonicalizer before proceeding.

- [ ] **Step 13: Commit**

```bash
git add backend/src/pipeline/companies.py backend/src/pipeline/store.py backend/src/pipeline/ingest.py backend/src/pipeline/__main__.py backend/tests/test_store.py backend/tests/test_ingest.py
git commit -m "feat: add store, ingest orchestrator, and pipeline CLI"
```

---

## Exit criteria (spec §12, Phases 0–1)

- `pytest` and `ruff check .` green; CI green.
- One real AAPL 10-K ingested end-to-end: sentences + viewer HTML in Postgres, sids aligned (proven by canonicalizer tests + smoke-run spot check).

## Follow-on plans (not in this document)

1. **Phase 2:** chunker + fastembed embeddings + hybrid retrieval (RRF) + retrieval eval harness (`recall@k`).
2. **Phase 3:** FastAPI `/ask` — generation (Claude Haiku), quote verification, SSE streaming.
3. **Phase 4:** Next.js frontend — ask page, filing viewer, citation highlighting.
4. **Phase 5:** full corpus ingestion, 40-question golden set, deployment.
