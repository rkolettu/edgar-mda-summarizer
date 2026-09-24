import time

import analysis
from tests.xbrl_fixture import apple_companyfacts

APPLE_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def gemini_calls(fake_gemini, schema=None):
    return [c for c in fake_gemini.calls if schema is None or c["schema"] == schema]


def test_repeat_request_served_from_cache(client, fake_sec, fake_gemini):
    fake_sec.add_json(APPLE_FACTS_URL, apple_companyfacts())
    first = client.get("/api/summarize", params={"ticker": "AAPL"})
    calls_after_first = len(gemini_calls(fake_gemini))
    second = client.get("/api/summarize", params={"ticker": "apple"})
    assert calls_after_first == 3
    assert len(gemini_calls(fake_gemini)) == 3
    assert second.json() == first.json()
    assert first.headers["cache-control"] == "public, max-age=0, s-maxage=86400, stale-while-revalidate=86400"


def test_degraded_result_not_cached(client, fake_sec, fake_gemini):
    fake_sec.add_json(APPLE_FACTS_URL, apple_companyfacts())
    original = fake_gemini.generate_content
    state = {"fail": True}

    def flaky(model, contents, config):
        if config.response_schema is analysis.Changes and state["fail"]:
            raise RuntimeError("quota exceeded")
        return original(model, contents, config)

    fake_gemini.generate_content = flaky
    first = client.get("/api/summarize", params={"ticker": "AAPL"})
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["changes"] is None

    state["fail"] = False
    second = client.get("/api/summarize", params={"ticker": "AAPL"}).json()
    assert second["changes"] is not None


def test_missing_companyfacts_is_not_cached(client, fake_gemini):
    client.get("/api/summarize", params={"ticker": "AAPL"})
    client.get("/api/summarize", params={"ticker": "AAPL"})
    assert len(gemini_calls(fake_gemini, "Analysis")) == 2


def test_new_filing_invalidates_cache(client, fake_sec, fake_gemini):
    fake_sec.add_json(APPLE_FACTS_URL, apple_companyfacts())
    client.get("/api/summarize", params={"ticker": "AAPL"})
    recent = fake_sec.routes["https://data.sec.gov/submissions/CIK0000320193.json"][1]["filings"]["recent"]
    recent["accessionNumber"][1] = "0000320193-26-000099"  # a newer 10-Q
    client.get("/api/summarize", params={"ticker": "AAPL"})
    assert len(gemini_calls(fake_gemini, "Analysis")) == 2


def test_search_is_cacheable(client):
    res = client.get("/api/search", params={"q": "apple"})
    assert "s-maxage=86400" in res.headers["cache-control"]


def test_gemini_calls_run_in_parallel(client, fake_sec, fake_gemini):
    fake_sec.add_json(APPLE_FACTS_URL, apple_companyfacts())
    original = fake_gemini.generate_content

    def slow(model, contents, config):
        time.sleep(0.4)
        return original(model, contents, config)

    fake_gemini.generate_content = slow
    start = time.perf_counter()
    body = client.get("/api/summarize", params={"ticker": "AAPL"}).json()
    elapsed = time.perf_counter() - start
    assert body["changes"] and body["latest_quarter"]
    assert elapsed < 1.0, f"three 0.4s Gemini calls took {elapsed:.2f}s; they should overlap"


def test_main_analysis_failure_returns_quickly(client, fake_gemini):
    original = fake_gemini.generate_content

    def fn(model, contents, config):
        if config.response_schema is analysis.Analysis:
            raise RuntimeError("bad request")
        time.sleep(1.5)
        return original(model, contents, config)

    fake_gemini.generate_content = fn
    start = time.perf_counter()
    res = client.get("/api/summarize", params={"ticker": "AAPL"})
    assert res.status_code == 502
    assert time.perf_counter() - start < 1.0
