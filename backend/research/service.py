"""Serves a company's research snapshot, ingesting it on demand (deterministic parsing only, no model calls), and
runs the model stages when a page asks for the AI analysis."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

import sec
from research import db, extract, ingest, interpret, llm, snapshot, store

# EDGAR is checked for newer filings at most this often per company; showcase companies are refreshed daily by
# the scheduled ingest, so their pages never wait on SEC.
FRESH_FOR = timedelta(hours=24)
# Non-showcase companies kept before the least recently viewed are evicted. Measured at 1.5-2.5 MB each (phase 2);
# later phases add narrative data, so 100 keeps the free tier's 0.5 GB comfortably clear.
MAX_COMPANIES = 100
# Refuse to add companies past this physical size, whatever the count says; Neon's free tier stops writes at 0.5 GB.
STORAGE_BRAKE_BYTES = 450_000_000
BUSY_RETRIES = 20
BUSY_WAIT_SECONDS = 3
# How long a request waits for another worker's model stages before telling the page to retry.
INSIGHTS_WAIT_SECONDS = 150
# After a spent quota, requests for the same company do not retry the models for this long.
QUOTA_BACKOFF_MINUTES = 30
QUOTA_MESSAGE = ("The free AI quota is used up for now, so the AI analysis could not be written. The tabs built from "
                 "the filings still work; try again later.")


def _resolve(conn, query: str) -> tuple[dict | None, dict | None]:
    """(stored company, SEC company) for a ticker or name; the SEC lookup only when the ticker is not stored."""
    company = store.find_company(conn, ticker=query)
    if company:
        return company, None
    resolved = sec.resolve_company(query)
    return store.find_company(conn, cik=resolved["cik"]), resolved


def _is_current(stored: dict | None) -> bool:
    return (
        stored is not None
        and stored["snapshot_version"] == snapshot.SNAPSHOT_VERSION
        and stored["parser_version"] == extract.PARSER_VERSION
        and datetime.now(timezone.utc) - stored["checked_at"] < FRESH_FOR
    )


def _served(payload: dict) -> dict:
    """Whether this server can write the AI analysis depends on where it runs (the daily job and the web app have
    their own keys), so it is set when the snapshot is served, not when it is built."""
    insights = payload.get("insights")
    if insights is not None:
        insights["configured"] = llm.configured()
    return payload


def get_snapshot(query: str) -> dict:
    with db.connect() as conn:
        company, _ = _resolve(conn, query)
        stored = store.load_snapshot(conn, company["company_id"]) if company else None
        if _is_current(stored):
            store.touch_company(conn, company["company_id"])
            return _served(stored["payload"])

        if company is None:
            if store.storage_bytes(conn) > STORAGE_BRAKE_BYTES:
                raise HTTPException(status_code=503, detail="The research database is full; try one of the featured companies.")
            store.evict_companies(conn, MAX_COMPANIES - 1)

        try:
            result = _ingest_waiting_for_others(conn, query)
        except HTTPException:
            if stored is not None:
                return _served(stored["payload"])  # SEC unavailable: serve what we have
            raise
        if not result["filings"]:
            raise HTTPException(status_code=422, detail="No supported annual or quarterly filings were found for this company.")
        store.touch_company(conn, result["company_id"])
        fresh = store.load_snapshot(conn, result["company_id"])
        return _served(fresh["payload"])


def _ingest_waiting_for_others(conn, query: str) -> dict:
    """Ingests, and when another request is already parsing some of the filings, waits for it instead of
    building a snapshot from half the filings."""
    for _ in range(BUSY_RETRIES):
        result = ingest.ingest_company(conn, query)
        if not any(f["status"] == "busy" for f in result["filings"]):
            return result
        time.sleep(BUSY_WAIT_SECONDS)
    return result


def generate_insights(query: str) -> dict:
    """Runs the model stages the company is missing and returns its snapshot with the AI analysis merged in."""
    if not llm.configured():
        raise HTTPException(status_code=503, detail="AI analysis is not configured on this server.")
    with db.connect() as conn:
        company, resolved = _resolve(conn, query)
        if company is None:
            raise HTTPException(status_code=404, detail="Load the company's research before its AI analysis.")
        company_id = company["company_id"]
        if store.recent_quota_failure(conn, company_id, QUOTA_BACKOFF_MINUTES):
            raise HTTPException(status_code=429, detail=QUOTA_MESSAGE)
        deadline = time.monotonic() + INSIGHTS_WAIT_SECONDS
        while True:
            try:
                interpret.run(conn, company_id)
                break
            except interpret.Busy as exc:
                if time.monotonic() > deadline:
                    raise HTTPException(status_code=503, detail="The AI analysis is still being written; try again in a minute.") from exc
                time.sleep(BUSY_WAIT_SECONDS)
            except llm.ModelUnavailable as exc:
                if exc.quota:
                    raise HTTPException(status_code=429, detail=QUOTA_MESSAGE) from exc
                raise HTTPException(status_code=503, detail=f"The AI analysis is unavailable ({exc}).") from exc
        stored = store.load_snapshot(conn, company_id)
        if stored is None or stored["snapshot_version"] != snapshot.SNAPSHOT_VERSION:
            return _served(snapshot.rebuild(conn, company_id))
        return _served(stored["payload"])
