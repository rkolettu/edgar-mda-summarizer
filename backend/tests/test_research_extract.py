from datetime import date
from pathlib import Path

import pytest

from research import concepts, extract, ixbrl
from tests.ixbrl_fixture import context, cover, document, row, text_block, value

FIXTURES = Path(__file__).parent / "fixtures"
P = ixbrl.Period


def parse(*docs: str) -> ixbrl.IxbrlFiling:
    return ixbrl.parse_documents([(f"doc{i}.htm", d.encode()) for i, d in enumerate(docs)])


def metrics(extraction: extract.Extraction, key: str) -> dict[tuple, extract.FactRecord]:
    return {(f.fiscal_year, f.fiscal_period): f for f in extraction.facts if f.canonical_metric == key}


# NVIDIA's 52/53-week fiscal 2027 starts 2026-01-26; its quarters end on Sundays.
NVDA = extract.FiscalCalendar(date(2026, 1, 26), 2027)


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (P(date(2026, 4, 27), date(2026, 7, 26)), (2027, "Q2")),
        (P(date(2026, 1, 26), date(2026, 7, 26)), (2027, "H1")),
        (P(date(2025, 4, 28), date(2025, 7, 27)), (2026, "Q2")),
        (P(date(2025, 1, 27), date(2025, 7, 27)), (2026, "H1")),
        (P(None, date(2026, 7, 26)), (2027, "Q2")),
        (P(None, date(2026, 1, 25)), (2026, "FY")),
        (P(date(2025, 1, 27), date(2026, 1, 25)), (2026, "FY")),
        (P(date(2025, 10, 27), date(2026, 1, 25)), (2026, "Q4")),
        (P(date(2025, 1, 27), date(2025, 10, 26)), (2026, "9M")),
    ],
)
def test_fiscal_calendar_labels_52_53_week_years(period, expected):
    assert NVDA.label(period) == expected


def test_fiscal_calendar_labels_calendar_years():
    calendar = extract.FiscalCalendar(date(2025, 1, 1), 2025)
    assert calendar.label(P(date(2023, 1, 1), date(2023, 12, 31))) == (2023, "FY")
    assert calendar.label(P(None, date(2024, 12, 31))) == (2024, "FY")
    assert calendar.label(P(date(2025, 7, 1), date(2025, 12, 31))) == (2025, "H2")


def quarterly_filing(extra_body: str = "", extra_contexts=()) -> str:
    body = (
        cover("ytd", "10-Q", "July 26, 2026", 2027, "Q2", fiscal_year_end="--01-31")
        + row("Revenue", value("us-gaap:Revenues", "q2", "96,221"), value("us-gaap:Revenues", "q2py", "46,743"),
              value("us-gaap:Revenues", "ytd", "177,837"))
        # A second revenue tag for the same period: the higher-priority concept wins.
        + row("Revenue from contracts", value("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "q2", "90,000"))
        + row("Net income", value("us-gaap:NetIncomeLoss", "q2", "59,688"))
        + row("Diluted", value("us-gaap:EarningsPerShareDiluted", "q2", "2.45", unit="usdPerShare", scale=0, decimals=2))
        + row("Total assets", value("us-gaap:Assets", "end", "320,272"), value("us-gaap:Assets", "fyend", "206,803"))
        # Segment revenue is dimensional and never becomes the consolidated metric.
        + row("Compute", value("us-gaap:Revenues", "seg", "80,000"))
        + extra_body
    )
    return document(body, [
        context("ytd", "2026-01-26", "2026-07-26"), context("q2", "2026-04-27", "2026-07-26"),
        context("q2py", "2025-04-28", "2025-07-27"), context("end", instant="2026-07-26"),
        context("fyend", instant="2026-01-25"),
        context("seg", "2026-04-27", "2026-07-26", dims=(("us-gaap:StatementBusinessSegmentsAxis", "acme:ComputeMember"),)),
        *extra_contexts,
    ])


def test_quarterly_filing_metadata_and_metrics():
    extraction = extract.extract(parse(quarterly_filing()), "10-Q")
    meta = extraction.meta
    assert (meta.form_type, meta.fiscal_year, meta.fiscal_period, meta.period_months) == ("10-Q", 2027, "Q2", 6)
    assert (meta.is_interim, meta.accounting_standard, meta.reporting_currency, meta.fiscal_year_end) == (True, "us-gaap", "USD", "01-31")
    revenue = metrics(extraction, "revenue")
    assert revenue[(2027, "Q2")].value_normalized == 96_221e6
    assert revenue[(2027, "Q2")].xbrl_concept == "us-gaap:Revenues"
    assert revenue[(2027, "Q2")].reported_label == "Revenue"
    assert revenue[(2027, "Q2")].is_comparative is False
    assert revenue[(2026, "Q2")].is_comparative is True
    assert revenue[(2027, "H1")].value_normalized == 177_837e6
    assert 80_000e6 not in {f.value_normalized for f in revenue.values()}
    eps = metrics(extraction, "eps_diluted")[(2027, "Q2")]
    assert (eps.value_normalized, eps.normalized_unit) == (2.45, "currency_per_share")
    assets = metrics(extraction, "total_assets")
    assert assets[(2026, "FY")].is_comparative and assets[(2027, "Q2")].period_type == "instant"
    assert revenue[(2027, "Q2")].sources[0].source_text == "Revenue 96,221 46,743 177,837"
    assert revenue[(2027, "Q2")].confidence_level == "high"


@pytest.mark.parametrize("label", ["Purchases of property and equipment", "Purchases related to property and equipment (12)"])
def test_custom_concept_capex_is_recognized_from_common_statement_labels(label):
    body = cover("fy", "10-K", "December 31, 2025", 2025, "FY") + row(
        label, value("acme:PropertyEquipmentPurchases", "fy", "7,800", sign="-"))
    filing = parse(document(body, [context("fy", "2025-01-01", "2025-12-31")]))
    extraction = extract.extract(filing, "10-K")
    capex = metrics(extraction, "capex")[(2025, "FY")]
    assert capex.value_normalized == 7_800e6


def test_ifrs_filer_prefers_ifrs_concepts_and_reporting_currency():
    body = (
        cover("fy", "20-F", "December 31, 2025", 2025, "FY")
        + row("Net revenue", value("ifrs-full:Revenue", "fy", "3,809,054.3", unit="twd"),
              value("ifrs-full:Revenue", "fy", "121,423.5", unit="usd"))
        + row("Profit attributable to owners", value("ifrs-full:ProfitLossAttributableToOwnersOfParent", "fy", "1,697,604.0", unit="twd"))
        + row("Profit", value("ifrs-full:ProfitLoss", "fy", "1,695,124.9", unit="twd"))
        + row("Total assets", value("ifrs-full:Assets", "fyend", "7,932,842.5", unit="twd"))
    )
    units = {"twd": "<xbrli:measure>iso4217:TWD</xbrli:measure>", "usd": "<xbrli:measure>iso4217:USD</xbrli:measure>"}
    filing = parse(document(body, [context("fy", "2025-01-01", "2025-12-31"), context("fyend", instant="2025-12-31")], units=units))
    extraction = extract.extract(filing, "20-F")
    assert (extraction.meta.accounting_standard, extraction.meta.reporting_currency, extraction.meta.is_annual) == ("ifrs", "TWD", True)
    revenue = metrics(extraction, "revenue")[(2025, "FY")]
    # The US dollar convenience translation is not the reported figure.
    assert (revenue.value_normalized, revenue.currency) == (3_809_054.3e6, "TWD")
    # Profit attributable to the parent, not total profit including noncontrolling interests.
    assert metrics(extraction, "net_income")[(2025, "FY")].xbrl_concept == "ifrs-full:ProfitLossAttributableToOwnersOfParent"


def test_company_specific_tag_named_after_a_standard_concept_is_a_medium_confidence_fallback():
    body = (
        cover("fy", "40-F", "December 31, 2025", 2025, "FY")
        + row("Operating revenues, net of royalties", value("acme:RevenueFromContractsWithCustomers.NetOfRoyaltyExpense", "fy", "48,908"))
        + row("Liabilities for share repurchases", value("acme:LiabilitiesForShareRepurchaseCommitment", "fyend", "12"))
    )
    filing = parse(document(body, [context("fy", "2025-01-01", "2025-12-31"), context("fyend", instant="2025-12-31")]))
    extraction = extract.extract(filing, "40-F")
    revenue = metrics(extraction, "revenue")[(2025, "FY")]
    assert (revenue.value_normalized, revenue.confidence_level) == (48_908e6, "medium")
    # More CamelCase words after the stem make it a different concept, not total liabilities.
    assert metrics(extraction, "total_liabilities") == {}


def test_ambiguous_company_specific_tags_are_left_unmapped():
    body = (
        cover("fy", "40-F", "December 31, 2025", 2025, "FY")
        + row("Gross", value("acme:RevenueFromContractsWithCustomers.Gross", "fy", "52,377"))
        + row("Net", value("acme:RevenueFromContractsWithCustomers.NetOfRoyaltyExpense", "fy", "48,908"))
    )
    extraction = extract.extract(parse(document(body, [context("fy", "2025-01-01", "2025-12-31")])), "40-F")
    assert metrics(extraction, "revenue") == {}
    assert any("several company-specific tags" in w for w in extraction.warnings)


@pytest.mark.parametrize(
    ("concept", "categories", "kind"),
    [
        ("us-gaap:CommitmentsAndContingenciesDisclosureTextBlock", ("commitments", "contingencies"), "disclosure"),
        ("us-gaap:OtherCommitmentsTableTextBlock", ("commitments",), "table"),
        ("us-gaap:ScheduleOfGuaranteeObligationsTextBlock", ("guarantees",), "table"),
        ("us-gaap:DebtSecuritiesAvailableForSaleTableTextBlock", ("investments",), "table"),
        ("us-gaap:DebtDisclosureTextBlock", ("debt",), "disclosure"),
        ("us-gaap:SubsequentEventsTextBlock", ("subsequent_events",), "disclosure"),
        ("us-gaap:ScheduleOfOtherNonoperatingIncomeExpenseTableTextBlock", ("non_operating_income",), "table"),
        ("us-gaap:ScheduleOfRevenuesFromExternalCustomersAndLongLivedAssetsByGeographicalAreasTableTextBlock",
         ("geographic_information",), "table"),
        ("us-gaap:IncomeTaxPolicyTextBlock", ("accounting_policies",), "policy"),
        ("ifrs-full:DisclosureOfCommitmentsAndContingentLiabilitiesExplanatory", ("commitments", "contingencies"), "disclosure"),
        ("ifrs-full:DisclosureOfEventsAfterReportingPeriodExplanatory", ("subsequent_events",), "disclosure"),
        ("ifrs-full:DisclosureOfBorrowingsExplanatory", ("debt",), "disclosure"),
        ("ifrs-full:DescriptionOfAccountingPolicyForLeasesExplanatory", ("accounting_policies",), "policy"),
        ("asml:InventoryValuationProvisionTableTableTextBlock", ("inventory",), "table"),
        ("acme:SomethingNewTextBlock", ("other",), "disclosure"),
        ("td:DisclosureOfProvisionsContingentLiabilitiesCommitmentsGuaranteesPledgedAssetsAndCollateralExplanatory",
         ("contingencies", "commitments", "guarantees"), "disclosure"),
    ],
)
def test_text_block_categories(concept, categories, kind):
    assert concepts.text_block_categories(concept) == categories
    assert concepts.text_block_kind(concept) == kind


def test_sections_store_text_once_and_coverage_reports_gaps():
    note = text_block("us-gaap:CommitmentsAndContingenciesDisclosureTextBlock", "end",
                      "<p>Note 13 - Commitments</p>" + text_block("us-gaap:ScheduleOfGuaranteeObligationsTextBlock", "end", "<p>Guarantees</p>", "g"),
                      "note")
    extraction = extract.extract(parse(quarterly_filing(note)), "10-Q", expected=("commitments", "debt", "management_discussion"))
    by_ref = {s.ref: s for s in extraction.sections}
    assert by_ref["note"].text.startswith("Note 13 - Commitments") and by_ref["note"].heading == "Note 13 - Commitments"
    assert by_ref["g"].text is None and by_ref["g"].parent_ref == "note" and by_ref["g"].char_count > 0
    coverage = extraction.coverage
    assert coverage["commitments"]["found"] and coverage["contingencies"]["found"] and coverage["guarantees"]["found"]
    assert coverage["debt"] == {"found": False, "tier": None, "confidence": 0.0}
    assert coverage["financial_statements"]["confidence"] == 1.0
    assert extraction.confidence_level == "high"
    # Two of three expected sections are missing.
    assert extraction.parser_confidence == pytest.approx(0.4 + 0.35 + 0.25 / 3, abs=1e-3)


def test_untagged_filing_falls_back_to_edgar_metadata():
    extraction = extract.extract(ixbrl.IxbrlFiling(), "10-K", expected=("management_discussion",), report_date=date(2019, 12, 31))
    meta = extraction.meta
    assert (meta.form_type, meta.period_end, meta.fiscal_year, meta.is_annual) == ("10-K", date(2019, 12, 31), 2019, True)
    assert extraction.facts == [] and extraction.confidence_level == "low"


def test_amendment_flag_marks_the_form():
    body = cover("ytd", "10-Q", "July 26, 2026", 2027, "Q2", amendment=True)
    meta = extract.extract(parse(document(body, [context("ytd", "2026-01-26", "2026-07-26")])), "10-Q/A").meta
    assert (meta.form_type, meta.base_form, meta.is_amendment) == ("10-Q/A", "10-Q", True)


def test_real_filings_end_to_end():
    def load(*names):
        return extract.extract(ixbrl.parse_documents([(n, (FIXTURES / n).read_bytes()) for n in names]), "")

    nvda = load("nvda-10q-2026q2.htm")
    assert (nvda.meta.fiscal_year, nvda.meta.fiscal_period, nvda.meta.reporting_currency) == (2027, "Q2", "USD")
    assert metrics(nvda, "revenue")[(2027, "Q2")].value_normalized == 96_221e6
    assert metrics(nvda, "nonoperating_income")[(2027, "Q2")].value_normalized == 7_773e6
    assert metrics(nvda, "long_term_debt")[(2027, "Q2")].value_normalized == 33_366e6

    tsmc = load("tsm-20f-2025.htm")
    assert (tsmc.meta.accounting_standard, tsmc.meta.reporting_currency) == ("ifrs", "TWD")
    assert metrics(tsmc, "revenue")[(2025, "FY")].value_normalized == pytest.approx(3_809_054.3e6)

    suncor = load("su-40f-2025.htm", "su-40f-2025-ex99-2.htm")
    assert (suncor.meta.form_type, suncor.meta.reporting_currency) == ("40-F", "CAD")
    revenue = metrics(suncor, "revenue")[(2025, "FY")]
    # IFRS revenue from contracts with customers is Suncor's gross revenue; the label keeps that visible.
    assert (revenue.value_normalized, revenue.reported_label) == (52_377e6, "Gross revenues")


def test_company_specific_tag_is_mapped_by_its_statement_row_when_unambiguous():
    body = (
        cover("fy", "10-K", "January 25, 2026", 2026, "FY")
        + row("Marketable securities", value("acme:MarketableSecuritiesAndEquitySecuritiesFVNI", "fyend", "51,951"))
        + row("Non-marketable equity securities", value("acme:NonMarketableSecurities", "fyend", "22,251"))
    )
    filing = parse(document(body, [context("fy", "2025-01-27", "2026-01-25"), context("fyend", instant="2026-01-25")]))
    extraction = extract.extract(filing, "10-K")
    securities = metrics(extraction, "marketable_securities")[(2026, "FY")]
    assert (securities.value_normalized, securities.confidence_level) == (51_951e6, "medium")


def test_bank_lines_outflows_and_company_specific_pretax():
    """A Canadian bank's statement: net interest income and non-interest expense under company names that extend
    US GAAP names in another case, pretax income under a longer company name, and capital spending tagged as a
    negative cash flow."""
    body = (
        cover("fy", "40-F", "October 31, 2025", 2025, "FY", fiscal_year_end="--10-31")
        + row("Total revenue", value("ifrs-full:Revenue", "fy", "67,777"))
        + row("Net interest income", value("acme:InterestIncomeExpenseNet1", "fy", "33,062"))
        + row("Non-interest expenses", value("acme:NonInterestExpense1", "fy", "33,539"))
        + row("Income before income taxes and share of associates",
              value("acme:ProfitLossBeforeTaxAndEquityInNetIncomeOfInvestmentInAssociates", "fy", "24,905"))
        + row("Net expenditures on premises", value("acme:NetExpendituresOnPremises", "fy", "(912)", sign="-"))
        + row("Deposits", value("acme:DepositsOtherThanTrading", "fyend", "1,267,104"))
        # TD's own names: its provision as the allowance's charge to profit, net loans, shares bought back to cancel.
        + row("Provision for credit losses",
              value("acme:AdditionalAllowanceRecognisedInRecoveredFromProfitOrLossAllowanceAccountForCreditLossesOfFinancialAsset",
                    "fy", "4,506"))
        + row("Total loans, net of allowance", value("acme:LoansNet", "fyend", "953,012"))
        + row("Total loans", value("acme:LoansBeforeAllowanceForLoanLosses", "fyend", "961,701"))
        + row("Repurchase of common shares", value("acme:PaymentForCommonSharesRepurchasedForCancellation", "fy", "(6,206)", sign="-"))
    )
    filing = parse(document(body, [context("fy", "2024-11-01", "2025-10-31"), context("fyend", instant="2025-10-31")]))
    extraction = extract.extract(filing, "40-F")
    assert metrics(extraction, "net_interest_income")[(2025, "FY")].value_normalized == 33_062e6
    assert metrics(extraction, "operating_expenses")[(2025, "FY")].xbrl_concept == "acme:NonInterestExpense1"
    assert metrics(extraction, "pretax_income")[(2025, "FY")].value_normalized == 24_905e6
    assert metrics(extraction, "deposits")[(2025, "FY")].value_normalized == 1_267_104e6
    assert metrics(extraction, "credit_loss_expense")[(2025, "FY")].value_normalized == 4_506e6
    assert metrics(extraction, "loans")[(2025, "FY")].value_normalized == 953_012e6
    assert metrics(extraction, "buybacks")[(2025, "FY")].value_normalized == 6_206e6


def test_outflows_are_positive_whatever_the_tagged_sign():
    body = (
        cover("fy", "40-F", "December 31, 2025", 2025, "FY")
        + row("Revenue", value("ifrs-full:Revenue", "fy", "38,000"))
        + row("Purchase of property, plant and equipment",
              value("ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "fy", "(6,676)", sign="-"))
    )
    extraction = extract.extract(parse(document(body, [context("fy", "2025-01-01", "2025-12-31")])), "40-F")
    capex = metrics(extraction, "capex")[(2025, "FY")]
    assert (capex.value_normalized, capex.value_reported) == (6_676e6, -6_676)


def test_member_labels_keep_acronyms_written_in_title_case():
    assert concepts.humanize("td:UsRetailMember") == "US retail"
    assert concepts.humanize("ubs:Emea1Member") == "EMEA 1"
    assert concepts.humanize("acme:AmountsDueToUsMember") == "Amounts due to us"


def test_ifrs_operating_segments_member_does_not_hide_a_segment():
    """RBC tags each segment's revenue with SegmentConsolidationItemsAxis=OperatingSegmentsMember alongside it."""
    body = (
        cover("fy", "40-F", "October 31, 2025", 2025, "FY", fiscal_year_end="--10-31")
        + row("Total revenue", value("ifrs-full:Revenue", "fy", "66,610"))
        + row("Wealth Management", value("ifrs-full:Revenue", "wm", "22,380"))
    )
    wm = [("ifrs-full:SegmentConsolidationItemsAxis", "ifrs-full:OperatingSegmentsMember"),
          ("ifrs-full:SegmentsAxis", "ry:WealthManagementMember")]
    filing = parse(document(body, [context("fy", "2024-11-01", "2025-10-31"), context("wm", "2024-11-01", "2025-10-31", dims=wm)]))
    segments = [f for f in extract.extract(filing, "40-F").facts if f.category == "segment"]
    assert [(f.label, f.value_normalized) for f in segments] == [("Wealth management", 22_380e6)]
