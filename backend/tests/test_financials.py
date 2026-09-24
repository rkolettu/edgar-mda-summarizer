import pytest

import financials
from tests.xbrl_fixture import B, apple_companyfacts, bank_companyfacts


@pytest.fixture
def apple():
    return financials.build_financials(apple_companyfacts(), "2025-09-27")


def test_takes_last_five_fiscal_years_in_order(apple):
    assert [y["period_end"] for y in apple["years"]] == [
        "2021-09-25", "2022-09-24", "2023-09-30", "2024-09-28", "2025-09-27",
    ]


def test_ignores_quarterly_durations(apple):
    assert apple["years"][-1]["revenue"] == pytest.approx(416.2 * B)


def test_latest_filed_value_wins_for_restatements(apple):
    assert apple["years"][-2]["revenue"] == pytest.approx(391.035 * B)


def test_falls_back_to_older_revenue_tag():
    result = financials.build_financials(apple_companyfacts(), "2020-09-26")
    assert [y["period_end"] for y in result["years"]] == ["2019-09-28", "2020-09-26"]
    assert result["years"][-1]["revenue"] == pytest.approx(274.5 * B)


def test_excludes_periods_after_the_filing(apple):
    result = financials.build_financials(apple_companyfacts(), "2024-09-28")
    assert result["years"][-1]["period_end"] == "2024-09-28"


def test_kpis(apple):
    k = apple["kpis"]
    assert k["revenue"] == pytest.approx(416.2 * B)
    assert k["revenue_growth"] == pytest.approx(416.2 / 391.035 - 1)
    assert k["gross_margin"] == pytest.approx(195.2 / 416.2)
    assert k["operating_margin"] == pytest.approx(133.1 / 416.2)
    assert k["free_cash_flow"] == pytest.approx((111.5 - 12.7) * B)
    assert k["eps_diluted"] == pytest.approx(7.46)
    assert k["eps_growth"] == pytest.approx(7.46 / 6.08 - 1)
    assert k["shareholder_returns"] == pytest.approx((90.7 + 15.4) * B)
    assert k["cash"] == pytest.approx(35.9 * B)


def test_capital_deployment_skips_missing_and_zero(apple):
    names = [d["name"] for d in apple["capital_deployment"]]
    assert names == ["Share Buybacks", "Dividends", "Capex"]


def test_missing_values_are_none_not_errors(apple):
    first = apple["years"][0]
    assert first["buybacks"] is None and first["cash"] is None


def test_bank_without_revenue_uses_net_income_years():
    result = financials.build_financials(bank_companyfacts(), "2024-12-31")
    assert [y["period_end"] for y in result["years"]] == ["2023-12-31", "2024-12-31"]
    assert result["kpis"]["revenue"] is None
    assert result["kpis"]["operating_margin"] is None


def test_no_facts_returns_none():
    assert financials.build_financials({"facts": {}}, "2025-09-27") is None
