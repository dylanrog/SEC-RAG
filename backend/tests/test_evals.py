import json
import os

import psycopg
import pytest

from api.retrieval import RetrievedChunk
from evals import harness
from tests.fakes import FakeEmbedder


def chunk(accession, sid_start, sid_end):
    return RetrievedChunk(1, accession, "10-K", "TSTC", "item1", sid_start, sid_end, "t", 1.0)


def test_hit_requires_matching_accession_and_sid_overlap():
    chunks = [chunk("ACC-1", 10, 20)]
    assert harness.hit(chunks, "ACC-1", [15]) is True
    assert harness.hit(chunks, "ACC-1", [21]) is False
    assert harness.hit(chunks, "ACC-2", [15]) is False


def test_load_golden_validates_fields(tmp_path):
    good = tmp_path / "golden.yaml"
    good.write_text(
        "- id: q001\n"
        "  question: What were net sales?\n"
        "  ticker: AAPL\n"
        '  accession: "0000320193-24-000123"\n'
        "  section: item7\n"
        "  gold_sids: [612, 613]\n",
        encoding="utf-8",
    )
    questions = harness.load_golden(good)
    assert questions[0].id == "q001"
    assert questions[0].gold_sids == [612, 613]

    bad = tmp_path / "bad.yaml"
    bad.write_text("- id: q002\n  question: Missing everything else\n", encoding="utf-8")
    with pytest.raises(ValueError, match="q002"):
        harness.load_golden(bad)


def test_append_results_writes_json_line(tmp_path):
    path = tmp_path / "results.jsonl"
    harness.append_results(path, {"recall@10": 0.9})
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["recall@10"] == 0.9
    assert "git_sha" in record and "timestamp" in record
    # A run against uncommitted code isn't reproducible from its sha, so the
    # log has to say so rather than leave it to be inferred later.
    assert isinstance(record["git_dirty"], bool)


@pytest.mark.db
def test_run_retrieval_eval_end_to_end():
    from datetime import date

    from pipeline import db, store
    from pipeline.canonicalize import CanonicalFiling, Sentence
    from pipeline.chunk import Chunk
    from pipeline.companies import Company
    from pipeline.edgar import FilingRef

    text = "The board approved a quarterly dividend increase of four percent."
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        db.migrate(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chunks WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = 'TESTE-24-000001')"
            )
            cur.execute(
                "DELETE FROM sentences WHERE filing_id IN"
                " (SELECT id FROM filings WHERE accession = 'TESTE-24-000001')"
            )
            cur.execute("DELETE FROM filings WHERE accession = 'TESTE-24-000001'")
        conn.commit()
        company = Company(999999005, "TSTE", "Test Co E")
        sentence = Sentence(0, "item1", text, 0, len(text))
        canonical = CanonicalFiling(
            text, [sentence], f'<p><span data-sid="0">{text}</span></p>'
        )
        ref = FilingRef(
            cik=999999005,
            accession="TESTE-24-000001",
            form_type="10-K",
            filing_date=date(2024, 11, 1),
            period_end=None,
            primary_document="t.htm",
        )
        filing_id = store.store_filing(conn, company, ref, canonical)
        store.store_chunks(
            conn, filing_id, [Chunk("item1", 0, 0, text, 10)],
            FakeEmbedder().embed_texts([text]),
        )

        questions = [
            harness.GoldenQuestion(
                "q001", text, "TSTE", "TESTE-24-000001", "item1", [0]
            ),
            harness.GoldenQuestion(
                "q002", "entirely unrelated basket weaving query", "TSTE",
                "TESTE-24-000001", "item1", [99],  # sid that no chunk covers
            ),
        ]
        metrics = harness.run_retrieval_eval(conn, FakeEmbedder(), questions)
        assert metrics["questions"] == 2
        assert metrics["recall@10"] == 0.5
        assert metrics["misses@10"] == ["q002"]
