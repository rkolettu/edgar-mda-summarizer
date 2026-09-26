"""Helpers over stored fact rows (store.company_facts), shared by the snapshot and the comparison engine."""

from __future__ import annotations

import re

FOOTNOTE = re.compile(r"(\s*(\([a-z0-9]{1,2}\)|\*+))+\s*$", re.IGNORECASE)
GENERIC_LABEL = re.compile(r"^(total|subtotal|net|other|none)\b[\w\s,]{0,14}$", re.IGNORECASE)


def fiscal_label(fiscal_year: int | None, fiscal_period: str | None) -> str | None:
    """'Q2 FY2027', 'FY2026'; None for dates that are not a period end (a subsequent event), which show their date."""
    if fiscal_year is None or fiscal_period is None:
        return None
    return f"FY{fiscal_year}" if fiscal_period == "FY" else f"{fiscal_period} FY{fiscal_year}"


def reported_label(row: dict) -> str | None:
    """The line item as the filing words it, without footnote markers; None when it only says 'Total'."""
    label = FOOTNOTE.sub("", row.get("reported_label") or "").strip()
    if not label or len(label) > 80 or GENERIC_LABEL.match(label) or not re.search(r"[A-Za-z]{3}", label):
        return None
    return label


def latest_by(rows: list[dict], key) -> dict:
    """Per key, the row from the latest filing (restated values win)."""
    best: dict = {}
    for row in rows:
        slot = key(row)
        if slot not in best or (row["filing_date"], row["fact_id"]) > (best[slot]["filing_date"], best[slot]["fact_id"]):
            best[slot] = row
    return best


def source(row: dict) -> dict | None:
    if not row.get("document_url"):
        return None
    return {"text": row.get("source_text"), "heading": row.get("heading"), "document_url": row["document_url"],
            "element_id": row.get("xbrl_element_id"), "filing": row["accession_number"]}
