"""Filing-type adapters: where a form keeps its tagged data and narrative, and what a complete filing contains.

This is the only layer that knows form types. It reuses sec.py's section rules (Item 7, 20-F operating reviews,
40-F management discussion exhibits, annual-report chapters) and hands everything downstream semantic categories.
Supporting a new form means adding an adapter here, not changing the schema, extraction or research code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from fastapi import HTTPException

import sec
from research.extract import SectionRecord, base_form, heading_of, text_hash

MDNA_CHARS = 400_000


@dataclass
class DocRef:
    url: str
    type: str          # EDGAR document type: '10-Q', 'EX-99.2', ...
    description: str
    ixbrl: bool
    role: str          # primary | xbrl_financials | exhibit


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


@dataclass(frozen=True)
class Adapter:
    forms: frozenset[str]
    expected: tuple[str, ...]
    narrative: Callable[[int, dict, str], tuple[list[NarrativeSection], list[str]]]


def list_documents(cik: int, filing: dict) -> list[DocRef]:
    """Every document in a filing from its EDGAR index page, with inline XBRL documents marked."""
    accession = filing["accession_number"]
    primary_url = sec.archive_url(cik, accession, filing["primary_doc"])
    index_url = sec.FILING_INDEX_URL.format(cik=cik, accession_no_dashes=accession.replace("-", ""), accession=accession)
    docs: list[DocRef] = []
    try:
        html = sec.sec_get(index_url).text
    except HTTPException:
        return [DocRef(primary_url, filing["form"], "primary document", True, "primary")]
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
        role = "primary" if url == primary_url else "xbrl_financials" if ixbrl else "exhibit"
        docs.append(DocRef(url, doc_type, cells[1].get_text(" ", strip=True), ixbrl, role))
    if not any(d.role == "primary" for d in docs):
        docs.insert(0, DocRef(primary_url, filing["form"], "primary document", True, "primary"))
    return docs


def _sections_from_loaded(loaded: dict, mdna_kind: str) -> list[NarrativeSection]:
    mdna = loaded["mdna"]
    sections = [NarrativeSection("management_discussion", mdna["source"], mdna_kind if mdna["url"] != loaded["document_url"] else "heading",
                                 mdna["url"], mdna["text"][:MDNA_CHARS], 0.9)]
    if loaded.get("risk_factors"):
        sections.append(NarrativeSection("risk_factors", "risk_factors", "heading", loaded["document_url"], loaded["risk_factors"], 0.9))
    return sections


def _loader_narrative(loader: Callable, mdna_kind: str = "exhibit"):
    def narrative(cik: int, filing: dict, html: str) -> tuple[list[NarrativeSection], list[str]]:
        try:
            loaded = loader(cik, {**filing, "form": base_form(filing["form"])}, html=html)
        except HTTPException as exc:
            return [], [f"Narrative sections not isolated: {exc.detail}"]
        sections = _sections_from_loaded(loaded, mdna_kind)
        warnings = [] if loaded.get("risk_factors") else ["Risk factors were not found under a recognized heading."]
        return sections, warnings

    return narrative


# A 10-Q's Part II Item 1A lists only updates to the annual risk factors, so its absence is normal.
TENQ_RISK_START = re.compile(rf"i\s*t\s*e\s*m\s*1a{sec.SEP}risk\s+factors", re.IGNORECASE)
TENQ_RISK_END = re.compile(rf"i\s*t\s*e\s*m\s*[2-6]{sec.SEP}(?:unregistered|defaults|mine|other\s+information|exhibits)", re.IGNORECASE)


def _tenq_narrative(cik: int, filing: dict, html: str) -> tuple[list[NarrativeSection], list[str]]:
    url = sec.archive_url(cik, filing["accession_number"], filing["primary_doc"])
    text = sec.html_to_text(html)
    sections, warnings = [], []
    mdna = sec.extract_section(text, sec.TENQ_MDNA_START, sec.TENQ_MDNA_END)
    if mdna:
        sections.append(NarrativeSection("management_discussion", "item2", "heading", url, mdna[:MDNA_CHARS], 0.9))
    else:
        warnings.append("Narrative sections not isolated: could not find Part I Item 2 MD&A.")
    risks = sec.extract_section(text, TENQ_RISK_START, TENQ_RISK_END, min_chars=200)
    if risks:
        sections.append(NarrativeSection("risk_factors", "item1a_update", "heading", url, risks[: sec.RISK_FACTORS_CHARS], 0.8))
    return sections, warnings


ANNUAL_EXPECTED = ("management_discussion", "risk_factors", "commitments", "debt", "income_taxes", "segment_information")
INTERIM_EXPECTED = ("management_discussion", "commitments", "debt")

ADAPTERS = [
    Adapter(frozenset({"10-K", "10-K/A", "10-KT"}), ANNUAL_EXPECTED, _loader_narrative(sec.load_10k)),
    Adapter(frozenset({"10-Q", "10-Q/A"}), INTERIM_EXPECTED, _tenq_narrative),
    Adapter(frozenset({"20-F", "20-F/A"}), ANNUAL_EXPECTED, _loader_narrative(sec.load_20f)),
    Adapter(frozenset({"40-F", "40-F/A"}), ANNUAL_EXPECTED, _loader_narrative(sec.load_40f)),
]
SUPPORTED_FORMS = frozenset().union(*(a.forms for a in ADAPTERS))


def adapter_for(form: str) -> Adapter | None:
    return next((a for a in ADAPTERS if form in a.forms), None)
