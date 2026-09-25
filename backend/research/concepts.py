"""Canonical metrics and semantic categories.

Taxonomy concepts (US GAAP and IFRS) map to stable fact keys, and note text blocks map to the semantic categories
the research pipeline consumes, so nothing downstream depends on form types, Item numbers or note numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    statement: str            # income_statement | balance_sheet | cash_flow | per_share
    period_type: str          # duration | instant
    unit: str                 # currency | currency_per_share | shares
    us_gaap: tuple[str, ...]  # tried in order; companies switch tags over time
    ifrs: tuple[str, ...] = ()
    # Set where the IFRS concept is not strictly the US GAAP one, so comparisons across standards can say so.
    ifrs_note: str | None = None

    @property
    def fact_key(self) -> str:
        return f"metric.{self.key}"


def _m(key, label, statement, period_type, unit, us_gaap, ifrs=(), ifrs_note=None) -> Metric:
    return Metric(key, label, statement, period_type, unit, tuple(us_gaap), tuple(ifrs), ifrs_note)


D, I = "duration", "instant"
IS, BS, CF, PS = "income_statement", "balance_sheet", "cash_flow", "per_share"

METRICS: list[Metric] = [
    _m("revenue", "Revenue", IS, D, "currency",
       ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet", "RevenuesNetOfInterestExpense"],
       ["Revenue", "RevenueFromContractsWithCustomers"]),
    _m("cost_of_revenue", "Cost of revenue", IS, D, "currency",
       ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"], ["CostOfSales"]),
    _m("gross_profit", "Gross profit", IS, D, "currency", ["GrossProfit"], ["GrossProfit"]),
    _m("rnd", "Research and development", IS, D, "currency",
       ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"], ["ResearchAndDevelopmentExpense"]),
    _m("sga", "Selling, general and administrative", IS, D, "currency",
       ["SellingGeneralAndAdministrativeExpense"], ["SellingGeneralAndAdministrativeExpense"]),
    _m("operating_income", "Operating income", IS, D, "currency", ["OperatingIncomeLoss"], ["ProfitLossFromOperatingActivities"],
       ifrs_note="IFRS does not define operating profit; each company chooses what it includes."),
    _m("interest_expense", "Interest expense", IS, D, "currency",
       ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"], ["FinanceCosts"],
       ifrs_note="IFRS finance costs can include items other than interest on debt."),
    _m("nonoperating_income", "Non-operating income (expense)", IS, D, "currency", ["NonoperatingIncomeExpense"]),
    _m("other_nonoperating_income", "Other income (expense), net", IS, D, "currency", ["OtherNonoperatingIncomeExpense"]),
    _m("pretax_income", "Income before income taxes", IS, D, "currency",
       ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
       ["ProfitLossBeforeTax"]),
    _m("income_tax", "Income tax expense (benefit)", IS, D, "currency", ["IncomeTaxExpenseBenefit"], ["IncomeTaxExpenseContinuingOperations"]),
    # Attributable to the parent first; ProfitLoss includes noncontrolling interests and is only a fallback.
    _m("net_income", "Net income", IS, D, "currency",
       ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
       ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"]),
    _m("eps_diluted", "Diluted EPS", PS, D, "currency_per_share",
       ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"], ["DilutedEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare"]),
    _m("eps_basic", "Basic EPS", PS, D, "currency_per_share",
       ["EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"], ["BasicEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare"]),
    _m("operating_cash_flow", "Operating cash flow", CF, D, "currency",
       ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
       ["CashFlowsFromUsedInOperatingActivities"]),
    _m("capex", "Capital expenditures", CF, D, "currency",
       ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsForCapitalImprovements"],
       ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "PurchaseOfPropertyPlantAndEquipment"]),
    _m("depreciation_amortization", "Depreciation and amortization", CF, D, "currency",
       ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"],
       ["DepreciationAndAmortisationExpense"]),
    _m("share_based_compensation", "Share-based compensation", CF, D, "currency",
       ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"], ["AdjustmentsForSharebasedPayments"]),
    _m("buybacks", "Share repurchases", CF, D, "currency",
       ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
       ["PaymentsToAcquireOrRedeemEntitysShares", "PurchaseOfTreasuryShares"]),
    _m("dividends_paid", "Dividends paid", CF, D, "currency",
       ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
       ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid", "DividendsPaidOrdinaryShares"]),
    _m("acquisitions", "Acquisitions, net of cash acquired", CF, D, "currency",
       ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
       ["CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities"]),
    _m("debt_issued", "Debt issued", CF, D, "currency",
       ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfSeniorLongTermDebt", "ProceedsFromIssuanceOfDebt",
        "ProceedsFromDebtNetOfIssuanceCosts"],
       ["ProceedsFromBorrowingsClassifiedAsFinancingActivities", "ProceedsFromIssueOfBondsNotesAndDebentures", "ProceedsFromNoncurrentBorrowings"]),
    _m("debt_repaid", "Debt repaid", CF, D, "currency",
       ["RepaymentsOfLongTermDebt", "RepaymentsOfDebt", "RepaymentsOfSeniorDebt"],
       ["RepaymentsOfBorrowingsClassifiedAsFinancingActivities", "RepaymentsOfBondsNotesAndDebentures", "RepaymentsOfNoncurrentBorrowings"]),
    _m("cash", "Cash and cash equivalents", BS, I, "currency",
       ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], ["CashAndCashEquivalents"]),
    # IFRS classifies investments by measurement basis, with no single equivalent of marketable securities.
    _m("marketable_securities", "Marketable securities", BS, I, "currency",
       ["MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "ShortTermInvestments"]),
    _m("accounts_receivable", "Accounts receivable", BS, I, "currency",
       ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"], ["CurrentTradeReceivables", "TradeAndOtherCurrentReceivables"]),
    _m("inventory", "Inventory", BS, I, "currency", ["InventoryNet"], ["Inventories"]),
    _m("accounts_payable", "Accounts payable", BS, I, "currency",
       ["AccountsPayableCurrent"], ["CurrentTradePayables", "TradeAndOtherCurrentPayables"]),
    _m("contract_liabilities", "Deferred revenue / contract liabilities", BS, I, "currency",
       ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"], ["CurrentContractLiabilities"]),
    _m("current_assets", "Current assets", BS, I, "currency", ["AssetsCurrent"], ["CurrentAssets"]),
    _m("current_liabilities", "Current liabilities", BS, I, "currency", ["LiabilitiesCurrent"], ["CurrentLiabilities"]),
    _m("total_assets", "Total assets", BS, I, "currency", ["Assets"], ["Assets"]),
    _m("total_liabilities", "Total liabilities", BS, I, "currency", ["Liabilities"], ["Liabilities"]),
    _m("equity", "Shareholders' equity", BS, I, "currency",
       ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
       ["EquityAttributableToOwnersOfParent", "Equity"]),
    # LongTermDebt includes current maturities; the noncurrent figure excludes them, so they stay separate series.
    _m("long_term_debt", "Long-term debt, including current portion", BS, I, "currency", ["LongTermDebt"]),
    _m("long_term_debt_noncurrent", "Long-term debt, noncurrent", BS, I, "currency",
       ["LongTermDebtNoncurrent"],
       ["NoncurrentPortionOfNoncurrentBorrowings", "NoncurrentPortionOfNoncurrentBondsIssued", "LongtermBorrowings"],
       ifrs_note="IFRS borrowings can include items US GAAP reports outside long-term debt."),
    _m("debt_current", "Short-term debt and current maturities", BS, I, "currency",
       ["LongTermDebtCurrent", "DebtCurrent"],
       ["CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "CurrentPortionOfLongtermBorrowings"]),
    _m("commercial_paper", "Commercial paper", BS, I, "currency", ["CommercialPaper"]),
    _m("goodwill", "Goodwill", BS, I, "currency", ["Goodwill"], ["Goodwill"]),
    _m("shares_outstanding", "Shares outstanding", BS, I, "shares", ["CommonStockSharesOutstanding"]),
]

METRICS_BY_KEY = {m.key: m for m in METRICS}


def metric_concepts(metric: Metric, standard: str) -> list[str]:
    """Standard concepts for a metric, the filer's own taxonomy first."""
    us = [f"us-gaap:{c}" for c in metric.us_gaap]
    ifrs = [f"ifrs-full:{c}" for c in metric.ifrs]
    return ifrs + us if standard == "ifrs" else us + ifrs


# --- note text blocks -> semantic categories ---

# Checked in order against the concept's local name; the first match wins, so specific rules come first
# ("DebtSecuritiesAvailableForSale" is an investment, not debt). A combined note covers every category it names.
TEXT_BLOCK_RULES: list[tuple[re.Pattern, tuple[str, ...]]] = [
    (re.compile(p), cats) for p, cats in [
        (r"SubsequentEvent|EventsAfterReportingPeriod", ("subsequent_events",)),
        (r"Guarantee", ("guarantees",)),
        (r"Cybersecurity", ("cybersecurity",)),
        (r"InsiderTrading|Clawback|ExecutiveCompensation|PayVsPerformance", ("governance",)),
        (r"CriticalAuditMatter", ("audit_matters",)),
        (r"Derivative|Hedg", ("derivatives",)),
        (r"DebtSecurities|Investment|MarketableSecurit|EquityMethod|EquitySecurities|InterestsInOtherEntities|Associates|JointVenture",
         ("investments",)),
        (r"CommitmentsAndContingen|CommitmentsAndContingentLiabilities", ("commitments", "contingencies")),
        (r"Commitment|PurchaseObligation|ContractualObligation", ("commitments",)),
        (r"Contingen|LegalMatters|Litigation|Provisions", ("contingencies",)),
        (r"Lease", ("leases",)),
        (r"Debt|Borrowing|CreditFacilit|NotesPayable|LineOfCredit|BondsIssued|Bonds", ("debt",)),
        (r"IncomeTax|DeferredTax|TaxRate", ("income_taxes",)),
        (r"Geograph|ExternalCustomersAndLongLived|RevenuesFromExternalCustomers", ("geographic_information",)),
        (r"Segment", ("segment_information",)),
        (r"Concentration|MajorCustomer", ("customer_concentration",)),
        (r"BusinessCombination|Acquisition|Disposal|DiscontinuedOperation|Divestiture", ("acquisitions",)),
        (r"RelatedPart", ("related_party_transactions",)),
        (r"ShareBased|Sharebased|StockCompensation|StockOption|EmployeeStockPurchase", ("equity_compensation",)),
        (r"Pension|PostEmployment|Postemployment|RetirementBenefit|EmployeeBenefit", ("employee_benefits",)),
        (r"StockholdersEquity|TreasuryStock|ShareRepurchase|Dividend|ShareCapital|IssuedCapital|EquityNote|EquityDisclosure",
         ("capital_return",)),
        (r"Goodwill|Intangible|Impairment", ("goodwill_impairment",)),
        (r"Restructuring", ("restructuring",)),
        (r"Inventor", ("inventory",)),
        (r"NonoperatingIncome|OtherIncome|OtherNonoperating|FinanceIncome|FinanceCost|InterestIncome|InterestExpense",
         ("non_operating_income",)),
        (r"Receivable|Payable|AccruedLiabilit|OtherLiabilit|OtherAssets|WorkingCapital|PrepaidExpense", ("working_capital",)),
        (r"Revenue|ContractWithCustomer|ContractsWithCustomers|DeferredRevenue", ("revenue",)),
        (r"EarningsPerShare", ("earnings_per_share",)),
        (r"FairValue|FinancialInstrument", ("fair_value",)),
        (r"PropertyPlantAndEquipment|CapitalExpenditure", ("property_plant_equipment",)),
        (r"CashFlow|SupplementalCash", ("cash_flow",)),
        (r"ComprehensiveIncome", ("comprehensive_income",)),
        (r"AccountingPolic|BasisOfPresentation|SignificantAccounting|NewAccountingPronouncement|AccountingStandards"
         r"|AccountingChanges|OrganizationConsolidation|NatureOfOperations|GeneralInformation", ("accounting_policies",)),
    ]
]


def text_block_kind(concept: str) -> str:
    name = concept.split(":", 1)[-1]
    if name.endswith("PolicyTextBlock") or name.startswith("DescriptionOfAccountingPolic"):
        return "policy"
    if "TableTextBlock" in name or name.startswith("ScheduleOf") or name.startswith("DisclosureOfDetailed"):
        return "table"
    if name.endswith("DisclosureTextBlock") or name.startswith("DisclosureOf") or name.endswith("TextBlock"):
        return "disclosure"
    return "block"


def text_block_categories(concept: str) -> tuple[str, ...]:
    """Semantic categories for a note text block; ('other',) when no rule knows the concept."""
    if text_block_kind(concept) == "policy":
        return ("accounting_policies",)
    name = concept.split(":", 1)[-1]
    for pattern, categories in TEXT_BLOCK_RULES:
        if pattern.search(name):
            return categories
    return ("other",)
