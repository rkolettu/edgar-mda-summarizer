"""Ingests filings into the research store: parse each filing once and store its facts and sections.

This stage is deterministic (no model calls, no tokens), so it is safe to run on a schedule:

    python -m research.ingest NVDA TSM SU        # specific companies
    python -m research.ingest --watchlist        # the showcase companies in research/watchlist.txt
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

from fastapi import HTTPException

import sec
from research import adapters, db, extract, ixbrl, snapshot, store

log = logging.getLogger("research.ingest")

WATCHLIST = Path(__file__).parent / "watchlist.txt"
# Three annual reports give five fiscal years of income statements (each carries three); quarters come from the
# last two fiscal years, whose 10-Qs also carry the prior-year quarters for year-over-year comparison.
DEFAULT_ANNUAL = 3
INTERIM_YEARS = 2
# Pause between filings so a watchlist run stays far below SEC's 10 requests per second.
PAUSE_SECONDS = 0.3


def read_watchlist(path: Path = WATCHLIST) -> list[str]:
    lines = (line.split("#", 1)[0].strip() for line in path.read_text().splitlines())
    return [line for line in lines if line]


def discover(submissions: dict, annual: int = DEFAULT_ANNUAL, interim_years: int = INTERIM_YEARS) -> list[dict]:
    """The latest `annual` annual filings, amendments to them, and interim filings from the last `interim_years`
    fiscal years, oldest first.

    Oldest first means originals are stored before their amendments and the company profile ends on the latest filing.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    filings = [
        {
            "form": form,
            "accession_number": recent["accessionNumber"][i],
            "primary_doc": recent["primaryDocument"][i],
            "filing_date": recent["filingDate"][i],
            "report_date": recent["reportDate"][i],
        }
        for i, form in enumerate(recent.get("form", []))
        if form in adapters.SUPPORTED_FORMS
    ]
    annuals = [f for f in filings if f["form"] in extract.ANNUAL_FORMS][:annual]
    if annuals:
        oldest = annuals[-1]["report_date"]
        if len(annuals) >= interim_years:
            interim_from = annuals[interim_years - 1]["report_date"]
        elif len(annuals) == annual:
            interim_from = oldest  # the caller asked for fewer years
        else:
            interim_from = ""  # a young filer: every interim report it has
        selected = [
            f for f in filings if f["report_date"] and (
                f in annuals
                or (extract.base_form(f["form"]) in extract.ANNUAL_FORMS and f["report_date"] >= oldest)
                or (extract.base_form(f["form"]) not in extract.ANNUAL_FORMS and f["report_date"] >= interim_from)
            )
        ]
    else:
        # A recent listing may have no annual report yet.
        selected = filings[:4]
    return list(reversed(selected))


def _content(response) -> bytes:
    content = getattr(response, "content", None)
    return content if isinstance(content, bytes) else response.text.encode()


def ingest_filing(conn, company_id: int, cik: int, filing: dict, force: bool = False) -> dict:
    accession = filing["accession_number"]
    summary = {"accession_number": accession, "form": filing["form"], "report_date": filing["report_date"]}
    adapter = adapters.adapter_for(filing["form"])
    if adapter is None:
        return {**summary, "status": "unsupported"}
    if not force and store.parsed_version(conn, accession) == extract.PARSER_VERSION:
        return {**summary, "status": "current"}
    run_id = store.claim_stage(conn, accession, "parse", extract.PARSER_VERSION, force=force)
    if run_id is None:
        return {**summary, "status": "busy"}

    try:
        documents = adapters.list_documents(cik, filing)
        primary = next(d for d in documents if d.role == "primary")
        responses = {primary.url: sec.sec_get(primary.url)}
        tagged = []
        for doc in documents:
            if not doc.ixbrl:
                continue
            response = responses.get(doc.url) or sec.sec_get(doc.url)
            responses[doc.url] = response
            if ixbrl.is_ixbrl(_content(response)):
                tagged.append((doc.url, _content(response)))
        parsed = ixbrl.parse_documents(tagged)

        narrative, narrative_warnings = adapter.narrative(cik, filing, responses[primary.url].text)
        is_amendment = filing["form"].endswith("/A")
        # Amendments are often partial (a 10-K/A may be only Part III), so nothing is expected of them.
        expected = () if is_amendment else adapter.expected
        report_date = date.fromisoformat(filing["report_date"]) if filing.get("report_date") else None
        extraction = extract.extract(
            parsed, filing["form"], expected, report_date, [n.as_section(i) for i, n in enumerate(narrative)]
        )
        if not tagged:
            extraction.warnings.insert(0, "No inline XBRL found; facts are unavailable for this filing.")
        extraction.warnings.extend(narrative_warnings)
        filing_id = store.save_filing(conn, company_id, filing, primary.url, documents, extraction, extract.PARSER_VERSION)
    except Exception as exc:
        store.finish_stage(conn, run_id, "failed", error=_error(exc))
        log.warning("Failed to ingest %s: %s", accession, _error(exc))
        return {**summary, "status": "failed", "error": _error(exc)}

    store.finish_stage(conn, run_id, "succeeded", filing_id=filing_id)
    return {
        **summary,
        "status": "ingested",
        "filing_id": filing_id,
        "facts": len(extraction.facts),
        "sections": len(extraction.sections),
        "confidence": extraction.parser_confidence,
        "missing": sorted(k for k, v in extraction.coverage.items() if isinstance(v, dict) and not v.get("found")),
        "warnings": extraction.warnings,
    }


def _error(exc: Exception) -> str:
    return exc.detail if isinstance(exc, HTTPException) else repr(exc)


def ingest_company(conn, query: str, *, annual: int = DEFAULT_ANNUAL, force: bool = False, showcase: bool = False) -> dict:
    company = sec.resolve_company(query)
    cik = company["cik"]
    submissions = sec.get_submissions(cik)
    filings = discover(submissions, annual)
    filer_cik = cik
    if not filings:
        # A newly reorganized holding company files under its predecessor until its first annual report.
        predecessor = sec.find_predecessor_cik(submissions)
        if predecessor:
            filer_cik, submissions = predecessor, sec.get_submissions(predecessor)
            filings = discover(submissions, annual)

    company_id = store.upsert_company(conn, cik, company["ticker"], submissions.get("name") or company["name"], showcase)
    results = []
    for filing in filings:
        results.append(ingest_filing(conn, company_id, filer_cik, filing, force))
        if results[-1]["status"] == "ingested":
            time.sleep(PAUSE_SECONDS)
    store.refresh_company_profile(conn, company_id)
    store.prune_section_text(conn, company_id)
    changed = any(r["status"] == "ingested" for r in results)
    stored = store.load_snapshot(conn, company_id)
    if changed or stored is None or (stored["snapshot_version"], stored["parser_version"]) != (snapshot.SNAPSHOT_VERSION, extract.PARSER_VERSION):
        snapshot.rebuild(conn, company_id)
    else:
        store.mark_checked(conn, company_id)
    return {"ticker": company["ticker"], "cik": cik, "company_id": company_id, "filings": results}


def _detail(result: dict) -> str:
    if result["status"] == "failed":
        return result["error"]
    if result["status"] != "ingested":
        return ""
    missing = f"; missing {', '.join(result['missing'])}" if result["missing"] else ""
    return f"{result['facts']} facts, {result['sections']} sections, confidence {result['confidence']}{missing}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse SEC filings into the research store (no model calls).")
    parser.add_argument("tickers", nargs="*", help="tickers or company names")
    parser.add_argument("--watchlist", action="store_true", help=f"also ingest the companies in {WATCHLIST.name}")
    parser.add_argument("--annual", type=int, default=DEFAULT_ANNUAL, help="annual filings to keep per company")
    parser.add_argument("--force", action="store_true", help="re-parse filings already stored at this parser version")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    watchlist = read_watchlist() if args.watchlist else []
    queries = list(dict.fromkeys(args.tickers + watchlist))
    if not queries:
        parser.error("name at least one ticker, or pass --watchlist")

    failures = 0
    with db.connect() as conn:
        for query in queries:
            try:
                result = ingest_company(conn, query, annual=args.annual, force=args.force, showcase=query in watchlist)
            except Exception as exc:
                failures += 1
                print(f"{query}: failed: {_error(exc)}", flush=True)
                continue
            print(f"{result['ticker']} (CIK {result['cik']})", flush=True)
            for f in result["filings"]:
                print(f"  {f['form']:<6} {f['report_date']}  {f['status']:<11} {_detail(f)}", flush=True)
                failures += f["status"] == "failed"
        print(f"Database size: {store.storage_bytes(conn) / 1e6:.1f} MB", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
