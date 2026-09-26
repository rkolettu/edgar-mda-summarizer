import pytest
from fastapi.testclient import TestClient

import main
from research import ingest, interpret, llm, store
from tests.test_research_ingest import nvda_sec  # noqa: F401 - fixture

QUARTER_QUOTE = ("Total net sales increased 11% to $138.4 billion during the first quarter of 2026 compared to the same "
                 "quarter in 2025.")


def extraction():
    item = {"headline": "Sales growth", "detail": "Net sales rose 11% to $138.4 billion.", "evidence": QUARTER_QUOTE}
    return {
        "business_summary": "The company designs accelerated computing platforms.",
        "segments": [],
        "strategy": [{"headline": "Invented", "detail": "A priority the filing never states.", "evidence": "We will colonize Mars by 2027 with our chips."}],
        "drivers": [{**item, "direction": "sideways"}],
        "outlook": [],
        "upside": [],
        "downside": [],
        "risks": [{"headline": "Export controls", "detail": "Export controls restrict some shipments.",
                   "evidence": "Export controls now restrict shipments of certain products.", "category": "trade and export controls",
                   "company_specific": True, "trend": "new", "realized": True}],
        "non_operating": [],
    }


def synthesis():
    return {
        "takeaways": [
            {"headline": "Quarterly revenue reached $96.2B", "detail": "Revenue was $96.2B in the latest quarter.", "refs": ["m.revenue", "c1"]},
            {"headline": "An invented claim", "detail": "Margins will reach $999.9B.", "refs": ["m.revenue"]},
            {"headline": "Cites nothing it was given", "detail": "Unsupported.", "refs": ["x9"]},
        ],
        "business_overview": "The company sells accelerated computing platforms.",
        "risks": [{"ref": "r1", "headline": "Export controls", "detail": "New restrictions on shipments.", "trend": "worse"}],
        "earnings_quality": {"summary": "Earnings come mostly from operations.", "points": []},
        "change_notes": [{"ref": "c1", "note": "It is the largest change in the filing."}, {"ref": "m.revenue", "note": "Not a change."}],
    }


@pytest.fixture
def model(fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    fake_gemini.responses["Extraction"] = extraction()
    fake_gemini.responses["Synthesis"] = synthesis()
    return fake_gemini


@pytest.fixture
def company(research_conn, nvda_sec):  # noqa: F811
    ingest.ingest_company(research_conn, "NVDA")
    return store.find_company(research_conn, ticker="NVDA")


def outputs(conn, company_id):
    return {(stage, form): output for stage, form, output in conn.execute(
        "SELECT o.stage, f.form_type, o.output FROM model_outputs o JOIN filings f USING (filing_id) WHERE o.company_id = %s",
        (company_id,)).fetchall()}


def test_extraction_input_keeps_prose_outline_and_changed_risks():
    business = "Item 1. Business\nOur Company\nWe sell accelerated computing platforms to cloud providers worldwide.\nFY2026 FY2025 $ 1,000 $ 2,000 3.1% 4.2%"
    risks = ("Item 1A. Risk Factors\nCompetition could adversely impact our market share and financial results.\n"
             "Competition in our markets is intense and our competitors have significant resources and scale today. "
             "Our competitors may introduce products that are better or cheaper than ours in several markets.\n"
             "We depend on third parties to manufacture our products.\n")
    base_risks = risks.replace("We depend on third parties to manufacture our products.\n", "")
    filing = {"filing_id": 2, "form_type": "10-K", "fiscal_year": 2026, "fiscal_period": "FY", "is_annual": True,
              "period_end": __import__("datetime").date(2026, 1, 25)}
    base = {"filing_id": 1, "form_type": "10-K", "fiscal_year": 2025, "fiscal_period": "FY"}
    texts = {(2, "business"): business, (2, "risk_factors"): risks, (1, "risk_factors"): base_risks}
    text = interpret.extraction_input({"name": "NVIDIA", "ticker": "NVDA", "reporting_currency": "USD"}, filing, texts, base)
    assert "We sell accelerated computing platforms" in text and "$ 1,000" not in text
    assert "- Competition could adversely impact our market share and financial results." in text
    assert "=== NEW OR CHANGED RISK FACTORS (since the 10-K for FY2025) ===\n[new] We depend on third parties" in text


def test_stages_run_once_verify_quotes_figures_and_references(research_conn, company, model):
    assert interpret.run(research_conn, company["company_id"]) is True
    assert [c["schema"] for c in model.calls] == ["Extraction", "Extraction", "Synthesis"]
    assert {c["model"] for c in model.calls} == {"gemini-3.5-flash-lite", "gemini-3.8-flash"}

    stored = outputs(research_conn, company["company_id"])
    quarter, annual = stored[("extract", "10-Q")], stored[("extract", "10-K")]
    # The quote is checked against the filing that was read: found in the 10-Q, not in the 10-K.
    assert quarter["drivers"][0]["status"] == "verified" and quarter["drivers"][0]["direction"] == "mixed"
    assert annual["drivers"][0]["status"] == "unverified"
    assert quarter["strategy"][0]["status"] == "unverified"  # an invented quote
    assert quarter["risks"][0]["status"] == "verified" and quarter["risks"][0]["trend"] == "new"

    synth = stored[("synthesize", "10-Q")]
    assert [t["headline"] for t in synth["takeaways"]] == ["Quarterly revenue reached $96.2B", "An invented claim"]
    first, invented = synth["takeaways"]
    assert first["status"] == "verified" and [r["id"] for r in first["refs"]] == ["m.revenue", "c1"]
    assert invented["status"] == "partial" and not invented["figures"]["detail"][0]["verified"]
    assert synth["risks"][0]["trend"] == "ongoing" and synth["risks"][0]["refs"][0]["type"] == "extraction"
    assert len(synth["change_notes"]) == 1

    runs = research_conn.execute("SELECT stage, status, model FROM analysis_runs WHERE stage <> 'parse' ORDER BY run_id").fetchall()
    assert runs == [("extract", "succeeded", "gemini-3.5-flash-lite")] * 2 + [("synthesize", "succeeded", "gemini-3.8-flash")] + [
        ("audit", "succeeded", "none")]  # nothing flagged was left uncited, so the check needed no model call

    payload = store.load_snapshot(research_conn, company["company_id"])["payload"]
    insights = payload["insights"]
    assert insights["status"] == "ready" and insights["models"] == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert insights["business"]["summary"] == "The company designs accelerated computing platforms."
    assert insights["risks"]["ranked"][0]["extracted"]["evidence"] == "Export controls now restrict shipments of certain products."
    assert insights["business"]["drivers"][0]["source"]["form"] == "10-Q"
    noted = [i for i in payload["changes"]["items"] if i.get("why_it_matters")]
    assert noted[0]["why_it_matters"]["note"] == "It is the largest change in the filing."

    # Stored once: a second request makes no model calls.
    calls = len(model.calls)
    assert interpret.run(research_conn, company["company_id"]) is False
    assert len(model.calls) == calls


def test_model_chain_moves_past_quota_and_unavailable_models(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    attempts = []

    def fake(model, stage, system, contents, schema):
        attempts.append(model)
        if model == "gemini-3.5-flash-lite":
            raise ProviderError(429, "RESOURCE_EXHAUSTED: quota exceeded")
        if model == "gemini-2.5-flash":
            raise ProviderError(404, "models/gemini-2.5-flash is not found")
        return llm.Result(interpret.Extraction.model_validate(extraction()), model, 10, 5)

    monkeypatch.setattr(llm, "_gemini", fake)
    assert llm.chain("extract") == ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-3.8-flash"]
    assert llm.generate("extract", "", "", interpret.Extraction).model == "gemini-3.8-flash"
    assert attempts == llm.chain("extract")

    monkeypatch.setattr(llm, "_gemini", lambda *a: (_ for _ in ()).throw(ProviderError(429, "quota exceeded")))
    with pytest.raises(llm.ModelUnavailable) as exc:
        llm.generate("synthesize", "", "", interpret.Synthesis)
    assert exc.value.quota

    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(llm.ModelUnavailable, match="No model is configured"):
        llm.generate("extract", "", "", interpret.Extraction)


class ProviderError(Exception):
    """Carries an HTTP status code the way the Gemini SDK's errors do."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def test_gemini_3_sets_thinking_depth_and_older_models_temperature(model):
    llm._gemini("gemini-3.5-flash-lite", "extract", "system", "text", interpret.Extraction)
    llm._gemini("gemini-2.5-flash", "synthesize", "system", "text", interpret.Extraction)
    first, second = (c["config"] for c in model.calls)
    assert first.thinking_config.thinking_level == "LOW" and first.temperature is None
    assert second.thinking_config is None and second.temperature == 0


def test_insights_endpoint(research_conn, company, model):
    client = TestClient(main.app)
    res = client.post("/api/research/NVDA/insights")
    assert res.status_code == 200 and res.json()["insights"]["status"] == "ready"


def test_insights_endpoint_backs_off_after_a_spent_quota(research_conn, company, model, monkeypatch):
    monkeypatch.setattr(llm, "_gemini", lambda *a: (_ for _ in ()).throw(ProviderError(429, "quota exceeded")))
    client = TestClient(main.app)
    res = client.post("/api/research/NVDA/insights")
    assert res.status_code == 429 and "quota" in res.json()["detail"]
    calls = len(model.calls)
    assert client.post("/api/research/NVDA/insights").status_code == 429  # no retry within the backoff window
    assert len(model.calls) == calls
    payload = client.get("/api/research/NVDA").json()
    assert payload["insights"]["status"] == "pending" and payload["financials"]["annual"]["rows"]


def test_insights_endpoint_without_a_model_key(research_conn, company, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    res = TestClient(main.app).post("/api/research/NVDA/insights")
    assert res.status_code == 503 and "not configured" in res.json()["detail"]


def test_whether_ai_is_configured_is_decided_when_serving(research_conn, company, monkeypatch):
    from research import service

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert service.get_snapshot("NVDA")["insights"] == {"status": "pending", "configured": True}
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert service.get_snapshot("NVDA")["insights"]["configured"] is False


def test_a_failure_after_the_model_answers_releases_the_lock(research_conn, company, model, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(interpret, "verify_synthesis", lambda *a: (_ for _ in ()).throw(ValueError("bad output")))
        with pytest.raises(ValueError):
            interpret.run(research_conn, company["company_id"])
    assert research_conn.execute("SELECT count(*) FROM analysis_runs WHERE status = 'running'").fetchone()[0] == 0
    assert interpret.run(research_conn, company["company_id"]) is True  # retried, not blocked
    assert {c["schema"] for c in model.calls} == {"Extraction", "Synthesis"}  # the fake answered every call
