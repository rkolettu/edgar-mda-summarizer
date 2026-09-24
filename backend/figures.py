"""Checks that dollar amounts and percentages written by the model trace back to the filing or SEC data."""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right

SCALE_WORDS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
SCALE_ABBR = {"K": 1e3, "M": 1e6, "mm": 1e6, "B": 1e9, "bn": 1e9, "T": 1e12, "tn": 1e12}
# Filing tables can omit a unit on each number, but only use a scale when a nearby
# table heading actually states it. An arbitrary page number or percentage is not
# evidence for a dollar claim.
TABLE_UNITS = re.compile(r"\b(?:in|amounts\s+in)\s+(thousands|millions|billions)\b", re.IGNORECASE)
TABLE_WINDOW = 240

NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
DOLLAR_CLAIM = re.compile(
    rf"\$\s?(?P<num>{NUMBER})"
    r"(?:\s*(?P<word>(?i:trillion|billion|million|thousand))\b|(?P<abbr>tn|bn|mm|[TBMK])\b)?"
)
PERCENT = re.compile(
    rf"(?<![\w.])(?P<num>{NUMBER})\s*"
    r"(?P<unit>%|(?i:percentage\s+points?|percent|basis\s+points?|bps|pts?)\b)"
)
SOURCE_AMOUNT = re.compile(
    rf"(?<![\w.])(?P<currency>\$)?\s?(?P<num>{NUMBER})"
    r"(?:\s*(?P<word>(?i:trillion|billion|million|thousand))\b|(?P<abbr>tn|bn|[TBM])\b)?"
)


def _parse(num: str) -> tuple[float, int]:
    digits = num.replace(",", "")
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    return float(digits), decimals


def _is_bps(unit: str) -> bool:
    return unit.lower().startswith(("basis", "bps"))


class FigureIndex:
    def __init__(self) -> None:
        self._amounts: list[float] = []
        self._percents: list[float] = []
        self._sorted = True

    def add_amount(self, value: float | None) -> None:
        if value is not None:
            self._amounts.append(abs(value))
            self._sorted = False

    def add_percent(self, value: float | None) -> None:
        if value is not None:
            self._percents.append(abs(value))
            self._sorted = False

    def add_text(self, text: str) -> None:
        percent_matches = list(PERCENT.finditer(text))
        percent_starts = {m.start("num") for m in percent_matches}
        table_headers = [(m.end(), SCALE_WORDS[m.group(1).lower().rstrip("s")]) for m in TABLE_UNITS.finditer(text)]
        table_positions = [position for position, _ in table_headers]
        for m in percent_matches:
            value, _ = _parse(m["num"])
            self.add_percent(value / 100 if _is_bps(m["unit"]) else value)
        for m in SOURCE_AMOUNT.finditer(text):
            if m.start("num") in percent_starts:
                continue
            value, _ = _parse(m["num"])
            scale = SCALE_WORDS.get((m["word"] or "").lower()) or SCALE_ABBR.get(m["abbr"] or "")
            if scale:
                self.add_amount(value * scale)
                continue
            header = bisect_right(table_positions, m.start("num")) - 1
            table_scale = table_headers[header][1] if header >= 0 and m.start("num") - table_positions[header] <= TABLE_WINDOW else None
            if table_scale:
                self.add_amount(value * table_scale)
            elif m["currency"]:
                self.add_amount(value)

    def _sort(self) -> None:
        if not self._sorted:
            self._amounts.sort()
            self._percents.sort()
            self._sorted = True

    @staticmethod
    def _contains(values: list[float], target: float, tolerance: float) -> bool:
        i = bisect_left(values, target - tolerance)
        return i < len(values) and values[i] <= target + tolerance

    def has_amount(self, value: float, tolerance: float) -> bool:
        self._sort()
        return self._contains(self._amounts, abs(value), tolerance)

    def has_percent(self, value: float, tolerance: float) -> bool:
        self._sort()
        return self._contains(self._percents, abs(value), tolerance)


def extract_claims(text: str) -> list[dict]:
    """Dollar amounts and percentages in model-written text, with the rounding tolerance their precision implies."""
    claims = []
    for m in DOLLAR_CLAIM.finditer(text):
        value, decimals = _parse(m["num"])
        scale = SCALE_WORDS.get((m["word"] or "").lower()) or SCALE_ABBR.get(m["abbr"] or "") or 1.0
        half_unit = 0.5 * 10 ** -decimals
        claims.append({
            "start": m.start(), "end": m.end(), "text": m.group(),
            "kind": "amount", "value": value * scale, "tolerance": half_unit * scale * (1 + 1e-9),
        })
    for m in PERCENT.finditer(text):
        value, decimals = _parse(m["num"])
        half_unit = 0.5 * 10 ** -decimals
        divisor = 100 if _is_bps(m["unit"]) else 1
        claims.append({
            "start": m.start(), "end": m.end(), "text": m.group(),
            "kind": "percent", "value": value / divisor, "tolerance": half_unit / divisor + 1e-9,
        })
    return sorted(claims, key=lambda c: c["start"])


def check_figures(text: str, index: FigureIndex) -> list[dict]:
    spans = []
    for c in extract_claims(text):
        found = (index.has_amount if c["kind"] == "amount" else index.has_percent)(c["value"], c["tolerance"])
        spans.append({"start": c["start"], "end": c["end"], "text": c["text"], "verified": found})
    return spans


MARGIN_METRICS = ("gross_profit", "operating_income", "net_income", "free_cash_flow")
GROWTH_METRICS = (
    "revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "free_cash_flow",
    "eps_diluted", "buybacks", "dividends", "capex", "rnd",
)


def add_financials(index: FigureIndex, fin: dict | None) -> None:
    """Adds reported XBRL values plus the few margins and growth rates a reader would derive from them.

    Derived percentages are limited to recent periods: every extra ratio widens the set of whole-number
    percentages that would match by coincidence.
    """
    if not fin:
        return
    years = fin["years"]
    for row in years:
        for key, value in row.items():
            if key != "period_end" and isinstance(value, (int, float)):
                index.add_amount(value)
    for row in years[-2:]:
        revenue = row.get("revenue")
        for key in MARGIN_METRICS:
            if revenue and row.get(key) is not None:
                index.add_percent(row[key] / revenue * 100)
    if len(years) >= 2:
        prev, curr = years[-2], years[-1]
        for key in GROWTH_METRICS:
            if curr.get(key) is not None and prev.get(key):
                index.add_percent((curr[key] - prev[key]) / abs(prev[key]) * 100)


def add_quarter(index: FigureIndex, metrics: dict | None) -> None:
    if not metrics:
        return
    for key, value in metrics.items():
        if not isinstance(value, (int, float)) or key == "fiscal_year":
            continue
        if key.endswith("_growth"):
            index.add_percent(value * 100)
        else:
            index.add_amount(value)
