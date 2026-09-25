from __future__ import annotations

import os
import re
from functools import lru_cache
from urllib.parse import quote_plus, urljoin

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

SEP = r"\s*[.:\-–—|]?\s*"
# Some filers repeat the company name inside the heading ("Item 7. Bank of America Corporation and Subsidiaries
# Management's Discussion and Analysis").
ITEM7_START = re.compile(
    rf"i\s*t\s*e\s*m\s*7{SEP}(?:[A-Z][\w.,&' ]{{2,80}}?\s+and\s+subsidiaries\s+)?management'?s\s+discussion\s+and\s+analysis",
    re.IGNORECASE,
)
ITEM7_END = re.compile(r"i\s*t\s*e\s*m\s*(?:7a\s*[.:\-–—|]?\s+quantitative|8\s*(?:[.:\-–—|]|\s+financial\s+statements))", re.IGNORECASE)
ITEM1A_START = re.compile(rf"i\s*t\s*e\s*m\s*1a{SEP}risk\s+factors", re.IGNORECASE)
ITEM1A_END = re.compile(
    rf"i\s*t\s*e\s*m\s*1b{SEP}unresolved\s+staff|i\s*t\s*e\s*m\s*1c{SEP}cybersecurity|i\s*t\s*e\s*m\s*2{SEP}properties", re.IGNORECASE
)
TENQ_MDNA_START = re.compile(rf"i\s*t\s*e\s*m\s*2{SEP}management'?s\s+discussion\s+and\s+analysis", re.IGNORECASE)
TENQ_MDNA_END = re.compile(rf"i\s*t\s*e\s*m\s*3{SEP}quantitative|i\s*t\s*e\s*m\s*4{SEP}controls\s+and\s+procedures", re.IGNORECASE)
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
    r"(?:\bsee|\bin|\bat|\bunder|\brefer\s+to|\bdescribed|\bdiscussed|\bincluded|\bset\s+forth|\bwithin|\bwith|\bto|\bfrom|\bof|\band|\bthis|\bour)"
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


# A holding-company reorganization gives the listed ticker a new registrant whose annual reports are still
# filed under the predecessor, as with ExxonMobil Holdings Corp (2026) and Exxon Mobil Corporation.
SUCCESSOR_FORMS = ("8-K12B", "8-K12G3")
PREDECESSOR = re.compile(
    r"([A-Z][A-Za-z0-9.&' -]{1,80}?),\s+an?\s+[A-Za-z ]{2,40}?(?:[Cc]orporation|[Cc]ompany)\s*(?:\([^)]{0,80}\)\s*)?,?\s+"
    r"(?:and\s+)?(?:the\s+)?[Pp]redecessor"
)
COMPANY_SEARCH_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={name}&type=10-K&dateb=&owner=include&count=10&output=atom"
)


def edgar_company_name(name: str) -> str:
    """EDGAR's conformed spelling of a legal name ("Exxon Mobil Corporation" -> "Exxon Mobil Corp")."""
    name = re.sub(r"[.,]", "", name).strip()
    for long, short in (("Corporation", "Corp"), ("Incorporated", "Inc"), ("Company", "Co"), ("Limited", "Ltd")):
        name = re.sub(rf"\b{long}$", short, name)
    return name


def find_predecessor_cik(submissions: dict) -> int | None:
    recent = submissions.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form not in SUCCESSOR_FORMS:
            continue
        try:
            cik = int(submissions.get("cik") or 0)
            text = html_to_text(sec_get(archive_url(cik, recent["accessionNumber"][i], recent["primaryDocument"][i])).text)
            match = PREDECESSOR.search(text[:30_000])
            if not match:
                continue
            name = edgar_company_name(match.group(1))
            feed = sec_get(COMPANY_SEARCH_URL.format(name=quote_plus(name))).text
        except (HTTPException, KeyError, ValueError):
            continue
        info = re.search(r"<company-info>.*?<cik>(\d+)</cik>.*?<conformed-name>([^<]+)</conformed-name>", feed, re.DOTALL)
        if info and int(info.group(1)) != cik and edgar_company_name(info.group(2)).upper().startswith(name.upper()):
            return int(info.group(1))
    return None


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


ANY_ITEM_HEADING = re.compile(r"\bi\s*t\s*e\s*m\s*\d{1,2}[a-c]?\s*[.:\-–—|]?\s", re.IGNORECASE)
TOC_WINDOW = 150


def is_cross_reference(text: str, index: int) -> bool:
    return bool(CROSS_REFERENCE.search(text[max(0, index - 40):index]))


def is_quoted(text: str, index: int) -> bool:
    # Headings are never in quotes; a quoted "Item 5. ..." is a reference to the section.
    return text[max(0, index - 2):index].rstrip().endswith(('"', "'", "‘"))


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
        if is_quoted(text, start.start()) or is_cross_reference(text, start.start()) or is_toc_entry(text, start.end()):
            continue
        end = next((m for m in end_re.finditer(text, start.end()) if not is_cross_reference(text, m.start())), None)
        if not end:
            continue
        section = text[start.start():end.start()]
        if len(section) > len(best):
            best = section
    return best if len(best) >= min_chars else None


# Headings of an MD&A that is laid out as an annual report chapter rather than under "Item 7".
# IBM titles it "Management Discussion"; "Management's Discussion of Financial Responsibility" is a different section.
MDNA_TITLE = re.compile(
    r"management'?s\s+discussion\s+and\s+analysis(?:\s+of\s+financial\s+condition\s+and\s+results\s+of\s+operations)?"
    r"|management\s+discussion\b(?!\s+of\b)",
    re.IGNORECASE,
)
TITLED_SECTION_CHARS = 400_000
PAGE_NUMBER = re.compile(r"(?<![\w$.,])\d{1,3}(?![\w%]|[.,]\d)")
# Item 7 pointers name the annual report section: 'under the heading "Management's Discussion and Analysis."'
POINTER_TITLE = re.compile(r"under\s+(?:the\s+(?:heading|caption|section)s?\s+)?\"([^\"]{3,80}?)\.?\"", re.IGNORECASE)


def is_heading_position(text: str, start: int, end: int) -> bool:
    """True when a title match sits where a heading would: after a sentence end, page number or another heading,
    and not in a quote, a prose reference ("in the section titled ...") or a table of contents line."""
    if not text[start].isupper():
        return False
    # "Strategic Report—Financial Review" is a path in a reference; "Group financial review; ..." a list item.
    if text[start - 1:start] in ("—", "–") or text[end:end + 1] == ";":
        return False
    before = text[max(0, start - 60):start].rstrip()
    if not before:
        return True
    if before[-1] in "\"'‘“•":
        return False
    previous = before.split()[-1]
    if previous[0].islower() and previous[-1] not in ".:;!?)":
        return False
    # "Shell's financial performance", "See Operating and Financial Review ..." are prose, not headings.
    if previous.endswith(("'s", "’s")) or is_cross_reference(text, start):
        return False
    # A table of contents line is followed by page numbers.
    return len(PAGE_NUMBER.findall(text[end:end + 150])) < 2


def looks_like_index(section: str) -> bool:
    """A cross-reference index ("A. Operating results 23-30, 36-41", "Business overview—Strategy; ...",
    '"Financial Review" on page 63') rather than the chapter it points to."""
    head = section[:800]
    return (
        len(PAGE_NUMBER.findall(head)) >= 6
        or head.count(";") + head.count("—") >= 8
        or len(re.findall(r"\bon\s+pages?\b", head, re.IGNORECASE)) >= 2
    )


def extract_titled_section(
    text: str, title: re.Pattern, end_re: re.Pattern, min_chars: int = 5_000, chapter_end: bool = False
) -> str | None:
    """The section under the first heading-positioned title, up to end_re. With chapter_end, the end must itself be
    a heading at least min_chars later, so running headers and navigation bars do not cut the chapter short."""
    headings = [m for m in title.finditer(text) if is_heading_position(text, m.start(), m.end())]
    def in_navigation_bar(match: re.Match, look_back: bool) -> bool:
        # A navigation bar lists other chapters next to this one ("Corporate Governance Financial Statements Additional
        # Information Financial Review ..."). A chapter's own pages carry the bar just before its title, so only an
        # end marker is checked on both sides.
        return any(
            is_heading_position(text, e.start(), e.end())
            for e in end_re.finditer(text, max(0, match.start() - 100) if look_back else match.end(), match.end() + 100)
            if e.start() != match.start()
        )

    if chapter_end:
        headings = [m for m in headings if not in_navigation_bar(m, look_back=False)]
    # Prefer a capitalized chapter heading over title-case running headers.
    headings.sort(key=lambda m: not m.group(0).isupper())
    for start in headings:
        ends = end_re.finditer(text, start.start() + min_chars if chapter_end else start.end())
        end = next((m for m in ends if not is_cross_reference(text, m.start())
                    and (not chapter_end or is_heading_position(text, m.start(), m.end()) and not in_navigation_bar(m, look_back=True))), None)
        if not end or end.start() - start.start() < min_chars:
            continue
        section = text[start.start():min(end.start(), start.start() + TITLED_SECTION_CHARS)]
        if chapter_end and looks_like_index(section):
            continue
        return section
    return None


def pointer_title(text: str) -> re.Pattern | None:
    """The annual report section an incorporated-by-reference Item 7 points to, as a heading pattern."""
    for start in ITEM7_START.finditer(text):
        match = POINTER_TITLE.search(text, start.end(), start.end() + 600)
        if match:
            return re.compile(r"\s+".join(re.escape(word) for word in match.group(1).split()), re.IGNORECASE)
    return None


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


def spaced(phrase: str) -> str:
    """A heading pattern that tolerates the stray spaces some filings put inside words ("FINAN CIAL")."""
    return r"\s+".join(r"\s?".join(re.escape(ch) for ch in word) for word in phrase.split())


TWENTYF_START = re.compile(
    rf"i\s*t\s*e\s*m\s*5\s*[.\-–—]?\s*{spaced('operating and financial')}\s+{spaced('review')}\s?s?\s+{spaced('and prospects')}",
    re.IGNORECASE,
)
TWENTYF_END = re.compile(rf"i\s*t\s*e\s*m\s*6\s*[.\-–—]?\s*{spaced('directors,')}?\s+{spaced('senior management')}", re.IGNORECASE)
TWENTYF_ITEM3_START = re.compile(rf"i\s*t\s*e\s*m\s*3{SEP}key\s+information", re.IGNORECASE)
TWENTYF_ITEM3_END = re.compile(rf"i\s*t\s*e\s*m\s*4{SEP}information\s+on\s+the\s+company", re.IGNORECASE)
TWENTYF_RISK_HEADING = re.compile(r"\bRisk Factors\b|\bRISK FACTORS\b")

# Reporting-currency markers. Bare "$" counts as US dollars only when no letter prefix (NT$, C$, HK$) precedes it.
CURRENCY_PATTERNS = {
    "USD": r"US\$|U\.S\.\s?dollars?|\bUSD(?![A-Za-z])|(?<![A-Za-z$])\$",
    "TWD": r"NT\$|New Taiwan dollars?|\bNT dollars?|\bTWD(?![A-Za-z])",
    "CAD": r"C\$|Canadian dollars?|\bCAD(?![A-Za-z])",
    "EUR": r"€|\bEUR(?![A-Za-z])|\beuros?\b",
    "GBP": r"£|\bGBP(?![A-Za-z])|pounds? sterling",
    "JPY": r"¥|\bJPY(?![A-Za-z])|\byen\b",
    "CNY": r"\bRMB(?![A-Za-z])|\bCNY(?![A-Za-z])|\bRenminbi\b",
    "HKD": r"HK\$|\bHKD(?![A-Za-z])|Hong Kong dollars?",
    "CHF": r"\bCHF(?![A-Za-z])|Swiss francs?",
    "INR": r"₹|\bINR(?![A-Za-z])|\bRs\.|Indian rupees?",
    "KRW": r"₩|\bKRW(?![A-Za-z])|Korean won",
    "BRL": r"R\$|\bBRL(?![A-Za-z])|Brazilian reais|\breais\b",
    "AUD": r"A\$|\bAUD(?![A-Za-z])|Australian dollars?",
    "DKK": r"\bDKK(?![A-Za-z])|Danish kroner",
}

MIN_CURRENCY_MENTIONS = 5


def detect_currency(text: str) -> str:
    """The most frequently cited currency in a management discussion, or "unknown" when none is cited."""
    counts = {code: len(re.findall(pattern, text, re.IGNORECASE if code != "USD" else 0)) for code, pattern in CURRENCY_PATTERNS.items()}
    code, count = max(counts.items(), key=lambda item: item[1])
    return code if count >= MIN_CURRENCY_MENTIONS else "unknown"


def extract_20f_risk_factors(text: str) -> str | None:
    item3 = extract_section(text, TWENTYF_ITEM3_START, TWENTYF_ITEM3_END)
    heading = TWENTYF_RISK_HEADING.search(item3) if item3 else None
    if not heading or len(item3) - heading.start() < MIN_SECTION_CHARS:
        return None
    return item3[heading.start():heading.start() + RISK_FACTORS_CHARS]


FORTYF_MDNA_START = re.compile(
    r"management'?s\s+discussion\s+and\s+analysis\s+(?:this\s+management'?s\s+discussion\s+and\s+analysis|management'?s\s+discussion\s+and\s+analysis\s*\(md&a\)|about\s+[a-z]+)",
    re.IGNORECASE,
)
FORTYF_REFERENCE = re.compile(
    r"(?:exhibit\s+(99[.\-]\d+|2)\s*:\s*management'?s\s+discussion\s+and\s+analysis|management'?s\s+discussion\s+and\s+analysis.{0,140}?(?:exhibit\s+(99[.\-]\d+|2)))",
    re.IGNORECASE,
)


# 20-Fs that are a cross-reference index into an integrated annual report title the operating review as an annual
# report chapter (Unilever "Group Financial Review", Vale and ICICI Bank "Operating and Financial Review and Prospects"
# without an Item number, HDFC Bank "Management's Discussion and Analysis", Petrobras "Consolidated Financial Performance").
ANNUAL_REPORT_REVIEW_TITLES = [
    re.compile(r"operating\s+and\s+financial\s+reviews?\s+and\s+prospects", re.IGNORECASE),
    MDNA_TITLE,
    re.compile(r"(?:group\s+)?financial\s+review", re.IGNORECASE),
    re.compile(r"operating\s+and\s+financial\s+review", re.IGNORECASE),
    re.compile(r"(?:group|consolidated)\s+financial\s+performance", re.IGNORECASE),
]
ANNUAL_REPORT_CHAPTER_END = re.compile(
    r"corporate\s+governance|risk\s+review|principal\s+risks|risk\s+factors|directors'?\s+remuneration|remuneration\s+report"
    r"|financial\s+statements|shareholder\s+information|additional\s+information|report\s+of\s+(?:the\s+)?independent"
    r"|independent\s+auditor|i\s*t\s*e\s*m\s*6\b",
    re.IGNORECASE,
)


ANNUAL_REPORT_REVIEW_CHARS = 15_000
# "... set forth under ... in the Annual Report 2025 included as exhibit 15.1 to this Form 20-F ... is incorporated by reference."
ANNUAL_REPORT_EXHIBIT = re.compile(r"exhibit\s+(15\.\d|99\.\d)", re.IGNORECASE)


def extract_annual_report_review(text: str) -> str | None:
    for title in ANNUAL_REPORT_REVIEW_TITLES:
        section = extract_titled_section(
            text, title, ANNUAL_REPORT_CHAPTER_END, min_chars=ANNUAL_REPORT_REVIEW_CHARS, chapter_end=True
        )
        if section:
            return section
    return None


def load_20f(cik: int, filing: dict) -> dict:
    document_url = archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = html_to_text(sec_get(document_url).text)
    mdna_url = document_url
    operating = extract_section(text, UBS_OPERATING_START, UBS_OPERATING_END)
    source = "operating_review"
    if not operating:
        operating = extract_section(text, TWENTYF_START, TWENTYF_END)
        source = "item5"
    # An incorporated-by-reference Item 5 is not the underlying management discussion.
    reference_only = bool(operating) and (
        len(operating) < 5_000 or "incorporated by reference" in operating[:1_500].lower() and len(operating) < 10_000
    )
    # Keep the Item 5 pointer, however short, to follow it to an annual report exhibit.
    reference = operating if reference_only else None if operating else extract_section(text, TWENTYF_START, TWENTYF_END, min_chars=1)
    if not operating or reference_only:
        operating, source = extract_annual_report_review(text), "annual_report"
    if not operating and reference:
        # Item 5 incorporates the review from the annual report filed as an exhibit (AstraZeneca: exhibit 15.1).
        exhibit = ANNUAL_REPORT_EXHIBIT.search(reference)
        exhibit_url = exhibit and find_exhibit(cik, filing["accession_number"], f"EX-{exhibit.group(1)}")
        if exhibit_url:
            operating = extract_annual_report_review(html_to_text(sec_get(exhibit_url).text))
            source, mdna_url = "annual_report", exhibit_url
    if not operating and reference_only:
        raise HTTPException(status_code=422, detail="The 20-F refers to a separate annual report; its management discussion could not be isolated.")
    if not operating:
        raise HTTPException(status_code=422, detail="Could not isolate the operating and financial review in this 20-F.")
    risk_start = UBS_RISK_START.search(text)
    operating_start = UBS_OPERATING_START.search(text)
    risks = None
    if risk_start:
        risk_end = risk_start.start() + RISK_FACTORS_CHARS
        if operating_start and operating_start.start() > risk_start.start():
            risk_end = min(risk_end, operating_start.start())
        risks = text[risk_start.start():risk_end]
    else:
        risks = extract_20f_risk_factors(text)
    operating = operating[:FOREIGN_MDNA_CHARS]
    return {**filing, "document_url": document_url, "currency": detect_currency(operating),
            "mdna": {"text": operating, "source": source, "url": mdna_url},
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

    # Some filers (often banks) incorporate MD&A by reference to the annual report filed as Exhibit 13,
    # sometimes under another title that the Item 7 pointer names (Wells Fargo: "Financial Review").
    exhibit_url = find_exhibit(cik, filing["accession_number"], "EX-13")
    if exhibit_url:
        exhibit_text = html_to_text(sec_get(exhibit_url).text)
        mdna = extract_section(exhibit_text, ANNUAL_REPORT_MDNA_START, ANNUAL_REPORT_MDNA_END)
        for title in (pointer_title(filing_text), MDNA_TITLE):
            if mdna or title is None:
                continue
            mdna = extract_titled_section(exhibit_text, title, ANNUAL_REPORT_MDNA_END)
        if mdna:
            return {"text": mdna, "source": "exhibit13", "url": exhibit_url}

    # Annual-report-style 10-Ks (Citi, GE, Honeywell) title the chapter without "Item 7".
    chapter = extract_titled_section(filing_text, MDNA_TITLE, ANNUAL_REPORT_MDNA_END)
    if chapter:
        return {"text": chapter, "source": "item7", "url": document_url}

    raise HTTPException(status_code=422, detail="Could not isolate MD&A in this 10-K or its Exhibit 13.")
