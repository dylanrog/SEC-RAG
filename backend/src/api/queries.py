from __future__ import annotations

import psycopg

from pipeline.canonicalize import Sentence


def load_chunk_sentences(
    conn: psycopg.Connection, filing_id: int, sid_start: int, sid_end: int
) -> list[Sentence]:
    """The sentences a chunk covers, in document order."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sid, section, text, char_start, char_end FROM sentences"
            " WHERE filing_id = %s AND sid BETWEEN %s AND %s ORDER BY sid",
            (filing_id, sid_start, sid_end),
        )
        return [Sentence(*row) for row in cur.fetchall()]
