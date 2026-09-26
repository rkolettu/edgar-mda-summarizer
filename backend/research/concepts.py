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


# How statements commonly word a line, for company-specific tags whose name follows no standard concept
# (NVIDIA tags "Marketable securities" as nvda:MarketableSecuritiesAndEquitySecuritiesFVNI).
REPORTED_LABEL_METRICS = {
    "marketable securities": "marketable_securities", "short-term investments": "marketable_securities",
    "revenue": "revenue", "revenues": "revenue", "total revenue": "revenue", "total revenues": "revenue",
    "net revenue": "revenue", "net revenues": "revenue", "net sales": "revenue", "total net sales": "revenue",
    "operating income": "operating_income", "income from operations": "operating_income",
    "net income": "net_income", "cash and cash equivalents": "cash", "total assets": "total_assets",
    "inventories": "inventory", "inventory": "inventory", "accounts receivable, net": "accounts_receivable",
    "accounts payable": "accounts_payable", "total liabilities": "total_liabilities",
    "capital expenditures": "capex", "purchases of property and equipment": "capex",
}


def label_key(label: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(\w\)|[:*]", "", label or "")).strip().lower()


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


# --- disclosure families: values the statements' headline lines do not capture ---

@dataclass(frozen=True)
class Family:
    key: str                          # commitment, guarantee, debt, ...
    fact_type: str
    concepts: re.Pattern              # matched against the concept's local name
    axes: frozenset[str] | None       # allowed dimension axes (local names); None allows any, empty only totals
    exclude: re.Pattern | None = None


def _family(key, fact_type, concepts, axes=None, exclude=None) -> Family:
    return Family(key, fact_type, re.compile(concepts), None if axes is None else frozenset(axes),
                  re.compile(exclude) if exclude else None)


SEGMENT_AXES = {"StatementBusinessSegmentsAxis", "SegmentsAxis"}
GEOGRAPHY_AXES = {"StatementGeographicalAxis", "GeographicalAreasAxis"}
PRODUCT_AXES = {"ProductOrServiceAxis", "ProductsAndServicesAxis"}
CONCENTRATION_AXES = {"ConcentrationRiskByBenchmarkAxis", "ConcentrationRiskByTypeAxis", "MajorCustomersAxis",
                      "StatementGeographicalAxis", "EquitySecuritiesByIndustryAxis"}
# Breakdowns that restate a total rather than disclose something new.
NOISE_AXES = {
    "StatementEquityComponentsAxis", "FairValueByFairValueHierarchyLevelAxis", "FairValueByMeasurementFrequencyAxis",
    "FairValueByMeasurementBasisAxis", "RangeAxis", "ConsolidatedEntitiesAxis", "LegalEntityAxis",
    "RevenueRemainingPerformanceObligationExpectedTimingOfSatisfactionStartDateAxis",
    "FinancingReceivablePortfolioSegmentAxis", "FinancingReceivableRecordedInvestmentByClassOfFinancingReceivableAxis",
    "MaturityAxis", "ContractualObligationFiscalYearMaturityScheduleAxis",
}
# Maturity-by-year splits, running totals and ratios of a disclosure are left out; the total is kept.
NOISE_CONCEPTS = re.compile(
    r"DueIn|Due(After|Within)|Remainder|Thereafter|Anniversary|Expiring|FutureMinimumPayments|NextTwelveMonths"
    r"|AfterYear|Year(One|Two|Three|Four|Five)|Accumulated|EvaluatedForImpairment|Reconciliation|Allowance"
    r"|InterestRate|Percentage(?!1$)|NumberOf|Weighted|Term$|Period$|Duration"
)
SUBSEQUENT_EVENT_AXIS = "SubsequentEventTypeAxis"
# Neutral members that do not change what a value measures.
NEUTRAL_MEMBERS = {("ConsolidationItemsAxis", "OperatingSegmentsMember")}

FAMILIES: list[Family] = [
    # "Guarantee deposits" (TSMC) are security deposits held or paid, not guarantees given.
    _family("guarantee", "guarantee", r"Guarant|LettersOfCredit|CreditSupport", exclude=r"Collateral|Payables$|Fee|Deposit"),
    _family("commitment", "commitment",
            r"OtherCommitment$|PurchaseObligation|ContractualObligation$|PurchaseCommitment|UnrecordedUnconditional"
            r"|RecordedUnconditional|FundingCommitment|CommitmentsContractualAmount|LendingRelated(Financial)?Commitments"
            r"|UnfundedCommitment|CapitalCommitment|ContractualCommitment",
            exclude=r"Allowance|Fee"),
    _family("debt", "debt",
            r"^LongTermDebt$|^LongTermDebtCurrent$|^LongTermDebtNoncurrent$|^CommercialPaper$|^ShortTermBorrowings$"
            r"|DebtInstrumentFaceAmount|DebtInstrumentCarryingAmount|LineOfCreditFacilityMaximumBorrowingCapacity"
            r"|ProceedsFromIssuanceOf(LongTerm|Senior|Convertible)?\w*Debt|RepaymentsOf\w*Debt|ProceedsFromRepaymentsOfCommercialPaper"
            r"|^Borrowings$|^LongtermBorrowings$|^ShorttermBorrowings$|^BondsIssued$|ProceedsFromIssueOfBonds|RepaymentsOfBonds"
            r"|ProceedsFrom(Non)?[Cc]urrentBorrowings|RepaymentsOf(Non)?[Cc]urrentBorrowings",
            axes={"DebtInstrumentAxis", "LongtermDebtTypeAxis", "ShortTermDebtTypeAxis", "LineOfCreditFacilityAxis",
                  "CreditFacilityAxis", "BorrowingsByNameAxis", "ClassesOfBorrowingsAxis"}),
    _family("investment", "investment",
            r"EquitySecuritiesFvNi(Gain|Unrealized|Realized)|GainLossOnInvestments|MarketableSecurities(Realized|Unrealized)GainLoss"
            r"|^EquityMethodInvestments$|IncomeLossFromEquityMethodInvestments|PaymentsToAcquire(EquityMethod|Other)?Investments"
            r"|PaymentsToAcquireEquitySecurities|ShareOfProfitLossOfAssociates|InvestmentsInAssociates",
            axes={"FinancialInstrumentAxis", "ScheduleOfEquityMethodInvestmentEquityMethodInvesteeNameAxis",
                  "InvestmentTypeAxis", "EquityMethodInvesteeNameAxis"}),
    _family("capital_return", "capital_return",
            r"StockRepurchaseProgram(Authorized|RemainingAuthorized)|StockRepurchased(AndRetired)?DuringPeriodValue"
            r"|CommonStockDividendsPerShareDeclared|DividendsRecognisedAsDistributionsToOwnersPerShare",
            axes={"ShareRepurchaseProgramAxis"}),
    _family("non_operating", "non_operating_income",
            r"InvestmentIncomeInterest$|InterestExpenseNonoperating|ForeignCurrencyTransactionGainLoss|^FinanceIncome$"
            r"|^OtherGainsLosses$|OtherNonoperatingIncome$|OtherNonoperatingExpense$", axes=()),
    _family("unusual_item", "unusual_item",
            r"Impairment|WriteDown|Writedown|Restructuring(Charges|AndRelatedCostIncurredCost)|LitigationSettlement"
            r"|BusinessCombinationAcquisitionRelatedCosts|GainLossOnDispositionOfAssets|GainLossOnSaleOf",
            axes={"RestructuringPlanAxis", "FinancialInstrumentAxis"}, exclude=r"Reversal|Recovery|Test"),
    _family("customer_concentration", "customer_concentration", r"^ConcentrationRiskPercentage1$", axes=CONCENTRATION_AXES),
    _family("backlog", "operating_metric", r"^RevenueRemainingPerformanceObligation$", axes=()),
    _family("tax", "tax_item", r"^EffectiveIncomeTaxRateContinuingOperations$|^UnrecognizedTaxBenefits$", axes=()),
]

BREAKDOWNS = [
    # (family, axes, metric keys whose concepts are broken out)
    ("segment", SEGMENT_AXES, ("revenue", "operating_income")),
    ("geography", GEOGRAPHY_AXES, ("revenue",)),
    ("product", PRODUCT_AXES, ("revenue",)),
]

FAMILY_LABELS = {
    "guarantee": "Guarantees", "commitment": "Commitments", "debt": "Debt", "investment": "Investments",
    "capital_return": "Capital return", "non_operating": "Non-operating items", "unusual_item": "Unusual items",
    "customer_concentration": "Customer concentration", "backlog": "Remaining performance obligations",
    "tax": "Income taxes", "segment": "Segments", "geography": "Geography", "product": "Products and services",
}


def family_for(concept: str, axes: set[str]) -> Family | None:
    """The disclosure family a tagged value belongs to, or None when it is noise or not tracked."""
    name = concept.split(":", 1)[-1]
    if NOISE_CONCEPTS.search(name) or axes & NOISE_AXES:
        return None
    for family in FAMILIES:
        if not family.concepts.search(name) or (family.exclude and family.exclude.search(name)):
            continue
        if family.axes is not None and not axes <= family.axes:
            return None
        return family
    return None


WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|\b|_|$)|[A-Z]?[a-z]+|\d+")
SMALL_WORDS = {"and", "of", "for", "the", "to", "in", "on", "or", "by", "with", "from", "at", "not", "yet"}


def humanize(qname: str, proper_name: bool = False) -> str:
    """'nvda:AICloudPartnershipCommitmentsMember' -> 'AI cloud partnership commitments'.

    proper_name keeps each word capitalized, for counterparties and investees ('SB Energy Corp')."""
    name = qname.split(":", 1)[-1]
    name = re.sub(r"(Member|Axis|Domain)$", "", name)
    name = re.sub(r"^Ifrs(?=[A-Z])", "", name)
    words = WORD.findall(name) or [name]
    out = []
    for i, word in enumerate(words):
        if word.isupper():
            out.append(word)  # acronyms, and letters naming anonymized parties ("Customer A")
        elif i and word.lower() in SMALL_WORDS:
            out.append(word.lower())
        elif proper_name:
            out.append(word[0].upper() + word[1:])
        else:
            out.append(word.lower() if i else word.capitalize())
    return " ".join(out)


# Axes whose members name a party, so their capitalization is kept.
PROPER_NAME_AXES = re.compile(r"Name|Counterparty|Investee|Acquiree|BusinessAcquisition")


# SEC country taxonomy members (country:TW) name places by ISO code.
COUNTRY_NAMES = {
    "US": "United States", "CN": "China", "TW": "Taiwan", "HK": "Hong Kong", "JP": "Japan", "KR": "South Korea",
    "SG": "Singapore", "IN": "India", "IL": "Israel", "DE": "Germany", "GB": "United Kingdom", "FR": "France",
    "NL": "Netherlands", "IE": "Ireland", "CH": "Switzerland", "CA": "Canada", "MX": "Mexico", "BR": "Brazil",
    "AU": "Australia", "MY": "Malaysia", "TH": "Thailand", "VN": "Vietnam", "PH": "Philippines", "ID": "Indonesia",
    "IT": "Italy", "ES": "Spain", "SE": "Sweden", "BE": "Belgium", "LU": "Luxembourg", "SA": "Saudi Arabia",
    "AE": "United Arab Emirates", "ZA": "South Africa", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
}


def member_label(axis: str, member: str) -> str:
    prefix, _, name = member.rpartition(":")
    if prefix == "country" and name in COUNTRY_NAMES:
        return COUNTRY_NAMES[name]
    return humanize(member, proper_name=bool(PROPER_NAME_AXES.search(axis.split(":", 1)[-1])))


def slug(qname: str) -> str:
    name = qname.split(":", 1)[-1]
    name = re.sub(r"(Member|Axis|Domain)$", "", name)
    return "_".join(w.lower() for w in WORD.findall(name)) or re.sub(r"\W+", "_", name.lower())


# Labels for concepts whose taxonomy names read badly; categories (members) otherwise name the value.
CONCEPT_LABELS = {
    "OtherCommitment": "Other commitments",
    "UnrecordedUnconditionalPurchaseObligationBalanceSheetAmount": "Purchase obligations",
    "PurchaseObligation": "Purchase obligations",
    "ContractualObligation": "Contractual obligations",
    "GuaranteeObligationsMaximumExposure": "Guarantees (maximum exposure)",
    "GuaranteeObligationsCurrentCarryingValue": "Guarantees (carrying value)",
    "LongTermDebt": "Long-term debt",
    "LongTermDebtCurrent": "Current portion of long-term debt",
    "LongTermDebtNoncurrent": "Long-term debt, noncurrent",
    "DebtInstrumentFaceAmount": "Debt principal",
    "DebtInstrumentCarryingAmount": "Debt carrying amount",
    "LineOfCreditFacilityMaximumBorrowingCapacity": "Credit facility capacity",
    "EquitySecuritiesFvNiUnrealizedGainLoss": "Unrealized gains (losses) on equity securities",
    "EquitySecuritiesFvNiRealizedGainLoss": "Realized gains (losses) on equity securities",
    "EquitySecuritiesFvNiGainLoss": "Gains (losses) on equity securities",
    "StockRepurchaseProgramAuthorizedAmount1": "Repurchase program authorized",
    "StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1": "Repurchase authorization remaining",
    "StockRepurchasedAndRetiredDuringPeriodValue": "Shares repurchased",
    "StockRepurchasedDuringPeriodValue": "Shares repurchased",
    "CommonStockDividendsPerShareDeclared": "Dividends declared per share",
    "ConcentrationRiskPercentage1": "Concentration",
    "RevenueRemainingPerformanceObligation": "Remaining performance obligations",
    "EffectiveIncomeTaxRateContinuingOperations": "Effective tax rate",
    "PaymentsToAcquireEquitySecuritiesFvNi": "Purchases of equity securities",
    "GainLossOnInvestments": "Gains (losses) on investments",
    "InventoryWriteDown": "Inventory write-downs",
    "AssetImpairmentCharges": "Asset impairments",
    "GoodwillImpairmentLoss": "Goodwill impairment",
    "InvestmentIncomeInterest": "Interest income",
    "InterestExpenseNonoperating": "Interest expense",
    "IncomeLossFromEquityMethodInvestments": "Income from equity-method investments",
    "PaymentsToAcquireInvestments": "Purchases of investments",
    "EquityMethodInvestments": "Equity-method investments",
    "UnrecognizedTaxBenefits": "Unrecognized tax benefits",
}
# Concepts whose category alone names the value ("Supply and capacity commitments", "Customer A").
MEMBER_NAMES_VALUE = {
    "OtherCommitment", "UnrecordedUnconditionalPurchaseObligationBalanceSheetAmount", "PurchaseObligation",
    "ContractualObligation", "GuaranteeObligationsMaximumExposure",
}


CONCENTRATION_BENCHMARKS = [(re.compile(r"Receivable"), "accounts receivable"), (re.compile(r"Revenue|Sales"), "revenue"),
                            (re.compile(r"Purchase|Supplier|Cost"), "purchases")]


def concentration_label(dims: list[tuple[str, str]]) -> str:
    """'Customer A (share of revenue)' from the subject (customer, region) and the benchmark axes."""
    by_axis = {axis.split(":", 1)[-1]: member for axis, member in dims}
    subject = by_axis.get("MajorCustomersAxis") or by_axis.get("StatementGeographicalAxis") or by_axis.get("EquitySecuritiesByIndustryAxis")
    benchmark_member = by_axis.get("ConcentrationRiskByBenchmarkAxis", "")
    benchmark = next((name for pattern, name in CONCENTRATION_BENCHMARKS if pattern.search(benchmark_member)), None)
    label = humanize(subject) if subject else "Concentration"
    return f"{label} (share of {benchmark})" if benchmark else label


def concept_label(concept: str) -> str:
    name = concept.split(":", 1)[-1]
    return CONCEPT_LABELS.get(name) or humanize(name)
