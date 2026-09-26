"""Why a figure in the financial tables is blank or looks unusual, in plain words and computed in code (never by a
model). Each note names the cells it explains, and the page numbers them under the table.

A blank has a cause that can be stated:
- the company tags no such line (the row is then listed as not shown, with the reason);
- the report for that period does not tag it (interim reports are condensed);
- the period appears only as a comparative column in a later report;
- a quarter is worked out from year-to-date totals and one of them is missing;
- a per-share amount cannot be worked out by subtraction;
- a ratio lacks an input.

An unusual figure stands far from the periods beside it, or is a payment far below its usual level. The note says what the filings tag for it (a one-off
gain, a release of credit loss provisions, a payment that fell in the next quarter), or that the tags do not say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median

from research import concepts, metrics
from research.rows import fiscal_label, money

# What each computed row is worked out from; "prior:" marks the same period a year earlier.
DERIVED = {
    "revenue_growth": ("revenue", "prior:revenue"),
    "eps_growth": ("eps_diluted", "prior:eps_diluted"),
    "gross_margin": ("gross_profit", "revenue"),
    "rnd_intensity": ("rnd", "revenue"),
    "operating_margin": ("operating_income", "revenue"),
    "effective_tax_rate": ("income_tax", "pretax_income"),
    "net_margin": ("net_income", "revenue"),
    "capex_intensity": ("capex", "revenue"),
    "free_cash_flow": ("operating_cash_flow", "capex"),
    "fcf_margin": ("operating_cash_flow", "capex", "revenue"),
    "cash_conversion": ("operating_cash_flow", "net_income"),
    "net_cash": ("cash", "total_debt"),
    "receivable_days": ("accounts_receivable", "revenue"),
    "inventory_days": ("inventory", "revenue"),
    "nii_share": ("net_interest_income", "revenue"),
    "cost_income_ratio": ("operating_expenses", "revenue"),
    "loans_to_deposits": ("loans", "deposits"),
    "credit_loss_rate": ("credit_loss_expense", "loans"),
    "roe": ("net_income", "equity"),
}
# Headline lines whose absence from a table is explained; the ratios built on them follow.
KEY_ROWS = ["revenue", "gross_profit", "operating_income", "pretax_income", "net_income", "eps_diluted",
            "operating_cash_flow", "capex", "free_cash_flow", "cash", "total_debt", "total_assets", "equity"]
BANK_KEY_ROWS = ["revenue", "net_interest_income", "fee_income", "credit_loss_expense", "operating_expenses",
                 "pretax_income", "net_income", "eps_diluted", "loans", "deposits", "total_assets", "equity"]
EXTRA_LABELS = {"income_tax": "income tax", "cost_of_revenue": "cost of revenue"}

# A figure this many times the periods beside it, or a payment this small a share of its typical level, is called out.
HIGH, LOW = 1.8, 0.35
# Lines whose spikes are one-offs worth explaining; payments whose timing can shift between quarters.
SPIKE_ROWS = ("net_income", "pretax_income", "operating_income", "noninterest_income", "revenue", "eps_diluted")
PAYMENT_ROWS = ("dividends_paid", "buybacks")
MIN_OTHER_PERIODS = 3
# A tagged one-off item explains a spike when it is at least this share of the amount above the typical level.
EXPLAINS_SHARE = 0.4
PART_NAMES = {"FY": "full-year", "9M": "nine-month", "H1": "first-half", "Q1": "first-quarter"}
YTD_PARTS = {"Q2": ("H1", "Q1"), "Q3": ("9M", "H1"), "Q4": ("FY", "9M"), "H2": ("FY", "H1")}


@dataclass
class Note:
    kind: str                                   # missing | unusual
    text: str
    cells: list[tuple[str, int]] = field(default_factory=list)


class Notes:
    """Notes collected for one table; cells with the same explanation share a note."""

    def __init__(self):
        self.by_text: dict[str, Note] = {}

    def add(self, kind: str, text: str, *cells: tuple[str, int]) -> None:
        note = self.by_text.setdefault(text, Note(kind, text))
        note.cells.extend(c for c in cells if c not in note.cells)

    def as_json(self) -> list[dict]:
        notes = sorted(self.by_text.values(), key=lambda n: (n.kind != "unusual", min(c[1] for c in n.cells) if n.cells else 0))
        return [{"n": i, "kind": n.kind, "text": n.text, "cells": [list(c) for c in n.cells]} for i, n in enumerate(notes, 1)]


@dataclass
class Context:
    m: metrics.Metrics
    kind: str
    bank: bool
    filings: list[dict]
    rows: list[dict]
    currency: str | None
    ifrs: bool

    def label(self, key: str) -> str:
        metric = concepts.METRICS_BY_KEY.get(key)
        name = EXTRA_LABELS.get(key) or (metric.label if metric else key.replace("_", " "))
        return name if name.isupper() else name[0].lower() + name[1:] if not name[:2].isupper() else name

    def report(self, fiscal_year: int, period: str) -> dict | None:
        return next((f for f in self.filings if not f["form_type"].endswith("/A") and f["fiscal_year"] == fiscal_year
                     and f["fiscal_period"] == period), None)

    def before_reports(self, fiscal_year: int, period: str) -> bool:
        """Whether the period ends before every stored report of its kind (it is only a comparative column)."""
        own = [f for f in self.filings if f["is_annual"] == (period == "FY") and f["fiscal_year"] is not None]
        return bool(own) and all((f["fiscal_year"], f["fiscal_period"]) > (fiscal_year, period) for f in own) \
            if period != "FY" else bool(own) and fiscal_year < min(f["fiscal_year"] for f in own)


def table_notes(table: dict, ctx: Context) -> None:
    """Adds notes (and the headline lines the table cannot show) to a table from metrics.table."""
    notes = Notes()
    columns = [(c["fiscal_year"], c["fiscal_period"]) for c in table["columns"]]
    for row in table["rows"]:
        for i, cell in enumerate(row["values"]):
            if cell is None:
                reason = _blank(row["key"], *columns[i], ctx)
                if reason:
                    notes.add("missing", reason, (row["key"], i))
    _unusual(table, columns, ctx, notes)
    table["notes"] = notes.as_json()
    table["omitted"] = _omitted(table, ctx)


# --- blanks ---

def _blank(key: str, fiscal_year: int, period: str, ctx: Context) -> str | None:
    if key in DERIVED:
        return _blank_derived(key, fiscal_year, period, ctx)
    return _blank_metric(key, fiscal_year, period, ctx)


def _blank_metric(key: str, fiscal_year: int, period: str, ctx: Context) -> str | None:
    m, label = ctx.m, ctx.label(key)
    where = fiscal_label(fiscal_year, period)
    if key in metrics.NOT_DERIVABLE and period in ("Q4", "H2"):
        return (f"{period} {label} is not reported on its own: the company gives {period} only within its annual report, "
                "and a per-share amount cannot be worked out as the year less the earlier periods because the number of "
                "shares changes.")
    values = m.values.get(key, {})
    instant = m.types.get(key) == "instant"
    if not instant and period in YTD_PARTS and (fiscal_year, period) not in values:
        whole, part = YTD_PARTS[period]
        gone = next((p for p in (whole, part) if (fiscal_year, p) not in values), None)
        if gone:
            return (f"{period} is worked out as the {PART_NAMES[whole]} figure less the {PART_NAMES[part]} one, and the "
                    f"{PART_NAMES[gone]} {label} for FY{fiscal_year} isn't tagged.")
    report = ctx.report(fiscal_year, "FY" if instant and period in ("Q4", "H2") else period)
    if report:
        condensed = "" if report["is_annual"] else " Interim reports are condensed and often leave out lines the annual report has."
        return f"The {report['form_type']} for {where} doesn't tag these lines.{condensed}"
    if ctx.before_reports(fiscal_year, period):
        return f"{where} comes only from the comparative columns of later reports, which don't repeat every line."
    return None


def _blank_derived(key: str, fiscal_year: int, period: str, ctx: Context) -> str | None:
    m = ctx.m
    if key == "cash_conversion":
        net = m.get("net_income", fiscal_year, period)
        if net is not None and net.value <= 0:
            return "Operating cash flow over net income means nothing when net income is a loss, so it is left out."
    if key == "net_cash" and m.get("cash", fiscal_year, period) and m.get("total_debt", fiscal_year, period):
        return ("Left out: marketable securities are reported in other periods but not this one, and cash less debt "
                "alone would overstate borrowing.")
    missing = []
    for source in DERIVED[key]:
        prior = source.startswith("prior:")
        metric = source.removeprefix("prior:")
        year = fiscal_year - 1 if prior else fiscal_year
        if m.get(metric, year, period) is None and not (metric in ("total_debt", "gross_profit") and _built(metric, year, period, m)):
            missing.append((metric, year))
    if not missing:
        return None
    if any(year < fiscal_year for _, year in missing) and fiscal_year - 1 < min(m.fiscal_years() or [fiscal_year]):
        return "Growth needs the same period a year earlier, which is before the earliest figures stored."
    by_metric: dict[str, list[int]] = {}
    for metric, year in missing:
        by_metric.setdefault(metric, []).append(year)
    names = [f"{ctx.label(metric)} for {' and '.join(fiscal_label(y, period) for y in sorted(years, reverse=True))}"
             for metric, years in by_metric.items()]
    return f"Worked out from {_joined(names)}, which the stored filings don't give."


def _joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _built(metric: str, fiscal_year: int, period: str, m: metrics.Metrics) -> bool:
    """Total debt and gross profit are assembled from parts when no total is tagged."""
    if metric == "gross_profit":
        return m.get("revenue", fiscal_year, period) is not None and m.get("cost_of_revenue", fiscal_year, period) is not None
    return any(m.get(p, fiscal_year, period) for p in ("long_term_debt", "long_term_debt_noncurrent", "debt_current"))


# --- lines the table cannot show ---

def _omitted(table: dict, ctx: Context) -> list[dict]:
    shown = {r["key"] for r in table["rows"]}
    layout = {key: label for key, label, *_ in (metrics.BANK_ROWS if ctx.bank else metrics.ROWS)}
    out = []
    for key in BANK_KEY_ROWS if ctx.bank else KEY_ROWS:
        if key in shown or key not in layout:
            continue
        out.append({"key": key, "label": layout[key], "reason": _absent(key, ctx)})
    if ctx.bank:
        out.append({"key": "bank_layout", "label": "Gross margin, free cash flow and working capital",
                    "reason": "Not shown for a bank: it has no cost of goods, and its cash flows move with lending and "
                              "deposits rather than with its earnings. Credit losses, efficiency and returns take their place."})
    return out


def _absent(key: str, ctx: Context) -> str:
    in_annual = any(fy_values for fy_values in ctx.m.values.get(key, {}) if fy_values[1] == "FY")
    if ctx.kind == "quarterly" and in_annual:
        return "Tagged only in the annual reports; the interim reports leave this line out."
    if ctx.ifrs and key in ("gross_profit", "operating_income"):
        line = "gross profit" if key == "gross_profit" else "operating income"
        return (f"The company reports under IFRS, which does not require {'an' if line[0] in 'aeiou' else 'a'} {line} line, "
                "and its income statement has none, so there is nothing to show.")
    if key == "free_cash_flow":
        gone = [ctx.label(k) for k in ("operating_cash_flow", "capex") if not ctx.m.values.get(k)]
        if gone:
            return f"Needs operating cash flow and capital expenditures, and {' and '.join(gone)} isn't tagged."
    return ("Not found in the company's tagged filings: it either doesn't report this line as a total or tags it under a "
            "name this tool doesn't recognise.")


# --- unusual figures ---

def _unusual(table: dict, columns: list[tuple[int, str]], ctx: Context, notes: Notes) -> None:
    rows = {r["key"]: r for r in table["rows"]}
    credit = rows.get("credit_loss_expense")
    if credit:
        for i, cell in enumerate(credit["values"]):
            if cell and cell["v"] < 0:
                notes.add("unusual", "Negative: a net release of credit loss provisions (more released than newly set "
                                     "aside), which added to profit.", ("credit_loss_expense", i))
    for key in PAYMENT_ROWS:
        if key in rows:
            _payments(rows[key], columns, ctx, notes)
    spikes: dict[int, list[tuple[str, float, float | None, float | None]]] = {}
    for key in SPIKE_ROWS:
        if key not in rows:
            continue
        cells = rows[key]["values"]
        for i, cell in enumerate(cells):
            if cell is None:
                continue
            before = cells[i - 1]["v"] if i > 0 and cells[i - 1] else None
            after = cells[i + 1]["v"] if i + 1 < len(cells) and cells[i + 1] else None
            neighbours = [v for v in (before, after) if v is not None]
            if not neighbours:
                continue
            value = cell["v"]
            # A peak stands above the periods on both sides; growth that lasts (NVIDIA's revenue) does not come back
            # down. A loss between profits is called out too, but not a lower revenue.
            peak = all(n > 0 and value > HIGH * n for n in neighbours)
            loss = key != "revenue" and value < 0 < min(neighbours)
            if peak or loss:
                spikes.setdefault(i, []).append((key, value, before, after))
    for i, found in spikes.items():
        _spike(i, found, columns, rows, ctx, notes)


def _payments(row: dict, columns: list[tuple[int, str]], ctx: Context, notes: Notes) -> None:
    """Dividends and buybacks: periods with little or none, and a payment that slipped into the next period."""
    cells = row["values"]
    values = [c["v"] if c else None for c in cells]
    present = [v for v in values if v is not None]
    if len(present) <= MIN_OTHER_PERIODS:
        return
    typical = median(present)
    if typical <= 0:
        return
    verb = "bought back little or no stock" if row["key"] == "buybacks" else "paid little or no dividends"
    explained: set[int] = set()
    for i, value in enumerate(values):
        if value is None or i in explained or value >= LOW * typical:
            continue
        after = values[i + 1] if i + 1 < len(values) else None
        # Dividends are paid on a schedule, so a low period next to a double one is a date that slipped; buybacks
        # vary from period to period, so no such reading is made for them.
        if (row["key"] == "dividends_paid" and after is not None and after > 1.6 * typical
                and abs(value + after - 2 * typical) <= 0.25 * 2 * typical):
            where, nxt = fiscal_label(*columns[i]), fiscal_label(*columns[i + 1])
            notes.add("unusual", (
                f"{where} is unusually low and {nxt} about double: together they come to {money(value + after, ctx.currency)}, "
                f"about two periods' worth against a typical {money(typical, ctx.currency)}. That points to a payment that "
                f"fell just after {where} closed rather than one that was skipped."), (row["key"], i), (row["key"], i + 1))
            explained |= {i, i + 1}
        elif abs(value) < 0.05 * typical:
            notes.add("unusual", f"Close to zero: the company {verb} in these periods, as tagged.", (row["key"], i))
        else:
            report = ctx.report(*columns[i])
            source = f" in the {report['form_type']}" if report else ""
            unit = "year" if ctx.kind == "annual" else "period"
            notes.add("unusual", f"Unusually low: {money(value, ctx.currency)} for {fiscal_label(*columns[i])} against a "
                                 f"typical {money(typical, ctx.currency)} a {unit}, as tagged{source}.", (row["key"], i))


def _spike(i: int, found: list[tuple[str, float, float | None, float | None]], columns: list[tuple[int, str]], rows: dict,
           ctx: Context, notes: Notes) -> None:
    fiscal_year, period = columns[i]
    where = fiscal_label(fiscal_year, period)
    lead = next((f for f in found if f[0] == "net_income"), found[0])
    _, lead_value, lead_before, lead_after = lead
    neighbours = [v for v in (lead_before, lead_after) if v is not None]
    item = _one_off(fiscal_year, period, lead_value - sum(neighbours) / len(neighbours), ctx)
    if lead_value >= 0 and not item and (lead_before is None or lead_after is None):
        return  # the first or latest period: a lasting step up cannot be told from a one-off without a tagged cause
    unit = "year" if period == "FY" else "period"
    parts = []
    for key, value, before, after in found:
        amount = (lambda v: f"{v:,.2f}") if key == "eps_diluted" else (lambda v: money(v, ctx.currency))
        around = [f"{amount(before)} the {unit} before"] if before is not None else []
        around += [f"{amount(after)} the {unit} after"] if after is not None else []
        parts.append(f"{ctx.label(key)} of {amount(value)}, against {' and '.join(around)}")
    text = f"{where}: " + "; ".join(parts) + "."
    if item:
        text += f" It includes {_item_name(item['label'])} of {money(abs(item['value']), ctx.currency)}, as tagged in the filing."
    elif lead_value < 0:
        text += " The tags don't separate out what caused the loss; the management discussion for this period explains it."
    else:
        text += " The tags don't separate out a one-off item; the management discussion for this period explains it."
    text += " Margins and returns for this period, and growth against it a year later, carry the same effect."
    flagged = {key for key, *_ in found}
    # Revenue carries a bank's non-interest income, and per-share earnings its net income.
    moved = flagged | ({"revenue"} if "noninterest_income" in flagged else set()) | (
        {"eps_diluted"} if "net_income" in flagged else set())
    cells = [(key, i) for key in flagged]
    later = next((j for j, c in enumerate(columns) if c == (fiscal_year + 1, period)), None)
    for key, sources in DERIVED.items():
        if key not in rows or not {s.removeprefix("prior:") for s in sources} & moved:
            continue
        cells.append((key, i))
        if later is not None and any(s.startswith("prior:") for s in sources):
            cells.append((key, later))  # growth a year later is measured against this period
    notes.add("unusual", text, *cells)


# Unusual items that are charges (they lower profit); the rest (bargain purchases, disposals) are gains when positive.
CHARGES = re.compile(r"Impairment|WriteDown|Writedown|Restructuring|Litigation|AcquisitionRelatedCosts")


def _one_off(fiscal_year: int, period: str, excess: float, ctx: Context) -> dict | None:
    """The largest tagged unusual item reported for the period that moves profit the same way as the excess (a gain
    for a peak, a charge for a loss) and accounts for a good part of it."""
    months = {"FY": 12, "H1": 6, "H2": 6}.get(period, 3)
    items = [r for r in ctx.rows if r["category"] == "unusual_item" and r["period_type"] == "duration"
             and r["normalized_unit"] == "currency" and r["fiscal_year"] == fiscal_year and r["fiscal_period"] == period
             and (r["period_months"] or months) == months and r["value"]
             and (bool(CHARGES.search(r["xbrl_concept"])) == (excess < 0))]
    best = max(items, key=lambda r: abs(r["value"]), default=None)
    return best if best and abs(best["value"]) >= EXPLAINS_SHARE * abs(excess) else None


def _item_name(label: str) -> str:
    """'Adjustments for gain loss on disposal of investments in subsidiaries...' -> 'a gain on disposal of ...';
    'Gain recognised in bargain purchase transaction: Credit Suisse Acquisition' -> '... (Credit Suisse Acquisition)'."""
    name = re.sub(r"^Adjustments for ", "", label, flags=re.IGNORECASE)
    name = re.sub(r"\bgains? (?:\(?loss(?:es)?\)?)\b", "gain", name, flags=re.IGNORECASE)
    concept, _, member = name.partition(": ")
    name = f"{concept} ({member})" if member else concept
    name = name[0].lower() + name[1:]
    return f"{'an' if name[0] in 'aeiou' else 'a'} {name}"
