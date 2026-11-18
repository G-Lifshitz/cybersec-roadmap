"""Shared test setup.

Unit tests need nothing. Tests marked `db` run the real models against a SQL
Server test database named by TEST_DATABASE_URL (CI starts SQL Server as a
service container; locally the compose stack has one). Without it they skip.
CI never points this at Azure SQL (A2 §5).
"""
import os

import pytest

os.environ.setdefault("TOKEN_SECRET", "test-secret-" + "x" * 32)
os.environ.setdefault("DB_CONNECT_DEADLINE_S", "5")

TEST_DB = os.environ.get("TEST_DATABASE_URL")
TABLES = ("progress_logs",)


def pytest_collection_modifyitems(config, items):
    if TEST_DB:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated():
    os.environ["DATABASE_URL"] = TEST_DB
    import migrate
    migrate.run()
    return migrate


@pytest.fixture
def clean_db(migrated):
    import db
    with db.transaction() as cur:
        for table in TABLES:
            cur.execute(f"DELETE FROM {table}")
    yield
