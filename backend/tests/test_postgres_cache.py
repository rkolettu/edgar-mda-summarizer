import time

import pytest

import cache

pgserver = pytest.importorskip("pgserver")


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    yield server.get_uri()


@pytest.fixture
def pg_cache(pg_url):
    db = cache.PostgresCache(pg_url)
    db.clear()
    return db


RESULT = {
    "ticker": "AAPL",
    "cik": 320193,
    "generated_at": "2026-09-25T15:00:00+00:00",
    "filing": {"form": "10-K", "accession_number": "0000320193-25-000079"},
    "summary": {"revenue_drivers": [{"headline": "Services", "figures": {"detail": [{"start": 0, "verified": True}]}}]},
    "financials": {"kpis": {"revenue": 416.2e9, "revenue_growth": 0.064}},
}


def test_round_trip(pg_cache):
    pg_cache.put("k1", RESULT)
    assert pg_cache.get("k1") == RESULT
    assert pg_cache.get("missing") is None


def test_upsert_replaces(pg_cache):
    pg_cache.put("k1", RESULT)
    pg_cache.put("k1", {**RESULT, "generated_at": "2026-09-26T00:00:00+00:00"})
    assert pg_cache.get("k1")["generated_at"] == "2026-09-26T00:00:00+00:00"
    assert pg_cache.stats()["rows"] == 1


def test_stats_and_clear(pg_cache):
    pg_cache.put("k1", RESULT)
    pg_cache.put("k2", {**RESULT, "ticker": "NVDA"})
    stats = pg_cache.stats()
    assert (stats["backend"], stats["rows"], stats["companies"]) == ("postgres", 2, 2)
    pg_cache.clear()
    assert pg_cache.stats()["rows"] == 0


def test_old_schema_version_is_ignored(pg_cache, monkeypatch):
    pg_cache.put("k1", RESULT)
    monkeypatch.setattr(cache, "SCHEMA_VERSION", cache.SCHEMA_VERSION + 1)
    assert pg_cache.get("k1") is None


def test_unreachable_database_degrades_to_cache_miss():
    db = cache.PostgresCache("postgresql://nobody@127.0.0.1:1/none", connect_timeout=1)
    start = time.perf_counter()
    with pytest.warns(UserWarning):
        assert db.get("k") is None
    with pytest.warns(UserWarning):
        db.put("k", RESULT)
    assert db.stats()["rows"] == 0
    assert time.perf_counter() - start < 10


def test_database_url_selects_postgres(monkeypatch, pg_url):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    assert isinstance(cache.make_cache(), cache.PostgresCache)
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("POSTGRES_URL", pg_url)
    assert isinstance(cache.make_cache(), cache.PostgresCache)
    monkeypatch.delenv("POSTGRES_URL")
    assert isinstance(cache.make_cache(), cache.DatabaseCache)


def test_saved_analysis_is_reused_by_a_fresh_instance(client, fake_sec, fake_gemini, pg_url, monkeypatch):
    import main
    from tests.xbrl_fixture import apple_companyfacts

    fake_sec.add_json("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", apple_companyfacts())
    monkeypatch.setattr(main.cache, "db_cache", cache.PostgresCache(pg_url))
    main.cache.db_cache.clear()

    first = client.get("/api/summarize", params={"ticker": "AAPL"}).json()
    gemini_calls = len(fake_gemini.calls)
    assert gemini_calls == 3

    # A different serverless instance: empty memory, new connection object, same database.
    main.RESULT_CACHE.clear()
    monkeypatch.setattr(main.cache, "db_cache", cache.PostgresCache(pg_url))
    second = client.get("/api/summarize", params={"ticker": "apple"}).json()

    assert len(fake_gemini.calls) == gemini_calls
    assert second == first
    assert main.cache.db_cache.stats()["companies"] == 1
