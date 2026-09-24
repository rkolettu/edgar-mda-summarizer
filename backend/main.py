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

SEC_HEADERS = {"User-Agent": "RishabKolettu InvestmentResearch (rishab@example.com)"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{padded_cik}.json"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
GEMINI_MODEL = "gemini-2.5-flash"
FALLBACK_CHARS = 100_000
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


class Item7Summary(BaseModel):
    revenue_drivers: list[str]
    capital_allocation: list[str]
    macro_risks: list[str]


def sec_get(url: str) -> requests.Response:
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"SEC request failed for {url}: {exc}") from exc
    return resp


@lru_cache(maxsize=1)
def load_ticker_map() -> dict[str, dict]:
    data = sec_get(TICKERS_URL).json()
    return {entry["ticker"].upper(): entry for entry in data.values()}


def lookup_cik(ticker: str) -> tuple[int, str]:
    ticker_map = load_ticker_map()
    entry = ticker_map.get(ticker) or ticker_map.get(ticker.replace(".", "-"))
    if not entry:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found in SEC ticker list.")
    return int(entry["cik_str"]), entry.get("title", "")


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


def summarize(company_name: str, ticker: str, mdna_text: str) -> Item7Summary:
    prompt = (
        "You are a senior buy-side equity analyst at a long/short fundamental hedge fund. "
        f"Below is the Management's Discussion and Analysis (Item 7) from the latest 10-K of "
        f"{company_name} ({ticker}).\n\n"
        "Extract the following, each as a JSON array of concise, specific bullet-point strings "
        "(4-7 bullets each). Cite concrete figures, growth rates, segments, and dollar amounts from "
        "the filing wherever possible. Do not invent numbers.\n"
        "- revenue_drivers: the key factors driving revenue growth or decline (segments, products, "
        "pricing, volume, geography).\n"
        "- capital_allocation: how management is deploying capital (buybacks, dividends, capex, "
        "M&A, debt paydown/issuance, R&D, liquidity position).\n"
        "- macro_risks: macroeconomic and external risks management highlights (rates, FX, "
        "inflation, supply chain, regulation, geopolitics, demand environment).\n\n"
        'Respond ONLY with a JSON object of the form {"revenue_drivers": [...], '
        '"capital_allocation": [...], "macro_risks": [...]}.\n\n'
        f"--- BEGIN ITEM 7 ---\n{mdna_text}\n--- END ITEM 7 ---"
    )

    try:
        response = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Item7Summary,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {exc}") from exc

    try:
        return Item7Summary.model_validate(json.loads(response.text))
    except (TypeError, json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=f"Gemini returned malformed JSON: {exc}") from exc


@app.get("/api/summarize")
def summarize_ticker(ticker: str = Query(..., min_length=1, max_length=10)):
    # Unhandled 500s bypass CORSMiddleware, which the browser reports only as "Failed to fetch".
    try:
        return run_pipeline(ticker.strip().upper())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc!r}") from exc


def run_pipeline(ticker: str) -> dict:
    cik, title = lookup_cik(ticker)
    padded_cik = str(cik).zfill(10)

    filing = find_latest_10k(padded_cik)
    accession_no_dashes = filing["accession_number"].replace("-", "")
    document_url = DOCUMENT_URL.format(
        cik=cik, accession=accession_no_dashes, primary_doc=filing["primary_doc"]
    )

    text = html_to_text(sec_get(document_url).text)
    item7 = extract_item7(text)
    extraction_method = "item7" if item7 else "fallback"
    mdna_text = item7 if item7 else text[:FALLBACK_CHARS]

    company_name = filing["company_name"] or title
    summary = summarize(company_name, ticker, mdna_text)

    return {
        "ticker": ticker,
        "company_name": company_name,
        "filing_date": filing["filing_date"],
        "accession_number": filing["accession_number"],
        "document_url": document_url,
        "extraction_method": extraction_method,
        **summary.model_dump(),
    }


@app.get("/")
def health():
    return {"status": "ok"}
