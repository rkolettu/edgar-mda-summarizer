"""Inline XBRL (iXBRL) parser.

Filings tag nearly every number, the cover page and each note of the financial statements inside the HTML itself.
Reading the tags gives exact units, scale, sign and period for every value, and note boundaries named by taxonomy
concept, independent of the form type and of how a document numbers or titles its notes.

A filing's tagged documents form one set: Suncor's 40-F defines every context in the primary document while its
facts sit in exhibit 99.2, so documents are parsed together and facts are resolved against the merged set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from itertools import islice

from lxml import etree

IX = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

# Taxonomy prefixes follow the namespace, not the prefix a document happens to declare.
STANDARD_NAMESPACES = [
    (re.compile(r"fasb\.org/us-gaap/"), "us-gaap"),
    (re.compile(r"xbrl\.ifrs\.org/taxonomy/.*ifrs-full"), "ifrs-full"),
    (re.compile(r"xbrl\.sec\.gov/dei/"), "dei"),
    (re.compile(r"fasb\.org/srt/"), "srt"),
    (re.compile(r"xbrl\.sec\.gov/ecd/"), "ecd"),
]

BLOCK_TAGS = {"p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "br", "section", "ul", "ol"}
CELL_TAGS = {"td", "th"}
ROW_TEXT_CHARS = 400
MAX_SOURCES = 3


@dataclass(frozen=True)
class Period:
    start: date | None
    end: date

    @property
    def is_instant(self) -> bool:
        return self.start is None

    @property
    def days(self) -> int:
        return 0 if self.start is None else (self.end - self.start).days


@dataclass(frozen=True)
class Context:
    id: str
    period: Period
    dimensions: tuple[tuple[str, str], ...] = ()  # sorted (axis, member); typed members carry their value


@dataclass
class Occurrence:
    element_id: str | None
    document: str
    text_block_id: str | None
    row_text: str | None
    row_label: str | None


@dataclass
class Fact:
    concept: str
    context: Context
    unit: str | None
    value: float | None           # scale and sign applied
    display_value: float | None   # the number as printed, signed ('279' for $279 billion)
    scale: int
    decimals: int | None
    parsed: bool                  # False when the display format could not be read
    occurrences: list[Occurrence] = field(default_factory=list)
    conflicting: bool = False     # duplicates of this fact disagreed beyond rounding

    @property
    def primary(self) -> Occurrence:
        return self.occurrences[0]


@dataclass
class TextBlock:
    id: str
    concept: str
    context: Context | None
    document: str
    text: str
    parent_id: str | None
    ordinal: int


@dataclass
class IxbrlFiling:
    contexts: dict[str, Context] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    text_blocks: list[TextBlock] = field(default_factory=list)
    dei: dict[str, tuple[str, Context | None]] = field(default_factory=dict)
    documents: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def dei_text(self, name: str) -> str | None:
        entry = self.dei.get(name)
        return entry[0] if entry else None

    @property
    def dei_context(self) -> Context | None:
        # The cover page context spans the fiscal year to date: a Q2 10-Q's runs six months.
        for name in ("DocumentPeriodEndDate", "DocumentType", "DocumentFiscalPeriodFocus"):
            entry = self.dei.get(name)
            if entry and entry[1]:
                return entry[1]
        return None


def is_ixbrl(data: bytes) -> bool:
    return IX.encode() in data[:50_000]


def local_name(qname: str) -> str:
    return qname.split(":", 1)[-1]


def _local(el) -> str:
    tag = el.tag
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _is(el, ns: str, name: str) -> bool:
    return isinstance(el.tag, str) and el.tag == f"{{{ns}}}{name}"


def _qname(el, value: str) -> str:
    """Rewrites a QName written in a document to its standard taxonomy prefix where the namespace is known."""
    value = value.strip()
    if ":" not in value:
        return value
    prefix, name = value.split(":", 1)
    uri = el.nsmap.get(prefix)
    if uri:
        for pattern, standard in STANDARD_NAMESPACES:
            if pattern.search(uri):
                return f"{standard}:{name}"
    return f"{prefix}:{name}"


def _date(text: str | None) -> date | None:
    if not text:
        return None
    # Some filers write dateTimes ("2026-07-26T00:00:00").
    return date.fromisoformat(text.strip()[:10])


def _text(el, skip_excluded: bool = True) -> str:
    """Readable text with line breaks between block elements and spacing between table cells."""
    parts: list[str] = []

    def walk(node):
        if skip_excluded and _is(node, IX, "exclude"):
            return
        name = _local(node)
        if name in BLOCK_TAGS:
            parts.append("\n")
        elif name in CELL_TAGS:
            parts.append(" ")
        if node.text and isinstance(node.tag, str):
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if name in BLOCK_TAGS:
            parts.append("\n")

    walk(el)
    text = "".join(parts).replace("\xa0", " ").replace("​", "")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line)).strip()


def _inline_text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext()).replace("\xa0", " ").replace("​", "")).strip()


# --- numeric display formats (Inline XBRL transformation registries 1-5 and the SEC's own) ---

WORD_NUMBERS = {
    "no": 0, "none": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
WORD_SCALES = {"hundred": 100, "thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}


def _words_to_number(text: str) -> float | None:
    total, current = 0.0, 0.0
    words = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    if not words:
        return None
    for word in words:
        if word in ("and", "a"):
            continue
        if word in WORD_NUMBERS:
            current += WORD_NUMBERS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word in WORD_SCALES:
            total += (current or 1) * WORD_SCALES[word]
            current = 0
        else:
            return None
    return total + current


def parse_display_number(text: str, fmt: str | None) -> float | None:
    fmt_name = local_name(fmt or "").lower()
    if fmt_name in ("fixed-zero", "fixedzero", "zerodash", "zero-dash", "nocontent"):
        return 0.0
    if "word" in fmt_name:
        return _words_to_number(text)
    comma_decimal = any(key in fmt_name for key in ("comma-decimal", "commadecimal", "numdotcomma", "numspacecomma"))
    decimal_mark = "," if comma_decimal else "."
    cleaned = re.sub(rf"[^0-9{re.escape(decimal_mark)}]", "", text)
    if not cleaned or not re.search(r"\d", cleaned):
        # A dash or blank in a table cell is how filings print zero.
        return 0.0 if re.fullmatch(r"\s*[-–—]?\s*", text) else None
    if comma_decimal:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


# --- document parsing ---


@dataclass
class _RawFact:
    el: object
    concept: str
    document: str
    owner: str | None


def parse_documents(documents: list[tuple[str, bytes]]) -> IxbrlFiling:
    """Parses every tagged document of one filing (name or URL, raw bytes) into a single set of facts."""
    result = IxbrlFiling()
    parsed: list[tuple[str, object]] = []
    for name, data in documents:
        parser = etree.XMLParser(huge_tree=True, recover=True, resolve_entities=False, no_network=True)
        try:
            root = etree.fromstring(data, parser)
        except etree.XMLSyntaxError as exc:
            result.warnings.append(f"{name}: not well-formed XHTML ({exc}); its tags were skipped.")
            continue
        if root is None:
            result.warnings.append(f"{name}: could not be parsed; its tags were skipped.")
            continue
        parsed.append((name, root))
        result.documents.append(name)

    continuations: dict[str, object] = {}
    for _, root in parsed:
        _read_resources(root, result)
        for el in root.iter(f"{{{IX}}}continuation"):
            if el.get("id"):
                continuations[el.get("id")] = el

    # Text block and continuation elements -> block id. The dict keeps these lxml proxies alive, so walking up from
    # a fact returns the same objects and membership tests hold (a node's proxy is only reused while referenced).
    block_of: dict[object, str] = {}
    for name, root in parsed:
        for el in root.iter(f"{{{IX}}}nonNumeric"):
            concept = _qname(el, el.get("name", ""))
            context = result.contexts.get(el.get("contextRef", ""))
            if concept.startswith("dei:"):
                result.dei.setdefault(local_name(concept), (_inline_text(el), context))
                continue
            if not _is_text_block(concept, el):
                continue
            ordinal = len(result.text_blocks)
            block_id = el.get("id") or f"textblock-{ordinal}"
            chain = [el] + _continuation_chain(el, continuations)
            # Outer blocks precede the blocks nested in them in document order.
            parent = next((block_of[a] for a in _ancestors(el) if a in block_of), None)
            for part in chain:
                block_of.setdefault(part, block_id)
            text = "\n\n".join(t for t in (_text(part) for part in chain) if t)
            result.text_blocks.append(TextBlock(block_id, concept, context, name, text, parent, ordinal))

    raw_numeric = [
        _RawFact(el, _qname(el, el.get("name", "")), name, next((block_of[a] for a in _ancestors(el) if a in block_of), None))
        for name, root in parsed
        for el in root.iter(f"{{{IX}}}nonFraction")
    ]
    result.facts = _resolve_facts(raw_numeric, result)
    return result


def _read_resources(root, result: IxbrlFiling) -> None:
    for ctx in root.iter(f"{{{XBRLI}}}context"):
        cid = ctx.get("id")
        if not cid or cid in result.contexts:
            continue
        instant = ctx.find(f".//{{{XBRLI}}}instant")
        try:
            if instant is not None:
                period = Period(None, _date(instant.text))
            else:
                period = Period(_date(ctx.findtext(f".//{{{XBRLI}}}startDate")), _date(ctx.findtext(f".//{{{XBRLI}}}endDate")))
        except (TypeError, ValueError):
            result.warnings.append(f"Context {cid} has an unreadable period; facts using it were skipped.")
            continue
        if period.end is None:
            continue
        dims = []
        for member in ctx.iter(f"{{{XBRLDI}}}explicitMember"):
            dims.append((_qname(member, member.get("dimension", "")), _qname(member, member.text or "")))
        for member in ctx.iter(f"{{{XBRLDI}}}typedMember"):
            dims.append((_qname(member, member.get("dimension", "")), _inline_text(member)))
        result.contexts[cid] = Context(cid, period, tuple(sorted(dims)))

    for unit in root.iter(f"{{{XBRLI}}}unit"):
        uid = unit.get("id")
        if not uid or uid in result.units:
            continue
        divide = unit.find(f"{{{XBRLI}}}divide")
        if divide is not None:
            num = "*".join(_qname(m, m.text or "") for m in divide.iterfind(f"{{{XBRLI}}}unitNumerator/{{{XBRLI}}}measure"))
            den = "*".join(_qname(m, m.text or "") for m in divide.iterfind(f"{{{XBRLI}}}unitDenominator/{{{XBRLI}}}measure"))
            result.units[uid] = f"{num}/{den}"
        else:
            result.units[uid] = "*".join(_qname(m, m.text or "") for m in unit.iterfind(f"{{{XBRLI}}}measure"))


def _is_text_block(concept: str, el) -> bool:
    name = local_name(concept)
    return name.endswith(("TextBlock", "Explanatory")) or (el.get("escape") == "true" and len(el) > 0)


def _continuation_chain(el, continuations: dict[str, object]) -> list:
    chain, seen = [], set()
    next_id = el.get("continuedAt")
    while next_id and next_id not in seen and next_id in continuations:
        seen.add(next_id)
        part = continuations[next_id]
        chain.append(part)
        next_id = part.get("continuedAt")
    return chain


def _ancestors(el, include_self: bool = False):
    node = el if include_self else el.getparent()
    while node is not None:
        yield node
        node = node.getparent()


ROW_SEARCH_DEPTH = 12
LAYOUT_ROW_CHARS = 1_000


def _row_context(el) -> tuple[str | None, str | None]:
    """The table row a value sits in (with its first labelled cell), or the sentence around it in prose.

    Cells often wrap values in paragraphs, so the row wins over a nearer paragraph, unless the "row" is a
    page-layout table holding whole passages."""
    ancestors = list(islice(_ancestors(el), ROW_SEARCH_DEPTH))
    row = next((a for a in ancestors if _local(a) == "tr"), None)
    if row is not None:
        cells = [c for c in (_inline_text(c) for c in row if _local(c) in CELL_TAGS) if c]
        text = " ".join(cells)
        if text and len(text) <= LAYOUT_ROW_CHARS:
            label = next((c for c in cells if re.search(r"[A-Za-z]{2,}", c)), None)
            return text[:ROW_TEXT_CHARS], label
    for node in ancestors:
        if _local(node) not in ("p", "li", "div"):
            continue
        text = _inline_text(node)
        if not text:
            continue
        value = _inline_text(el)
        at = text.find(value) if value else -1
        if at < 0 or len(text) <= ROW_TEXT_CHARS:
            return text[:ROW_TEXT_CHARS], None
        start = max(text.rfind(". ", 0, at) + 2, at - 250, 0)
        end = text.find(". ", at)
        end = len(text) if end < 0 else end + 1
        return text[start:min(end, start + ROW_TEXT_CHARS)], None
    return None, None


def _resolve_facts(raw_facts: list[_RawFact], result: IxbrlFiling) -> list[Fact]:
    facts: dict[tuple, Fact] = {}
    missing_contexts: set[str] = set()
    for raw in raw_facts:
        el = raw.el
        if el.get(XSI_NIL) in ("true", "1"):
            continue
        context = result.contexts.get(el.get("contextRef", ""))
        if context is None:
            missing_contexts.add(el.get("contextRef", ""))
            continue
        unit = result.units.get(el.get("unitRef", ""), el.get("unitRef"))
        display = _inline_text(el)
        number = parse_display_number(display, el.get("format"))
        try:
            scale = int(el.get("scale") or 0)
        except ValueError:
            scale = 0
        decimals_attr = el.get("decimals")
        decimals = None if decimals_attr in (None, "INF") else _int_or_none(decimals_attr)
        sign = -1 if el.get("sign") == "-" else 1
        display_value = None if number is None else sign * number
        value = None if number is None else sign * number * 10 ** scale
        row_text, row_label = _row_context(el)
        occurrence = Occurrence(el.get("id"), raw.document, raw.owner, row_text, row_label)

        key = (raw.concept, context.id, unit)
        existing = facts.get(key)
        if existing is None:
            facts[key] = Fact(raw.concept, context, unit, value, display_value, scale, decimals, number is not None, [occurrence])
            continue
        # Prefer places where the row names the line item (the statements) over bare cells in summary tables.
        if occurrence.row_label and not existing.primary.row_label:
            existing.occurrences.insert(0, occurrence)
            del existing.occurrences[MAX_SOURCES:]
        elif len(existing.occurrences) < MAX_SOURCES:
            existing.occurrences.append(occurrence)
        if value is None or existing.value is None:
            if existing.value is None and value is not None:
                existing.value, existing.display_value, existing.scale, existing.decimals, existing.parsed = value, display_value, scale, decimals, True
            continue
        if not _same_value(existing.value, existing.decimals, value, decimals):
            existing.conflicting = True
            # Keep the more precise of two disagreeing duplicates.
            if (decimals or -99) > (existing.decimals or -99):
                existing.value, existing.display_value, existing.scale, existing.decimals = value, display_value, scale, decimals
    if missing_contexts:
        result.warnings.append(f"{len(missing_contexts)} context reference(s) were undefined; their facts were skipped.")
    conflicts = sum(1 for f in facts.values() if f.conflicting)
    if conflicts:
        result.warnings.append(f"{conflicts} tagged value(s) appear more than once with different amounts.")
    return list(facts.values())


def _int_or_none(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _same_value(a: float, a_decimals: int | None, b: float, b_decimals: int | None) -> bool:
    # Values printed at different precision ("$5.2 billion" and "5,213") agree when they round alike.
    precision = min(d for d in (a_decimals, b_decimals, 10) if d is not None)
    tolerance = 0.5 * 10 ** -precision
    return abs(a - b) <= tolerance + 1e-9 * max(abs(a), abs(b))
