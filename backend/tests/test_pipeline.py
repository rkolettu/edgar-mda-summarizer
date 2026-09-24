import pytest

import analysis
import sec
from tests.conftest import APPLE_10K_URL
from tests.xbrl_fixture import apple_companyfacts

APPLE_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def test_summarize_happy_path(client, fake_sec, fake_gemini):
    res = client.get("/api/summarize", params={"ticker": "apple"}, headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "*"
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["company_name"] == "Apple Inc."
    assert body["filing"]["filing_date"] == "2025-10-31"
    assert body["filing"]["report_date"] == "2025-09-27"
    assert body["filing"]["document_url"] == APPLE_10K_URL
    assert body["filing"]["mdna_source"] == "item7"
    assert body["summary"]["revenue_drivers"][0]["headline"] == "Services Acceleration"


def test_financials_from_xbrl(client, fake_sec):
    fake_sec.add_json(APPLE_FACTS_URL, apple_companyfacts())
    body = client.get("/api/summarize", params={"ticker": "AAPL"}).json()
    assert body["financials"]["kpis"]["revenue"] == pytest.approx(416.2e9)
    assert len(body["financials"]["years"]) == 5
    assert body["charts"]["capital_deployment_source"] == "xbrl"
    assert body["charts"]["capital_deployment"][0] == {"name": "Share Buybacks", "value": pytest.approx(90.7e9)}
    assert body["charts"]["revenue_segments"][0] == {"name": "iPhone", "value": pytest.approx(209.6e9)}
    assert body["warnings"] == []


def test_without_xbrl_falls_back_to_gemini_chart_data(client):
    body = client.get("/api/summarize", params={"ticker": "AAPL"}).json()
    assert body["financials"] is None
    assert body["charts"]["capital_deployment_source"] == "gemini"
    assert body["charts"]["capital_deployment"] == [{"name": "Buybacks", "value": pytest.approx(90.7e9)}]
    assert any("XBRL" in w for w in body["warnings"])


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
