import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
CACHE_DB = Path(__file__).parent.parent / "data" / "cache.db"


class DatabaseCache:
    """SQLite-backed persistent cache for pipeline results."""

    def __init__(self, db_path: Path = CACHE_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
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

    def get(self, key: str) -> dict | None:
        """Retrieve cached result by key. Returns None if key missing or schema mismatch."""
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

    def put(self, key: str, value: dict) -> None:
        """Store result in cache with current schema version."""
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

    def clear(self) -> None:
        """Wipe all cached data."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM cache")
                conn.commit()

    def stats(self) -> dict:
        """Return cache statistics."""
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


# Singleton instance
db_cache = DatabaseCache()
