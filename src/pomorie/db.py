"""Database connections and a minimal forward-only migration runner.

Usage:
    python -m pomorie.db migrate
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from pomorie.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "sql" / "migrations"


def connect(dsn: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(dsn or get_settings().postgres_dsn, autocommit=autocommit)


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


def main() -> int:
    if sys.argv[1:] != ["migrate"]:
        print("usage: python -m pomorie.db migrate")
        return 2
    applied = migrate()
    print(f"applied {len(applied)} migration(s): {', '.join(applied) or 'none pending'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
