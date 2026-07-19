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
