"""Turns a parsed filing into records for the research store: filing metadata, facts, sections and coverage.

Everything here is deterministic. Values come from the tags, never from a model, and each fact keeps where it
appeared so an insight built on it can be traced back to the filing.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from calendar import month_name
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from research import concepts
from research.ixbrl import Fact, IxbrlFiling, Period

PARSER_VERSION = 1

ANNUAL_FORMS = {"10-K", "10-KT", "20-F", "40-F"}
YEAR_DAYS = 365.25
MONTH_DAYS = YEAR_DAYS / 12
# Period lengths in days (end minus start), wide enough for 52/53-week calendars.
MONTH_BUCKETS = [(3, 80, 100), (6, 170, 196), (9, 260, 285), (12, 350, 380)]
HEADING_CHARS = 160


def period_months(period: Period) -> int | None:
    if period.is_instant:
        return None
    for months, low, high in MONTH_BUCKETS:
        if low <= period.days <= high:
            return months
    return max(1, round(period.days / MONTH_DAYS))


@dataclass(frozen=True)
class FiscalCalendar:
    """Places any date relative to the filing's fiscal year, so 52/53-week and non-calendar years label correctly."""

    fy_start: date
    fiscal_year: int

    def year_offset(self, end: date) -> tuple[int, float]:
        position = (end + timedelta(days=1) - self.fy_start).days
        # A 53-week year runs a few days past 365; the small allowance keeps its last day in the same year.
        offset = math.ceil(position / YEAR_DAYS - 0.03) - 1
        return offset, (position - offset * YEAR_DAYS) / MONTH_DAYS

    def label(self, period: Period) -> tuple[int, str | None]:
        offset, months_into = self.year_offset(period.end)
        fiscal_year = self.fiscal_year + offset
        into = round(months_into)
        months = period_months(period)
        if period.is_instant:
            return fiscal_year, {3: "Q1", 6: "Q2", 9: "Q3", 12: "FY"}.get(into)
        if months == 12:
            return fiscal_year, "FY"
        if months == 3 and into in (3, 6, 9, 12):
            return fiscal_year, f"Q{into // 3}"
        if months == 6 and into in (6, 12):
            return fiscal_year, "H1" if into == 6 else "H2"
        if months == 9 and into == 9:
            return fiscal_year, "9M"
        return fiscal_year, None


@dataclass
class FilingMeta:
    form_type: str
    base_form: str
    is_amendment: bool
    period_start: date | None
    period_end: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    period_months: int | None
    is_annual: bool
    is_interim: bool
    accounting_standard: str
    reporting_currency: str | None
    fiscal_year_end: str | None
    calendar: FiscalCalendar | None


@dataclass
class SourceRecord:
    document_url: str
    xbrl_element_id: str | None
    source_text: str | None
    table_label: str | None
    section_ref: str | None   # text block id; the store resolves it to a section row
    heading: str | None = None


@dataclass
class FactRecord:
    fact_key: str
    fact_type: str
    category: str | None
    subcategory: str | None
    canonical_metric: str | None
    label: str
    reported_label: str | None
    xbrl_concept: str | None
    dimensions: dict
    value_reported: float | None
    reported_scale: int | None
    reported_unit: str | None
    reported_currency: str | None
    value_normalized: float | None
    normalized_unit: str
    currency: str | None
    decimals: int | None
    accounting_standard: str
    period_type: str
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    period_months: int | None
    is_comparative: bool
    extraction_method: str
    parser_confidence: float
    sources: list[SourceRecord] = field(default_factory=list)
    text_value: str | None = None

    @property
    def dimensions_hash(self) -> str:
        return dimensions_hash(self.dimensions)

    @property
    def confidence_level(self) -> str:
        return confidence_level(self.parser_confidence)


@dataclass
class SectionRecord:
    ref: str                      # stable id within the filing (text block id or a narrative key)
    parent_ref: str | None
    category: str
    categories: tuple[str, ...]
    source_kind: str
    source_label: str | None
    heading: str | None
    document_url: str | None
    element_id: str | None
    ordinal: int
    text: str | None
    char_count: int
    text_hash: str
    confidence: float


@dataclass
class Extraction:
    meta: FilingMeta
    facts: list[FactRecord]
    sections: list[SectionRecord]
    coverage: dict
    parser_confidence: float
    warnings: list[str]

    @property
    def confidence_level(self) -> str:
        return confidence_level(self.parser_confidence)


def confidence_level(score: float) -> str:
    return "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"


def dimensions_hash(dims: dict) -> str:
    if not dims:
        return ""
    return hashlib.sha1(json.dumps(dims, sort_keys=True).encode()).hexdigest()[:16]


def text_hash(text: str) -> str:
    return hashlib.sha1(" ".join(text.split()).lower().encode()).hexdigest()


# --- filing-level metadata ---


def base_form(form: str) -> str:
    return form[:-2] if form.endswith("/A") else form


def accounting_standard(filing: IxbrlFiling) -> str:
    prefixes = Counter(f.concept.split(":", 1)[0] for f in filing.facts)
    if prefixes["ifrs-full"] > prefixes["us-gaap"]:
        return "ifrs"
    return "us-gaap" if prefixes["us-gaap"] else "other"


def currency_of(unit: str | None) -> str | None:
    if not unit or not unit.startswith("iso4217:"):
        return None
    return unit.split("/", 1)[0].split(":", 1)[1]


CURRENCY_ANCHORS = ("Revenues", "Revenue", "Assets", "NetIncomeLoss", "ProfitLoss", "RevenueFromContractWithCustomerExcludingAssessedTax")


def reporting_currency(filing: IxbrlFiling) -> str | None:
    """The currency of the headline statements; TSMC tags convenience US dollar translations next to its NT dollars."""
    anchored = Counter(
        currency_of(f.unit) for f in filing.facts
        if not f.context.dimensions and f.concept.split(":", 1)[-1] in CURRENCY_ANCHORS and currency_of(f.unit)
    )
    if anchored:
        return anchored.most_common(1)[0][0]
    monetary = Counter(currency_of(f.unit) for f in filing.facts if currency_of(f.unit) and "/" not in (f.unit or ""))
    return monetary.most_common(1)[0][0] if monetary else None


def fiscal_calendar(filing: IxbrlFiling, fiscal_year: int | None) -> FiscalCalendar | None:
    """The fiscal year starts where the longest year-to-date span ending on the report date begins."""
    cover = filing.dei_context
    if cover is None or fiscal_year is None:
        return None
    end = cover.period.end
    spans = [
        f.context.period for f in filing.facts
        if not f.context.dimensions and not f.context.period.is_instant
        and abs((f.context.period.end - end).days) <= 3 and f.context.period.days <= 380
    ]
    if cover.period.start:
        spans.append(cover.period)
    if not spans:
        return None
    return FiscalCalendar(min(spans, key=lambda p: p.start).start, fiscal_year)


def _int(text: str | None) -> int | None:
    try:
        return int(text.strip()) if text else None
    except ValueError:
        return None


def fiscal_year_end(text: str | None) -> str | None:
    """'--01-31', '1/31' or 'December 31' -> 'MM-DD'."""
    if not text:
        return None
    text = text.strip()
    if m := re.fullmatch(r"-*(\d{1,2})[-/](\d{1,2})", text):
        return f"{int(m[1]):02d}-{int(m[2]):02d}"
    for i in range(1, 13):
        if m := re.search(rf"{month_name[i]}\s+(\d{{1,2}})", text, re.IGNORECASE):
            return f"{i:02d}-{int(m[1]):02d}"
    return None


def filing_meta(filing: IxbrlFiling, edgar_form: str, report_date: date | None = None) -> FilingMeta:
    form = (filing.dei_text("DocumentType") or edgar_form).strip().upper()
    amendment_flag = (filing.dei_text("AmendmentFlag") or "").strip().lower() in ("true", "1")
    is_amendment = amendment_flag or form.endswith("/A") or edgar_form.endswith("/A")
    base = base_form(form)
    if is_amendment and not form.endswith("/A"):
        form = f"{form}/A"
    # Untagged filings (before inline XBRL, or exhibits-only 6-Ks) fall back to EDGAR's period of report.
    cover = filing.dei_context
    period_end = cover.period.end if cover else report_date
    fiscal_year = _int(filing.dei_text("DocumentFiscalYearFocus")) or (period_end.year if period_end else None)
    fiscal_period = (filing.dei_text("DocumentFiscalPeriodFocus") or "").strip().upper() or None
    is_annual = base in ANNUAL_FORMS or fiscal_period == "FY"
    return FilingMeta(
        form_type=form,
        base_form=base,
        is_amendment=is_amendment,
        period_start=cover.period.start if cover else None,
        period_end=period_end,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        period_months=period_months(cover.period) if cover else None,
        is_annual=is_annual,
        is_interim=not is_annual,
        accounting_standard=accounting_standard(filing),
        reporting_currency=reporting_currency(filing),
        fiscal_year_end=fiscal_year_end(filing.dei_text("CurrentFiscalYearEndDate")),
        calendar=fiscal_calendar(filing, fiscal_year),
    )


# --- facts ---


def _unit_fits(metric: concepts.Metric, unit: str | None, currency: str | None) -> bool:
    if metric.unit == "shares":
        return unit == "xbrli:shares"
    if metric.unit == "currency_per_share":
        return bool(unit) and unit.endswith("/xbrli:shares") and currency_of(unit) == currency
    return bool(unit) and "/" not in unit and currency_of(unit) == currency


def _period_fits(metric: concepts.Metric, period: Period) -> bool:
    return period.is_instant == (metric.period_type == "instant")


def _extension_candidates(metric: concepts.Metric, facts_by_concept: dict[str, list[Fact]]) -> list[str]:
    """Company-specific concepts named after a standard one, such as Suncor's
    'RevenueFromContractsWithCustomers.NetOfRoyaltyExpense'. Used only when unambiguous."""
    stems = metric.us_gaap + metric.ifrs
    found = []
    for concept in facts_by_concept:
        prefix, _, name = concept.partition(":")
        if prefix in ("us-gaap", "ifrs-full", "dei", "srt", "ecd"):
            continue
        # A separator after the stem marks a variant; more CamelCase words make it a different concept.
        if any(name.startswith(stem) and (len(name) == len(stem) or not name[len(stem)].isalpha()) for stem in stems):
            found.append(concept)
    return found


STANDARD_CONFIDENCE = 0.95
FALLBACK_CONFIDENCE = 0.9
EXTENSION_CONFIDENCE = 0.6
CONFLICT_PENALTY = 0.25


def metric_facts(filing: IxbrlFiling, meta: FilingMeta, section_headings: dict[str, str]) -> tuple[list[FactRecord], list[str]]:
    warnings: list[str] = []
    facts_by_concept: dict[str, list[Fact]] = defaultdict(list)
    for fact in filing.facts:
        if not fact.context.dimensions and fact.value is not None:
            facts_by_concept[fact.concept].append(fact)

    records: list[FactRecord] = []
    currency = meta.reporting_currency
    for metric in concepts.METRICS:
        chosen: dict[Period, tuple[Fact, float]] = {}
        for rank, concept in enumerate(concepts.metric_concepts(metric, meta.accounting_standard)):
            confidence = STANDARD_CONFIDENCE if rank == 0 else FALLBACK_CONFIDENCE
            for fact in facts_by_concept.get(concept, []):
                if _period_fits(metric, fact.context.period) and _unit_fits(metric, fact.unit, currency):
                    chosen.setdefault(fact.context.period, (fact, confidence))
        if not chosen:
            candidates = _extension_candidates(metric, facts_by_concept)
            if len(candidates) == 1:
                for fact in facts_by_concept[candidates[0]]:
                    if _period_fits(metric, fact.context.period) and _unit_fits(metric, fact.unit, currency):
                        chosen.setdefault(fact.context.period, (fact, EXTENSION_CONFIDENCE))
            elif len(candidates) > 1:
                warnings.append(f"{metric.label}: several company-specific tags could be it ({', '.join(sorted(candidates))}); left unmapped.")
        for period, (fact, confidence) in chosen.items():
            if fact.conflicting:
                confidence -= CONFLICT_PENALTY
            records.append(_metric_record(metric, fact, period, confidence, meta, section_headings))
    return records, warnings


def _metric_record(metric, fact: Fact, period: Period, confidence: float, meta: FilingMeta, section_headings) -> FactRecord:
    fiscal_year, fiscal_period = meta.calendar.label(period) if meta.calendar else (None, None)
    return FactRecord(
        fact_key=metric.fact_key,
        fact_type="financial_metric",
        category=metric.statement,
        subcategory=None,
        canonical_metric=metric.key,
        label=metric.label,
        reported_label=next((o.row_label for o in fact.occurrences if o.row_label), None),
        xbrl_concept=fact.concept,
        dimensions={},
        value_reported=fact.display_value,
        reported_scale=fact.scale,
        reported_unit=fact.unit,
        reported_currency=currency_of(fact.unit),
        value_normalized=fact.value,
        normalized_unit=metric.unit,
        currency=currency_of(fact.unit),
        decimals=fact.decimals,
        accounting_standard=meta.accounting_standard,
        period_type=metric.period_type,
        period_start=period.start,
        period_end=period.end,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        period_months=period_months(period),
        is_comparative=meta.period_end is not None and period.end != meta.period_end,
        extraction_method="xbrl",
        parser_confidence=round(confidence, 3),
        sources=[
            SourceRecord(o.document, o.element_id, o.row_text, None, o.text_block_id, section_headings.get(o.text_block_id or ""))
            for o in fact.occurrences
        ],
    )


# --- sections ---


def heading_of(text: str) -> str | None:
    first = text.strip().split("\n", 1)[0].strip()
    return first[:HEADING_CHARS] or None


def text_block_sections(filing: IxbrlFiling) -> list[SectionRecord]:
    sections = []
    for block in filing.text_blocks:
        categories = concepts.text_block_categories(block.concept)
        # Nested blocks (a note's tables) repeat their parent's text, so only top-level notes store it.
        stored = block.text if block.parent_id is None else None
        sections.append(SectionRecord(
            ref=block.id,
            parent_ref=block.parent_id,
            category=categories[0],
            categories=categories,
            source_kind="xbrl_textblock",
            source_label=block.concept,
            heading=heading_of(block.text),
            document_url=block.document,
            element_id=block.id,
            ordinal=block.ordinal,
            text=stored,
            char_count=len(block.text),
            text_hash=text_hash(block.text),
            confidence=0.95 if categories != ("other",) else 0.5,
        ))
    return sections


# --- coverage and confidence ---

CORE_METRICS = ("revenue", "net_income", "total_assets")


def coverage(sections: list[SectionRecord], facts: list[FactRecord], expected: tuple[str, ...]) -> dict:
    report: dict[str, dict] = {}
    for section in sections:
        # Nested blocks count: a guarantee schedule can sit inside the commitments note.
        if section.category == "accounting_policies":
            continue
        for category in section.categories:
            entry = report.setdefault(category, {"found": True, "tier": section.source_kind, "confidence": section.confidence})
            entry["confidence"] = max(entry["confidence"], section.confidence)
    for category in expected:
        report.setdefault(category, {"found": False, "tier": None, "confidence": 0.0})
    found_metrics = {f.canonical_metric for f in facts if not f.is_comparative}
    report["financial_statements"] = {
        "found": bool(found_metrics),
        "tier": "xbrl" if found_metrics else None,
        "confidence": round(sum(m in found_metrics for m in CORE_METRICS) / len(CORE_METRICS), 2),
        "metrics": sorted(found_metrics),
    }
    return report


def score_confidence(has_ixbrl: bool, report: dict, expected: tuple[str, ...]) -> float:
    statements = report.get("financial_statements", {}).get("confidence", 0.0)
    found = [report.get(c, {}).get("found", False) for c in expected]
    sections = sum(found) / len(found) if found else 1.0
    return round((0.4 if has_ixbrl else 0.0) + 0.35 * statements + 0.25 * sections, 3)


def extract(filing: IxbrlFiling, edgar_form: str, expected: tuple[str, ...] = (), report_date: date | None = None,
            extra_sections: list[SectionRecord] = ()) -> Extraction:
    """extra_sections are narrative sections an adapter found by heading (MD&A, risk factors)."""
    meta = filing_meta(filing, edgar_form, report_date)
    sections = text_block_sections(filing)
    headings = {s.ref: s.heading for s in sections if s.heading}
    sections += [replace(s, ordinal=len(sections) + i) for i, s in enumerate(extra_sections)]
    facts, warnings = metric_facts(filing, meta, headings)
    report = coverage(sections, facts, expected)
    if not report["financial_statements"]["found"]:
        warnings.append("No headline financial statement values were found in the tagged data.")
    return Extraction(meta, facts, sections, report, score_confidence(bool(filing.facts), report, expected), filing.warnings + warnings)
