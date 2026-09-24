from __future__ import annotations

import re

from figures import FigureIndex, check_figures

MIN_QUOTE_CHARS = 25
MIN_FRAGMENT_CHARS = 15
ELLIPSIS = re.compile(r"\.\.\.|…")


def normalize(text: str) -> str:
    # Compare on letters and digits only so curly quotes, dashes, and whitespace from HTML don't matter.
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def quote_in_source(quote: str, normalized_source: str) -> bool:
    if len(normalize(quote)) < MIN_QUOTE_CHARS:
        return False
    fragments = [normalize(f) for f in ELLIPSIS.split(quote)]
    fragments = [f for f in fragments if len(f) >= MIN_FRAGMENT_CHARS]
    return bool(fragments) and all(f in normalized_source for f in fragments)


def annotate_item(item: dict, normalized_source: str, index: FigureIndex) -> dict:
    quote_ok = quote_in_source(item.get("evidence", ""), normalized_source)
    figures = {field: check_figures(item.get(field, ""), index) for field in ("headline", "detail")}
    all_traced = all(span["verified"] for spans in figures.values() for span in spans)
    # An unverified quote means the insight isn't anchored to the filing at all; untraced figures on an
    # anchored insight are flagged individually.
    status = "unverified" if not quote_ok else "verified" if all_traced else "partial"
    return {**item, "verified": quote_ok, "figures": figures, "status": status}


def annotate(insights: list[dict], normalized_source: str, index: FigureIndex | None = None) -> list[dict]:
    index = index or FigureIndex()
    return [annotate_item(i, normalized_source, index) for i in insights]


def segment_check(segments: list[dict], reported_revenue: float | None, tolerance: float = 0.05) -> dict | None:
    total = sum(s["value"] for s in segments if s["value"] > 0)
    if not total or not reported_revenue:
        return None
    return {
        "segments_total": total,
        "reported_revenue": reported_revenue,
        "difference": total / reported_revenue - 1,
        "reconciles": abs(total / reported_revenue - 1) <= tolerance,
    }
