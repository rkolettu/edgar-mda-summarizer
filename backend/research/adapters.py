"""Filing-type adapters: where a form keeps its tagged data and narrative, and what a complete filing contains.

This is the only layer that knows form types. It reuses sec.py's section rules (Item 7, 20-F operating reviews,
annual-report chapters) and research.reports for foreign issuers (Form 20-F cross-reference tables, 40-F document
sets), and hands everything downstream semantic categories. Supporting a new form means adding an adapter here, not
changing the schema, extraction or research code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from fastapi import HTTPException

import sec
from research import reports
from research.extract import SectionRecord, base_form, heading_of, text_hash

MDNA_CHARS = 400_000


@dataclass
class DocRef:
    url: str
    type: str          # EDGAR document type: '10-Q', 'EX-99.2', ...
    description: str
    ixbrl: bool
    role: str          # primary | xbrl_financials | exhibit | companion (a 6-K filed with the annual report)
    size: int | None = None


@dataclass
class NarrativeSection:
    category: str
    source_label: str  # which rule found it: item7, exhibit13, item5, annual_report, mdna_exhibit, ...
    source_kind: str   # heading | exhibit
    document_url: str
    text: str
    confidence: float

    def as_section(self, ordinal: int) -> SectionRecord:
        return SectionRecord(
            ref=f"narrative:{self.category}", parent_ref=None, category=self.category, categories=(self.category,),
            source_kind=self.source_kind, source_label=self.source_label, heading=heading_of(self.text),
            document_url=self.document_url, element_id=None, ordinal=ordinal, text=self.text,
            char_count=len(self.text), text_hash=text_hash(self.text), confidence=self.confidence,
        )


def list_documents(cik: int, filing: dict, role: str | None = None) -> list[DocRef]:
    """Every document in a filing from its EDGAR index page, with inline XBRL documents marked. With role, every
    document takes that role (a companion 6-K's)."""
    accession = filing["accession_number"]
    primary_url = sec.archive_url(cik, accession, filing["primary_doc"])
    index_url = sec.FILING_INDEX_URL.format(cik=cik, accession_no_dashes=accession.replace("-", ""), accession=accession)
    docs: list[DocRef] = []
    try:
        html = sec.sec_get(index_url).text
    except HTTPException:
        return [DocRef(primary_url, filing["form"], "primary document", True, role or "primary")]
    for row in BeautifulSoup(html, "html.parser").select("table.tableFile tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        link = cells[2].find("a")
        href = (link.get("href", "") if link else "").replace("/ix?doc=", "")
        if not href.lower().endswith((".htm", ".html", ".xhtml")):
            continue
        url = urljoin("https://www.sec.gov", href)
        doc_type = cells[3].get_text(strip=True)
        ixbrl = "ixbrl" in cells[2].get_text(" ", strip=True).lower() or "/ix?doc=" in (link.get("href", "") if link else "")
        size = cells[4].get_text(strip=True) if len(cells) > 4 else ""
        docs.append(DocRef(url, doc_type, cells[1].get_text(" ", strip=True), ixbrl,
                           role or ("primary" if url == primary_url else "xbrl_financials" if ixbrl else "exhibit"),
                           int(size) if size.isdigit() else None))
    if not role and not any(d.role == "primary" for d in docs):
        docs.insert(0, DocRef(primary_url, filing["form"], "primary document", True, "primary"))
    return docs


# Where 40-F and 6-K filers put their disclosure documents (annual information form, MD&A, statements, reports).
DISCLOSURE_EXHIBIT = re.compile(r"^EX-(?:99|1|2|3|13|15)(?:\.\d+)?$", re.IGNORECASE)
MIN_DISCLOSURE_BYTES = 15_000


class Files:
    """A filing's documents, fetched once and converted to text with paragraphs as lines."""

    def __init__(self, documents: list[DocRef], responses: dict | None = None):
        self.documents = documents
        self._responses = dict(responses or {})
        self._texts: dict[str, str] = {}

    def html(self, url: str) -> str:
        if url not in self._responses:
            self._responses[url] = sec.sec_get(url)
        return self._responses[url].text

    def text(self, url: str) -> str:
        if url not in self._texts:
            with sec.keeping_lines():
                self._texts[url] = sec.html_to_text(self.html(url))
        return self._texts[url]

    def disclosure_documents(self) -> list[DocRef]:
        """The primary document, a companion 6-K's documents and the exhibits that can hold disclosure documents."""
        return [d for d in self.documents if d.role in ("primary", "companion", "xbrl_financials")
                or (DISCLOSURE_EXHIBIT.match(d.type) and (d.size is None or d.size >= MIN_DISCLOSURE_BYTES))]


Narrative = Callable[[int, dict, str, Files], tuple[list[NarrativeSection], list[str]]]


def _sections_from_loaded(loaded: dict, mdna_kind: str) -> list[NarrativeSection]:
    mdna = loaded["mdna"]
    sections = [NarrativeSection("management_discussion", mdna["source"], mdna_kind if mdna["url"] != loaded["document_url"] else "heading",
                                 mdna["url"], mdna["text"][:MDNA_CHARS], 0.9)]
    if loaded.get("risk_factors"):
        sections.append(NarrativeSection("risk_factors", "risk_factors", "heading", loaded["document_url"], loaded["risk_factors"], 0.9))
    if loaded.get("business"):
        sections.append(NarrativeSection("business", "business", "heading", loaded["document_url"], loaded["business"], 0.85))
    return sections


def _loader_narrative(loader: Callable, mdna_kind: str = "exhibit") -> Narrative:
    def narrative(cik: int, filing: dict, html: str, files: Files) -> tuple[list[NarrativeSection], list[str]]:
        try:
            with sec.keeping_lines():
                loaded = loader(cik, {**filing, "form": base_form(filing["form"])}, html=html)
        except HTTPException as exc:
            return [], [f"Narrative sections not isolated: {exc.detail}"]
        sections = _sections_from_loaded(loaded, mdna_kind)
        warnings = [] if loaded.get("risk_factors") else ["Risk factors were not found under a recognized heading."]
        return sections, warnings

    return narrative


def _twentyf_narrative(cik: int, filing: dict, html: str, files: Files) -> tuple[list[NarrativeSection], list[str]]:
    """An integrated annual report is read through its Form 20-F cross-reference table (UBS, HSBC, Shell, ASML); a
    20-F laid out by Item (TSMC) through its Item headings."""
    url = sec.archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = files.text(url)
    found = reports.cross_referenced_sections(text)
    if not found.get("management_discussion"):
        try:
            with sec.keeping_lines():
                loaded = sec.load_20f(cik, {**filing, "form": base_form(filing["form"])}, html=html, text=text)
        except HTTPException as exc:
            return [], [f"Narrative sections not isolated: {exc.detail}"]
        sections = _sections_from_loaded(loaded, "exhibit")
        return sections, [] if loaded.get("risk_factors") else ["Risk factors were not found under a recognized heading."]
    risks = found.get("risk_factors") or sec.extract_20f_risk_factors(text)
    business = found.get("business") or sec.extract_business(text, "20-F")
    sections = [NarrativeSection("management_discussion", "cross_reference", "heading", url,
                                 found["management_discussion"][:MDNA_CHARS], 0.85)]
    if risks:
        sections.append(NarrativeSection("risk_factors", "cross_reference", "heading", url, risks[:sec.RISK_FACTORS_CHARS], 0.85))
    if business:
        sections.append(NarrativeSection("business", "cross_reference", "heading", url, business[:sec.BUSINESS_CHARS], 0.8))
    return sections, [] if risks else ["Risk factors were not found under a recognized heading."]


def _documents(files: Files) -> list[reports.Document]:
    out = []
    for doc in files.disclosure_documents():
        try:
            out.append(reports.Document(doc.url, files.text(doc.url)))
        except HTTPException:
            continue
    return out


def _fortyf_narrative(cik: int, filing: dict, html: str, files: Files) -> tuple[list[NarrativeSection], list[str]]:
    """A 40-F's annual information form, MD&A and statements are found by their titles, wherever they are filed:
    as exhibits, inside the 40-F itself, or in a 6-K filed the same day."""
    found = reports.fortyf_sections(_documents(files), sec.BUSINESS_CHARS, sec.RISK_FACTORS_CHARS)
    sections, warnings = [], []
    labels = {"management_discussion": "mdna_document", "risk_factors": "risk_factors", "business": "annual_information_form"}
    for category in ("management_discussion", "risk_factors", "business"):
        if category in found:
            url, text = found[category]
            limit = MDNA_CHARS if category == "management_discussion" else len(text)
            sections.append(NarrativeSection(category, labels[category], "exhibit", url, text[:limit], 0.85))
    if "management_discussion" not in found:
        warnings.append("Narrative sections not isolated: no management's discussion and analysis was found among the 40-F's documents.")
    if "risk_factors" not in found:
        warnings.append("Risk factors were not found under a recognized heading.")
    return sections, warnings


def _sixk_narrative(cik: int, filing: dict, html: str, files: Files) -> tuple[list[NarrativeSection], list[str]]:
    """A tagged interim report furnished on Form 6-K: its MD&A when the report has one (Canadian banks' quarterly
    reports to shareholders); interim reports without one still give their tagged statements."""
    parts = reports.document_parts(_documents(files))
    if not parts.mdna:
        return [], []
    url, text = parts.mdna
    return [NarrativeSection("management_discussion", "mdna_document", "exhibit", url, text[:MDNA_CHARS], 0.8)], []


# A 10-Q's Part II Item 1A lists only updates to the annual risk factors, so its absence is normal.
TENQ_RISK_START = re.compile(rf"i\s*t\s*e\s*m\s*1a{sec.SEP}risk\s+factors", re.IGNORECASE)
TENQ_RISK_END = re.compile(rf"i\s*t\s*e\s*m\s*[2-6]{sec.SEP}(?:unregistered|defaults|mine|other\s+information|exhibits)", re.IGNORECASE)


def _tenq_narrative(cik: int, filing: dict, html: str, files: Files) -> tuple[list[NarrativeSection], list[str]]:
    url = sec.archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = files.text(url)
    sections, warnings = [], []
    # Some banks lay the 10-Q out like an annual report, with Item 2 only an entry in the contents (JPMorgan).
    mdna = sec.extract_section(text, sec.TENQ_MDNA_START, sec.TENQ_MDNA_END) or reports.mdna_from_contents(text)
    if mdna:
        sections.append(NarrativeSection("management_discussion", "item2", "heading", url, mdna[:MDNA_CHARS], 0.9))
    else:
        warnings.append("Narrative sections not isolated: could not find Part I Item 2 MD&A.")
    risks = sec.extract_section(text, TENQ_RISK_START, TENQ_RISK_END, min_chars=200)
    if risks:
        sections.append(NarrativeSection("risk_factors", "item1a_update", "heading", url, risks[: sec.RISK_FACTORS_CHARS], 0.8))
    return sections, warnings


ANNUAL_EXPECTED = ("management_discussion", "risk_factors", "commitments", "debt", "income_taxes", "segment_information")
# Every annual report describes the business: 10-K Item 1, 20-F Item 4 and a 40-F's annual information form.
BUSINESS_EXPECTED = (*ANNUAL_EXPECTED, "business")
INTERIM_EXPECTED = ("management_discussion", "commitments", "debt")


@dataclass(frozen=True)
class Adapter:
    forms: frozenset[str]
    expected: tuple[str, ...]
    narrative: Narrative


ADAPTERS = [
    Adapter(frozenset({"10-K", "10-K/A", "10-KT"}), BUSINESS_EXPECTED, _loader_narrative(sec.load_10k)),
    Adapter(frozenset({"10-Q", "10-Q/A"}), INTERIM_EXPECTED, _tenq_narrative),
    Adapter(frozenset({"20-F", "20-F/A"}), BUSINESS_EXPECTED, _twentyf_narrative),
    Adapter(frozenset({"40-F", "40-F/A"}), BUSINESS_EXPECTED, _fortyf_narrative),
    # Only 6-Ks that carry inline XBRL are discovered: tagged interim reports (and an annual report's companion,
    # which is read with its 40-F). What else a 6-K holds varies, so nothing is expected of it.
    Adapter(frozenset({"6-K", "6-K/A"}), (), _sixk_narrative),
]
SUPPORTED_FORMS = frozenset().union(*(a.forms for a in ADAPTERS))


def adapter_for(form: str) -> Adapter | None:
    return next((a for a in ADAPTERS if form in a.forms), None)
