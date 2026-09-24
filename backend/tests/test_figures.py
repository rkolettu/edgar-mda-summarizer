import pytest

from figures import FigureIndex, add_financials, add_quarter, check_figures, extract_claims

FILING = (
    "Revenue for fiscal year 2026 was $215.9 billion, up 65% from a year ago. "
    "Gross margin decreased 3.9 percentage points to 71.1%. We returned $41.1 billion to shareholders. "
    "Operating expenses increased by 90 basis points. Quarterly dividend of $0.01 per share. "
    "Consolidated Statements of Income (in millions) Revenue 215,938 130,497 Cost of revenue 62,475"
)


@pytest.fixture
def index():
    idx = FigureIndex()
    idx.add_text(FILING)
    return idx


def claims(text):
    return [(c["text"], c["kind"], round(c["value"], 6)) for c in extract_claims(text)]


def test_extracts_dollar_and_percent_claims():
    assert claims("Revenue rose 65.5% to $215.9B; dividends were $974M and $1.1 billion; EPS $4.90.") == [
        ("65.5%", "percent", 65.5),
        ("$215.9B", "amount", 215.9e9),
        ("$974M", "amount", 974e6),
        ("$1.1 billion", "amount", 1.1e9),
        ("$4.90", "amount", 4.9),
    ]


def test_extracts_points_and_bps():
    assert claims("margin fell 3.9 percentage points and rose 90bps; $18,500 million") == [
        ("3.9 percentage points", "percent", 3.9),
        ("90bps", "percent", 0.9),
        ("$18,500 million", "amount", 18.5e9),
    ]


def test_years_and_counts_are_not_claims():
    assert claims("In fiscal year 2026 the 20-year lease covers 4.25 gigawatts across 3 sites.") == []


@pytest.mark.parametrize(
    "text",
    [
        "$215.9B",  # stated as "$215.9 billion"
        "$215.94B",  # table "215,938" in millions rounds to 215.94
        "$216B",  # coarser rounding of the same figure
        "$130.5B",  # prior-year table column
        "$62.5B",
        "$41.1B",
        "71.1%",
        "3.9 percentage points",
        "90 bps",
        "$0.01",
    ],
)
def test_figures_traced_to_filing(index, text):
    assert [s["verified"] for s in check_figures(text, index)] == [True]


@pytest.mark.parametrize(
    "text",
    [
        "$215.8B",  # off by one in the last stated digit
        "$215.95B",  # more precise than anything that rounds from the source
        "$40.4B",
        "72%",
        "65.5%",  # derived growth rate not stated in the text
        "3.8 percentage points",
    ],
)
def test_untraceable_figures_flagged(index, text):
    assert [s["verified"] for s in check_figures(text, index)] == [False]


def test_unrelated_numbers_cannot_verify_dollar_claims():
    idx = FigureIndex()
    idx.add_text("Operating margin was 75%. See page 51. The share price was $18.")
    assert [s["verified"] for s in check_figures("$75B, $51B and $18B", idx)] == [False, False, False]
    assert check_figures("$18", idx)[0]["verified"]


def test_spans_point_at_the_figures():
    text = "Revenue grew to $215.9B while margins hit 72%."
    spans = check_figures(text, FigureIndex())
    assert [text[s["start"]:s["end"]] for s in spans] == ["$215.9B", "72%"]


def test_xbrl_values_and_derived_ratios_are_traceable():
    idx = FigureIndex()
    fin = {
        "years": [
            {"period_end": "2025-01-26", "revenue": 130.497e9, "gross_profit": 97.858e9, "buybacks": 33.7e9},
            {"period_end": "2026-01-25", "revenue": 215.938e9, "gross_profit": 153.463e9, "buybacks": 40.1e9, "eps_diluted": 4.90},
        ],
    }
    add_financials(idx, fin)
    add_quarter(idx, {"revenue": 96.2e9, "revenue_growth": 1.059, "fiscal_year": 2027})
    verdicts = {s["text"]: s["verified"] for s in check_figures(
        "Revenue grew 65.5% to $215.9B, gross margin 71.1%, buybacks $40.1B, EPS $4.90, Q2 revenue $96.2B up 105.9%.", idx
    )}
    assert verdicts == {"65.5%": True, "$215.9B": True, "71.1%": True, "$40.1B": True, "$4.90": True, "$96.2B": True, "105.9%": True}


def test_add_quarter_ignores_labels():
    idx = FigureIndex()
    add_quarter(idx, {"fiscal_year": 2027, "fiscal_period": "Q2", "revenue": 1e9})
    assert [s["verified"] for s in check_figures("$2,027", idx)] == [False]


def test_older_derived_ratios_are_not_traceable():
    from tests.xbrl_fixture import apple_companyfacts
    import financials

    idx = FigureIndex()
    add_financials(idx, financials.build_financials(apple_companyfacts(), "2025-09-27"))
    verdicts = {s["text"]: s["verified"] for s in check_figures(
        "FY2025 net margin 26.9%, FY2024 net margin 24.0%, FY2021 net margin 25.9%, FY2022 revenue growth 7.8%", idx
    )}
    assert verdicts == {"26.9%": True, "24.0%": True, "25.9%": False, "7.8%": False}
