from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import analysis
import sec

app = FastAPI(title="item7-extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return json_errors(sec.search_companies, q, limit)


@app.get("/api/summarize")
def summarize_ticker(ticker: str = Query(..., min_length=1, max_length=100)):
    return json_errors(run_pipeline, ticker)


def run_pipeline(query: str) -> dict:
    company = sec.resolve_company(query)
    ticker, cik = company["ticker"], company["cik"]

    submissions = sec.get_submissions(cik)
    tenks = sec.find_filings(submissions, "10-K", limit=1)
    if not tenks:
        raise HTTPException(status_code=404, detail="No 10-K filing found in the company's recent submissions.")
    filing = tenks[0]
    document_url = sec.archive_url(cik, filing["accession_number"], filing["primary_doc"])

    text = sec.html_to_text(sec.sec_get(document_url).text)
    item7 = sec.extract_item7(text)
    extraction_method = "item7" if item7 else "fallback"
    mdna_text = item7 if item7 else text[: sec.FALLBACK_CHARS]

    company_name = submissions.get("name") or company["name"]
    result = analysis.summarize(company_name, ticker, mdna_text)

    return {
        "ticker": ticker,
        "company_name": company_name,
        "filing_date": filing["filing_date"],
        "report_date": filing["report_date"],
        "accession_number": filing["accession_number"],
        "document_url": document_url,
        "extraction_method": extraction_method,
        **result.model_dump(),
    }


@app.get("/")
def health():
    return {"status": "ok"}
