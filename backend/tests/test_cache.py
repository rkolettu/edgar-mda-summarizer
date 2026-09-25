from pathlib import Path

import cache


def test_unwritable_location_does_not_crash_startup():
    # A path under a regular file can't be created even by root, like Vercel's read-only filesystem.
    db = cache.DatabaseCache(Path("/dev/null/nope/cache.db"))
    assert db.get("k") is None
    db.put("k", {"a": 1})
    assert db.stats()["rows"] == 0


def test_round_trip(tmp_path):
    db = cache.DatabaseCache(tmp_path / "sub" / "cache.db")
    db.put("k", {"ticker": "AAPL"})
    assert db.get("k") == {"ticker": "AAPL"}


def test_uses_tmp_on_vercel(monkeypatch):
    import importlib

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("CACHE_DB_PATH", raising=False)
    try:
        assert str(importlib.reload(cache).CACHE_DB) == "/tmp/edgar-cache.db"
    finally:
        monkeypatch.delenv("VERCEL")
        importlib.reload(cache)


def test_repeat_search_served_from_persistent_cache(client, fake_sec, fake_gemini):
    import main
    from tests.xbrl_fixture import apple_companyfacts

    fake_sec.add_json("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", apple_companyfacts())
    client.get("/api/summarize", params={"ticker": "AAPL"})
    calls = len(fake_gemini.calls)
    main.RESULT_CACHE.clear()  # simulate a fresh serverless instance
    body = client.get("/api/summarize", params={"ticker": "AAPL"}).json()
    assert body["ticker"] == "AAPL"
    assert len(fake_gemini.calls) == calls
