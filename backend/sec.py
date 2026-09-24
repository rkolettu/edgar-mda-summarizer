from __future__ import annotations

import os
import re
from functools import lru_cache
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{padded_cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{padded_cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{filename}"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{accession}-index.htm"
REQUEST_TIMEOUT = 30

FALLBACK_CHARS = 100_000
RISK_FACTORS_CHARS = 80_000
MIN_SECTION_CHARS = 2_000

SEP = r"\s*[.:\-–—]?\s*"
ITEM7_START = re.compile(rf"item\s*7{SEP}management'?s\s+discussion\s+and\s+analysis", re.IGNORECASE)
ITEM7_END = re.compile(r"item\s*8\s*(?:[.:\-–—]|\s+financial\s+statements)", re.IGNORECASE)
ITEM1A_START = re.compile(rf"item\s*1a{SEP}risk\s+factors", re.IGNORECASE)
ITEM1A_END = re.compile(
    rf"item\s*1b{SEP}unresolved\s+staff|item\s*1c{SEP}cybersecurity|item\s*2{SEP}properties", re.IGNORECASE
)
TENQ_MDNA_START = re.compile(rf"item\s*2{SEP}management'?s\s+discussion\s+and\s+analysis", re.IGNORECASE)
TENQ_MDNA_END = re.compile(rf"item\s*3{SEP}quantitative|item\s*4{SEP}controls\s+and\s+procedures", re.IGNORECASE)
ANNUAL_REPORT_MDNA_START = re.compile(
    r"management'?s\s+discussion\s+and\s+analysis\s+of\s+(?:the\s+)?(?:consolidated\s+)?(?:financial\s+condition|results)",
    re.IGNORECASE,
)
ANNUAL_REPORT_MDNA_END = re.compile(
    r"management'?s\s+report\s+on\s+internal\s+control|report\s+of\s+independent\s+registered\s+public\s+accounting\s+firm",
    re.IGNORECASE,
)
# A heading reference inside prose ("see Item 8. Financial Statements", "discussed in Part II, Item 7. ...")
# is not a section boundary.
CROSS_REFERENCE = re.compile(
    r"(?:\bsee|\bin|\bunder|\brefer\s+to|\bdescribed|\bdiscussed|\bincluded|\bset\s+forth|\bwithin|\bwith|\bto|\bfrom|\bof|\band|\bthis|\bour)"
    r"[\s,]*(?:part\s+[iv]+[\s,.]*)?[\"“(']?\s*$",
    re.IGNORECASE,
)


def sec_get(url: str) -> requests.Response:
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise HTTPException(
            status_code=500,
            detail="SEC_USER_AGENT is not configured. Set it to an application name and real contact email.",
        )
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT)
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
    text = text.replace("\xa0", " ").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


ANY_ITEM_HEADING = re.compile(r"\bitem\s*\d{1,2}[a-c]?\s*[.:\-–—]?\s", re.IGNORECASE)
TOC_WINDOW = 150


def is_cross_reference(text: str, index: int) -> bool:
    return bool(CROSS_REFERENCE.search(text[max(0, index - 40):index]))


def is_toc_entry(text: str, end_of_heading: int) -> bool:
    # In a table of contents the next item heading follows within a few words (after a page number);
    # an intro sentence like "read with ... Part II, Item 8" is a cross-reference, not a TOC line.
    return any(
        not is_cross_reference(text, m.start())
        for m in ANY_ITEM_HEADING.finditer(text, end_of_heading, end_of_heading + TOC_WINDOW)
    )


def extract_section(text: str, start_re: re.Pattern, end_re: re.Pattern, min_chars: int = MIN_SECTION_CHARS) -> str | None:
    # The table of contents also matches, so take the longest heading-to-heading span.
    best = ""
    for start in start_re.finditer(text):
        if is_cross_reference(text, start.start()) or is_toc_entry(text, start.end()):
            continue
        end = next((m for m in end_re.finditer(text, start.end()) if not is_cross_reference(text, m.start())), None)
        if not end:
            continue
        section = text[start.start():end.start()]
        if len(section) > len(best):
            best = section
    return best if len(best) >= min_chars else None


def extract_item7(text: str) -> str | None:
    return extract_section(text, ITEM7_START, ITEM7_END)


def extract_risk_factors(text: str) -> str | None:
    section = extract_section(text, ITEM1A_START, ITEM1A_END)
    return section[:RISK_FACTORS_CHARS] if section else None


def find_exhibit(cik: int, accession_number: str, exhibit_type: str) -> str | None:
    index_url = FILING_INDEX_URL.format(
        cik=cik, accession_no_dashes=accession_number.replace("-", ""), accession=accession_number
    )
    try:
        html = sec_get(index_url).text
    except HTTPException:
        return None
    for row in BeautifulSoup(html, "html.parser").select("table.tableFile tr"):
        cells = row.find_all("td")
        if len(cells) < 4 or not cells[3].get_text(strip=True).upper().startswith(exhibit_type):
            continue
        link = cells[2].find("a")
        href = link.get("href", "") if link else ""
        href = href.replace("/ix?doc=", "")
        if href.lower().endswith((".htm", ".html", ".txt")):
            return urljoin("https://www.sec.gov", href)
    return None


def load_10k(cik: int, filing: dict) -> dict:
    document_url = archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = html_to_text(sec_get(document_url).text)
    return {
        **filing,
        "document_url": document_url,
        "mdna": extract_mdna(cik, filing, text, document_url),
        "risk_factors": extract_risk_factors(text),
    }


def load_10q(cik: int, filing: dict) -> dict:
    document_url = archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = html_to_text(sec_get(document_url).text)
    mdna = extract_section(text, TENQ_MDNA_START, TENQ_MDNA_END)
    return {
        **filing,
        "document_url": document_url,
        "mdna": {"text": mdna or text[:FALLBACK_CHARS], "source": "item2" if mdna else "fallback", "url": document_url},
    }


def extract_mdna(cik: int, filing: dict, filing_text: str, document_url: str) -> dict:
    item7 = extract_item7(filing_text)
    if item7:
        return {"text": item7, "source": "item7", "url": document_url}

    # Some filers (often banks) incorporate MD&A by reference to the annual report filed as Exhibit 13.
    exhibit_url = find_exhibit(cik, filing["accession_number"], "EX-13")
    if exhibit_url:
        exhibit_text = html_to_text(sec_get(exhibit_url).text)
        mdna = extract_section(exhibit_text, ANNUAL_REPORT_MDNA_START, ANNUAL_REPORT_MDNA_END)
        return {"text": mdna or exhibit_text[:FALLBACK_CHARS], "source": "exhibit13", "url": exhibit_url}

    return {"text": filing_text[:FALLBACK_CHARS], "source": "fallback", "url": document_url}
