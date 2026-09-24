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

RISK_FACTORS_CHARS = 80_000
MIN_SECTION_CHARS = 2_000
FOREIGN_MDNA_CHARS = 120_000

SEP = r"\s*[.:\-–—]?\s*"
ITEM7_START = re.compile(rf"it\s*em\s*7{SEP}management'?s\s+discussion\s+and\s+analysis", re.IGNORECASE)
ITEM7_END = re.compile(r"it\s*em\s*(?:7a\s*[.:\-–—]?\s+quantitative|8\s*(?:[.:\-–—]|\s+financial\s+statements))", re.IGNORECASE)
ITEM1A_START = re.compile(rf"it\s*em\s*1a{SEP}risk\s+factors", re.IGNORECASE)
ITEM1A_END = re.compile(
    rf"it\s*em\s*1b{SEP}unresolved\s+staff|it\s*em\s*1c{SEP}cybersecurity|it\s*em\s*2{SEP}properties", re.IGNORECASE
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
# Some large filers put a short pointer under Item 7 and place the full MD&A later in
# the same 10-K. Require the standalone heading followed by its opening sentence so
# a table-of-contents entry or an Item 7 cross-reference cannot become the start.
INLINE_MDNA_START = re.compile(
    r"management'?s\s+discussion\s+and\s+analysis\s+the\s+following\s+is\s+management'?s\s+discussion\s+and\s+analysis\s+of\s+(?:the\s+)?financial\s+condition",
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


ANY_ITEM_HEADING = re.compile(r"\bit\s*em\s*\d{1,2}[a-c]?\s*[.:\-–—]?\s", re.IGNORECASE)
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


# UBS incorporates Item 5 by reference to the full annual report embedded in its 20-F.
# Both boundaries are specific annual-report chapter headers, avoiding the short Item 5 pointer.
UBS_OPERATING_START = re.compile(
    r"Annual Report\s+\d{4}\s*\|\s*Financial and operating performance\s*\|\s*Accounting and financial reporting\s+\d+\s+Financial and operating performance\s+Management report",
    re.IGNORECASE,
)
UBS_OPERATING_END = re.compile(
    r"Annual Report\s+\d{4}\s*\|\s*Risk,\s*capital,\s*liquidity and funding,\s*and balance sheet\s+\d+\s+Risk,",
    re.IGNORECASE,
)
UBS_RISK_START = re.compile(r"Risk factors\s+Certain risks,\s+including those described below", re.IGNORECASE)
TWENTYF_START = re.compile(r"item\s*5\s*[.\-–—]?\s*operating\s+and\s+financial\s+review\s+and\s+prospects", re.IGNORECASE)
TWENTYF_END = re.compile(r"item\s*6\s*[.\-–—]?\s*directors,?\s+senior\s+management", re.IGNORECASE)
FORTYF_MDNA_START = re.compile(
    r"management'?s\s+discussion\s+and\s+analysis\s+(?:this\s+management'?s\s+discussion\s+and\s+analysis|management'?s\s+discussion\s+and\s+analysis\s*\(md&a\)|about\s+[a-z]+)",
    re.IGNORECASE,
)
FORTYF_REFERENCE = re.compile(
    r"(?:exhibit\s+(99[.\-]\d+|2)\s*:\s*management'?s\s+discussion\s+and\s+analysis|management'?s\s+discussion\s+and\s+analysis.{0,140}?(?:exhibit\s+(99[.\-]\d+|2)))",
    re.IGNORECASE,
)


def load_20f(cik: int, filing: dict) -> dict:
    document_url = archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = html_to_text(sec_get(document_url).text)
    operating = extract_section(text, UBS_OPERATING_START, UBS_OPERATING_END)
    source = "operating_review"
    if not operating:
        operating = extract_section(text, TWENTYF_START, TWENTYF_END)
        source = "item5"
    if not operating:
        raise HTTPException(status_code=422, detail="Could not isolate the operating and financial review in this 20-F.")
    # An incorporated-by-reference Item 5 is not the underlying management discussion.
    if len(operating) < 5_000 or "incorporated by reference" in operating[:1_500].lower() and len(operating) < 10_000:
        raise HTTPException(status_code=422, detail="The 20-F refers to a separate annual report; its management discussion could not be isolated.")
    risk_start = UBS_RISK_START.search(text)
    operating_start = UBS_OPERATING_START.search(text)
    risks = None
    if risk_start:
        risk_end = risk_start.start() + RISK_FACTORS_CHARS
        if operating_start and operating_start.start() > risk_start.start():
            risk_end = min(risk_end, operating_start.start())
        risks = text[risk_start.start():risk_end]
    return {**filing, "document_url": document_url,
            "mdna": {"text": operating[:FOREIGN_MDNA_CHARS], "source": source, "url": document_url},
            "risk_factors": risks}


def load_40f(cik: int, filing: dict) -> dict:
    document_url = archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = html_to_text(sec_get(document_url).text)
    reference = FORTYF_REFERENCE.search(text)
    if not reference:
        raise HTTPException(status_code=422, detail="Could not locate a management discussion exhibit in this 40-F.")
    exhibit_type = "EX-" + (reference.group(1) or reference.group(2)).upper().replace("-", ".")
    exhibit_url = find_exhibit(cik, filing["accession_number"], exhibit_type)
    if not exhibit_url:
        raise HTTPException(status_code=422, detail="The 40-F management discussion exhibit is unavailable.")
    exhibit_text = html_to_text(sec_get(exhibit_url).text)
    # The exhibit must itself identify as MD&A near the beginning; do not summarize financial statements.
    start = FORTYF_MDNA_START.search(exhibit_text[:30_000])
    if not start or len(exhibit_text) - start.start() < 5_000:
        raise HTTPException(status_code=422, detail="Could not verify the management discussion in this 40-F exhibit.")
    risks = None
    risk_match = re.search(r"Risk Factors that May Affect Future Results\s+", exhibit_text[10_000:], re.IGNORECASE)
    if risk_match:
        pos = 10_000 + risk_match.start()
        risks = exhibit_text[pos:pos + RISK_FACTORS_CHARS]
    sample = exhibit_text[:FOREIGN_MDNA_CHARS]
    currency = ("CAD" if re.search(r"Canadian dollars|\bCAD\b|C\$", sample, re.IGNORECASE)
                else "USD" if re.search(r"U\.?S\.?\s+dollars|\bUSD\b|US\$", sample, re.IGNORECASE)
                else "unknown")
    return {**filing, "document_url": document_url, "currency": currency,
            "mdna": {"text": exhibit_text[start.start():start.start() + FOREIGN_MDNA_CHARS], "source": "mdna_exhibit", "url": exhibit_url},
            "risk_factors": risks}


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
        if len(cells) < 4 or not re.match(rf"{re.escape(exhibit_type)}(?:\.|$)", cells[3].get_text(strip=True).upper()):
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
    if mdna is None:
        raise HTTPException(status_code=422, detail="Could not isolate Item 2 MD&A in the 10-Q.")
    return {
        **filing,
        "document_url": document_url,
        "mdna": {"text": mdna, "source": "item2", "url": document_url},
    }


def extract_mdna(cik: int, filing: dict, filing_text: str, document_url: str) -> dict:
    item7 = extract_item7(filing_text)
    if item7:
        return {"text": item7, "source": "item7", "url": document_url}

    inline = extract_section(filing_text, INLINE_MDNA_START, ANNUAL_REPORT_MDNA_END)
    if inline:
        return {"text": inline, "source": "item7", "url": document_url}

    # Some filers (often banks) incorporate MD&A by reference to the annual report filed as Exhibit 13.
    exhibit_url = find_exhibit(cik, filing["accession_number"], "EX-13")
    if exhibit_url:
        exhibit_text = html_to_text(sec_get(exhibit_url).text)
        mdna = extract_section(exhibit_text, ANNUAL_REPORT_MDNA_START, ANNUAL_REPORT_MDNA_END)
        if mdna:
            return {"text": mdna, "source": "exhibit13", "url": exhibit_url}

    raise HTTPException(status_code=422, detail="Could not isolate MD&A in this 10-K or its Exhibit 13.")
