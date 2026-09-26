"""Postgres connections and versioned migrations for the research store."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_migrated: set[str] = set()
_lock = threading.Lock()


def database_url() -> str | None:
    # Vercel's Neon integration sets DATABASE_URL and/or POSTGRES_URL.
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def connect(url: str | None = None, *, migrate: bool = True) -> psycopg.Connection:
    url = url or database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set; the research store requires Postgres.")
    # Neon's pooled endpoints run PgBouncer in transaction mode, where server-side prepared statements can land on
    # another backend, so never prepare. Autocommit keeps a long ingest from holding a transaction open; writes that
    # must be atomic use conn.transaction().
    conn = psycopg.connect(url, connect_timeout=10, prepare_threshold=None, autocommit=True)
    if migrate and url not in _migrated:
        with _lock:
            if url not in _migrated:
                apply_migrations(conn)
                _migrated.add(url)
    return conn


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Applies pending NNN_name.sql files in order, each at most once, under a lock so parallel cold starts agree."""
    applied = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('research_migrations'))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(path.name[:3])
            if version in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (%s, %s)", (version, path.stem))
            applied.append(path.stem)
    return applied
