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


def load_companyfacts(cik: int) -> dict:
    try:
        return sec.get_companyfacts(cik)
    except HTTPException:
        return {}


def load_financials(companyfacts: dict, report_date: str, warnings: list[str]) -> dict | None:
    result = financials.build_financials(companyfacts, report_date)
    if result is None:
        warnings.append("No XBRL financial data found; KPIs and trend charts are unavailable.")
    return result


def find_newer_10q(submissions: dict, tenk: dict) -> dict | None:
    tenqs = sec.find_filings(submissions, "10-Q", limit=1)
    return tenqs[0] if tenqs and tenqs[0]["filing_date"] > tenk["filing_date"] else None


def build_latest_quarter(company_name: str, ticker: str, cik: int, tenq_filing: dict | None, companyfacts: dict, warnings: list[str]) -> dict | None:
    if tenq_filing is None:
        return None
    try:
        tenq = sec.load_10q(cik, tenq_filing)
        result = analysis.summarize_quarter(company_name, ticker, tenq)
    except HTTPException as exc:
        warnings.append(f"Latest 10-Q update unavailable: {exc.detail}")
        return None
    return {
        "filing": {
            "form": tenq["form"],
            "filing_date": tenq["filing_date"],
            "report_date": tenq["report_date"],
            "document_url": tenq["document_url"],
            "mdna_source": tenq["mdna"]["source"],
        },
        "metrics": financials.build_quarter(companyfacts, tenq["report_date"]),
        "highlights": verify.annotate(
            [h.model_dump() for h in result.highlights], verify.normalize(tenq["mdna"]["text"])
        ),
    }


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
    companyfacts = load_companyfacts(cik)
    fin = load_financials(companyfacts, current["report_date"], warnings)
    changes = build_changes(company_name, ticker, cik, current, prior_filing, warnings)
    latest_quarter = build_latest_quarter(
        company_name, ticker, cik, find_newer_10q(submissions, current), companyfacts, warnings
    )

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
        "latest_quarter": latest_quarter,
        "warnings": warnings,
    }


@app.get("/")
def health():
    return {"status": "ok"}
