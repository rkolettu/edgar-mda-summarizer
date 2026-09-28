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
        """A metric for a fiscal year and period; discrete quarters and second halves of flows are derived from
        year-to-date values. A balance at the end of a half is the one at the end of its second or fourth quarter."""
        values = self.values.get(metric, {})
        instant = self.types.get(metric) == "instant"
        if instant:
            period = {"Q4": "FY", "H2": "FY", "H1": "Q2"}.get(period, period)
        if (fiscal_year, period) in values:
            return values[(fiscal_year, period)]
        if instant or metric in NOT_DERIVABLE or period not in ("Q2", "Q3", "Q4", "H2"):
            return None
        whole, part = {"Q2": ("H1", "Q1"), "Q3": ("9M", "H1"), "Q4": ("FY", "9M"), "H2": ("FY", "H1")}[period]
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

    def halves(self) -> list[tuple[int, str]]:
        """Half-year periods, for issuers that report interim results twice a year (UBS, HSBC, Shell on Form 6-K)."""
        years = sorted({fy for metric in ANCHORS for (fy, _) in self.values.get(metric, {})})
        return [(fy, h) for fy in years for h in ("H1", "H2") if any(self.get(metric, fy, h) for metric in ANCHORS)]

    # Set from the filings (set_interim): whether interim reports come by quarter or by half year.
    interim: str | None = None

    def set_interim(self, filings: list[dict]) -> None:
        """quarterly when any interim report is a 10-Q or covers three months (a Canadian bank's quarterly 6-K);
        half_yearly when the only interim reports are half-year 6-Ks (UBS, HSBC, Shell)."""
        interim = [f for f in filings if not f["is_annual"]]
        if any(f["form_type"].startswith("10-Q") or f.get("period_months") == 3 or f["fiscal_period"] in ("Q1", "Q3")
               for f in interim):
            self.interim = "quarterly"
        elif interim:
            self.interim = "half_yearly"

    def interim_kind(self) -> str | None:
        if self.interim == "half_yearly" and self.halves():
            return "half_yearly"
        return "quarterly" if self.quarters() else ("half_yearly" if self.halves() else None)

    def is_bank(self) -> bool:
        """A deposit-taking bank: customer deposits of 30% or more of total assets at the latest year end, or net
        interest income of a quarter or more of revenue (an industrial company's net interest is a sliver)."""
        years = self.fiscal_years()
        if not years:
            return False
        fy = years[-1]
        deposits, assets = self.get("deposits", fy, "FY"), self.get("total_assets", fy, "FY")
        if deposits and assets and assets.value and deposits.value / assets.value >= 0.3:
            return True
        nii, revenue = self.get("net_interest_income", fy, "FY"), self.get("revenue", fy, "FY")
        return bool(nii and revenue and revenue.value and nii.value / revenue.value >= 0.25)


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


# Banks: revenue mix, credit losses and efficiency instead of gross margin, free cash flow and working capital.
BANK_ROWS = [
    ("revenue", "Total revenues", "Income statement", "currency"),
    ("revenue_growth", "Revenue growth (YoY)", "Income statement", "ratio"),
    ("net_interest_income", "Net interest income", "Income statement", "currency"),
    ("nii_share", "Net interest income as % of revenue", "Income statement", "ratio"),
    ("fee_income", "Net fee and commission income", "Income statement", "currency"),
    ("noninterest_income", "Non-interest income", "Income statement", "currency"),
    ("credit_loss_expense", "Credit loss expense", "Income statement", "currency"),
    ("operating_expenses", "Operating expenses", "Income statement", "currency"),
    ("cost_income_ratio", "Cost/income ratio", "Income statement", "ratio"),
    ("pretax_income", "Income before taxes", "Income statement", "currency"),
    ("effective_tax_rate", "Effective tax rate", "Income statement", "ratio"),
    ("net_income", "Net income", "Income statement", "currency"),
    ("net_margin", "Net margin", "Income statement", "ratio"),
    ("eps_diluted", "Diluted EPS", "Income statement", "currency_per_share"),
    ("eps_growth", "Diluted EPS growth (YoY)", "Income statement", "ratio"),
    ("buybacks", "Share repurchases", "Capital return", "currency"),
    ("dividends_paid", "Dividends paid", "Capital return", "currency"),
    ("loans", "Loans", "Balance sheet", "currency"),
    ("deposits", "Deposits", "Balance sheet", "currency"),
    ("loans_to_deposits", "Loans / deposits", "Balance sheet", "ratio"),
    ("credit_loss_rate", "Credit loss expense / loans", "Balance sheet", "ratio"),
    ("total_assets", "Total assets", "Balance sheet", "currency"),
    ("equity", "Shareholders' equity", "Balance sheet", "currency"),
    ("roe", "Return on equity", "Balance sheet", "ratio"),
]
# Flows over a quarter or half are annualized for return on equity and the credit loss rate.
ANNUALIZE = {"FY": 1, "H1": 2, "H2": 2, "Q1": 4, "Q2": 4, "Q3": 4, "Q4": 4}
PREVIOUS = {"FY": None, "H1": ("FY", -1), "H2": ("H1", 0), "Q1": ("FY", -1), "Q2": ("Q1", 0), "Q3": ("Q2", 0), "Q4": ("Q3", 0)}


def _average(m: Metrics, metric: str, fiscal_year: int, period: str) -> Value | None:
    """The average of a balance over a period: its opening (the previous period's close) and closing values."""
    closing = m.get(metric, fiscal_year, period)
    previous = PREVIOUS.get(period)
    opening = m.get(metric, fiscal_year - 1, "FY") if period == "FY" else (
        m.get(metric, fiscal_year + previous[1], previous[0]) if previous else None)
    if closing is None:
        return None
    if opening is None:
        return closing
    return Value((closing.value + opening.value) / 2, derived=True)


def bank_column_values(m: Metrics, fiscal_year: int, period: str, kind: str) -> dict[str, Value | None]:
    get = lambda metric, fy=fiscal_year: m.get(metric, fy, period)  # noqa: E731
    revenue, net = get("revenue"), get("net_income")
    scale = ANNUALIZE.get(period, 1)
    equity = _average(m, "equity", fiscal_year, period)
    credit = get("credit_loss_expense")
    return {
        "revenue": revenue,
        "revenue_growth": _growth(revenue, get("revenue", fiscal_year - 1)),
        "net_interest_income": get("net_interest_income"),
        "nii_share": _ratio(get("net_interest_income"), revenue),
        "fee_income": get("fee_income"),
        "noninterest_income": get("noninterest_income"),
        "credit_loss_expense": credit,
        "operating_expenses": get("operating_expenses"),
        "cost_income_ratio": _ratio(get("operating_expenses"), revenue),
        "pretax_income": get("pretax_income"),
        "effective_tax_rate": _ratio(get("income_tax"), get("pretax_income")),
        "net_income": net,
        "net_margin": _ratio(net, revenue),
        "eps_diluted": get("eps_diluted"),
        "eps_growth": _growth(get("eps_diluted"), get("eps_diluted", fiscal_year - 1)),
        "buybacks": get("buybacks"),
        "dividends_paid": get("dividends_paid"),
        "loans": get("loans"),
        "deposits": get("deposits"),
        "loans_to_deposits": _ratio(get("loans"), get("deposits")),
        "credit_loss_rate": Value(credit.value * scale / get("loans").value, derived=True)
        if credit and get("loans") and get("loans").value else None,
        "total_assets": get("total_assets"),
        "equity": get("equity"),
        "roe": Value(net.value * scale / equity.value, derived=True) if net and equity and equity.value else None,
    }


def column_values(m: Metrics, fiscal_year: int, period: str, kind: str) -> dict[str, Value | None]:
    """Every row's value for one column. Growth compares with the same period a year earlier."""
    get = lambda metric, fy=fiscal_year: m.get(metric, fy, period)  # noqa: E731
    days = DAYS[kind]
    revenue, cost = get("revenue"), get("cost_of_revenue")
    gross = get("gross_profit") or _diff(revenue, cost)
    capex = get("capex")
    ocf = get("operating_cash_flow")
    # Filers differ on whether investing cash outflows are tagged as positive payments or negative cash flows.
    # FCF always deducts the cash spent rather than adding a negative tagged value.
    fcf = Value(ocf.value - abs(capex.value), derived=True) if ocf and capex else None
    # Prefer the separately reported current and noncurrent components.  LongTermDebt is an aggregate including
    # current maturities, so use it only when the components are unavailable and add commercial paper only then.
    current, noncurrent = get("debt_current"), get("long_term_debt_noncurrent")
    if current is not None and noncurrent is not None:
        total_debt = _sum(current, noncurrent)
    elif get("long_term_debt") is not None:
        total_debt = _sum(get("long_term_debt"), get("commercial_paper"))
    else:
        total_debt = _sum(noncurrent, current)
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
        # Both operands are fetched from this exact fiscal column; a missing component leaves the value blank rather
        # than silently carrying cash or debt from another balance-sheet date.
        "net_cash": _diff(get("cash"), total_debt),
        "accounts_receivable": get("accounts_receivable"),
        "receivable_days": _days(get("accounts_receivable"), revenue, days),
        "inventory": get("inventory"),
        "inventory_days": _days(get("inventory"), cost or (_diff(revenue, gross) if gross else None), days),
        "accounts_payable": get("accounts_payable"),
        "contract_liabilities": get("contract_liabilities"),
        "total_assets": get("total_assets"),
        "equity": get("equity"),
    }


def table(m: Metrics, kind: str, bank: bool = False) -> dict:
    """kind is annual or quarterly; the quarterly table holds half years for issuers that report by half year."""
    if kind == "annual":
        columns = [(fy, "FY") for fy in m.fiscal_years()[-ANNUAL_COLUMNS:]]
    elif m.interim_kind() == "half_yearly":
        columns = m.halves()[-QUARTER_COLUMNS:]
    else:
        columns = m.quarters()[-QUARTER_COLUMNS:]
    compute, layout = (bank_column_values, BANK_ROWS) if bank else (column_values, ROWS)
    values = [compute(m, fy, period, kind) for fy, period in columns]
    rows = []
    for key, label, group, unit in layout:
        cells = [v[key].as_json() if v[key] is not None else None for v in values]
        if any(cells):
            rows.append({"key": key, "label": label, "group": group, "unit": unit, "values": cells})
    return {"columns": [{"fiscal_year": fy, "fiscal_period": period} for fy, period in columns], "rows": rows}


OTHER_ITEMS_SHARE = 0.005


def bank_bridge(m: Metrics, fiscal_year: int, period: str) -> dict | None:
    """Revenue to net income for a bank: credit losses and operating expenses, then tax."""
    get = lambda metric: m.get(metric, fiscal_year, period)  # noqa: E731
    revenue, net = get("revenue"), get("net_income")
    if revenue is None or net is None:
        return None
    values = {k: get(k) for k in ("net_interest_income", "fee_income", "noninterest_income", "credit_loss_expense",
                                  "operating_expenses", "pretax_income", "income_tax")}
    # What the statement shows between expenses and pretax income beyond credit losses: insurance claims (TD, RBC),
    # the share of associates' profit, other items. Shown when it is more than rounding.
    other = None
    if values["pretax_income"] and values["operating_expenses"]:
        residual = values["pretax_income"].value - (revenue.value - values["operating_expenses"].value
                                                    - (values["credit_loss_expense"].value if values["credit_loss_expense"] else 0))
        other = residual if abs(residual) > OTHER_ITEMS_SHARE * abs(revenue.value) else None
    return {
        "kind": "bank", "fiscal_year": fiscal_year, "fiscal_period": period, "revenue": revenue.value,
        **{k: v.value if v else None for k, v in values.items()}, "other_items": other, "net_income": net.value,
        "cost_income_ratio": values["operating_expenses"].value / revenue.value
        if values["operating_expenses"] and revenue.value else None,
    }


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
