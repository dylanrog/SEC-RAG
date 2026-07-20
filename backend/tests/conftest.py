import os

import pytest


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
