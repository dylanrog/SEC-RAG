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
