from __future__ import annotations

import re
from functools import lru_cache

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException

SEC_HEADERS = {"User-Agent": "RishabKolettu InvestmentResearch (rishab@example.com)"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{padded_cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{padded_cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{filename}"
REQUEST_TIMEOUT = 30

FALLBACK_CHARS = 100_000
MIN_SECTION_CHARS = 2_000

ITEM7_PATTERN = re.compile(
    r"item\s*7\s*[.:\-]?\s*management['’]?s\s+discussion\s+and\s+analysis", re.IGNORECASE
)
ITEM8_PATTERN = re.compile(r"item\s*8\s*[.:\-]", re.IGNORECASE)


def sec_get(url: str) -> requests.Response:
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=REQUEST_TIMEOUT)
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


def get_submissions(cik: int) -> dict:
    return sec_get(SUBMISSIONS_URL.format(padded_cik=str(cik).zfill(10))).json()


def get_companyfacts(cik: int) -> dict:
    return sec_get(COMPANYFACTS_URL.format(padded_cik=str(cik).zfill(10))).json()


def find_filings(submissions: dict, form: str, limit: int) -> list[dict]:
    recent = submissions.get("filings", {}).get("recent", {})
    filings = []
    for i, f in enumerate(recent.get("form", [])):
        if f != form:
            continue
        filings.append(
            {
                "form": f,
                "accession_number": recent["accessionNumber"][i],
                "primary_doc": recent["primaryDocument"][i],
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
            }
        )
        if len(filings) == limit:
            break
    return filings


def archive_url(cik: int, accession_number: str, filename: str) -> str:
    return ARCHIVE_URL.format(
        cik=cik, accession_no_dashes=accession_number.replace("-", ""), filename=filename
    )


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
