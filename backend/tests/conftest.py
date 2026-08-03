import os

import pytest

from pipeline.env import load_env

# So TEST_DATABASE_URL can live in backend/.env rather than the machine's
# environment. override=False inside load_env means an exported value still
# wins, and CI — which has no .env — is unaffected.
load_env()


def pytest_collection_modifyitems(config, items):
    skip_db = (
        None
        if os.environ.get("TEST_DATABASE_URL")
        else pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    )
    skip_slow = (
        None
        if os.environ.get("RUN_SLOW_TESTS")
        else pytest.mark.skip(reason="RUN_SLOW_TESTS not set")
    )
    for item in items:
        if skip_db and "db" in item.keywords:
            item.add_marker(skip_db)
        if skip_slow and "slow" in item.keywords:
            item.add_marker(skip_slow)
