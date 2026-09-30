"""Database connection and the SQL migration runner."""

from __future__ import annotations

from pathlib import Path

import psycopg

from jobintel.config import PROJECT_ROOT, get_settings

MIGRATIONS_DIR = PROJECT_ROOT / "sql" / "migrations"


def connect(database_url: str | None = None) -> psycopg.Connection:
    url = database_url or get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    return psycopg.connect(url)


def migrate(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in filename order. Returns the names applied."""
    with conn.transaction():
        conn.execute("create schema if not exists ops")
        conn.execute(
            """create table if not exists ops.schema_migrations (
                   filename text primary key,
                   applied_at timestamptz not null default now())"""
        )
    applied = {r[0] for r in conn.execute("select filename from ops.schema_migrations")}
    done = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into ops.schema_migrations (filename) values (%s)", (path.name,))
        done.append(path.name)
    return done
