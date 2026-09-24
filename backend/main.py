from __future__ import annotations

import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

import analysis
import figures
import financials
import sec
import verify

# Filings never change once filed, so a finished analysis can be served from Vercel's CDN for a day;
# a new filing shows up in the next response after that.
SUMMARY_CACHE_CONTROL = "public, max-age=0, s-maxage=86400, stale-while-revalidate=86400"
SEARCH_CACHE_CONTROL = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
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
        return Section(None, ["No prior-year 10-K found; the year-over-year comparison is unavailable."])
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
    prior_filing = {k: prior[k] for k in ("filing_date", "report_date", "document_url")}
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
    tenks = sec.find_filings(submissions, "10-K", limit=2)
    if not tenks:
        raise HTTPException(status_code=404, detail="No 10-K filing found in the company's recent submissions.")
    prior_filing = tenks[1] if len(tenks) > 1 else None
    tenq_filing = find_newer_10q(submissions, tenks[0])

    cache_key = (cik, *(f["accession_number"] if f else None for f in (tenks[0], prior_filing, tenq_filing)))
    cached = RESULT_CACHE.get(cache_key)
    if cached is not None:
        return cached, False

    company_name = submissions.get("name") or company["name"]
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        current_future = pool.submit(sec.load_10k, cik, tenks[0])
        prior_future = pool.submit(sec.load_10k, cik, prior_filing) if prior_filing else None
        tenq_future = pool.submit(sec.load_10q, cik, tenq_filing) if tenq_filing else None
        facts_future = pool.submit(load_companyfacts, cik)

        current = current_future.result()
        # Financials come first so every Gemini call can be given the authoritative figures.
        fin_section = build_financials(facts_future, current["report_date"])
        fin = fin_section.value
        summary_future = pool.submit(
            analysis.summarize, company_name, ticker, current["mdna"]["text"], current["risk_factors"],
            financials.reference_block(fin),
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

    # Gemini reports chart values in billions; the API returns raw USD everywhere.
    segments = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.revenue_segments]
    if fin and fin["capital_deployment"]:
        deployment, deployment_source = fin["capital_deployment"], "xbrl"
    else:
        deployment = [{"name": p.name, "value": p.value * 1e9} for p in result.charts.capital_deployment]
        deployment_source = "gemini"

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
        RESULT_CACHE.put(cache_key, response)
    return response, degraded


@app.get("/")
@router.get("/health")
def health():
    return {"status": "ok"}


# Vercel Services forwards /api/... with the prefix intact; also serve the bare paths in case a
# deployment strips it, so the routes work either way.
app.include_router(router, prefix="/api")
app.include_router(router)
