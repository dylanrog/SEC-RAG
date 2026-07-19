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
