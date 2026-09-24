from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import analysis
import financials
import sec
import verify

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


def filing_source(tenk: dict) -> str:
    return verify.normalize(f"{tenk['mdna']['text']}\n{tenk['risk_factors'] or ''}")


def build_changes(company_name: str, ticker: str, cik: int, current: dict, prior_filing: dict | None, warnings: list[str]) -> dict | None:
    if prior_filing is None:
        warnings.append("No prior-year 10-K found; the year-over-year comparison is unavailable.")
        return None
    try:
        prior = sec.load_10k(cik, prior_filing)
        result = analysis.compare(company_name, ticker, current, prior)
    except HTTPException as exc:
        warnings.append(f"Year-over-year comparison unavailable: {exc.detail}")
        return None

    sources = {"current": filing_source(current), "prior": filing_source(prior)}
    items = [
        {
            **c.model_dump(),
            "verified": verify.quote_in_source(c.evidence, sources["prior" if c.change_type == "removed" else "current"]),
        }
        for c in result.changes
    ]
    return {
        "prior_filing": {
            "filing_date": prior["filing_date"],
            "report_date": prior["report_date"],
            "document_url": prior["document_url"],
        },
        "items": items,
    }


def run_pipeline(query: str) -> dict:
    company = sec.resolve_company(query)
    ticker, cik = company["ticker"], company["cik"]
    warnings: list[str] = []

    submissions = sec.get_submissions(cik)
    tenks = sec.find_filings(submissions, "10-K", limit=2)
    if not tenks:
        raise HTTPException(status_code=404, detail="No 10-K filing found in the company's recent submissions.")
    current = sec.load_10k(cik, tenks[0])
    prior_filing = tenks[1] if len(tenks) > 1 else None
    mdna, risk_factors = current["mdna"], current["risk_factors"]
    if mdna["source"] == "fallback":
        warnings.append("Item 7 could not be isolated; the analysis used the start of the filing instead.")

    company_name = submissions.get("name") or company["name"]
    result = analysis.summarize(company_name, ticker, mdna["text"], risk_factors)
    fin = load_financials(cik, current["report_date"], warnings)
    changes = build_changes(company_name, ticker, cik, current, prior_filing, warnings)

    # Gemini reports chart values in billions; the API returns raw USD everywhere.
    segments = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.revenue_segments]
    if fin and fin["capital_deployment"]:
        deployment, deployment_source = fin["capital_deployment"], "xbrl"
    else:
        deployment = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.capital_deployment]
        deployment_source = "gemini"

    normalized_source = filing_source(current)
    summary = {
        key: verify.annotate([i.model_dump() for i in insights], normalized_source)
        for key, insights in result.summary
    }

    return {
        "ticker": ticker,
        "company_name": company_name,
        "cik": cik,
        "filing": {
            "form": current["form"],
            "accession_number": current["accession_number"],
            "filing_date": current["filing_date"],
            "report_date": current["report_date"],
            "document_url": current["document_url"],
            "mdna_source": mdna["source"],
            "mdna_url": mdna["url"],
            "risk_factors_found": risk_factors is not None,
        },
        "summary": summary,
        "charts": {
            "revenue_segments": segments,
            "capital_deployment": deployment,
            "capital_deployment_source": deployment_source,
        },
        "checks": {
            "segments": verify.segment_check(segments, fin and fin["kpis"]["revenue"]),
        },
        "financials": fin,
        "changes": changes,
        "warnings": warnings,
    }


@app.get("/")
def health():
    return {"status": "ok"}
