from __future__ import annotations

from datetime import date

ANNUAL_FORMS = {"10-K", "10-K/A"}
ANNUAL_DAYS = (350, 380)
YEARS = 5

# Tags are tried in order per period; companies switch tags over time (e.g. ASC 606 moved many to
# RevenueFromContractWithCustomer...), so each period takes the first tag that reports it.
DURATION_CONCEPTS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "RevenuesNetOfInterestExpense",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements",
    ],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "rnd": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "acquisitions": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "debt_repayment": ["RepaymentsOfLongTermDebt", "RepaymentsOfDebt"],
}
PER_SHARE_CONCEPTS = {"eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]}
INSTANT_CONCEPTS = {
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
}

CAPITAL_DEPLOYMENT = [
    ("buybacks", "Share Buybacks"),
    ("dividends", "Dividends"),
    ("capex", "Capex"),
    ("acquisitions", "Acquisitions"),
    ("debt_repayment", "Debt Repayment"),
]


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _latest_filed(entries, keep) -> dict[str, float]:
    best: dict[str, dict] = {}
    for e in entries:
        if e.get("form") not in ANNUAL_FORMS or not keep(e):
            continue
        prev = best.get(e["end"])
        if prev is None or e.get("filed", "") > prev.get("filed", ""):
            best[e["end"]] = e
    return {end: e["val"] for end, e in best.items()}


def _series(facts: dict, tags: list[str], unit: str, instant: bool) -> dict[str, float]:
    if instant:
        keep = lambda e: "start" not in e  # noqa: E731
    else:
        keep = lambda e: "start" in e and ANNUAL_DAYS[0] <= _days(e["start"], e["end"]) <= ANNUAL_DAYS[1]  # noqa: E731
    merged: dict[str, float] = {}
    for tag in tags:
        entries = facts.get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit, [])
        for end, val in _latest_filed(entries, keep).items():
            merged.setdefault(end, val)
    return merged


def _ratio(num, den):
    if num is None or not den:
        return None
    return num / den


def _growth(curr, prev):
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev)


def build_financials(companyfacts: dict, report_date: str) -> dict | None:
    facts = companyfacts.get("facts", {})
    series = {k: _series(facts, tags, "USD", False) for k, tags in DURATION_CONCEPTS.items()}
    series |= {k: _series(facts, tags, "USD/shares", False) for k, tags in PER_SHARE_CONCEPTS.items()}
    series |= {k: _series(facts, tags, "USD", True) for k, tags in INSTANT_CONCEPTS.items()}

    anchor = series["revenue"] or series["net_income"]
    cutoff = date.fromisoformat(report_date)
    ends = sorted(end for end in anchor if (date.fromisoformat(end) - cutoff).days <= 10)[-YEARS:]
    if not ends:
        return None

    years = []
    for end in ends:
        row = {"period_end": end, **{k: s.get(end) for k, s in series.items()}}
        ocf, capex = row["operating_cash_flow"], row["capex"]
        row["free_cash_flow"] = ocf - capex if ocf is not None and capex is not None else None
        years.append(row)

    latest = years[-1]
    prior = years[-2] if len(years) > 1 and ANNUAL_DAYS[0] <= _days(years[-2]["period_end"], latest["period_end"]) <= ANNUAL_DAYS[1] else None
    returns = [latest[k] for k in ("buybacks", "dividends") if latest[k] is not None]

    kpis = {
        "period_end": latest["period_end"],
        "revenue": latest["revenue"],
        "revenue_growth": _growth(latest["revenue"], prior and prior["revenue"]),
        "gross_margin": _ratio(latest["gross_profit"], latest["revenue"]),
        "operating_margin": _ratio(latest["operating_income"], latest["revenue"]),
        "net_margin": _ratio(latest["net_income"], latest["revenue"]),
        "net_income": latest["net_income"],
        "free_cash_flow": latest["free_cash_flow"],
        "fcf_margin": _ratio(latest["free_cash_flow"], latest["revenue"]),
        "eps_diluted": latest["eps_diluted"],
        "eps_growth": _growth(latest["eps_diluted"], prior and prior["eps_diluted"]),
        "shareholder_returns": sum(returns) if returns else None,
        "cash": latest["cash"],
        "long_term_debt": latest["long_term_debt"],
    }

    capital_deployment = [
        {"name": label, "value": latest[key]}
        for key, label in CAPITAL_DEPLOYMENT
        if latest[key] is not None and latest[key] > 0
    ]

    return {"years": years, "kpis": kpis, "capital_deployment": capital_deployment}


QUARTER_FORMS = {"10-Q", "10-Q/A"}
QUARTER_DAYS = (80, 100)
SAME_QUARTER_LAST_YEAR_DAYS = (357, 371)
QUARTER_CONCEPTS = {
    "revenue": (DURATION_CONCEPTS["revenue"], "USD"),
    "net_income": (DURATION_CONCEPTS["net_income"], "USD"),
    "eps_diluted": (PER_SHARE_CONCEPTS["eps_diluted"], "USD/shares"),
}


def _quarter_entries(facts: dict, tags: list[str], unit: str) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for tag in tags:
        best: dict[str, dict] = {}
        for e in facts.get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit, []):
            if e.get("form") not in QUARTER_FORMS or "start" not in e:
                continue
            if not QUARTER_DAYS[0] <= _days(e["start"], e["end"]) <= QUARTER_DAYS[1]:
                continue
            prev = best.get(e["end"])
            if prev is None or e.get("filed", "") > prev.get("filed", ""):
                best[e["end"]] = e
        for end, e in best.items():
            merged.setdefault(end, e)
    return merged


def build_quarter(companyfacts: dict, period_end: str) -> dict | None:
    facts = companyfacts.get("facts", {})
    result: dict = {"period_end": period_end, "fiscal_period": None, "fiscal_year": None}
    found = False
    for key, (tags, unit) in QUARTER_CONCEPTS.items():
        entries = _quarter_entries(facts, tags, unit)
        current = entries.get(period_end)
        prior = next(
            (e for end, e in entries.items() if SAME_QUARTER_LAST_YEAR_DAYS[0] <= _days(end, period_end) <= SAME_QUARTER_LAST_YEAR_DAYS[1]),
            None,
        )
        result[key] = current["val"] if current else None
        result[f"{key}_prior"] = prior["val"] if prior else None
        result[f"{key}_growth"] = _growth(result[key], result[f"{key}_prior"])
        if current:
            found = True
            result["fiscal_period"] = result["fiscal_period"] or current.get("fp")
            result["fiscal_year"] = result["fiscal_year"] or current.get("fy")
    return result if found else None


REFERENCE_FIELDS = [
    ("revenue", "Revenue"),
    ("gross_profit", "Gross profit"),
    ("operating_income", "Operating income"),
    ("net_income", "Net income"),
    ("operating_cash_flow", "Operating cash flow"),
    ("capex", "Capital expenditures"),
    ("free_cash_flow", "Free cash flow (operating cash flow minus capital expenditures)"),
    ("buybacks", "Share repurchases (cash paid)"),
    ("dividends", "Dividends paid"),
    ("rnd", "R&D expense"),
    ("acquisitions", "Acquisitions, net of cash acquired"),
    ("debt_repayment", "Debt repayments"),
    ("eps_diluted", "Diluted EPS"),
    ("cash", "Cash and cash equivalents at period end"),
    ("long_term_debt", "Long-term debt at period end"),
]


def format_usd(value: float) -> str:
    sign, v = ("-" if value < 0 else ""), abs(value)
    if v >= 1e12:
        return f"{sign}${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.0f}M"
    return f"{sign}${v:,.2f}"


def _pct(fraction: float) -> str:
    return f"{fraction * 100:+.1f}%" if fraction is not None else ""


def reference_block(fin: dict | None, quarter: dict | None = None, years: int = 2) -> str | None:
    """Authoritative XBRL figures for the prompt, rounded the same way the model is asked to write them."""
    lines = []
    if fin:
        for row in fin["years"][-years:]:
            parts = [f"{label} {format_usd(row[key])}" for key, label in REFERENCE_FIELDS if row.get(key)]
            lines.append(f"- Fiscal year ended {row['period_end']}: " + "; ".join(parts))
        k = fin["kpis"]
        derived = [
            (label, k[key], signed)
            for key, label, signed in (
                ("revenue_growth", "revenue growth year over year", True),
                ("gross_margin", "gross margin", False),
                ("operating_margin", "operating margin", False),
                ("net_margin", "net margin", False),
                ("fcf_margin", "free cash flow margin", False),
                ("eps_growth", "diluted EPS growth year over year", True),
            )
            if k.get(key) is not None
        ]
        if derived:
            lines.append(
                f"- Derived for fiscal year ended {k['period_end']}: "
                + "; ".join(f"{label} {_pct(v) if signed else f'{v * 100:.1f}%'}" for label, v, signed in derived)
            )
    if quarter:
        label = f" ({quarter['fiscal_period']} FY{quarter['fiscal_year']})" if quarter.get("fiscal_period") else ""
        parts = []
        for key, name in (("revenue", "Revenue"), ("net_income", "Net income"), ("eps_diluted", "Diluted EPS")):
            if quarter.get(key) is not None:
                growth = quarter.get(f"{key}_growth")
                suffix = f" ({_pct(growth)} vs. the same quarter last year)" if growth is not None else ""
                parts.append(f"{name} {format_usd(quarter[key])}{suffix}")
        if parts:
            lines.append(f"- Quarter ended {quarter['period_end']}{label}: " + "; ".join(parts))
    if not lines:
        return None
    return "REFERENCE FIGURES (from the company's audited SEC XBRL data; authoritative):\n" + "\n".join(lines)
