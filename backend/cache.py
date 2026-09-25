from __future__ import annotations

import json
import os
import sqlite3
import threading
import warnings
from datetime import datetime
from pathlib import Path

# Bump when the saved result shape or meaning changes; older rows are then ignored and recomputed.
# 2: 20-F filings carry a detected reporting currency (non-USD charts omitted).
SCHEMA_VERSION = 2
# Vercel's deployment filesystem is read-only; /tmp is the only writable location there (per instance).
CACHE_DB = Path(
    os.environ.get("CACHE_DB_PATH")
    or ("/tmp/edgar-cache.db" if os.environ.get("VERCEL") else Path(__file__).parent.parent / "data" / "cache.db")
)


class DatabaseCache:
    """SQLite-backed persistent cache for pipeline results."""

    def __init__(self, db_path: Path = CACHE_DB):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache (
                        cache_key TEXT PRIMARY KEY,
                        schema_version INTEGER NOT NULL,
                        result JSON NOT NULL,
                        created_at TIMESTAMP NOT NULL
                    )
                    """
                )
                conn.commit()
        except (OSError, sqlite3.Error) as e:
            # Cache unavailable (read-only filesystem or permission issue)
            # App still works, just without L2 cache
            import warnings
            warnings.warn(f"Cache initialization failed: {e}. Continuing without persistent cache.")

    def get(self, key: str) -> dict | None:
        """Retrieve cached result by key. Returns None if key missing or schema mismatch."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute(
                        "SELECT result, schema_version FROM cache WHERE cache_key = ?",
                        (key,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    result_json, cached_version = row
                    if cached_version != SCHEMA_VERSION:
                        return None
                    return json.loads(result_json)
        except (OSError, sqlite3.Error):
            # Cache unavailable; return None to fall through to pipeline
            return None

    def put(self, key: str, value: dict) -> None:
        """Store result in cache with current schema version."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO cache
                        (cache_key, schema_version, result, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            key,
                            SCHEMA_VERSION,
                            json.dumps(value),
                            datetime.utcnow().isoformat(),
                        ),
                    )
                    conn.commit()
        except (OSError, sqlite3.Error):
            # Cache unavailable; silently skip persistence
            pass

    def clear(self) -> None:
        """Wipe all cached data."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("DELETE FROM cache")
                    conn.commit()
        except (OSError, sqlite3.Error):
            pass

    def stats(self) -> dict:
        """Return cache statistics."""
        try:
            with self._lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM cache")
                    count = cursor.fetchone()[0]
                    cursor = conn.execute(
                        "SELECT SUM(LENGTH(result)) FROM cache"
                    )
                    size_bytes = cursor.fetchone()[0] or 0
                    return {
                        "rows": count,
                        "size_bytes": size_bytes,
                        "schema_version": SCHEMA_VERSION,
                    }
        except (OSError, sqlite3.Error):
            return {
                "rows": 0,
                "size_bytes": 0,
                "schema_version": SCHEMA_VERSION,
                "error": "cache unavailable",
            }


class PostgresCache:
    """Postgres-backed store that survives deploys and is shared by every server instance.

    Same interface as DatabaseCache. Errors are swallowed so a database outage only costs a cache miss.
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS analyses (
            cache_key TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            ticker TEXT,
            cik INTEGER,
            form TEXT,
            accession_number TEXT,
            generated_at TIMESTAMPTZ,
            result JSONB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS analyses_ticker_idx ON analyses (ticker);
    """

    def __init__(self, url: str, connect_timeout: int = 5):
        self.url = url
        self.connect_timeout = connect_timeout
        self._schema_ready = False
        self._lock = threading.Lock()

    def _connect(self):
        import psycopg

        conn = psycopg.connect(self.url, connect_timeout=self.connect_timeout, autocommit=True)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    conn.execute(self.SCHEMA)
                    self._schema_ready = True
        return conn

    def get(self, key: str) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT result FROM analyses WHERE cache_key = %s AND schema_version = %s",
                    (key, SCHEMA_VERSION),
                ).fetchone()
            return row[0] if row else None
        except Exception as exc:
            warnings.warn(f"Postgres cache read failed: {exc!r}")
            return None

    def put(self, key: str, value: dict) -> None:
        try:
            from psycopg.types.json import Jsonb

            filing = value.get("filing") or {}
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO analyses (cache_key, schema_version, ticker, cik, form, accession_number, generated_at, result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cache_key) DO UPDATE
                        SET schema_version = EXCLUDED.schema_version, generated_at = EXCLUDED.generated_at,
                            result = EXCLUDED.result
                    """,
                    (
                        key, SCHEMA_VERSION, value.get("ticker"), value.get("cik"), filing.get("form"),
                        filing.get("accession_number"), value.get("generated_at"), Jsonb(value),
                    ),
                )
        except Exception as exc:
            warnings.warn(f"Postgres cache write failed: {exc!r}")

    def clear(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM analyses")
        except Exception as exc:
            warnings.warn(f"Postgres cache clear failed: {exc!r}")

    def stats(self) -> dict:
        try:
            with self._connect() as conn:
                count, size_bytes, companies = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(pg_column_size(result)), 0), COUNT(DISTINCT ticker) FROM analyses"
                ).fetchone()
            return {
                "backend": "postgres",
                "rows": count,
                "companies": companies,
                "size_bytes": int(size_bytes),
                "schema_version": SCHEMA_VERSION,
            }
        except Exception as exc:
            return {"backend": "postgres", "rows": 0, "size_bytes": 0, "schema_version": SCHEMA_VERSION, "error": repr(exc)}


def database_url() -> str | None:
    # Vercel's Neon/Postgres integrations set DATABASE_URL and/or POSTGRES_URL.
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def make_cache():
    url = database_url()
    return PostgresCache(url) if url else DatabaseCache()


db_cache = make_cache()
