from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from api.retrieval import RetrievedChunk, retrieve

GOLDEN_PATH = Path(__file__).parent / "golden.yaml"
RESULTS_PATH = Path(__file__).parent / "results.jsonl"
_REQUIRED = ("id", "question", "ticker", "accession", "section", "gold_sids")


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    question: str
    ticker: str
    accession: str
    section: str
    gold_sids: list[int]


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenQuestion]:
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    questions = []
    for entry in entries:
        entry_id = entry.get("id", "<missing id>")
        for field in _REQUIRED:
            if field not in entry:
                raise ValueError(f"golden entry {entry_id}: missing field {field!r}")
        if not isinstance(entry["gold_sids"], list) or not all(
            isinstance(s, int) for s in entry["gold_sids"]
        ):
            raise ValueError(f"golden entry {entry_id}: gold_sids must be a list of ints")
        questions.append(GoldenQuestion(*(entry[f] for f in _REQUIRED)))
    return questions


def hit(chunks: list[RetrievedChunk], accession: str, gold_sids: list[int]) -> bool:
    return any(
        chunk.accession == accession
        and any(chunk.sid_start <= sid <= chunk.sid_end for sid in gold_sids)
        for chunk in chunks
    )


def _score(conn, embedder, questions, *, ks, k_each: int, scoped: bool) -> dict:
    """Recall over one retrieval arm; `scoped` applies each question's ticker."""
    top_k = max(ks)
    hits_at = {k: 0 for k in ks}
    misses_at_top: list[str] = []
    for question in questions:
        chunks = retrieve(
            conn,
            embedder,
            question.question,
            k_each=k_each,
            k_final=top_k,
            **({"ticker": question.ticker} if scoped else {}),
        )
        for k in ks:
            if hit(chunks[:k], question.accession, question.gold_sids):
                hits_at[k] += 1
        if not hit(chunks, question.accession, question.gold_sids):
            misses_at_top.append(question.id)
    n = len(questions)
    scores: dict = {f"recall@{k}": round(hits_at[k] / n, 4) if n else 0.0 for k in ks}
    scores[f"misses@{top_k}"] = misses_at_top
    return scores


def run_retrieval_eval(conn, embedder, questions, *, ks=(5, 10), k_each: int = 20) -> dict:
    """Score retrieval twice: scoped to each question's ticker, and unscoped.

    The scoped arm measures the retriever itself, and is what the unprefixed
    keys have always meant -- on the single-company corpus these numbers were
    first taken against, the two arms were identical by construction. The
    unfiltered arm measures what a user gets when they leave the ticker filter
    empty on /ask, where every other filer's boilerplate competes for the same
    ten slots. Reporting only one of them hides a real behavior: the golden
    set requires a ticker, so scoping is legitimate, but most gold sentences
    are generic enough that unscoped retrieval loses them.
    """
    metrics: dict = {"questions": len(questions), "k_each": k_each}
    metrics |= _score(conn, embedder, questions, ks=ks, k_each=k_each, scoped=True)
    unfiltered = _score(conn, embedder, questions, ks=ks, k_each=k_each, scoped=False)
    metrics |= {f"unfiltered_{key}": value for key, value in unfiltered.items()}
    return metrics


def _git(*args: str) -> str:
    # check=False is the intent: a failed git call (no repo, detached state)
    # degrades to "" below rather than aborting an eval run.
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def append_results(path: Path, metrics: dict) -> None:
    # git_dirty matters as much as git_sha: an eval run against a working tree
    # with uncommitted changes is not reproducible from its recorded sha, and
    # a results log that can't be replayed is worse than no log. Recording the
    # flag makes that visible in the file instead of inferrable from commit
    # timestamps.
    record = {
        "git_sha": _git("rev-parse", "--short", "HEAD") or "unknown",
        "git_dirty": bool(_git("status", "--porcelain")),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        **metrics,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
