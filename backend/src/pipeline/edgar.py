from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
OVERFLOW_URL = "https://data.sec.gov/submissions/{name}"
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
        # UTC rather than the machine's local date: the lookback window should
        # not shift depending on where the pipeline runs. Callers pass `today`
        # explicitly in tests.
        cutoff = (today or datetime.now(UTC).date()) - timedelta(days=lookback_days)
        data = self._get(SUBMISSIONS_URL.format(cik=cik)).json()
        refs = self._collect(data["filings"]["recent"], cik, forms, cutoff)

        # `recent` holds only the newest ~1000 filings, counted across *every*
        # form type. A filer that submits constantly -- JPM files 424B2/FWP
        # prospectuses daily -- can have under a year of history there, so its
        # in-window 10-K/10-Qs live in these overflow pages instead. Reading
        # `recent` alone truncates such a company silently: no error, just
        # fewer filings than the lookback asked for.
        for page in data["filings"].get("files", []):
            if date.fromisoformat(page["filingTo"]) < cutoff:
                continue  # page ends before the window; nothing in it can match
            block = self._get(OVERFLOW_URL.format(name=page["name"])).json()
            refs.extend(self._collect(block, cik, forms, cutoff))
        return refs

    def _collect(
        self,
        block: dict[str, list],
        cik: int,
        forms: tuple[str, ...],
        cutoff: date,
    ) -> list[FilingRef]:
        """Pull in-window filings out of one submissions column-array block.

        `recent` and each overflow page share this shape -- parallel arrays
        keyed by field name -- so both are read the same way.
        """
        refs: list[FilingRef] = []
        for i, form in enumerate(block["form"]):
            if form not in forms:
                continue
            filed = date.fromisoformat(block["filingDate"][i])
            if filed < cutoff:
                continue
            report = block["reportDate"][i]
            refs.append(
                FilingRef(
                    cik=cik,
                    accession=block["accessionNumber"][i],
                    form_type=form,
                    filing_date=filed,
                    period_end=date.fromisoformat(report) if report else None,
                    primary_document=block["primaryDocument"][i],
                )
            )
        return refs

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
