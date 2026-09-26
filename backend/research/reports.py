"""Finding the narrative sections of foreign private issuers' annual reports.

Many 20-Fs are the company's integrated annual report with a Form 20-F cross-reference table in front ("Item 5.A
Operating results: Financial review, pages 64-110"). The table is the most reliable map of the report: its page
numbers are resolved against the report's own running headers and footers, which print the page number next to a
line repeated on every page ("HSBC Holdings plc Annual Report on Form 20-F", "Annual Report 2025 |").

A 40-F is an envelope for Canadian disclosure documents: the annual information form (business, risk factors), the
management's discussion and analysis and the audited financial statements. They arrive as numbered exhibits, inside
the 40-F itself, or in a 6-K filed the same day, so each document is identified by its title page rather than its
exhibit number.

Everything works on text with paragraphs and table rows as lines (sec.keeping_lines).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

NUMBER_LINE = re.compile(r"^(?:page\s+)?(\d{1,3})$", re.IGNORECASE)
FREQUENT_LINE = 10        # a running header or footer repeats on at least this many pages
MAX_PAGE_STEP = 6         # unnumbered divider pages between two numbered ones
MIN_RUN_PAGES = 20


@dataclass(frozen=True)
class Page:
    number: int
    start: int            # character offset of the page's first line
    end: int


def page_map(text: str) -> list[Page]:
    """Numbered pages of a long document, from page numbers printed next to a running header or footer.

    A number line counts only beside a line that repeats across the document, so table cells and list numbers are
    ignored. The longest run of increasing page numbers wins: a 20-F wrapper numbers its own few pages separately
    from the annual report it contains."""
    lines = text.split("\n")
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    counts = Counter(line for line in lines if 4 <= len(line) <= 120 and not NUMBER_LINE.match(line))
    frequent = {line for line, n in counts.items() if n >= FREQUENT_LINE}
    markers: list[tuple[int, int, int]] = []   # (line index, page number, offset of the page's first line)
    for i, line in enumerate(lines):
        match = NUMBER_LINE.match(line)
        if not match or not any(x in frequent for x in lines[max(0, i - 2):i] + lines[i + 1:i + 3]):
            continue
        number = int(match.group(1))
        if markers and markers[-1][1] == number and i - markers[-1][0] < 12:
            continue  # a page number printed twice (header and footer on facing layouts)
        # The page starts at its running header, which sits just above the number when there is one.
        first = i
        while first > 0 and i - first < 2 and lines[first - 1] in frequent:
            first -= 1
        markers.append((i, number, offsets[first]))
    main = _longest_chain(markers)
    if len(main) < MIN_RUN_PAGES:
        return []
    return [Page(number, start, main[n + 1][2] if n + 1 < len(main) else len(text))
            for n, (_, number, start) in enumerate(main)]


LOOK_BACK = 600
# A step of n pages may span at most (n + SLACK_PAGES) typical pages of text, so a chain cannot jump from a 20-F
# wrapper's page 22 to the report's page 23 over the report's own pages 2 to 22.
SLACK_PAGES = 8


def _longest_chain(markers: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """The longest sequence of markers whose page numbers rise by one to MAX_PAGE_STEP, skipping stray numbers
    (a table cell next to a repeated row label) wherever they fall."""
    consecutive = sorted(b[2] - a[2] for a, b in zip(markers, markers[1:]) if b[1] == a[1] + 1 and b[2] > a[2])
    typical = consecutive[len(consecutive) // 2] if consecutive else 0
    length = [1] * len(markers)
    previous = [-1] * len(markers)
    for i, (_, number, start) in enumerate(markers):
        for j in range(max(0, i - LOOK_BACK), i):
            step = number - markers[j][1]
            if not 0 < step <= MAX_PAGE_STEP or length[j] + 1 <= length[i]:
                continue
            if typical and start - markers[j][2] > (step + SLACK_PAGES) * typical:
                continue
            length[i], previous[i] = length[j] + 1, j
    if not markers:
        return []
    i = max(range(len(markers)), key=lambda k: length[k])
    chain = []
    while i >= 0:
        chain.append(markers[i])
        i = previous[i]
    return chain[::-1]


HEADER_LINES = 16
# A chapter's navigation bar opens only that chapter's pages, so the share is low; page titles repeat far less
# ("Risk factors (continued)" opens a dozen pages of several hundred).
FURNITURE_SHARE = 0.08
FURNITURE_CHARS = 80


def furniture(text: str, pages: list[Page]) -> set[str]:
    """Running headers, navigation bars and footers: short lines that open many pages."""
    counts = Counter()
    for page in pages:
        counts.update(set(text[page.start:page.end].split("\n", HEADER_LINES)[:HEADER_LINES]))
    return {line for line, n in counts.items()
            if n >= max(FREQUENT_LINE, FURNITURE_SHARE * len(pages)) and len(line) <= FURNITURE_CHARS}


def _body(text: str, page: Page, chrome: set[str]) -> list[str]:
    lines = text[page.start:page.end].split("\n")
    # Whatever precedes the page's own number near its top is the previous page's last line ("$ million").
    number = next((i for i, line in enumerate(lines[:5]) if NUMBER_LINE.match(line) and int(NUMBER_LINE.match(line).group(1)) == page.number), -1)
    start = number + 1
    while start < min(len(lines), HEADER_LINES + number + 1) and (lines[start] in chrome or NUMBER_LINE.match(lines[start])):
        start += 1
    return [line for line in lines[start:] if line not in chrome]


TITLE_LINES = 4


def page_titles(text: str, page: Page, chrome: set[str]) -> list[str]:
    """The first lines under a page's running header, where its title sits ('Risk factors (continued)')."""
    return _body(text, page, chrome)[:TITLE_LINES]


def page_text(text: str, pages: list[Page], first: int, last: int, chrome: set[str] = frozenset()) -> str:
    """The text of pages first..last without their running headers and footers."""
    return "\n".join("\n".join(_body(text, p, chrome)) for p in pages if first <= p.number <= last)


# --- the Form 20-F cross-reference table ---

@dataclass(frozen=True)
class Reference:
    title: str
    first: int
    last: int


# Where each item's entry starts and ends in the table, as the item letters and captions are printed.
DASH = r"\s*[.\-–—:]?\s*"
ITEM_ENTRIES = {
    "risk_factors": (rf"\bD{DASH}Risk\s+factors", rf"(?:Item\s*)?4\b{DASH}(?:\.\s*)?Information\s+on\s+the\s+Company|\bA{DASH}History\s+and\s+development"),
    "business": (rf"\bB{DASH}Business\s+(?:overview|review)", rf"\bC{DASH}Organi[sz]ational\s+structure"),
    "operating_results": (rf"\bA{DASH}Operating\s+results", rf"\bB{DASH}Liquidity\s+and\s+capital\s+resources"),
    "trend_information": (rf"\bD{DASH}Trend\s+information", rf"\bE{DASH}Critical|(?:Item\s*)?6\b{DASH}(?:\.\s*)?Directors"),
    "statements_item8": (rf"\bA{DASH}Consolidated\s+statements\s+and\s+other\s+financial\s+information",
                         rf"\bB{DASH}Significant\s+changes"),
    "statements_item18": (rf"(?:Item\s*)?18\b{DASH}(?:\.\s*)?Financial\s+statements", rf"(?:Item\s*)?19\b"),
}
TABLE_ANCHOR = re.compile(r"Operating\s+and\s+Financial\s+Review\s+and\s+Prospects", re.IGNORECASE)
TABLE_CHARS = 60_000
# "12-15", "(62-85)", "4 - 31", "54"; not note numbers, sub-item numbers ("1, 2 and 5:"), exhibits, forms, dates or years.
PAGE_REFERENCE = re.compile(r"(?<![\w.,/])(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?(?![\w%]|[.,]\d)")
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
NOT_PAGES = re.compile(
    r"\bNote\s+\d+\s*[a-z]?\)?\s*\d?[a-z]?\)?|\bNotes?\s+\d+(?:\s*(?:,|and|to)\s*\d+)*|Exhibits?\s+[\d.]+|\bItem\s+\d+[A-Z]?"
    r"|\b\d+(?:\s*(?:,|and)\s*\d+)*\s*:|\b(?:19|20)\d\d\b|Regulation\s+S-K|Subpart\s+\d+|Rule\s+[\d\w-]+|Section\s+\d+\w*"
    rf"|\b(?:20|40)-F\b|\b6-K\b|\b10-[KQ]\b|{MONTH}\s+\d{{1,2}}\b|\b\d{{1,2}}\s+{MONTH}|Supplement\s*\(?\s*\d+(?:\s*[-–]\s*\d+)?\)?"
    r"|\b\d+(?:\.\d+)?\s*(?:%|per\s*cent|bn|m)\b|\b[1-4]Q\d\d\b|\bQ[1-4]\b",
    re.IGNORECASE)
# Chapters the narrative sections leave out: the financial statements' notes and governance.
EXCLUDED_TITLES = re.compile(
    r"\bNote\b|Notes\s+to|financial\s+statements|statements?\s+of\s+(?:income|cash|financial|comprehensive|changes)"
    r"|income\s+statement|balance\s+sheet|governance|remuneration|compensation|board\s+of\s+directors|directors'?\s+report"
    r"|supplement|shareholder\s+information|glossary|exhibit",
    re.IGNORECASE)
REVIEW_TITLE = re.compile(
    r"financial\s+review|operating\s+and\s+financial\s+review|financial\s+and\s+operating\s+performance|financial\s+performance"
    r"|management'?s\s+discussion|results\s+of\s+operations|group\s+performance|business\s+performance|operating\s+results",
    re.IGNORECASE)
STATEMENTS_TITLE = re.compile(r"financial\s+statements|consolidated\s+statements", re.IGNORECASE)
CONTINUED = re.compile(r"\s*[(\[]?\s*(?:continued|cont'?d\.?)\s*[)\]]?\s*$", re.IGNORECASE)
MAX_CHAPTER_PAGES = 40


def cross_reference_table(text: str) -> str | None:
    """The Form 20-F cross-reference table: the stretch around its Item 5 caption that also names Items 3 and 4."""
    for anchor in TABLE_ANCHOR.finditer(text):
        window = text[max(0, anchor.start() - TABLE_CHARS // 2):anchor.start() + TABLE_CHARS // 2]
        if re.search(r"Liquidity\s+and\s+capital\s+resources", window, re.IGNORECASE) and \
                re.search(r"Information\s+on\s+the\s+Company", window, re.IGNORECASE) and \
                len(PAGE_REFERENCE.findall(window)) >= 30:
            return window
    return None


def _references(entry: str) -> list[Reference]:
    """Titled page ranges in one item's entry; the title is the text since the previous page reference."""
    cleaned = NOT_PAGES.sub(lambda m: " " * len(m.group(0)), entry)
    references, previous = [], 0
    for match in PAGE_REFERENCE.finditer(cleaned):
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        title = re.sub(r"\s+", " ", entry[previous:match.start()]).strip(" ,;.:()-–\n")
        previous = match.end()
        if first == 0 or last < first or last - first > 200:
            continue
        references.append(Reference(title, first, last))
    return references


def item_references(table: str) -> dict[str, list[Reference]]:
    out = {}
    for key, (start, end) in ITEM_ENTRIES.items():
        begin = re.search(start, table, re.IGNORECASE)
        if not begin:
            continue
        finish = re.search(end, table[begin.end():], re.IGNORECASE)
        entry = table[begin.end():begin.end() + (finish.start() if finish else 3_000)]
        out[key] = _references(entry[:6_000])
    return out


def statements_start(items: dict[str, list[Reference]]) -> int | None:
    """The first page of the audited financial statements: a financial statements chapter of ten or more pages (or
    the single page a table points to), else the longest range in Item 8.A or Item 18."""
    references = items.get("statements_item18", []) + items.get("statements_item8", [])
    titled = [r for r in references if STATEMENTS_TITLE.search(r.title) and not re.search(r"\bNote\b", r.title, re.I)
              and (r.last - r.first >= 10 or r.first == r.last)]
    if titled:
        return min(r.first for r in titled)
    long = [r for r in references if r.last - r.first >= 30]
    return max(long, key=lambda r: r.last - r.first).first if long else None


def _chapter(text: str, pages: list[Page], chrome: set[str], reference: Reference) -> Reference:
    """A single cited page extended over the pages that continue it ('Risk factors', 'Risk factors (continued)')."""
    if reference.first != reference.last:
        return reference
    by_number = {p.number: p for p in pages}
    start = by_number.get(reference.first)
    if start is None:
        return reference
    titles = {CONTINUED.sub("", t).strip().lower() for t in page_titles(text, start, chrome)} - {""}
    last = reference.first
    while titles and last - reference.first < MAX_CHAPTER_PAGES and (page := by_number.get(last + 1)):
        continued = {CONTINUED.sub("", t).strip().lower() for t in page_titles(text, page, chrome) if CONTINUED.search(t)}
        if not continued & titles:
            break
        titles = continued & titles
        last += 1
    return Reference(reference.title, reference.first, last)


def _page_set(references: list[Reference]) -> set[int]:
    return {page for r in references for page in range(r.first, r.last + 1)}


def cross_referenced_sections(text: str) -> dict[str, str]:
    """risk_factors, business and management_discussion text of an integrated annual report, from its Form 20-F
    cross-reference table; empty when the report has no such table or no usable page numbers.

    Risk factor pages are left out of the other two, and the financial statements and governance chapters out of all
    three; the business overview and the operating review may share pages (both cite "Our businesses")."""
    table = cross_reference_table(text)
    pages = page_map(text) if table else []
    if not table or not pages:
        return {}
    chrome = furniture(text, pages)
    items = item_references(table)
    first_statement = statements_start(items)
    known = {p.number for p in pages}

    def wanted(key: str, titled: re.Pattern | None = None) -> set[int]:
        references = [_chapter(text, pages, chrome, r) for r in items.get(key, [])
                      if not EXCLUDED_TITLES.search(r.title) and (titled is None or titled.search(r.title))]
        found = _page_set(references) & known
        return {p for p in found if first_statement is None or p < first_statement}

    risk = wanted("risk_factors")
    # The operating review's own chapter leads ("Financial review" before the strategic report it also cites), then the
    # rest of Item 5.A, then trend information; each group in page order.
    review = wanted("operating_results", REVIEW_TITLE) - risk
    operating = wanted("operating_results") - risk - review
    trend = wanted("trend_information") - risk - review - operating
    groups = {"risk_factors": [risk], "management_discussion": [review, operating, trend], "business": [wanted("business") - risk]}
    out = {}
    for key, parts in groups.items():
        text_parts = [page_text(text, pages, a, b, chrome) for part in parts for a, b in _spans(sorted(part))]
        if any(text_parts):
            out[key] = "\n".join(t for t in text_parts if t)
    return out


def _spans(pages: list[int]) -> list[tuple[int, int]]:
    spans: list[list[int]] = []
    for page in pages:
        if spans and page == spans[-1][1] + 1:
            spans[-1][1] = page
        else:
            spans.append([page, page])
    return [(a, b) for a, b in spans]


# --- 40-F document sets ---

def squash(line: str) -> str:
    """A line without spaces, lowercased: 'Mana gement's Discussion' and 'MANAGEMENT'S DISCUSSION' compare equal."""
    return re.sub(r"\s+", "", line).lower().replace("’", "'")


@dataclass(frozen=True)
class Line:
    index: int
    offset: int
    text: str


def _lines(text: str) -> list[Line]:
    out, offset = [], 0
    for i, line in enumerate(text.split("\n")):
        out.append(Line(i, offset, line))
        offset += len(line) + 1
    return out


def headings(text: str, title: re.Pattern, lines: list[Line] | None = None) -> list[int]:
    """Offsets of heading lines whose squashed text matches title, alone or joined with the next line ("GENERAL
    DEVELOPMENT" / "OF THE BUSINESS"). Table of contents entries (followed by a page number) are left out."""
    lines = lines if lines is not None else _lines(text)
    found = []
    for n, line in enumerate(lines):
        # A heading starts with a capital (or an item number) and is not a bare page number.
        if len(line.text) > 140 or not re.match(r"(?:[\d.]+\s*|item\s+\d+\S*\s*|ex-[\d.]+\s*)?[A-Z]", line.text, re.IGNORECASE) \
                or not re.search(r"[A-Z]", line.text[:3] + re.sub(r"^[\d.\s]+", "", line.text)[:1]):
            continue
        second = lines[n + 1].text if n + 1 < len(lines) and len(lines[n + 1].text) <= 60 else ""
        # A title broken over two lines matches only joined; when the second line holds the whole title, it is the
        # heading and this line is something else (a glossary entry above "AIF Annual Information Form").
        spans_both = second and not title.search(squash(second)) and title.fullmatch(squash(line.text + second))
        if not (title.fullmatch(squash(line.text)) or spans_both):
            continue
        if n and _is_acronym_of(lines[n - 1].text, line.text):
            continue  # a glossary entry: "AIF" / "Annual Information Form"
        after = n + (2 if spans_both and not title.fullmatch(squash(line.text)) else 1)
        if (after < len(lines) and NUMBER_LINE.match(lines[after].text)) or re.search(r"\s\d{1,3}$", line.text):
            continue  # a table of contents entry
        found.append(line.offset)
    return found


# A running header may prefix the title ("CN ANNUAL 2025 MANAGEMENT'S DISCUSSION AND ANALYSIS"); a glossary line
# ("MD&A Management's Discussion and Analysis") is not a title.
def _is_acronym_of(previous: str, line: str) -> bool:
    letters = re.sub(r"[^A-Z]", "", previous)
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z][\w']*", line) if w[0].isupper())
    return 2 <= len(letters) <= 6 and len(previous) <= 8 and previous.upper() == previous and initials.startswith(letters)


MDNA_HEADING = re.compile(r"(?!md&a).{0,40}?management'?sdiscussion(?:and|&)analysis")
MDNA_INTRO = re.compile(
    r"(?:this|the\s+following|our)\s+(?:annual\s+)?(?:management'?s\s+)?discussion\s+and\s+analysis|\(\s*[\"“”']?\s*MD&A"
    r"|should\s+be\s+read\s+in\s+conjunction|is\s+(?:presented|provided|designed|intended)\s+to", re.IGNORECASE)
MDNA_INTRO_CHARS = 15_000
AIF_HEADING = re.compile(r"(?!aif)(?:ex-[\d.]+)?.{0,60}?annualinformationform(?:dated.{0,40})?")
STATEMENTS_HEADING = re.compile(
    r"management'?s(?:statementof)?(?:report|responsibility)(?:for|on)(?:the)?(?:consolidated)?financial(?:statements|reporting|information)"
    r"|reportofindependentregisteredpublicaccountingfirm.{0,80}"
    # Interim reports have no auditor's report: their statements open with the first statement's title.
    r"|(?:interim|condensed|unaudited)(?:condensed|interim)?consolidated(?:interim)?(?:financialstatements|balancesheets?"
    r"|statementsoffinancialposition|statementsof(?:income|operations))(?:\(unaudited\))?")
BUSINESS_HEADING = re.compile(
    r"(?:item\d+[-–:.]?|\d+(?:\.\d+)*\.?)?(?:generaldevelopmentofthebusiness|(?:narrative)?descriptionof(?:the)?(?:[a-z.'&]+'s)?businesse?s?)")
# An annual report that doubles as the annual information form titles the section plainly (Thomson Reuters: "Business").
REPORT_BUSINESS_HEADING = re.compile(
    r"(?:\d+(?:\.\d+)*\.?)?(?:generaldevelopmentofthebusiness|(?:narrative)?descriptionof(?:the)?(?:[a-z.'&]+'s)?businesse?s?"
    r"|ourbusiness(?:es)?|business|businessoverview)")
RISK_HEADING = re.compile(r"(?:item\d+[-–:.]?|\d+(?:\.\d+)*\.?)?riskfactors(?:thatmayaffectfutureresults)?")
# Risk sections of an MD&A, most specific first.
MDNA_RISK_HEADINGS = [re.compile(r"(?:\d+(?:\.\d+)*\.?)?" + p) for p in (
    r"riskfactors(?:thatmayaffectfutureresults)?", r"businessrisks", r"risksthatmayaffect.{0,40}", r"keyrisks",
    r"risksanduncertainties", r"topandemergingrisks", r"riskmanagement")]
# Where a business description or risk factors section of an annual information form ends: the next top-level item.
AIF_ITEM_HEADING = re.compile(
    r"(?:item\d+[-–:.]?|\d+(?:\.\d+)*\.?)?(?:riskfactors|dividends(?:anddistributions)?|dividendpolicy|descriptionof(?:the)?capitalstructure"
    r"|capitalstructure|marketforsecurities|tradingpriceandvolume|directorsandofficers|directorsandexecutiveofficers"
    r"|legalproceedings(?:andregulatoryactions)?|interestsofexperts|transferagents?(?:andregistrars?)?|materialcontracts"
    r"|auditcommittee(?:information)?|additionalinformation|escrowedsecurities.{0,40}|statementofreservesdata.{0,60}"
    r"|interestofmanagement.{0,80}|conflictsofinterest|environmental,?socialandgovernance"
    r"|ratings|creditratings|securityratings|environmentalandsocialpolicies)")
MIN_PART_CHARS = 20_000
MIN_SUBSECTION_CHARS = 2_000
# An annual information form's risk section shorter than this usually refers the reader to the MD&A.
POINTER_CHARS = 10_000


@dataclass
class Document:
    url: str
    text: str


@dataclass
class Parts:
    """The management's discussion and annual information form found across a 40-F's documents."""
    mdna: tuple[str, str] | None = None        # (document url, text)
    aif: tuple[str, str] | None = None
    other: list[tuple[str, str]] | None = None  # documents with neither (an annual report's front section)


def _boundaries(text: str, lines: list[Line]) -> list[tuple[int, str]]:
    marks = [(o, "statements") for o in headings(text, STATEMENTS_HEADING, lines)]
    marks += [(o, "aif") for o in headings(text, AIF_HEADING, lines)]
    marks += [(o, "mdna") for o in headings(text, MDNA_HEADING, lines)
              if MDNA_INTRO.search(text[o:o + MDNA_INTRO_CHARS])]
    return sorted(marks)


def _part(text: str, marks: list[tuple[int, str]], kind: str) -> str | None:
    """The longest stretch from a heading of kind to the next heading of another kind."""
    best = ""
    for n, (offset, mark) in enumerate(marks):
        if mark != kind:
            continue
        end = next((o for o, m in marks[n + 1:] if m != kind), len(text))
        if end - offset > len(best):
            best = text[offset:end]
    return best if len(best) >= MIN_PART_CHARS else None


# The glossary of terms a bank puts after its MD&A (TD's quarterly reports): definitions, not discussion. A heading in
# the first half is a contents entry.
GLOSSARY_HEADING = re.compile(r"^[ \t]*glossary(?:[ \t]+of[ \t]+terms)?[ \t]*$", re.IGNORECASE | re.MULTILINE)


def _without_glossary(text: str) -> str:
    found = next((m.start() for m in GLOSSARY_HEADING.finditer(text) if m.start() >= len(text) // 2), None)
    return text[:found] if found is not None else text


def document_parts(documents: list[Document]) -> Parts:
    parts = Parts(other=[])
    for doc in documents:
        lines = _lines(doc.text)
        marks = _boundaries(doc.text, lines)
        mdna, aif = _part(doc.text, marks, "mdna"), _part(doc.text, marks, "aif")
        mdna = _without_glossary(mdna) if mdna else None
        if mdna and (parts.mdna is None or len(mdna) > len(parts.mdna[1])):
            parts.mdna = (doc.url, mdna)
        if aif and (parts.aif is None or len(aif) > len(parts.aif[1])):
            parts.aif = (doc.url, aif)
        if not mdna and not aif and len(doc.text) >= MIN_PART_CHARS:
            parts.other.append((doc.url, doc.text))
        elif mdna and not aif:
            # An annual report's front section before its MD&A (Thomson Reuters: business, risk factors).
            start = doc.text.find(mdna[:200])
            if start >= MIN_PART_CHARS:
                parts.other.append((doc.url, doc.text[:start]))
    return parts


def subsection(text: str, title: re.Pattern, end: re.Pattern, max_chars: int) -> str | None:
    """The stretch under the first heading matching title that runs a meaningful length before the next heading
    matching end (a stray match, such as "Business" in a director's biography, comes later in the document)."""
    lines = _lines(text)
    ends = sorted(headings(text, end, lines))
    for offset in headings(text, title, lines):
        stop = next((e for e in ends if e > offset + 200), len(text))
        if stop - offset >= MIN_SUBSECTION_CHARS:
            return text[offset:stop][:max_chars]
    return None


def fortyf_sections(documents: list[Document], business_chars: int, risk_chars: int) -> dict[str, tuple[str, str]]:
    """management_discussion, business and risk_factors as (document url, text) from a 40-F's documents."""
    parts = document_parts(documents)
    out: dict[str, tuple[str, str]] = {}
    if parts.mdna:
        out["management_discussion"] = parts.mdna
    sources = ([(*parts.aif, BUSINESS_HEADING)] if parts.aif else []) + [(u, t, REPORT_BUSINESS_HEADING) for u, t in parts.other or []]
    for url, text, business_heading in sources:
        if "business" not in out and (found := subsection(text, business_heading, AIF_ITEM_HEADING, business_chars)):
            out["business"] = (url, found)
        if "risk_factors" not in out and (found := subsection(text, RISK_HEADING, AIF_ITEM_HEADING, risk_chars)):
            out["risk_factors"] = (url, found)
    pointer = out.get("risk_factors") and len(out["risk_factors"][1]) < POINTER_CHARS
    if ("risk_factors" not in out or pointer) and parts.mdna:
        # Banks and some issuers leave risk factors to the MD&A ("Risk management", "Business risks"); the annual
        # information form then has a paragraph that points there.
        for heading in MDNA_RISK_HEADINGS:
            if found := subsection(parts.mdna[1], heading, re.compile(r"(?!)"), risk_chars):
                out["risk_factors"] = (parts.mdna[0], found)
                break
    return out


# --- a 10-Q whose Item 2 is only a contents entry (JPMorgan) ---

CONTENTS_MDNA = re.compile(r"Item\s*2\.?\s*\n?\s*Management'?s\s+Discussion\s+and\s+Analysis[^\n]*\n", re.IGNORECASE)
CONTENTS_ENTRY = re.compile(r"^([A-Z][^\n]{2,90})\n\d{1,3}$", re.MULTILINE)
CONTENTS_NEXT_ITEM = re.compile(r"^Item\s*[34]\b", re.IGNORECASE | re.MULTILINE)
INTERIM_STATEMENTS_START = re.compile(
    r"^(?:Condensed\s+)?Consolidated\s+(?:statements?\s+of\s+(?:income|operations|earnings)|balance\s+sheets?)(?:\s*\(unaudited\))?$"
    r"|^Item\s*[34]\s*\.?\s*(?:Quantitative|Controls)", re.IGNORECASE | re.MULTILINE)


def mdna_from_contents(text: str, min_chars: int = MIN_PART_CHARS) -> str | None:
    """The MD&A of a 10-Q laid out like an annual report: its contents list the MD&A's sections under Item 2, and the
    body starts at the first of them and runs to the financial statements."""
    item = CONTENTS_MDNA.search(text)
    if not item:
        return None
    following = CONTENTS_NEXT_ITEM.search(text, item.end())
    contents = text[item.end():following.start() if following else item.end() + 5_000]
    entries = CONTENTS_ENTRY.findall(contents)
    if not entries:
        return None
    body_from = following.end() if following else item.end()
    start = re.compile(rf"^{re.escape(entries[0])}\b", re.IGNORECASE | re.MULTILINE).search(text, body_from)
    if not start:
        return None
    end = INTERIM_STATEMENTS_START.search(text, start.start() + min_chars)
    section = text[start.start():end.start() if end else len(text)]
    return section if len(section) >= min_chars else None
