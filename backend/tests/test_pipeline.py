import analysis
import sec
from tests.conftest import APPLE_10K_URL


def test_summarize_happy_path(client, fake_sec, fake_gemini):
    res = client.get("/api/summarize", params={"ticker": "apple"}, headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "*"
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["company_name"] == "Apple Inc."
    assert body["filing_date"] == "2025-10-31"
    assert body["report_date"] == "2025-09-27"
    assert body["document_url"] == APPLE_10K_URL
    assert body["extraction_method"] == "item7"
    assert body["summary"]["revenue_drivers"][0]["headline"] == "Services Acceleration"


def test_every_sec_request_sends_user_agent(client, fake_sec):
    client.get("/api/summarize", params={"ticker": "AAPL"})
    assert fake_sec.calls
    for _, headers in fake_sec.calls:
        assert headers["User-Agent"] == "RishabKolettu InvestmentResearch (rishab@example.com)"


def test_gemini_gets_item7_not_table_of_contents(client, fake_gemini):
    client.get("/api/summarize", params={"ticker": "AAPL"})
    call = fake_gemini.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert call["config"].response_mime_type == "application/json"
    mdna = call["contents"].split("--- BEGIN 10-K MD&A ---")[1]
    assert mdna.strip().startswith("Item 7. Management's Discussion and Analysis of Financial Condition and Results")
    assert "Item 8. Financial Statements and Supplementary Data" not in mdna


def test_unknown_ticker_404(client):
    res = client.get("/api/summarize", params={"ticker": "ZZZZ"})
    assert res.status_code == 404


def test_unexpected_error_keeps_cors_headers(client, monkeypatch):
    def boom(_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(sec, "html_to_text", boom)
    res = client.get("/api/summarize", params={"ticker": "AAPL"}, headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 500
    assert res.headers["access-control-allow-origin"] == "*"
    assert "kaboom" in res.json()["detail"]


def test_missing_gemini_key(fake_sec, monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    analysis.get_client.cache_clear()
    res = TestClient(main.app).get("/api/summarize", params={"ticker": "AAPL"})
    assert res.status_code == 500
    assert "GEMINI_API_KEY" in res.json()["detail"]
