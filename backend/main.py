from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import hmac
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import analysis
import cache
import figures
import financials
import sec
import verify
from research import db as research_db
from research import service as research_service
from research import store as research_store

# Filings never change once filed, so a finished analysis can be served from Vercel's CDN for a day;
# a new filing shows up in the next response after that.
SUMMARY_CACHE_CONTROL = "public, max-age=0, s-maxage=86400, stale-while-revalidate=86400"
SEARCH_CACHE_CONTROL = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
# Stored research changes when the scheduled ingest adds a filing, so the CDN copy stays short-lived.
RESEARCH_CACHE_CONTROL = "public, max-age=0, s-maxage=300, stale-while-revalidate=3600"
RESULT_CACHE_SIZE = 64

app = FastAPI(title="item7-extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResultCache:
    def __init__(self, size: int):
        self._size = size
        self._items: OrderedDict[tuple, dict] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> dict | None:
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def put(self, key: tuple, value: dict) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


RESULT_CACHE = ResultCache(RESULT_CACHE_SIZE)


@dataclass
class Section:
    value: dict | None = None
    warnings: list[str] = field(default_factory=list)
    # A transient failure (SEC or Gemini error) means the result must not be cached.
    degraded: bool = False


def json_errors(fn, *args):
    # Unhandled 500s bypass CORSMiddleware, which the browser reports only as "Failed to fetch".
    try:
        return fn(*args)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc!r}") from exc


def error_detail(exc: Exception) -> str:
    return exc.detail if isinstance(exc, HTTPException) else repr(exc)


router = APIRouter()


@router.get("/search")
def search(
    response: Response,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(8, ge=1, le=25),
):
    results = json_errors(sec.search_companies, q, limit)
    response.headers["Cache-Control"] = SEARCH_CACHE_CONTROL
    return results


@router.get("/summarize")
def summarize_ticker(response: Response, ticker: str = Query(..., min_length=1, max_length=100)):
    result, degraded = json_errors(run_pipeline, ticker)
    response.headers["Cache-Control"] = "no-store" if degraded else SUMMARY_CACHE_CONTROL
    return result


def load_companyfacts(cik: int) -> tuple[dict, bool]:
    try:
        return sec.get_companyfacts(cik), False
    except HTTPException:
        return {}, True


def build_financials(facts_future: Future, report_date: str) -> Section:
    companyfacts, failed = facts_future.result()
    fin = financials.build_financials(companyfacts, report_date)
    if fin is None:
        return Section(None, ["No XBRL financial data found; KPIs and trend charts are unavailable."], failed)
    return Section(fin)


def find_newer_10q(submissions: dict, tenk: dict) -> dict | None:
    tenqs = sec.find_filings(submissions, "10-Q", limit=1)
    return tenqs[0] if tenqs and tenqs[0]["filing_date"] > tenk["filing_date"] else None


def filing_texts(tenk: dict) -> list[str]:
    return [tenk["mdna"]["text"], tenk["risk_factors"] or ""]


def filing_source(tenk: dict) -> str:
    return verify.normalize("\n".join(filing_texts(tenk)))


def figure_index(texts: list[str], fin: dict | None, quarter: dict | None = None) -> figures.FigureIndex:
    index = figures.FigureIndex()
    for text in texts:
        index.add_text(text)
    figures.add_financials(index, fin)
    figures.add_quarter(index, quarter)
    return index


def build_changes(company_name: str, ticker: str, current: dict, prior_future: Future | None, fin: dict | None) -> Section:
    if prior_future is None:
        return Section(None, [f"No prior-year {current['form']} found; the year-over-year comparison is unavailable."])
    try:
        prior = prior_future.result()
        result = analysis.compare(company_name, ticker, current, prior, financials.reference_block(fin))
    except Exception as exc:
        return Section(None, [f"Year-over-year comparison unavailable: {error_detail(exc)}"], degraded=True)

    sources = {"current": filing_source(current), "prior": filing_source(prior)}
    index = figure_index(filing_texts(current) + filing_texts(prior), fin)
    items = [
        verify.annotate_item(c.model_dump(), sources["prior" if c.change_type == "removed" else "current"], index)
        for c in result.changes
    ]
    prior_filing = {k: prior[k] for k in ("form", "filing_date", "report_date", "document_url")}
    return Section({"prior_filing": prior_filing, "items": items})


def build_latest_quarter(
    company_name: str, ticker: str, tenq_future: Future | None, companyfacts: dict, fin: dict | None
) -> Section:
    if tenq_future is None:
        return Section()
    try:
        tenq = tenq_future.result()
        metrics = financials.build_quarter(companyfacts, tenq["report_date"])
        result = analysis.summarize_quarter(company_name, ticker, tenq, financials.reference_block(fin, metrics, years=1))
    except Exception as exc:
        return Section(None, [f"Latest 10-Q update unavailable: {error_detail(exc)}"], degraded=True)

    index = figure_index([tenq["mdna"]["text"]], fin, metrics)
    return Section({
        "filing": {
            "form": tenq["form"],
            "filing_date": tenq["filing_date"],
            "report_date": tenq["report_date"],
            "document_url": tenq["document_url"],
            "mdna_source": tenq["mdna"]["source"],
        },
        "metrics": metrics,
        "highlights": verify.annotate(
            [h.model_dump() for h in result.highlights], verify.normalize(tenq["mdna"]["text"]), index
        ),
    })


def run_pipeline(query: str) -> tuple[dict, bool]:
    company = sec.resolve_company(query)
    ticker, cik = company["ticker"], company["cik"]

    submissions = sec.get_submissions(cik)
    forms = {"10-K": sec.load_10k, "20-F": sec.load_20f, "40-F": sec.load_40f}

    def latest_annual(submissions: dict) -> list[dict] | None:
        annual_groups = [filings for form in forms if (filings := sec.find_filings(submissions, form, limit=2))]
        return max(annual_groups, key=lambda filings: filings[0]["filing_date"], default=None)

    annual = latest_annual(submissions)
    if not annual:
        # A newly reorganized holding company files its annual reports under the predecessor until its first 10-K.
        predecessor = sec.find_predecessor_cik(submissions)
        if predecessor:
            cik, submissions = predecessor, sec.get_submissions(predecessor)
            annual = latest_annual(submissions)
    if not annual:
        raise HTTPException(status_code=404, detail="No 10-K, 20-F, or 40-F found in the company's recent submissions.")
    current_filing = annual[0]
    prior_filing = annual[1] if len(annual) > 1 else None
    tenq_filing = find_newer_10q(submissions, current_filing) if current_filing["form"] == "10-K" else None

    cache_key = (cik, *(f["accession_number"] if f else None for f in (current_filing, prior_filing, tenq_filing)))
    # L1: Check in-memory LRU cache
    cached = RESULT_CACHE.get(cache_key)
    if cached is not None:
        return cached, False
    # L2: Check SQLite persistent cache
    db_key = str(cache_key)
    db_cached = cache.db_cache.get(db_key)
    if db_cached is not None:
        # Warm up the in-memory cache for next time
        RESULT_CACHE.put(cache_key, db_cached)
        return db_cached, False

    company_name = submissions.get("name") or company["name"]
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        loader = forms[current_filing["form"]]
        current_future = pool.submit(loader, cik, current_filing)
        prior_future = pool.submit(loader, cik, prior_filing) if prior_filing else None
        tenq_future = pool.submit(sec.load_10q, cik, tenq_filing) if tenq_filing else None
        facts_future = pool.submit(load_companyfacts, cik) if current_filing["form"] == "10-K" else pool.submit(lambda: ({}, False))

        current = current_future.result()
        # Financials come first so every Gemini call can be given the authoritative figures.
        fin_section = build_financials(facts_future, current["report_date"]) if current["form"] == "10-K" else Section()
        fin = fin_section.value
        summary_future = pool.submit(
            analysis.summarize, company_name, ticker, current["mdna"]["text"], current["risk_factors"],
            financials.reference_block(fin), current["form"], current.get("currency"),
        )
        changes_future = pool.submit(build_changes, company_name, ticker, current, prior_future, fin)
        quarter_future = pool.submit(
            build_latest_quarter, company_name, ticker, tenq_future, facts_future.result()[0], fin
        )

        result = summary_future.result()
        changes, quarter = changes_future.result(), quarter_future.result()
    finally:
        # Don't hold the response for optional work if the main analysis failed.
        pool.shutdown(wait=False, cancel_futures=True)

    mdna, risk_factors = current["mdna"], current["risk_factors"]
    warnings: list[str] = []
    for section in (fin_section, changes, quarter):
        warnings.extend(section.warnings)
    if current["form"] != "10-K":
        warnings.insert(0, "Financial trend cards are unavailable for this filing's XBRL taxonomy.")
    if current.get("currency") in analysis.CURRENCY_NAMES:
        name = analysis.CURRENCY_NAMES[current["currency"]][0]
        warnings.append(f"Charts are omitted because this filing reports {name} and chart data requires US dollars.")
    elif current.get("currency") == "unknown":
        warnings.append("Charts are omitted because the filing's reporting currency could not be verified.")

    # Gemini reports chart values in billions; the API returns raw USD everywhere.
    segments = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.revenue_segments]
    if fin and fin["capital_deployment"]:
        deployment, deployment_source = fin["capital_deployment"], "xbrl"
    else:
        deployment = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.capital_deployment]
        deployment_source = "gemini"
    if current.get("currency") not in (None, "USD"):
        segments, deployment = [], []

    normalized_source = filing_source(current)
    index = figure_index(filing_texts(current), fin)
    summary = {
        key: verify.annotate([i.model_dump() for i in insights], normalized_source, index)
        for key, insights in result.summary
    }

    response = {
        "ticker": ticker,
        "company_name": company_name,
        "cik": cik,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filing": {
            "form": current["form"],
            "currency": current.get("currency"),
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
        "changes": changes.value,
        "latest_quarter": quarter.value,
        "warnings": warnings,
    }

    degraded = any(s.degraded for s in (fin_section, changes, quarter))
    if not degraded:
        # L1: Store in in-memory LRU cache
        RESULT_CACHE.put(cache_key, response)
        # L2: Persist to SQLite cache for warm restarts
        db_key = str(cache_key)
        cache.db_cache.put(db_key, response)
    return response, degraded


@router.get("/research/{ticker}")
def research_snapshot(response: Response, ticker: str):
    """Every research tab's data for a company, from the stored snapshot; ingests the company on first request."""
    if not research_db.database_url():
        raise HTTPException(status_code=503, detail="The research store is not configured.")
    result = json_errors(research_service.get_snapshot, ticker)
    response.headers["Cache-Control"] = RESEARCH_CACHE_CONTROL
    return result


@router.post("/research/{ticker}/insights")
def research_insights(ticker: str):
    """Writes the company's AI analysis if it is missing (model calls, once per filing) and returns the snapshot."""
    if not research_db.database_url():
        raise HTTPException(status_code=503, detail="The research store is not configured.")
    return json_errors(research_service.generate_insights, ticker)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatTurn] = []


# Questions per visitor per minute, per server instance; the providers' own quotas are the backstop.
CHAT_PER_MINUTE = 10
_chat_times: dict[str, list[float]] = {}
_chat_lock = threading.Lock()


def _chat_allowed(visitor: str) -> bool:
    now = time.monotonic()
    with _chat_lock:
        recent = [t for t in _chat_times.get(visitor, []) if now - t < 60]
        allowed = len(recent) < CHAT_PER_MINUTE
        if allowed:
            recent.append(now)
        _chat_times[visitor] = recent
        if len(_chat_times) > 10_000:
            _chat_times.clear()
    return allowed


@router.post("/research/{ticker}/chat")
def research_chat(ticker: str, body: ChatRequest, request: Request):
    """Answers a question about the company's stored filings, citing the passages it used."""
    if not research_db.database_url():
        raise HTTPException(status_code=503, detail="The research store is not configured.")
    visitor = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    if not _chat_allowed(visitor):
        raise HTTPException(status_code=429, detail="Too many questions in a minute; wait a moment and ask again.")
    return json_errors(research_service.ask, ticker, body.question, [t.model_dump() for t in body.history])


@router.get("/research/{ticker}/filings")
def research_filings(response: Response, ticker: str):
    """Filings stored for a company with their coverage and headline facts (read-only; ingestion runs separately)."""
    if not research_db.database_url():
        raise HTTPException(status_code=503, detail="The research store is not configured.")
    result = json_errors(load_research_filings, ticker)
    response.headers["Cache-Control"] = RESEARCH_CACHE_CONTROL
    return result


def load_research_filings(query: str) -> dict:
    with research_db.connect() as conn:
        company = research_store.find_company(conn, ticker=query)
        if company is None:
            try:
                company = research_store.find_company(conn, cik=sec.resolve_company(query)["cik"])
            except HTTPException:
                company = None
        if company is None:
            raise HTTPException(status_code=404, detail=f"No stored research for '{query}' yet.")
        filings = research_store.company_filings(conn, company["company_id"])
        latest = next((f for f in filings if not f["form_type"].endswith("/A")), None)
        metrics = research_store.current_metrics(conn, latest["filing_id"]) if latest else []
    return {"company": company, "filings": filings, "latest_metrics": metrics}


@app.get("/")
@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/cache/stats")
def cache_stats():
    """Return cache statistics for debugging."""
    db_stats = cache.db_cache.stats()
    return {
        "memory_cache_size": RESULT_CACHE._size,
        "memory_cache_items": len(RESULT_CACHE._items),
        "persistent_cache": db_stats,
    }


@router.post("/cache/clear")
def cache_clear(x_admin_token: Optional[str] = Header(default=None)):
    """Clear all caches. Disabled unless CACHE_ADMIN_TOKEN is set; the request must send it as X-Admin-Token."""
    expected = os.environ.get("CACHE_ADMIN_TOKEN")
    if not expected or not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=403, detail="Clearing the cache requires the admin token.")
    RESULT_CACHE.clear()
    cache.db_cache.clear()
    return {"status": "cleared"}


# Vercel Services forwards /api/... with the prefix intact; also serve the bare paths in case a
# deployment strips it, so the routes work either way.
app.include_router(router, prefix="/api")
app.include_router(router)


if __name__ == "__main__":
    import sys
    if "--clear-cache" in sys.argv:
        print("Clearing all caches...")
        RESULT_CACHE.clear()
        cache.db_cache.clear()
        print("Caches cleared.")
