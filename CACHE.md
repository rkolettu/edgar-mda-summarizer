# Database Cache Configuration

## Overview

The application uses a two-tier caching strategy to improve performance and reduce API calls:

- **L1 Cache**: In-memory LRU cache (64 items max) for hot-path queries
- **L2 Cache**: SQLite persistent cache for warm restarts and out-of-window repeats
- **L3 Cache**: HTTP CDN (Vercel) for long-lived summaries (24hr)

## Cache Storage

- **Location**: `./data/cache.db` (auto-created on first run)
- **Format**: SQLite3 with JSON columns
- **Size**: Grows with usage; typically <100MB for 1000s of cached filings

## Schema

```sql
CREATE TABLE cache (
    cache_key TEXT PRIMARY KEY,        -- "(cik, accession1, accession2, accession3)"
    schema_version INTEGER NOT NULL,   -- Current: 1
    result JSON NOT NULL,              -- Serialized pipeline result
    created_at TIMESTAMP NOT NULL      -- When cached
);
```

## Cache Keys

Cache keys are tuples of (CIK, current_accession, prior_accession, tenq_accession):
- SEC filing accession numbers are **immutable** once published
- Amended filings get **new accession numbers** (e.g., `/A` suffix)
- No invalidation logic needed; different filings = different keys

## Degraded Results

Results marked as "degraded" (transient errors from SEC or Gemini APIs) are **never persisted** to SQLite. These fail-fast on restart to prevent serving stale data.

## Operations

### Check Cache Stats
```bash
curl http://localhost:8000/api/cache/stats
```

Returns:
```json
{
  "memory_cache_size": 64,
  "memory_cache_items": 12,
  "persistent_cache": {
    "rows": 245,
    "size_bytes": 45283920,
    "schema_version": 1
  }
}
```

### Clear All Caches

**Via CLI (before startup):**
```bash
python main.py --clear-cache
```

**Via API (at runtime):**
```bash
curl -X POST http://localhost:8000/api/cache/clear
```

### Schema Versioning

When the output schema of `analysis.summarize()`, `financials.build_financials()`, or other pipeline functions changes:

1. Increment `SCHEMA_VERSION` in `cache.py`
2. Deploy the new code
3. Old cached records (with old `schema_version`) are automatically ignored
4. New records use the new schema

No migration needed; old records eventually age out as they're re-requested.

## Troubleshooting

### Cache misses after restart
- Expected for queries outside the in-memory LRU window (64 items)
- First request in L1 miss → L2 hit = 5-10ms penalty vs. ~2-3s for full pipeline
- Subsequent requests use L1

### Large cache.db file
- Normal; each filing result is ~100-500KB
- Safe to delete `./data/cache.db` to rebuild from scratch
- Better to use the CLI flag: `python main.py --clear-cache`

### SQLite database locked
- Rare; indicates concurrent access. In production, consider Redis if locking becomes an issue.

## Future Upgrades

**To Redis** (when needed):
- Replace SQLite with Redis for true distributed cache
- Allows cache sharing across multiple app instances
- Requires external Redis service (AWS ElastiCache, local docker, etc.)

**To PostgreSQL** (when needed):
- Better for complex queries, full-text search, or multi-tenant scenarios
- Requires DB migration and connection pooling

For now, SQLite provides the optimal simplicity-to-performance ratio.
