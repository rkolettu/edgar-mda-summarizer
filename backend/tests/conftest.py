from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import analysis
import main
import sec

COMPANIES = [
    ("NVDA", "NVIDIA CORP", 1045810),
    ("AAPL", "Apple Inc.", 320193),
    ("MSFT", "MICROSOFT CORP", 789019),
    ("GOOGL", "Alphabet Inc.", 1652044),
    ("AMZN", "AMAZON COM INC", 1018724),
    ("GOOG", "Alphabet Inc.", 1652044),
    ("BRK-B", "BERKSHIRE HATHAWAY INC", 1067983),
    ("JPM", "JPMORGAN CHASE & CO", 19617),
    ("APP", "AppLovin Corp", 1751008),
    ("APH", "AMPHENOL CORP", 820313),
    ("APLE", "Apple Hospitality REIT, Inc.", 1418121),
    ("MA", "Mastercard Inc", 1141391),
]

MDNA_BODY = (
    "Net sales increased 8% to $416.2 billion driven by iPhone and Services. "
    "Services net sales grew 14% year over year to $109.2 billion. "
) * 60


RISK_BODY = (
    "The Company's operations are subject to tariffs imposed on imports from China and India. "
    "Changes in foreign exchange rates could adversely affect net sales and gross margins. "
) * 40


def ten_k_html(mdna_body: str = MDNA_BODY, risk_body: str = RISK_BODY) -> str:
    return f"""<html><head><style>.x{{}}</style></head><body>
    <table>
      <tr><td>Item&nbsp;1A.</td><td>Risk Factors</td><td>5</td></tr>
      <tr><td>Item 7.</td><td>Management&#8217;s Discussion and Analysis of Financial Condition</td><td>20</td></tr>
      <tr><td>Item 8.</td><td>Financial Statements</td><td>30</td></tr>
    </table>
    <p>PART I</p><p>Item 1. Business</p><p>The Company designs smartphones. See Item 1A. Risk Factors for more.</p>
    <p><b>Item 1A. Risk Factors</b></p><p>{risk_body}</p>
    <p>Item 1B. Unresolved Staff Comments</p><p>None.</p>
    <p>Item 1C. Cybersecurity</p><p>The Company maintains a cybersecurity program.</p>
    <p>Item 2. Properties</p><p>Cupertino.</p>
    <p>PART II</p>
    <p><b>Item 7. Management’s Discussion and Analysis</b> of Financial Condition and Results of Operations</p>
    <p>{mdna_body}</p>
    <p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>
    <p><b>Item 8. Financial Statements and Supplementary Data</b></p><p>Balance sheet.</p>
    </body></html>"""


class FakeSEC:
    """Routes requests.get by URL to canned JSON or text responses."""

    def __init__(self):
        self.routes: dict[str, tuple[int, object]] = {}
        self.calls: list[tuple[str, dict]] = []

    def add_json(self, url, payload, status=200):
        self.routes[url] = (status, payload)

    def add_text(self, url, text, status=200):
        self.routes[url] = (status, text)

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers or {}))
        if url not in self.routes:
            status, payload = 404, "not found"
        else:
            status, payload = self.routes[url]
        resp = SimpleNamespace(status_code=status, url=url)
        resp.json = lambda: payload
        resp.text = payload if isinstance(payload, str) else json.dumps(payload)

        def raise_for_status():
            if status >= 400:
                raise requests.HTTPError(f"{status} for {url}")

        resp.raise_for_status = raise_for_status
        return resp


def submissions_payload(name, filings):
    keys = ["form", "accessionNumber", "primaryDocument", "filingDate", "reportDate"]
    recent = {k: [f[k] for f in filings] for k in keys}
    return {"name": name, "filings": {"recent": recent}}


APPLE_FILINGS = [
    {"form": "8-K", "accessionNumber": "0000320193-26-000010", "primaryDocument": "x.htm", "filingDate": "2026-02-01", "reportDate": "2026-02-01"},
    {"form": "10-Q", "accessionNumber": "0000320193-26-000006", "primaryDocument": "aapl-20251227.htm", "filingDate": "2026-01-30", "reportDate": "2025-12-27"},
    {"form": "10-K", "accessionNumber": "0000320193-25-000079", "primaryDocument": "aapl-20250927.htm", "filingDate": "2025-10-31", "reportDate": "2025-09-27"},
    {"form": "10-Q", "accessionNumber": "0000320193-25-000073", "primaryDocument": "aapl-20250628.htm", "filingDate": "2025-08-01", "reportDate": "2025-06-28"},
    {"form": "10-K", "accessionNumber": "0000320193-24-000123", "primaryDocument": "aapl-20240928.htm", "filingDate": "2024-11-01", "reportDate": "2024-09-28"},
]

APPLE_10K_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"


class FakeGemini:
    """Answers generate_content with a canned payload chosen by the requested response schema."""

    def __init__(self):
        self.responses: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.models = self

    def generate_content(self, model, contents, config):
        name = config.response_schema.__name__
        self.calls.append({"model": model, "contents": contents, "config": config, "schema": name})
        return SimpleNamespace(text=json.dumps(self.responses[name]))


def default_analysis():
    insight = {
        "headline": "Services Acceleration",
        "detail": "Services grew 14% to $109.2B.",
        "evidence": "Services net sales grew 14% year over year to $109.2 billion.",
    }
    return {
        "summary": {
            "revenue_drivers": [insight],
            "capital_allocation": [{"headline": "Buybacks", "detail": "Repurchased $90.7B.", "evidence": "The Company repurchased $90.7 billion of its common stock."}],
            "macro_risks": [{"headline": "Tariffs", "detail": "Tariff costs of $1.1B.", "evidence": ""}],
        },
        "charts": {
            "revenue_segments": [{"name": "iPhone", "value": 209.6}, {"name": "Services", "value": 109.2}],
            "capital_deployment": [{"name": "Buybacks", "value": 90.7}],
        },
    }


@pytest.fixture
def fake_sec(monkeypatch):
    fake = FakeSEC()
    tickers = {str(i): {"cik_str": cik, "ticker": t, "title": n} for i, (t, n, cik) in enumerate(COMPANIES)}
    fake.add_json(sec.TICKERS_URL, tickers)
    fake.add_json(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        submissions_payload("Apple Inc.", APPLE_FILINGS),
    )
    fake.add_text(APPLE_10K_URL, ten_k_html())
    monkeypatch.setattr(sec.requests, "get", fake.get)
    sec.load_companies.cache_clear()
    sec.load_ticker_map.cache_clear()
    yield fake
    sec.load_companies.cache_clear()
    sec.load_ticker_map.cache_clear()


@pytest.fixture
def fake_gemini(monkeypatch):
    fake = FakeGemini()
    fake.responses["Analysis"] = default_analysis()
    monkeypatch.setattr(analysis, "get_client", lambda: fake)
    return fake


@pytest.fixture
def client(fake_sec, fake_gemini):
    return TestClient(main.app)
