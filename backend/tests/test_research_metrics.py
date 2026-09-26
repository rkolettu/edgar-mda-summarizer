from datetime import date

import pytest

from research import metrics

_ids = iter(range(1, 10_000))


def fact(metric, fy, fp, value, filed="2026-08-26", instant=False, start=None, end=None):
    return {
        "canonical_metric": metric, "fiscal_year": fy, "fiscal_period": fp, "value": value,
        "period_type": "instant" if instant else "duration", "period_start": start or date(fy, 1, 1),
        "period_end": end or date(fy, 12, 31), "filing_date": date.fromisoformat(filed), "fact_id": next(_ids),
    }


def spans(metric, fy, **values):
    """Distinct spans per fiscal period label so each is its own period."""
    ends = {"Q1": 3, "Q2": 6, "Q3": 9, "H1": 6, "9M": 9, "FY": 12}
    starts = {"Q1": 1, "Q2": 4, "Q3": 7, "H1": 1, "9M": 1, "FY": 1}
    return [fact(metric, fy, fp, v, start=date(fy, starts[fp], 1), end=date(fy, ends[fp], 28)) for fp, v in values.items()]


def test_quarters_are_derived_from_year_to_date_values():
    m = metrics.Metrics(
        spans("operating_cash_flow", 2026, Q1=50, H1=74, **{"9M": 110}, FY=150)
        + spans("revenue", 2026, Q1=80, Q2=96, Q3=100, FY=340)
    )
    assert m.get("revenue", 2026, "Q2").value == 96 and not m.get("revenue", 2026, "Q2").derived
    assert (m.get("operating_cash_flow", 2026, "Q2").value, m.get("operating_cash_flow", 2026, "Q2").derived) == (24, True)
    assert m.get("operating_cash_flow", 2026, "Q3").value == 36
    assert m.get("operating_cash_flow", 2026, "Q4").value == 40
    # Q4 revenue needs nine-month revenue, which this company did not report as a span of its own.
    assert m.get("revenue", 2026, "Q4") is None


def test_per_share_values_are_never_differenced_and_instants_use_the_year_end_for_q4():
    m = metrics.Metrics(
        spans("eps_diluted", 2026, **{"9M": 3.0}, FY=4.1)
        + [fact("cash", 2026, "FY", 10, instant=True, start=None, end=date(2026, 12, 31))]
    )
    assert m.get("eps_diluted", 2026, "Q4") is None
    assert m.get("cash", 2026, "Q4").value == 10


def test_restated_values_from_the_latest_filing_win():
    original = fact("revenue", 2025, "FY", 100, filed="2026-02-01", start=date(2025, 1, 1), end=date(2025, 12, 31))
    restated = fact("revenue", 2025, "FY", 98, filed="2027-02-01", start=date(2025, 1, 1), end=date(2025, 12, 31))
    assert metrics.Metrics([restated, original]).get("revenue", 2025, "FY").value == 98


def test_column_values_compute_margins_growth_cash_flow_and_debt():
    rows = []
    for fy, revenue, cost, op, net, ocf, capex in ((2025, 130, 32, 81, 73, 64, 3), (2026, 216, 62, 130, 120, 103, 6)):
        rows += spans("revenue", fy, FY=revenue) + spans("cost_of_revenue", fy, FY=cost) + spans("operating_income", fy, FY=op)
        rows += spans("net_income", fy, FY=net) + spans("operating_cash_flow", fy, FY=ocf) + spans("capex", fy, FY=capex)
    for metric, value in (("long_term_debt", 8.5), ("commercial_paper", 1.0), ("cash", 10.0), ("marketable_securities", 50.0),
                          ("accounts_receivable", 38.0), ("inventory", 21.0)):
        rows.append(fact(metric, 2026, "FY", value, instant=True, start=None, end=date(2026, 12, 31)))
    m = metrics.Metrics(rows)
    v = metrics.column_values(m, 2026, "FY", "annual")
    assert v["gross_profit"].value == 154 and v["gross_profit"].derived
    assert v["gross_margin"].value == pytest.approx(154 / 216)
    assert v["operating_margin"].value == pytest.approx(130 / 216)
    assert v["revenue_growth"].value == pytest.approx(216 / 130 - 1)
    assert v["free_cash_flow"].value == 97 and v["fcf_margin"].value == pytest.approx(97 / 216)
    assert v["cash_conversion"].value == pytest.approx(103 / 120)
    assert v["total_debt"].value == pytest.approx(9.5)
    assert v["net_cash"].value == pytest.approx(60 - 9.5)
    assert v["receivable_days"].value == pytest.approx(38 / 216 * 365)
    assert v["inventory_days"].value == pytest.approx(21 / 62 * 365)


def test_total_debt_without_a_long_term_total_uses_noncurrent_plus_current_only():
    rows = [fact(k, 2026, "FY", v, instant=True, start=None, end=date(2026, 12, 31))
            for k, v in (("long_term_debt_noncurrent", 30.0), ("debt_current", 3.0), ("commercial_paper", 1.0))]
    m = metrics.Metrics(rows)
    # DebtCurrent may already include commercial paper, so it is not added again.
    assert metrics.column_values(m, 2026, "FY", "annual")["total_debt"].value == 33.0


def test_tables_keep_recent_columns_and_drop_empty_rows():
    rows = []
    for fy in range(2019, 2027):
        rows += spans("revenue", fy, FY=100 + fy, Q1=20, Q2=25)
    table = metrics.table(metrics.Metrics(rows), "annual")
    assert [c["fiscal_year"] for c in table["columns"]] == [2022, 2023, 2024, 2025, 2026]
    assert {r["key"] for r in table["rows"]} == {"revenue", "revenue_growth"}
    quarterly = metrics.table(metrics.Metrics(rows), "quarterly")
    assert len(quarterly["columns"]) == 8 and quarterly["columns"][-1] == {"fiscal_year": 2026, "fiscal_period": "Q2"}


def test_earnings_bridge_shows_non_operating_share():
    rows = spans("operating_income", 2027, Q2=63.7) + spans("pretax_income", 2027, Q2=71.5) + spans("net_income", 2027, Q2=59.7)
    rows += spans("nonoperating_income", 2027, Q2=7.8) + spans("income_tax", 2027, Q2=11.8)
    bridge = metrics.earnings_bridge(metrics.Metrics(rows), 2027, "Q2")
    assert bridge["non_operating"] == 7.8 and bridge["non_operating_share_of_pretax"] == pytest.approx(7.8 / 71.5)


def test_net_cash_is_left_blank_when_a_reported_component_is_missing():
    rows = [fact(k, fy, "FY", v, instant=True, start=None, end=date(fy, 12, 31))
            for fy, k, v in ((2025, "cash", 8.6), (2025, "marketable_securities", 34.6), (2025, "long_term_debt", 8.5),
                             (2026, "cash", 22.4), (2026, "long_term_debt", 33.4))]
    m = metrics.Metrics(rows)
    assert metrics.column_values(m, 2025, "FY", "annual")["net_cash"].value == pytest.approx(34.7)
    # 2026 lacks marketable securities the company reported before: no misleading net debt.
    assert metrics.column_values(m, 2026, "FY", "annual")["net_cash"] is None
