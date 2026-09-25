"""Builds the small inline XBRL fixtures in this directory from full SEC filings.

Keeps the cover page facts, chosen facts with their table rows, and chosen note text blocks with their continuations,
plus exactly the contexts and units those reference; drops styling. Usage:

    python tests/fixtures/trim_ixbrl.py SOURCE.htm OUT.htm --facts us-gaap:Revenues ... --blocks us-gaap:...TextBlock ...

A multi-document filing keeps its contexts in one document: trim the exhibit with --no-header, then trim the
primary document with --header-for EXHIBIT_OUT.htm so its header carries the contexts the exhibit uses.
"""

from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path

from lxml import etree

IX = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI = "http://www.xbrl.org/2003/instance"
XHTML = "http://www.w3.org/1999/xhtml"


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _strip(el):
    for node in el.iter():
        if isinstance(node.tag, str):
            for attr in ("style", "class"):
                node.attrib.pop(attr, None)
    return el


def _row(el):
    node = el.getparent()
    for _ in range(12):
        if node is None:
            return None
        if _local(node) == "tr":
            return node
        node = node.getparent()
    return None


def trim(source: Path, facts: set[str], blocks: set[str], header: bool = True, header_for: list[Path] = ()) -> bytes:
    root = etree.fromstring(source.read_bytes(), etree.XMLParser(huge_tree=True, recover=True))
    out = etree.Element(f"{{{XHTML}}}html", nsmap=root.nsmap)
    body = etree.SubElement(out, f"{{{XHTML}}}body")
    continuations = {el.get("id"): el for el in root.iter(f"{{{IX}}}continuation")}

    def add(el, wrapper="div"):
        holder = etree.SubElement(body, f"{{{XHTML}}}{wrapper}")
        holder.append(_strip(copy.deepcopy(el)))
        return holder

    for el in root.iter(f"{{{IX}}}nonNumeric"):
        name = el.get("name", "")
        if name.startswith("dei:") and name.split(":")[1] in (
            "DocumentType", "DocumentPeriodEndDate", "DocumentFiscalYearFocus", "DocumentFiscalPeriodFocus",
            "AmendmentFlag", "CurrentFiscalYearEndDate", "EntityCentralIndexKey", "EntityRegistrantName",
        ):
            add(el)
        if name in blocks:
            add(el)
            # Follow continuation chains of the block and of any block nested in it, each part once.
            pending, copied = [el], set()
            while pending:
                node = pending.pop()
                for inner in [node, *node.iter(f"{{{IX}}}nonNumeric")]:
                    next_id = inner.get("continuedAt")
                    while next_id in continuations and next_id not in copied:
                        copied.add(next_id)
                        part = continuations[next_id]
                        add(part)
                        pending.append(part)
                        next_id = part.get("continuedAt")
    # Holding the row elements keeps their lxml proxies alive, so membership tests are reliable (id() is not).
    seen_rows = set()
    for el in root.iter(f"{{{IX}}}nonFraction"):
        if el.get("name") not in facts:
            continue
        row = _row(el)
        if row is None:
            add(el, "p")
        elif row not in seen_rows:
            seen_rows.add(row)
            table = etree.SubElement(body, f"{{{XHTML}}}table")
            table.append(_strip(copy.deepcopy(row)))

    if header:
        users = [out] + [etree.fromstring(p.read_bytes()) for p in header_for]
        refs = {el.get("contextRef") for doc in users for el in doc.iter() if el.get("contextRef")}
        units = {el.get("unitRef") for doc in users for el in doc.iter() if el.get("unitRef")}
        ix_header = etree.Element(f"{{{IX}}}header")
        resources = etree.SubElement(ix_header, f"{{{IX}}}resources")
        for ctx in root.iter(f"{{{XBRLI}}}context"):
            if ctx.get("id") in refs:
                resources.append(copy.deepcopy(ctx))
        for unit in root.iter(f"{{{XBRLI}}}unit"):
            if unit.get("id") in units:
                resources.append(copy.deepcopy(unit))
        hidden_div = etree.Element(f"{{{XHTML}}}div")
        hidden_div.append(ix_header)
        body.insert(0, hidden_div)
    text = etree.tostring(out, xml_declaration=True, encoding="utf-8")
    return re.sub(rb">\s+<", b"><", text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--facts", nargs="*", default=[])
    parser.add_argument("--blocks", nargs="*", default=[])
    parser.add_argument("--no-header", action="store_true", help="omit contexts (they live in another document)")
    parser.add_argument("--header-for", type=Path, nargs="*", default=[], help="also carry contexts these trimmed documents use")
    args = parser.parse_args()
    args.out.write_bytes(trim(args.source, set(args.facts), set(args.blocks), not args.no_header, args.header_for))
    print(args.out, args.out.stat().st_size)


if __name__ == "__main__":
    main()
