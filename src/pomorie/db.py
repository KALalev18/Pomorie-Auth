"""Database connections and a minimal forward-only migration runner.

Usage:
    python -m pomorie.db migrate
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql

from pomorie.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "sql" / "migrations"


def connect(dsn: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(dsn or get_settings().postgres_dsn, autocommit=autocommit)


def wait_for_db(dsn: str | None = None, timeout_s: float = 60) -> None:
    """Postgres restarts once after first-time init; retry until it accepts queries."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with connect(dsn) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def migrate(dsn: str | None = None) -> list[str]:
    """Apply pending ``sql/migrations/*.sql`` files in order, each in its own transaction."""
    applied_now: list[str] = []
    with connect(dsn) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
            " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        conn.commit()
        done = {row[0] for row in conn.execute("SELECT version FROM public.schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.stem in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text("utf-8").encode())
                conn.execute(
                    "INSERT INTO public.schema_migrations (version) VALUES (%s)", [path.stem]
                )
            applied_now.append(path.stem)
    return applied_now


def ensure_dashboard_login(dsn: str | None = None) -> None:
    """Login role for the dashboard, member of analytics_reader; password from the env."""
    settings = get_settings()
    with connect(dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", [settings.dashboard_db_user]
        ).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            sql.SQL("{} ROLE {} LOGIN PASSWORD {} IN ROLE analytics_reader").format(
                sql.SQL(verb),
                sql.Identifier(settings.dashboard_db_user),
                sql.Literal(settings.dashboard_db_password),
            )
            if verb == "CREATE"
            else sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(settings.dashboard_db_user),
                sql.Literal(settings.dashboard_db_password),
            )
        )


def main() -> int:
    if sys.argv[1:] != ["migrate"]:
        print("usage: python -m pomorie.db migrate")
        return 2
    wait_for_db()
    applied = migrate()
    ensure_dashboard_login()
    print(f"applied {len(applied)} migration(s): {', '.join(applied) or 'none pending'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
