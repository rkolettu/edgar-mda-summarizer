import pytest
from fastapi.testclient import TestClient

import main
from research import chat, ingest, llm, store
from tests.test_research_snapshot import company_sec  # noqa: F401 - fixture


@pytest.fixture
def company(research_conn, company_sec):  # noqa: F811
    ingest.ingest_company(research_conn, "NVDA")
    return store.find_company(research_conn, ticker="NVDA")


@pytest.fixture
def providers(monkeypatch):
    """Records chat calls; Groq answers unless told to be out of quota."""
    monkeypatch.setenv("GROQ_API_KEY", "groq-test")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    state = {"calls": [], "groq_quota": False}

    def fake(url, key, model, system, prompt):
        state["calls"].append({"url": url, "model": model, "prompt": prompt})
        if "groq" in url and state["groq_quota"]:
            raise llm.ProviderError(429, "rate limit reached")
        return llm.Reply("Supply commitments were $279 billion as of July 26, 2026 [S1]. Revenue was $999.9B [F].", model, 900, 40)

    monkeypatch.setattr(llm, "_openai_chat", fake)
    monkeypatch.setattr(main, "_chat_times", {})
    return state


def ask(question, history=()):
    return TestClient(main.app).post("/api/research/NVDA/chat", json={"question": question, "history": list(history)})


def test_answers_from_matching_passages_with_citations(research_conn, company, providers):
    res = ask("How large are the supply commitments?", [{"role": "user", "content": "Tell me about guarantees"},
                                                         {"role": "assistant", "content": "There is a $105 billion guarantee [S1]."}])
    assert res.status_code == 200
    body = res.json()
    assert body["model"] == "openai/gpt-oss-120b"
    assert [s["id"] for s in body["sources"]] == ["S1"] and "$279 billion" in body["sources"][0]["text"]
    assert body["sources"][0]["label"] == "10-Q Q2 FY2027 · Commitments and contingencies"
    spans = {s["text"]: s["verified"] for s in body["figures"]}
    assert spans == {"$279 billion": True, "$999.9B": False}
    prompt = providers["calls"][0]["prompt"]
    assert "KEY FIGURES [F]" in prompt and "CONVERSATION SO FAR" in prompt and prompt.endswith("QUESTION: How large are the supply commitments?")


def test_groq_quota_falls_back_to_mistral_and_never_gemini(research_conn, company, providers, fake_gemini):
    providers["groq_quota"] = True
    res = ask("What are the commitments?")
    assert res.status_code == 200 and res.json()["model"] == "mistral-small-latest"
    assert [c["model"] for c in providers["calls"]] == ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "mistral-small-latest"]
    assert fake_gemini.calls == []


def test_chat_limits_and_configuration(research_conn, company, providers, monkeypatch):
    assert ask("x" * 501).status_code == 422
    monkeypatch.setattr(main, "CHAT_PER_MINUTE", 2)
    monkeypatch.setattr(main, "_chat_times", {})
    assert [ask("commitments?").status_code for _ in range(3)] == [200, 200, 429]
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("MISTRAL_API_KEY")
    monkeypatch.setattr(main, "_chat_times", {})
    res = ask("commitments?")
    assert res.status_code == 503 and "not configured" in res.json()["detail"]
    assert TestClient(main.app).get("/api/research/NVDA").json()["chat"] == {"configured": False}


def test_ranking_prefers_passages_about_the_question():
    filings = {1: {"filing_id": 1, "form_type": "10-K", "fiscal_year": 2026, "fiscal_period": "FY"}}
    sections = [
        {"filing_id": 1, "category": "risk_factors", "ordinal": 1, "heading": None, "document_url": "u",
         "text": "Export controls restrict shipments of our data center products to China and other regions.\n"
                 + "Our business depends on hiring and keeping engineers in competitive markets. " * 12},
        {"filing_id": 1, "category": "management_discussion", "ordinal": 2, "heading": None, "document_url": "u",
         "text": "Revenue grew because data center demand rose sharply across cloud providers this year."},
    ]
    ranked = chat.rank(chat.chunks(sections, filings), "What do export controls mean for China sales?")
    assert ranked[0].text.startswith("Export controls") and ranked[0].id == "S1"
    assert chat.rank(chat.chunks(sections, filings), "the of and") == []
