import json
from datetime import date
from pathlib import Path

import httpx

from pipeline.edgar import EdgarClient, FilingRef

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
