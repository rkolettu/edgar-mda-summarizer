import json
import re
from datetime import date
from types import SimpleNamespace

import pytest

from research import audit, ingest, interpret, store
from tests.test_research_snapshot import company_sec  # noqa: F401 - fixture


class ProviderError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def synthesis(takeaway_refs):
    return {
        "takeaways": [{"headline": "A new $105.0B guarantee", "detail": "The filing adds a $105.0B financial guarantee.",
                       "refs": takeaway_refs}],
        "business_overview": "",
        "risks": [],
        "earnings_quality": {"summary": "", "points": []},
        "change_notes": [],
    }


def audit_answer(contents):
    ids = dict((label, ref) for ref, label in re.findall(r"^(X\d+) \[filing change, [^\]]*\] \w+: (.+?) \$", contents, re.M))
    supply = ids["Supply and capacity commitments"]
    others = [ref for ref in re.findall(r"^(X\d+) ", contents, re.M) if ref != supply]
    decisions = [{"ref": supply, "decision": "add", "covered_by": "", "reason": "The largest commitment change."}]
    if others:
        decisions.append({"ref": others[0], "decision": "covered", "covered_by": "T9", "reason": "Names a point that does not exist."})
    for ref in others[1:]:
        decisions.append({"ref": ref, "decision": "not_material", "covered_by": "", "reason": "Routine."})
    return {
        "decisions": decisions,
        "additions": [
            {"headline": "Supply commitments reached $279.0B", "detail": "Up from $119.0B in the previous quarter.", "refs": [supply]},
            {"headline": "Cites nothing flagged", "detail": "Unsupported.", "refs": ["X99"]},
        ],
    }


@pytest.fixture
def model(fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    fake_gemini.responses["Synthesis"] = synthesis(["c1", "m.revenue"])
    answer = fake_gemini.generate_content

    def generate_content(model, contents, config):
        if config.response_schema.__name__ == "Audit":
            fake_gemini.calls.append({"model": model, "contents": contents, "config": config, "schema": "Audit"})
            if fake_gemini.responses.get("Audit") == "quota":
                raise ProviderError(429, "RESOURCE_EXHAUSTED: quota exceeded")
            return SimpleNamespace(text=json.dumps(audit_answer(contents)))
        return answer(model, contents, config)

    fake_gemini.generate_content = generate_content
    return fake_gemini


@pytest.fixture
def company(research_conn, company_sec):  # noqa: F811
    ingest.ingest_company(research_conn, "NVDA")
    return store.find_company(research_conn, ticker="NVDA")


def test_audit_checks_every_flagged_item_and_adds_what_the_summary_missed(research_conn, company, model):
    assert interpret.run(research_conn, company["company_id"]) is True
    audit_calls = [c for c in model.calls if c["schema"] == "Audit"]
    assert len(audit_calls) == 1
    # The model sees only what the summary does not cite: the guarantee it cites is not sent.
    assert "Financial guarantee" not in audit_calls[0]["contents"].split("FLAGGED ITEMS")[1]

    result = store.load_snapshot(research_conn, company["company_id"])["payload"]["insights"]["audit"]
    items = {i["label"]: i for i in result["items"]}
    guarantee = items["Financial guarantee"]
    assert (guarantee["decision"], guarantee["by"], guarantee["covered_by"]) == ("covered", "code", "A new $105.0B guarantee")
    supply = items["Supply and capacity commitments"]
    assert (supply["decision"], supply["by"]) == ("add", "model")
    assert "unresolved" in {i["decision"] for i in result["items"]}  # "covered" by a point that does not exist
    assert [a["headline"] for a in result["additions"]] == ["Supply commitments reached $279.0B"]
    assert result["additions"][0]["status"] == "verified"
    assert result["checked"] == len(result["items"]) and result["counts"]["covered"] >= 1
    assert result["model"] == "gemini-3.8-flash"

    calls = len(model.calls)
    assert interpret.run(research_conn, company["company_id"]) is False  # stored once
    assert len(model.calls) == calls


def test_no_model_call_when_the_summary_cites_everything_flagged(research_conn, company, model, monkeypatch):
    monkeypatch.setattr(audit, "candidates", lambda *a: [])
    interpret.run(research_conn, company["company_id"])
    assert "Audit" not in {c["schema"] for c in model.calls}
    result = store.load_snapshot(research_conn, company["company_id"])["payload"]["insights"]["audit"]
    assert result["checked"] == 0 and result["model"] == "none"


def test_a_spent_quota_on_the_audit_keeps_the_summary(research_conn, company, model):
    model.responses["Audit"] = "quota"
    assert interpret.run(research_conn, company["company_id"]) is True
    insights = store.load_snapshot(research_conn, company["company_id"])["payload"]["insights"]
    assert insights["status"] == "ready" and insights["takeaways"] and insights["audit"] is None
    status = research_conn.execute("SELECT status FROM analysis_runs WHERE stage = 'audit'").fetchone()[0]
    assert status == "failed"


def test_language_candidates_need_the_event_to_have_happened():
    filing = {"filing_id": 1, "form_type": "10-K", "fiscal_year": 2026, "fiscal_period": "FY", "period_end": date(2026, 1, 25)}
    text = ("We identified a material weakness in our internal control over financial reporting during the fourth quarter.\n"
            "We did not identify any restatement of previously issued financial statements this year.\n"
            "If we fail to comply with covenants, we could be in default under our credit agreements.\n"
            "We received a subpoena from the Department of Justice requesting documents about export sales.")
    sections = [{"filing_id": 1, "category": "risk_factors", "ordinal": 1, "text": text}]
    found = audit.language_candidates(sections, [filing], {"takeaways": []}, [(filing, {})])
    assert {c.reasons[0] for c in found} == {"says material weakness has happened", "says subpoena has happened"}
    covered = audit.language_candidates(sections, [filing], {"takeaways": [
        {"headline": "Material weakness reported", "detail": "A material weakness was identified.", "refs": []}]}, [(filing, {})])
    assert {c.label.split("”")[0].strip("“"): bool(c.covered_by) for c in covered} == {"material weakness": True, "subpoena": False}


def test_change_candidates_count_metric_citations_as_coverage():
    payload = {"changes": {"items": [
        {"id": "a", "kind": "numeric", "label": "Revenue", "category_label": "Financial statements", "tier": "top", "flags": [],
         "change_type": "changed", "value": 2e9, "base_value": 1e9, "unit": "currency", "currency": "USD", "change": 1.0,
         "period_label": "FY2026", "base_period_label": "FY2025", "score": 0.8, "reasons": []},
        {"id": "b", "kind": "numeric", "label": "Guarantee", "category_label": "Guarantees", "tier": "notable",
         "flags": ["subsequent_event"], "change_type": "new", "value": 5e9, "base_value": None, "unit": "currency",
         "currency": "USD", "change": None, "period_label": "2026-08-31", "score": 0.6, "reasons": ["subsequent event"]},
        {"id": "c", "kind": "numeric", "label": "Minor", "category_label": "Debt", "tier": "notable", "flags": [],
         "change_type": "changed", "value": 1e8, "base_value": 2e8, "unit": "currency", "currency": "USD", "change": -0.5,
         "period_label": "FY2026", "score": 0.5, "reasons": []},
    ]}}
    synth = {"takeaways": [{"headline": "Revenue doubled", "detail": "", "refs": [{"type": "metric", "label": "Revenue"}]}]}
    found = {c.label: c for c in audit.change_candidates(payload, synth)}
    assert set(found) == {"Revenue", "Guarantee"}  # notable items without a must-review flag are not flagged
    assert found["Revenue"].covered_by == ["Revenue doubled"] and found["Guarantee"].covered_by == []
