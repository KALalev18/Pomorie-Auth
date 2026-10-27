from collections.abc import Iterator

import psycopg
import pytest

from pomorie.config import get_settings
from pomorie.db import migrate

TEST_DB = "pomorie_test"


@pytest.fixture(scope="session")
def db_dsn() -> Iterator[str]:
    """A freshly migrated throwaway database; skipped when Postgres is not running."""
    settings = get_settings()
    admin_dsn = settings.postgres_dsn
    try:
        admin = psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not available (run: docker compose up -d postgres)")
    with admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    dsn = admin_dsn.rsplit("/", 1)[0] + f"/{TEST_DB}"
    migrate(dsn)
    yield dsn
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture
def conn(db_dsn: str) -> Iterator[psycopg.Connection]:
    """A connection whose work is rolled back after each test."""
    with psycopg.connect(db_dsn) as connection:
        yield connection
        connection.rollback()
