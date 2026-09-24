import pytest

import analysis
import financials
from tests.conftest import APPLE_10Q_URL
from tests.xbrl_fixture import B, apple_companyfacts

APPLE_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def get(client):
    return client.get("/api/summarize", params={"ticker": "AAPL"}).json()


def test_quarter_metrics_from_xbrl():
    q = financials.build_quarter(apple_companyfacts(), "2025-12-27")
    assert q["fiscal_period"] == "Q1" and q["fiscal_year"] == 2026
    assert q["revenue"] == pytest.approx(138.4 * B)
    assert q["revenue_prior"] == pytest.approx(124.3 * B)
    assert q["revenue_growth"] == pytest.approx(138.4 / 124.3 - 1)
    assert q["net_income_growth"] == pytest.approx(42.1 / 36.3 - 1)
    assert q["eps_diluted"] is None and q["eps_diluted_growth"] is None


def test_quarter_metrics_absent_for_unknown_period():
    assert financials.build_quarter(apple_companyfacts(), "2026-03-28") is None


def test_latest_quarter_section(client, fake_sec, fake_gemini):
    fake_sec.add_json(APPLE_FACTS_URL, apple_companyfacts())
    body = get(client)
    lq = body["latest_quarter"]
    assert lq["filing"] == {
        "form": "10-Q",
        "filing_date": "2026-01-30",
        "report_date": "2025-12-27",
        "document_url": APPLE_10Q_URL,
        "mdna_source": "item2",
    }
    assert lq["metrics"]["revenue"] == pytest.approx(138.4 * B)
    assert [h["verified"] for h in lq["highlights"]] == [True, False]

    call = next(c for c in fake_gemini.calls if c["schema"] == "QuarterUpdate")
    mdna = call["contents"].split("--- BEGIN 10-Q MD&A (quarter ended 2025-12-27) ---")[1]
    assert mdna.strip().startswith("Item 2. Management's Discussion and Analysis of Financial Condition")
    assert "No material changes" not in mdna
    assert body["warnings"] == []


def test_no_10q_after_the_10k(client, fake_sec):
    subs = fake_sec.routes["https://data.sec.gov/submissions/CIK0000320193.json"][1]["filings"]["recent"]
    subs["filingDate"][1] = "2025-10-01"  # the only 10-Q now predates the 10-K
    body = get(client)
    assert body["latest_quarter"] is None
    assert not any("10-Q" in w for w in body["warnings"])


def test_quarter_failure_degrades_gracefully(client, fake_gemini):
    original = fake_gemini.generate_content

    def flaky(model, contents, config):
        if config.response_schema is analysis.QuarterUpdate:
            raise RuntimeError("model overloaded")
        return original(model, contents, config)

    fake_gemini.generate_content = flaky
    body = get(client)
    assert body["latest_quarter"] is None
    assert any("model overloaded" in w for w in body["warnings"])


def test_quarter_without_item2_is_omitted(client, fake_sec):
    fake_sec.add_text(APPLE_10Q_URL, "<p>10-Q with no MD&A section.</p>")
    body = get(client)
    assert body["latest_quarter"] is None
    assert any("Could not isolate Item 2" in w for w in body["warnings"])
