"""Financial series and ratios for the research tabs, computed in code from stored facts (never by a model).

Values are keyed by fiscal year and period ('FY', 'Q1'..'Q4', 'H1', '9M'). When filings disagree about a period
(a restatement), the latest filing wins. Cash flow statements in interim filings report year-to-date amounts only,
so discrete quarters are derived (Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M) and flagged as derived.
"""

from __future__ import annotations

from dataclasses import dataclass

ANNUAL_COLUMNS = 5
QUARTER_COLUMNS = 8
DAYS = {"annual": 365.0, "quarterly": 91.25}
# Per-share amounts cannot be differenced across periods (share counts change).
NOT_DERIVABLE = {"eps_diluted", "eps_basic"}
ANCHORS = ("revenue", "net_income")


@dataclass
class Value:
    value: float
    fact_id: int | None = None
    derived: bool = False

    def as_json(self) -> dict:
        out = {"v": self.value}
        if self.fact_id is not None:
            out["fact_id"] = self.fact_id
        if self.derived:
            out["derived"] = True
        return out


class Metrics:
    """Stored headline values for one company, addressable by fiscal period."""

    def __init__(self, rows: list[dict]):
        best: dict[tuple, dict] = {}
        for row in rows:
            if not row["canonical_metric"] or row["fiscal_year"] is None or row["fiscal_period"] is None:
                continue
            slot = (row["canonical_metric"], row["period_start"], row["period_end"])
            current = best.get(slot)
            if current is None or (row["filing_date"], row["fact_id"]) > (current["filing_date"], current["fact_id"]):
                best[slot] = row
        self.values: dict[str, dict[tuple[int, str], Value]] = {}
        self.types: dict[str, str] = {}
        for (metric, _, _), row in best.items():
            self.values.setdefault(metric, {})[(row["fiscal_year"], row["fiscal_period"])] = Value(row["value"], row["fact_id"])
            self.types[metric] = row["period_type"]

    def get(self, metric: str, fiscal_year: int, period: str) -> Value | None:
        """A metric for a fiscal year and period; discrete quarters of flows are derived from year-to-date values."""
        values = self.values.get(metric, {})
        instant = self.types.get(metric) == "instant"
        if instant and period == "Q4":
            period = "FY"
        if (fiscal_year, period) in values:
            return values[(fiscal_year, period)]
        if instant or metric in NOT_DERIVABLE or period not in ("Q2", "Q3", "Q4"):
            return None
        whole, part = {"Q2": ("H1", "Q1"), "Q3": ("9M", "H1"), "Q4": ("FY", "9M")}[period]
        total, earlier = values.get((fiscal_year, whole)), values.get((fiscal_year, part))
        if total is None or earlier is None:
            return None
        return Value(total.value - earlier.value, derived=True)

    def fiscal_years(self) -> list[int]:
        return sorted({fy for metric in ANCHORS for (fy, period) in self.values.get(metric, {}) if period == "FY"})

    def quarters(self) -> list[tuple[int, str]]:
        years = sorted({fy for metric in ANCHORS for (fy, _) in self.values.get(metric, {})})
        found = [
            (fy, f"Q{n}") for fy in years for n in range(1, 5)
            if any(self.get(metric, fy, f"Q{n}") for metric in ANCHORS)
        ]
        return found


def _ratio(a: Value | None, b: Value | None) -> Value | None:
    if a is None or b is None or not b.value:
        return None
    return Value(a.value / b.value, derived=True)


def _growth(current: Value | None, prior: Value | None) -> Value | None:
    if current is None or prior is None or not prior.value:
        return None
    return Value((current.value - prior.value) / abs(prior.value), derived=True)


def _sum(*values: Value | None) -> Value | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return Value(sum(v.value for v in present), derived=len(present) > 1 or any(v.derived for v in present))


def _diff(a: Value | None, b: Value | None) -> Value | None:
    if a is None or b is None:
        return None
    return Value(a.value - b.value, derived=True)


def _days(balance: Value | None, flow: Value | None, days: float) -> Value | None:
    ratio = _ratio(balance, flow)
    return Value(ratio.value * days, derived=True) if ratio else None


# (key, label, group, unit); unit is currency | currency_per_share | ratio | days
ROWS = [
    ("revenue", "Revenue", "Income statement", "currency"),
    ("revenue_growth", "Revenue growth (YoY)", "Income statement", "ratio"),
    ("gross_profit", "Gross profit", "Income statement", "currency"),
    ("gross_margin", "Gross margin", "Income statement", "ratio"),
    ("rnd", "Research and development", "Income statement", "currency"),
    ("rnd_intensity", "R&D as % of revenue", "Income statement", "ratio"),
    ("operating_income", "Operating income", "Income statement", "currency"),
    ("operating_margin", "Operating margin", "Income statement", "ratio"),
    ("nonoperating_income", "Non-operating income (expense)", "Income statement", "currency"),
    ("pretax_income", "Income before taxes", "Income statement", "currency"),
    ("effective_tax_rate", "Effective tax rate", "Income statement", "ratio"),
    ("net_income", "Net income", "Income statement", "currency"),
    ("net_margin", "Net margin", "Income statement", "ratio"),
    ("eps_diluted", "Diluted EPS", "Income statement", "currency_per_share"),
    ("eps_growth", "Diluted EPS growth (YoY)", "Income statement", "ratio"),
    ("operating_cash_flow", "Operating cash flow", "Cash flow", "currency"),
    ("capex", "Capital expenditures", "Cash flow", "currency"),
    ("capex_intensity", "Capex as % of revenue", "Cash flow", "ratio"),
    ("free_cash_flow", "Free cash flow", "Cash flow", "currency"),
    ("fcf_margin", "Free cash flow margin", "Cash flow", "ratio"),
    ("cash_conversion", "Operating cash flow / net income", "Cash flow", "ratio"),
    ("buybacks", "Share repurchases", "Cash flow", "currency"),
    ("dividends_paid", "Dividends paid", "Cash flow", "currency"),
    ("cash", "Cash and equivalents", "Balance sheet", "currency"),
    ("marketable_securities", "Marketable securities", "Balance sheet", "currency"),
    ("total_debt", "Total debt", "Balance sheet", "currency"),
    ("net_cash", "Net cash (debt)", "Balance sheet", "currency"),
    ("accounts_receivable", "Accounts receivable", "Balance sheet", "currency"),
    ("receivable_days", "Receivable days", "Balance sheet", "days"),
    ("inventory", "Inventory", "Balance sheet", "currency"),
    ("inventory_days", "Inventory days", "Balance sheet", "days"),
    ("accounts_payable", "Accounts payable", "Balance sheet", "currency"),
    ("contract_liabilities", "Deferred revenue", "Balance sheet", "currency"),
    ("total_assets", "Total assets", "Balance sheet", "currency"),
    ("equity", "Shareholders' equity", "Balance sheet", "currency"),
]


def column_values(m: Metrics, fiscal_year: int, period: str, kind: str) -> dict[str, Value | None]:
    """Every row's value for one column. Growth compares with the same period a year earlier."""
    get = lambda metric, fy=fiscal_year: m.get(metric, fy, period)  # noqa: E731
    days = DAYS[kind]
    revenue, cost = get("revenue"), get("cost_of_revenue")
    gross = get("gross_profit") or _diff(revenue, cost)
    capex = get("capex")
    ocf = get("operating_cash_flow")
    fcf = _diff(ocf, capex) if ocf and capex else None
    # LongTermDebt includes current maturities but not commercial paper; a DebtCurrent fallback may already include
    # commercial paper, so it is added only to the LongTermDebt total.
    if get("long_term_debt") is not None:
        total_debt = _sum(get("long_term_debt"), get("commercial_paper"))
    else:
        total_debt = _sum(get("long_term_debt_noncurrent"), get("debt_current"))
    cash_like = _sum(get("cash"), get("marketable_securities"))
    return {
        "revenue": revenue,
        "revenue_growth": _growth(revenue, get("revenue", fiscal_year - 1)),
        "gross_profit": gross,
        "gross_margin": _ratio(gross, revenue),
        "rnd": get("rnd"),
        "rnd_intensity": _ratio(get("rnd"), revenue),
        "operating_income": get("operating_income"),
        "operating_margin": _ratio(get("operating_income"), revenue),
        "nonoperating_income": get("nonoperating_income"),
        "pretax_income": get("pretax_income"),
        "effective_tax_rate": _ratio(get("income_tax"), get("pretax_income")),
        "net_income": get("net_income"),
        "net_margin": _ratio(get("net_income"), revenue),
        "eps_diluted": get("eps_diluted"),
        "eps_growth": _growth(get("eps_diluted"), get("eps_diluted", fiscal_year - 1)),
        "operating_cash_flow": ocf,
        "capex": capex,
        "capex_intensity": _ratio(capex, revenue),
        "free_cash_flow": fcf,
        "fcf_margin": _ratio(fcf, revenue),
        "cash_conversion": _ratio(ocf, get("net_income")) if get("net_income") and get("net_income").value > 0 else None,
        "buybacks": get("buybacks"),
        "dividends_paid": get("dividends_paid"),
        "cash": get("cash"),
        "marketable_securities": get("marketable_securities"),
        "total_debt": total_debt,
        # A company that reports marketable securities in other periods but not this one would look indebted.
        "net_cash": _diff(cash_like, total_debt)
        if cash_like and total_debt and (get("marketable_securities") or not m.values.get("marketable_securities"))
        else None,
        "accounts_receivable": get("accounts_receivable"),
        "receivable_days": _days(get("accounts_receivable"), revenue, days),
        "inventory": get("inventory"),
        "inventory_days": _days(get("inventory"), cost or (_diff(revenue, gross) if gross else None), days),
        "accounts_payable": get("accounts_payable"),
        "contract_liabilities": get("contract_liabilities"),
        "total_assets": get("total_assets"),
        "equity": get("equity"),
    }


def table(m: Metrics, kind: str) -> dict:
    if kind == "annual":
        columns = [(fy, "FY") for fy in m.fiscal_years()[-ANNUAL_COLUMNS:]]
    else:
        columns = m.quarters()[-QUARTER_COLUMNS:]
    values = [column_values(m, fy, period, kind) for fy, period in columns]
    rows = []
    for key, label, group, unit in ROWS:
        cells = [v[key].as_json() if v[key] is not None else None for v in values]
        if any(cells):
            rows.append({"key": key, "label": label, "group": group, "unit": unit, "values": cells})
    return {"columns": [{"fiscal_year": fy, "fiscal_period": period} for fy, period in columns], "rows": rows}


def earnings_bridge(m: Metrics, fiscal_year: int, period: str) -> dict | None:
    """Operating income to net income for one period, the frame for the earnings quality tab."""
    get = lambda metric: m.get(metric, fiscal_year, period)  # noqa: E731
    operating, pretax, tax, net = get("operating_income"), get("pretax_income"), get("income_tax"), get("net_income")
    if operating is None or net is None:
        return None
    non_operating = get("nonoperating_income") or (_diff(pretax, operating) if pretax else None)
    return {
        "fiscal_year": fiscal_year,
        "fiscal_period": period,
        "operating_income": operating.value,
        "non_operating": non_operating.value if non_operating else None,
        "pretax_income": pretax.value if pretax else None,
        "income_tax": tax.value if tax else None,
        "net_income": net.value,
        "non_operating_share_of_pretax": (non_operating.value / pretax.value) if non_operating and pretax and pretax.value else None,
    }
