import analysis
from tests.conftest import APPLE_PRIOR_10K_URL


def get(client):
    return client.get("/api/summarize", params={"ticker": "AAPL"}).json()


def test_changes_compare_latest_and_prior_filings(client, fake_gemini):
    body = get(client)
    call = next(c for c in fake_gemini.calls if c["schema"] == "Changes")
    assert "--- BEGIN LATEST 10-K MD&A (fiscal year ended 2025-09-27) ---" in call["contents"]
    assert "--- BEGIN PRIOR 10-K MD&A (fiscal year ended 2024-09-28) ---" in call["contents"]
    assert "supply constraints" in call["contents"].split("BEGIN PRIOR")[1]
    assert "--- BEGIN PRIOR 10-K RISK FACTORS ---" in call["contents"]
    assert body["changes"]["prior_filing"] == {
        "filing_date": "2024-11-01",
        "report_date": "2024-09-28",
        "document_url": APPLE_PRIOR_10K_URL,
    }


def test_change_types_normalized(client):
    items = get(client)["changes"]["items"]
    assert [i["change_type"] for i in items] == ["new", "removed", "changed"]


def test_evidence_checked_against_the_right_filing(client):
    items = get(client)["changes"]["items"]
    assert items[0]["verified"] is True  # new: quote is in the latest filing
    assert items[1]["verified"] is True  # removed: quote is in the prior filing
    assert items[2]["verified"] is False  # changed: prior-year sentence isn't in the latest filing


def test_missing_prior_filing_degrades_gracefully(client, fake_sec):
    del fake_sec.routes[APPLE_PRIOR_10K_URL]
    body = get(client)
    assert body["changes"] is None
    assert body["summary"]["revenue_drivers"]
    assert any("Year-over-year comparison unavailable" in w for w in body["warnings"])


def test_compare_gemini_failure_degrades_gracefully(client, fake_gemini):
    del fake_gemini.responses["Changes"]
    original = fake_gemini.generate_content

    def flaky(model, contents, config):
        if config.response_schema is analysis.Changes:
            raise RuntimeError("quota exceeded")
        return original(model, contents, config)

    fake_gemini.generate_content = flaky
    body = get(client)
    assert body["changes"] is None
    assert any("quota exceeded" in w for w in body["warnings"])


def test_only_one_10k_on_record(client, fake_sec):
    url = "https://data.sec.gov/submissions/CIK0000320193.json"
    subs = fake_sec.routes[url][1]
    recent = subs["filings"]["recent"]
    idx = [i for i, f in enumerate(recent["form"]) if f == "10-K"][1]
    for key in recent:
        recent[key] = recent[key][:idx] + recent[key][idx + 1:]
    body = get(client)
    assert body["changes"] is None
    assert any("No prior-year 10-K" in w for w in body["warnings"])
