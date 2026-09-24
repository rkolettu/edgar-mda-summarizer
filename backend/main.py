from __future__ import annotations

import json
import os
import re
from functools import lru_cache

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{padded_cik}.json"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
GEMINI_MODEL = "gemini-2.5-flash"
MIN_SECTION_CHARS = 2_000
REQUEST_TIMEOUT = 30

ITEM7_PATTERN = re.compile(
    r"item\s*7\s*[.:\-]?\s*management['’]?s\s+discussion\s+and\s+analysis", re.IGNORECASE
)
ITEM8_PATTERN = re.compile(r"item\s*8\s*[.:\-]", re.IGNORECASE)

app = FastAPI(title="item7-extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


SYSTEM_PROMPT = """
You are an elite buy-side equity analyst. Analyze the 10-K MD&A section and output a strict JSON response.

CRITICAL RULES:
1. Give up to 4 substantive insights per category, each with a headline and 2-3 sentence detail. Only include numbers, comparisons and management outlook that appear in the supplied text. If the text does not support an insight, return fewer insights or an empty array.
2. ABBREVIATE NUMBERS: Convert large numbers to billions/millions (e.g., "$109.1B").
3. SYNTHESIZE: Group related metrics together so the analysis reads like a professional investment memo.
4. CHART DATA: Use only explicitly reported amounts. All chart values MUST be in USD billions (e.g. $750 million = 0.75). Revenue segments must be mutually exclusive parts of the same period's revenue; do not mix segment and product totals or include a total as a segment. Capital deployment values must be distinct actual spending categories for the same fiscal year, not authorizations or forecasts. Use empty arrays if comparable figures or units are unavailable. Never invent values.

Output EXACTLY this JSON format:
{
  "summary": {
    "revenue_drivers": [
      {
        "headline": "Strong Services Acceleration",
        "detail": "Services revenue grew 14% to $109.1B, driven by high-margin App Store and cloud growth. This offset hardware softness and expanded overall gross margins."
      }
    ],
    "capital_allocation": [
      {
        "headline": "Aggressive Share Repurchases",
        "detail": "Management retired $89.3B in stock under the new $100B authorization. Additionally, R&D spend increased 10% to $34.5B to support infrastructure buildouts."
      }
    ],
    "macro_risks": [
      {
        "headline": "Q2 Tariff Headwinds & FX Drag",
        "detail": "..."
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


def sec_get(url: str) -> requests.Response:
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise HTTPException(
            status_code=500,
            detail="SEC_USER_AGENT is not configured. Set it to your application name and contact email.",
        )
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"SEC request failed for {url}: {exc}") from exc
    return resp


def normalize_name(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


# SEC orders company_tickers.json roughly by market cap, so list position is a good popularity tiebreak.
@lru_cache(maxsize=1)
def load_companies() -> list[dict]:
    data = sec_get(TICKERS_URL).json()
    return [
        {
            "ticker": entry["ticker"].upper(),
            "name": entry["title"],
            "cik": int(entry["cik_str"]),
            "norm_name": normalize_name(entry["title"]),
            "compact_name": normalize_name(entry["title"]).replace(" ", ""),
        }
        for entry in data.values()
    ]


@lru_cache(maxsize=1)
def load_ticker_map() -> dict[str, dict]:
    return {company["ticker"]: company for company in load_companies()}


def search_companies(query: str, limit: int) -> list[dict]:
    ticker_q = query.strip().upper().replace(".", "-")
    name_q = normalize_name(query)
    compact_q = name_q.replace(" ", "")
    if not ticker_q:
        return []

    ranked = []
    for position, company in enumerate(load_companies()):
        name = company["norm_name"]
        if company["ticker"] == ticker_q:
            rank = 0
        elif company["ticker"].startswith(ticker_q):
            rank = 1
        elif name_q and name.startswith(name_q):
            rank = 2
        elif name_q and f" {name_q}" in f" {name}":
            rank = 3
        elif len(compact_q) >= 3 and compact_q in company["compact_name"]:
            rank = 4
        else:
            continue
        ranked.append((rank, position, company))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [
        {"ticker": c["ticker"], "name": c["name"], "cik": c["cik"]}
        for _, _, c in ranked[:limit]
    ]


def resolve_company(query: str) -> dict:
    exact = load_ticker_map().get(query.strip().upper().replace(".", "-"))
    if exact:
        return exact
    matches = search_companies(query, limit=1)
    if not matches:
        raise HTTPException(status_code=404, detail=f"No SEC-registered company matches '{query}'.")
    return load_ticker_map()[matches[0]["ticker"]]


def find_latest_10k(padded_cik: str) -> dict:
    submissions = sec_get(SUBMISSIONS_URL.format(padded_cik=padded_cik)).json()
    recent = submissions.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form == "10-K":
            return {
                "company_name": submissions.get("name", ""),
                "accession_number": recent["accessionNumber"][i],
                "primary_doc": recent["primaryDocument"][i],
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
            }
    raise HTTPException(status_code=404, detail="No 10-K filing found in the company's recent submissions.")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ").replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def extract_item7(text: str) -> str | None:
    # The table of contents also matches, so take the longest Item 7 -> Item 8 span.
    best = ""
    for start in ITEM7_PATTERN.finditer(text):
        end = ITEM8_PATTERN.search(text, start.end())
        if not end:
            continue
        section = text[start.start():end.start()]
        if len(section) > len(best):
            best = section
    return best if len(best) >= MIN_SECTION_CHARS else None


# Cached so the client outlives each call: genai.Client closes its HTTP connection when garbage-collected.
@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY environment variable is not set.")
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return client


def summarize(company_name: str, ticker: str, mdna_text: str) -> Analysis:
    contents = (
        f"Company: {company_name} ({ticker})\n\n"
        f"--- BEGIN 10-K MD&A ---\n{mdna_text}\n--- END 10-K MD&A ---"
    )

    try:
        response = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=Analysis,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {exc}") from exc

    try:
        return Analysis.model_validate(json.loads(response.text))
    except (TypeError, json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=f"Gemini returned malformed JSON: {exc}") from exc


def json_errors(fn, *args):
    # Unhandled 500s bypass CORSMiddleware, which the browser reports only as "Failed to fetch".
    try:
        return fn(*args)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc!r}") from exc


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(8, ge=1, le=25)):
    return json_errors(search_companies, q, limit)


@app.get("/api/summarize")
def summarize_ticker(ticker: str = Query(..., min_length=1, max_length=100)):
    return json_errors(run_pipeline, ticker)


def run_pipeline(query: str) -> dict:
    company = resolve_company(query)
    ticker, cik, title = company["ticker"], company["cik"], company["name"]
    padded_cik = str(cik).zfill(10)

    filing = find_latest_10k(padded_cik)
    accession_no_dashes = filing["accession_number"].replace("-", "")
    document_url = DOCUMENT_URL.format(
        cik=cik, accession=accession_no_dashes, primary_doc=filing["primary_doc"]
    )

    text = html_to_text(sec_get(document_url).text)
    item7 = extract_item7(text)
    if item7 is None:
        raise HTTPException(
            status_code=422,
            detail="Could not isolate Item 7 in this filing. Open the source filing to review it directly.",
        )

    company_name = filing["company_name"] or title
    analysis = summarize(company_name, ticker, item7)

    return {
        "ticker": ticker,
        "company_name": company_name,
        "filing_date": filing["filing_date"],
        "report_date": filing["report_date"],
        "accession_number": filing["accession_number"],
        "document_url": document_url,
        "extraction_method": "item7",
        **analysis.model_dump(),
    }


@app.get("/")
def health():
    return {"status": "ok"}
