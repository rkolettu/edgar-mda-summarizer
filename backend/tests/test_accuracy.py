import pytest

from tests.xbrl_fixture import apple_companyfacts

APPLE_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


@pytest.fixture
def with_xbrl(fake_sec):
    fake_sec.add_json(APPLE_FACTS_URL, apple_companyfacts())


def summarize(client):
    return client.get("/api/summarize", params={"ticker": "AAPL"}).json()


def test_insight_statuses(client, fake_gemini, with_xbrl):
    drivers = fake_gemini.responses["Analysis"]["summary"]["revenue_drivers"]
    drivers.append({
        "headline": "Services Hits $999.9B",
        "detail": "Services grew 14% to $109.2B.",
        "evidence": "Services net sales grew 14% year over year to $109.2 billion.",
    })
    body = summarize(client)
    verified, partial = body["summary"]["revenue_drivers"]
    assert verified["status"] == "verified"
    assert [(s["text"], s["verified"]) for s in verified["figures"]["detail"]] == [("14%", True), ("$109.2B", True)]
    assert partial["status"] == "partial"
    assert [(s["text"], s["verified"]) for s in partial["figures"]["headline"]] == [("$999.9B", False)]
    assert body["summary"]["capital_allocation"][0]["status"] == "unverified"


def test_xbrl_figures_verify_text_claims(client, fake_gemini, with_xbrl):
    fake_gemini.responses["Analysis"]["summary"]["revenue_drivers"][0]["detail"] = (
        "Revenue grew 6.4% to $416.2B with gross margin of 46.9%; buybacks were $90.7B."
    )
    spans = summarize(client)["summary"]["revenue_drivers"][0]["figures"]["detail"]
    assert all(s["verified"] for s in spans), spans


def test_reference_figures_sent_to_every_gemini_call(client, fake_gemini, with_xbrl):
    summarize(client)
    by_schema = {c["schema"]: c for c in fake_gemini.calls}
    for schema in ("Analysis", "Changes", "QuarterUpdate"):
        contents = by_schema[schema]["contents"]
        assert "REFERENCE FIGURES (from the company's SEC XBRL data; authoritative values):" in contents
        assert "Revenue $416.2B" in contents
        assert "REFERENCE FIGURES: When a REFERENCE FIGURES block is provided" in by_schema[schema]["config"].system_instruction
    assert "Quarter ended 2025-12-27 (Q1 FY2026): Revenue $138.4B (+11.3%" in by_schema["QuarterUpdate"]["contents"]


def test_no_reference_block_without_xbrl(client, fake_gemini):
    summarize(client)
    assert all("REFERENCE FIGURES (from" not in c["contents"] for c in fake_gemini.calls)


def test_temperature_zero(client, fake_gemini):
    summarize(client)
    assert {c["config"].temperature for c in fake_gemini.calls} == {0}


def test_changes_and_quarter_get_statuses(client, with_xbrl):
    body = summarize(client)
    assert [i["status"] for i in body["changes"]["items"]] == ["verified", "verified", "unverified"]
    assert [h["status"] for h in body["latest_quarter"]["highlights"]] == ["verified", "unverified"]
    q_spans = body["latest_quarter"]["highlights"][0]["figures"]["detail"]
    assert [(s["text"], s["verified"]) for s in q_spans] == [("11%", True), ("$138.4B", True)]


def test_reference_block_values_verify_against_themselves(with_xbrl):
    import figures
    import financials

    fin = financials.build_financials(apple_companyfacts(), "2025-09-27")
    quarter = financials.build_quarter(apple_companyfacts(), "2025-12-27")
    block = financials.reference_block(fin, quarter)
    index = figures.FigureIndex()
    figures.add_financials(index, fin)
    figures.add_quarter(index, quarter)
    unverified = [s["text"] for s in figures.check_figures(block, index) if not s["verified"]]
    assert unverified == []
