from __future__ import annotations

import json
import os
from functools import lru_cache

from fastapi import HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """
You are an elite buy-side equity analyst. Analyze the 10-K MD&A section and output a strict JSON response.

CRITICAL RULES:
1. DEPTH OVER BREVITY: Do not use one-line bullets. For each category, provide 3 to 4 detailed insights. Each insight must have a punchy "headline" and a "detail" paragraph (2-3 sentences). The detail must include specific numbers, margin impacts, year-over-year changes, and management's forward-looking context.
2. ABBREVIATE NUMBERS: Convert large numbers to billions/millions (e.g., "$109.1B").
3. SYNTHESIZE: Group related metrics together so the analysis reads like a professional investment memo.
4. EXTRACT CHART DATA: Pull the quantitative revenue segment mix and capital allocation mix into the data arrays.
5. CITE EVIDENCE: Every insight must include an "evidence" field: one sentence copied VERBATIM from the filing text that supports the insight. Do not paraphrase, merge sentences, or change any number; the quote is checked against the filing.
6. MACRO RISKS: When an Item 1A Risk Factors section is provided, draw macro_risks from both it and the MD&A. Prioritize risks management quantifies or describes as new or heightened, and skip generic boilerplate.

Output EXACTLY this JSON format:
{
  "summary": {
    "revenue_drivers": [
      {
        "headline": "Strong Services Acceleration",
        "detail": "Services revenue grew 14% to $109.1B, driven by high-margin App Store and cloud growth. This offset hardware softness and expanded overall gross margins.",
        "evidence": "Services net sales increased during 2025 compared to 2024 due primarily to higher net sales from advertising, the App Store and cloud services."
      }
    ],
    "capital_allocation": [
      {
        "headline": "Aggressive Share Repurchases",
        "detail": "Management retired $89.3B in stock under the new $100B authorization. Additionally, R&D spend increased 10% to $34.5B to support infrastructure buildouts.",
        "evidence": "..."
      }
    ],
    "macro_risks": [
      {
        "headline": "Q2 Tariff Headwinds & FX Drag",
        "detail": "...",
        "evidence": "..."
      }
    ]
  },
  "charts": {
    "revenue_segments": [ {"name": "iPhone", "value": 209.5}, {"name": "Services", "value": 109.1} ],
    "capital_deployment": [ {"name": "Buybacks", "value": 89.3}, {"name": "R&D", "value": 34.5} ]
  }
}
"""


class Insight(BaseModel):
    headline: str
    detail: str
    evidence: str


class Summary(BaseModel):
    revenue_drivers: list[Insight]
    capital_allocation: list[Insight]
    macro_risks: list[Insight]


class ChartPoint(BaseModel):
    name: str
    value: float


class Charts(BaseModel):
    revenue_segments: list[ChartPoint]
    capital_deployment: list[ChartPoint]


class Analysis(BaseModel):
    summary: Summary
    charts: Charts


# Cached so the client outlives each call: genai.Client closes its HTTP connection when garbage-collected.
@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY environment variable is not set.")
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return client


def generate(system_prompt: str, contents: str, schema: type[BaseModel]) -> BaseModel:
    try:
        response = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {exc}") from exc

    try:
        return schema.model_validate(json.loads(response.text))
    except (TypeError, json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=f"Gemini returned malformed JSON: {exc}") from exc


def summarize(company_name: str, ticker: str, mdna_text: str, risk_factors: str | None) -> Analysis:
    contents = (
        f"Company: {company_name} ({ticker})\n\n"
        f"--- BEGIN 10-K MD&A ---\n{mdna_text}\n--- END 10-K MD&A ---"
    )
    if risk_factors:
        contents += f"\n\n--- BEGIN 10-K ITEM 1A RISK FACTORS ---\n{risk_factors}\n--- END 10-K ITEM 1A RISK FACTORS ---"
    return generate(SYSTEM_PROMPT, contents, Analysis)


COMPARE_PROMPT = """
You are an elite buy-side equity analyst comparing a company's latest 10-K with the prior year's 10-K. Output a strict JSON response.

CRITICAL RULES:
1. FOCUS ON WHAT MOVED: Identify the 4 to 6 most investment-relevant changes between the two filings' MD&A and Risk Factors: new or removed risks, shifts in guidance or tone, new strategic priorities, changed segment reporting, and meaningful swings in key metrics. Ignore routine date or number rollovers.
2. CLASSIFY: "change_type" must be exactly one of "new" (appears only in the latest filing), "removed" (appears only in the prior filing), or "changed" (present in both but materially different).
3. DEPTH: Each change needs a punchy "headline" and a "detail" paragraph (2-3 sentences) explaining why it matters to an investor, with specific numbers where available.
4. ABBREVIATE NUMBERS: Convert large numbers to billions/millions (e.g., "$109.1B").
5. CITE EVIDENCE: "evidence" is one sentence copied VERBATIM from the LATEST filing, or from the PRIOR filing when change_type is "removed". Do not paraphrase or change any number; the quote is checked against the filing.

Output EXACTLY this JSON format:
{
  "changes": [
    {
      "headline": "Tariff Risk Elevated to a Primary Margin Headwind",
      "detail": "...",
      "change_type": "new",
      "evidence": "..."
    }
  ]
}
"""

COMPARE_MDNA_CHARS = 120_000
CHANGE_TYPES = {"new", "removed", "changed"}


class Change(BaseModel):
    headline: str
    detail: str
    change_type: str
    evidence: str


class Changes(BaseModel):
    changes: list[Change]


def _filing_block(label: str, tenk: dict) -> str:
    block = f"--- BEGIN {label} 10-K MD&A (fiscal year ended {tenk['report_date']}) ---\n{tenk['mdna']['text'][:COMPARE_MDNA_CHARS]}\n--- END {label} 10-K MD&A ---"
    if tenk["risk_factors"]:
        block += f"\n\n--- BEGIN {label} 10-K RISK FACTORS ---\n{tenk['risk_factors']}\n--- END {label} 10-K RISK FACTORS ---"
    return block


def compare(company_name: str, ticker: str, latest: dict, prior: dict) -> Changes:
    contents = (
        f"Company: {company_name} ({ticker})\n\n"
        f"{_filing_block('LATEST', latest)}\n\n{_filing_block('PRIOR', prior)}"
    )
    result = generate(COMPARE_PROMPT, contents, Changes)
    for change in result.changes:
        change.change_type = change.change_type.strip().lower()
        if change.change_type not in CHANGE_TYPES:
            change.change_type = "changed"
    return result


QUARTER_PROMPT = """
You are an elite buy-side equity analyst reviewing a company's latest 10-Q, filed after its annual 10-K. Output a strict JSON response.

CRITICAL RULES:
1. WHAT IS NEW: Provide 3 to 4 highlights on what has developed since the annual report: the quarter's revenue and margin trends versus the prior-year quarter, updated guidance or outlook, capital return activity, and any new risks or one-time items.
2. DEPTH: Each highlight needs a punchy "headline" and a "detail" paragraph (2-3 sentences) with specific numbers and year-over-year changes.
3. ABBREVIATE NUMBERS: Convert large numbers to billions/millions (e.g., "$109.1B").
4. CITE EVIDENCE: "evidence" is one sentence copied VERBATIM from the 10-Q text. Do not paraphrase or change any number; the quote is checked against the filing.

Output EXACTLY this JSON format:
{
  "highlights": [
    { "headline": "...", "detail": "...", "evidence": "..." }
  ]
}
"""


class QuarterUpdate(BaseModel):
    highlights: list[Insight]


def summarize_quarter(company_name: str, ticker: str, tenq: dict) -> QuarterUpdate:
    contents = (
        f"Company: {company_name} ({ticker})\n\n"
        f"--- BEGIN 10-Q MD&A (quarter ended {tenq['report_date']}) ---\n{tenq['mdna']['text']}\n--- END 10-Q MD&A ---"
    )
    return generate(QUARTER_PROMPT, contents, QuarterUpdate)
