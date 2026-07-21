from __future__ import annotations

import argparse

from pipeline import db
from pipeline.embed import Embedder

from . import harness


def cmd_run(args) -> None:
    if not args.retrieval_only:
        print("note: faithfulness eval arrives in Phase 3; running retrieval only")
    questions = harness.load_golden()
    with db.connect() as conn:
        if args.debug:
            from api.retrieval import lexical_search, vector_search

            embedder = Embedder()
            for question in questions:
                vec = vector_search(conn, embedder.embed_query(question.question), k=5)
                lex = lexical_search(conn, question.question, k=5)
                print(f"\n{question.id}: {question.question}")
                print("  vector:", [(r[1], r[5], r[6]) for r in vec])
                print("  lexical:", [(r[1], r[5], r[6]) for r in lex])
            return
        metrics = harness.run_retrieval_eval(conn, Embedder(), questions)
    for key, value in metrics.items():
        print(f"{key}: {value}")
    harness.append_results(harness.RESULTS_PATH, metrics)
    print(f"appended to {harness.RESULTS_PATH}")


def cmd_verify(args) -> None:
    """Check every golden entry against the DB: accession exists, sids exist."""
    questions = harness.load_golden()
    failures = 0
    with db.connect() as conn, conn.cursor() as cur:
        for question in questions:
            cur.execute(
                "SELECT id FROM filings WHERE accession = %s", (question.accession,)
            )
            row = cur.fetchone()
            if row is None:
                print(f"FAIL {question.id}: accession {question.accession} not in DB")
                failures += 1
                continue
            filing_id = row[0]
            for sid in question.gold_sids:
                cur.execute(
                    "SELECT text FROM sentences WHERE filing_id = %s AND sid = %s",
                    (filing_id, sid),
                )
                sentence = cur.fetchone()
                if sentence is None:
                    print(f"FAIL {question.id}: sid {sid} not in {question.accession}")
                    failures += 1
                else:
                    print(f"ok  {question.id} sid {sid}: {sentence[0][:90]}")
    if failures:
        raise SystemExit(f"{failures} golden-set problems")
    print(f"all {len(questions)} entries verified")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="evals")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="run the eval harness against DATABASE_URL")
    p_run.add_argument("--retrieval-only", action="store_true")
    p_run.add_argument("--debug", action="store_true", help="print per-arm top results")
    sub.add_parser("verify", help="validate golden entries against the DB")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        cmd_run(args)
    else:
        cmd_verify(args)


if __name__ == "__main__":
    main()
