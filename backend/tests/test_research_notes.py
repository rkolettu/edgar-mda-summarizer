"""Notes that say why a figure in the financial tables is blank or looks unusual."""

from datetime import date

from research import metrics, notes
from tests.test_research_metrics import fact, spans


def annual(key, **by_year):
    return [r for fy, v in by_year.items() for r in spans(key, int(fy[1:]), FY=v)]


def filing(fy, fp="FY", form="20-F"):
    return {"form_type": form, "fiscal_year": fy, "fiscal_period": fp, "is_annual": fp == "FY", "period_end": date(fy, 12, 31)}


def noted(rows, kind="annual", bank=False, filings=(), facts=(), ifrs=False):
    m = metrics.Metrics(rows)
    table = metrics.table(m, kind, bank)
    notes.table_notes(table, notes.Context(m, kind, bank, list(filings), list(facts), "USD", ifrs))
    return table


def cells_of(table, text):
    return [n["cells"] for n in table["notes"] if text in n["text"]]


def unusual_item(fy, value, label, concept, fp="FY", months=12):
    return {"category": "unusual_item", "period_type": "duration", "normalized_unit": "currency", "fiscal_year": fy,
            "fiscal_period": fp, "period_months": months, "value": value, "label": label, "xbrl_concept": concept}


def test_a_one_off_gain_is_named_for_the_year_it_lifts():
    """UBS's FY2023 profit included the gain on buying Credit Suisse below its book value."""
    bn = 1e9
    rows = annual("revenue", y2021=35.4 * bn, y2022=34.6 * bn, y2023=40.8 * bn, y2024=48.6 * bn, y2025=49.6 * bn)
    rows += annual("net_income", y2021=7.5 * bn, y2022=7.6 * bn, y2023=27.4 * bn, y2024=5.1 * bn, y2025=7.8 * bn)
    gain = unusual_item(2023, 27.7 * bn, "Gain recognised in bargain purchase transaction: Credit Suisse Acquisition",
                        "ifrs-full:GainRecognisedInBargainPurchaseTransaction")
    table = noted(rows, facts=[gain], filings=[filing(y) for y in (2023, 2024, 2025)])
    note = next(n for n in table["notes"] if n["kind"] == "unusual")
    assert note["text"].startswith("FY2023: net income of $27.4B, against $7.6B the year before and $5.1B the year after.")
    assert "a gain recognised in bargain purchase transaction (Credit Suisse Acquisition) of $27.7B" in note["text"]
    assert ["net_income", 2] in note["cells"]
    # Revenue did not jump, and a charge would not explain a higher profit.
    assert ["revenue", 2] not in note["cells"]


def test_lasting_growth_is_not_called_unusual():
    """NVIDIA's revenue and profit kept climbing: no period stands above both of its neighbours."""
    rows = annual("revenue", y2022=27.0, y2023=27.0, y2024=61.0, y2025=130.5, y2026=216.0)
    rows += annual("net_income", y2022=9.8, y2023=4.4, y2024=29.8, y2025=72.9, y2026=120.0)
    assert not [n for n in noted(rows)["notes"] if n["kind"] == "unusual"]


def test_a_dividend_that_slipped_into_the_next_quarter():
    """TD paid its January dividend in February: Q1 is a sliver and Q2 about double."""
    quarters = {"Q1": 1.79, "Q2": 2.02, "Q3": 1.89}
    rows = [r for fy in (2025,) for fp, v in quarters.items() for r in spans("dividends_paid", fy, **{fp: v})]
    rows += spans("dividends_paid", 2026, Q1=0.14, Q2=3.76, Q3=1.93)
    rows += [r for fy in (2025, 2026) for fp in ("Q1", "Q2", "Q3") for r in spans("revenue", fy, **{fp: 15.0})]
    table = noted(rows, kind="quarterly", bank=True)
    slipped = next(n for n in table["notes"] if "about double" in n["text"])
    assert slipped["text"].startswith("Q1 FY2026 is unusually low and Q2 FY2026 about double")
    assert len(slipped["cells"]) == 2


def test_a_credit_loss_release_is_explained():
    rows = annual("revenue", y2021=49.0, y2022=50.0, y2023=51.0) + annual("credit_loss_expense", y2021=-0.93, y2022=3.58, y2023=3.45)
    rows += [fact(m, fy, "FY", v, instant=True, start=None, end=date(fy, 12, 31))
             for m, v in (("deposits", 1600.0), ("total_assets", 3000.0)) for fy in (2021, 2022, 2023)]
    table = noted(rows, bank=True)
    assert cells_of(table, "net release of credit loss provisions") == [[["credit_loss_expense", 0]]]


def test_blanks_say_why():
    rows = annual("revenue", y2022=10.0, y2023=11.0, y2024=12.0)
    rows += spans("eps_diluted", 2024, Q3=1.0, **{"9M": 3.0}, FY=4.1) + spans("revenue", 2024, Q3=3.0, **{"9M": 9.0})
    rows += annual("net_income", y2023=2.0, y2024=2.2) + annual("total_assets", y2023=50.0, y2024=55.0)
    rows = [r if r["canonical_metric"] != "total_assets" else {**r, "period_type": "instant"} for r in rows]
    table = noted(rows, filings=[filing(2023), filing(2024)])
    texts = " ".join(n["text"] for n in table["notes"])
    # FY2022 comes only from the FY2023 report's comparative column, which has revenue but not net income.
    assert "FY2022 comes only from the comparative columns of later reports" in texts
    assert "Growth needs the same period a year earlier" in texts
    quarterly = noted(rows, kind="quarterly", filings=[filing(2023), filing(2024)])
    assert any(n["text"].startswith("Q4 diluted EPS is not reported on its own") for n in quarterly["notes"])


def test_lines_an_ifrs_income_statement_does_not_have_are_listed_as_not_shown():
    rows = annual("revenue", y2024=280.0, y2025=270.0) + annual("net_income", y2024=16.0, y2025=17.8)
    omitted = {o["key"]: o["reason"] for o in noted(rows, ifrs=True)["omitted"]}
    assert "does not require an operating income line" in omitted["operating_income"]
    assert "doesn't report this line as a total" in omitted["cash"]


def test_a_charge_does_not_explain_a_higher_profit():
    bn = 1e9
    rows = annual("net_income", y2021=5 * bn, y2022=5 * bn, y2023=15 * bn, y2024=5 * bn)
    charge = unusual_item(2023, 12 * bn, "Impairment loss recognised in profit or loss",
                          "ifrs-full:ImpairmentLossRecognisedInProfitOrLoss")
    note = next(n for n in noted(rows, facts=[charge])["notes"] if n["kind"] == "unusual")
    assert "It includes" not in note["text"] and "don't separate out a one-off item" in note["text"]
