from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import analysis
import financials
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


def load_financials(cik: int, report_date: str, warnings: list[str]) -> dict | None:
    try:
        result = financials.build_financials(sec.get_companyfacts(cik), report_date)
    except HTTPException:
        result = None
    if result is None:
        warnings.append("No XBRL financial data found; KPIs and trend charts are unavailable.")
    return result


def run_pipeline(query: str) -> dict:
    company = sec.resolve_company(query)
    ticker, cik = company["ticker"], company["cik"]
    warnings: list[str] = []

    submissions = sec.get_submissions(cik)
    tenks = sec.find_filings(submissions, "10-K", limit=1)
    if not tenks:
        raise HTTPException(status_code=404, detail="No 10-K filing found in the company's recent submissions.")
    filing = tenks[0]
    document_url = sec.archive_url(cik, filing["accession_number"], filing["primary_doc"])

    text = sec.html_to_text(sec.sec_get(document_url).text)
    item7 = sec.extract_item7(text)
    mdna_source = "item7" if item7 else "fallback"
    mdna_text = item7 if item7 else text[: sec.FALLBACK_CHARS]
    if not item7:
        warnings.append("Item 7 could not be isolated; the analysis used the start of the filing instead.")

    company_name = submissions.get("name") or company["name"]
    result = analysis.summarize(company_name, ticker, mdna_text)
    fin = load_financials(cik, filing["report_date"], warnings)

    # Gemini reports chart values in billions; the API returns raw USD everywhere.
    segments = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.revenue_segments]
    if fin and fin["capital_deployment"]:
        deployment, deployment_source = fin["capital_deployment"], "xbrl"
    else:
        deployment = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.capital_deployment]
        deployment_source = "gemini"

    return {
        "ticker": ticker,
        "company_name": company_name,
        "cik": cik,
        "filing": {
            "form": filing["form"],
            "accession_number": filing["accession_number"],
            "filing_date": filing["filing_date"],
            "report_date": filing["report_date"],
            "document_url": document_url,
            "mdna_source": mdna_source,
        },
        "summary": result.summary.model_dump(),
        "charts": {
            "revenue_segments": segments,
            "capital_deployment": deployment,
            "capital_deployment_source": deployment_source,
        },
        "financials": fin,
        "warnings": warnings,
    }


@app.get("/")
def health():
    return {"status": "ok"}
