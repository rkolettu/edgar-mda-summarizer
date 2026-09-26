import pytest

from research import concepts, extract, ixbrl
from tests.ixbrl_fixture import context, cover, document, row, value

END = "2026-07-26"
CONTEXTS = [context("ytd", "2026-01-26", END), context("q", "2026-04-27", END), context("end", instant=END)]


def dims_context(cid: str, *dims, instant: str = END, start: str | None = None) -> str:
    return context(cid, start=start, end=None if start is None else instant, instant=None if start else instant, dims=dims)


def family_list(body: str, contexts=()) -> list[extract.FactRecord]:
    doc = document(cover("ytd", "10-Q", "July 26, 2026", 2027, "Q2") + body, CONTEXTS + list(contexts))
    extraction = extract.extract(ixbrl.parse_documents([("q2.htm", doc.encode())]), "10-Q")
    return [f for f in extraction.facts if f.fact_type != "financial_metric"]


def families(body: str, contexts=()) -> dict[str, extract.FactRecord]:
    return {f.fact_key: f for f in family_list(body, contexts)}


SUPPLY = ("us-gaap:OtherCommitmentsAxis", "acme:SupplyAndCapacityCommitmentsMember")


def test_commitments_by_category_get_stable_keys_and_readable_labels():
    facts = families(
        row("Supply and capacity", value("us-gaap:OtherCommitment", "supply", "279", scale=9))
        + row("AI cloud agreements", value("us-gaap:OtherCommitment", "cloud", "36", scale=9)),
        [dims_context("supply", SUPPLY),
         dims_context("cloud", ("us-gaap:OtherCommitmentsAxis", "acme:AICloudPartnershipCommitmentsMember"))],
    )
    supply = facts["commitment.other_commitment.supply_and_capacity_commitments"]
    assert (supply.value_normalized, supply.label, supply.reported_label) == (279e9, "Supply and capacity commitments", "Supply and capacity")
    assert (supply.fact_type, supply.category, supply.is_comparative, supply.confidence_level) == ("commitment", "commitment", False, "high")
    assert supply.dimensions == {"us-gaap:OtherCommitmentsAxis": "acme:SupplyAndCapacityCommitmentsMember"}
    assert facts["commitment.other_commitment.ai_cloud_partnership_commitments"].label == "AI cloud partnership commitments"


def test_subsequent_events_are_flagged_and_keep_their_key():
    guarantee = ("us-gaap:GuaranteeObligationsByNatureAxis", "us-gaap:FinancialGuaranteeMember")
    subsequent = ("us-gaap:SubsequentEventTypeAxis", "us-gaap:SubsequentEventMember")
    records = family_list(
        row("Financial guarantees", value("us-gaap:GuaranteeObligationsMaximumExposure", "g", "105", scale=9))
        + "<p>In August we guaranteed $" + value("us-gaap:GuaranteeObligationsMaximumExposure", "after", "105", scale=9) + " billion.</p>",
        [dims_context("g", guarantee), dims_context("after", guarantee, subsequent, instant="2026-08-31")],
    )
    by_date = {f.period_end.isoformat(): f for f in records}
    assert {f.fact_key for f in records} == {"guarantee.guarantee_obligations_maximum_exposure.financial_guarantee"}
    assert by_date["2026-07-26"].triggers == [] and by_date["2026-07-26"].subcategory is None
    after = by_date["2026-08-31"]
    assert (after.triggers, after.subcategory, after.is_comparative) == (["subsequent_event"], "subsequent_event", False)
    assert "us-gaap:SubsequentEventTypeAxis" in after.dimensions


def test_noise_is_left_out():
    facts = families(
        row("Due in year two", value("us-gaap:OtherCommitmentDueInSecondYear", "end", "87", scale=9))
        + row("Buyback, retained earnings", value("us-gaap:StockRepurchasedAndRetiredDuringPeriodValue", "equity", "10"))
        + row("Stated rate", value("us-gaap:DebtInstrumentInterestRateStatedPercentage", "note", "4.5", unit="pure", scale=-2, decimals=3))
        + row("Level 1 equity securities", value("us-gaap:EquitySecuritiesFvNiUnrealizedGainLoss", "level1", "3"))
        + row("Later than five years", value("ifrs-full:ContractualCapitalCommitments", "late", "10"))
        # A headline metric is stored once, as the metric.
        + row("Long-term debt", value("us-gaap:LongTermDebt", "end", "33,366")),
        [dims_context("equity", ("us-gaap:StatementEquityComponentsAxis", "us-gaap:RetainedEarningsMember"), start="2026-01-26"),
         dims_context("note", ("us-gaap:DebtInstrumentAxis", "acme:Notes2030Member")),
         dims_context("level1", ("us-gaap:FairValueByFairValueHierarchyLevelAxis", "us-gaap:FairValueInputsLevel1Member"), start="2026-01-26"),
         dims_context("late", ("ifrs-full:MaturityAxis", "ifrs-full:LaterThanFiveYearsMember"))],
    )
    assert facts == {}


def test_one_amount_tagged_twice_in_one_sentence_is_one_fact():
    axis = "us-gaap:LeaseContractualTermAxis"
    sentence = ("<p>We had additional leases, primarily for datacenters, that had not yet commenced of $"
                + value("us-gaap:UnrecordedUnconditionalPurchaseObligationBalanceSheetAmount", "fin", "329.1", scale=9) + "<span style='display:none'>"
                + value("us-gaap:UnrecordedUnconditionalPurchaseObligationBalanceSheetAmount", "op", "329.1", scale=9) + "</span> billion.</p>")
    equal_rows = (row("Data center leases", value("us-gaap:OtherCommitment", "dc", "25", scale=9))
                  + row("Equity investments", value("us-gaap:OtherCommitment", "eq", "25", scale=9)))
    facts = families(sentence + equal_rows, [
        dims_context("fin", (axis, "acme:FinanceLeaseMember")), dims_context("op", (axis, "acme:OperatingLeaseMember")),
        dims_context("dc", ("us-gaap:OtherCommitmentsAxis", "acme:DataCenterLeaseMember")),
        dims_context("eq", ("us-gaap:OtherCommitmentsAxis", "acme:EquityInvestmentMember")),
    ])
    leases = [f for f in facts.values() if f.value_normalized == pytest.approx(329.1e9)]
    assert len(leases) == 1 and leases[0].label == "Finance lease / Operating lease"
    assert {f.label for f in facts.values() if f.value_normalized == 25e9} == {"Data center lease", "Equity investment"}


def test_segment_revenue_prefers_the_same_concept_as_consolidated_revenue():
    segment = ("us-gaap:StatementBusinessSegmentsAxis", "acme:ComputeAndNetworkingMember")
    facts = families(
        row("Compute & Networking", value("us-gaap:Revenues", "seg", "87,000"))
        + row("Compute & Networking (contracts)", value("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "seg", "86,000"))
        + row("Compute & Networking operating income", value("us-gaap:OperatingIncomeLoss", "seg", "60,000")),
        [dims_context("seg", segment, start="2026-04-27")],
    )
    assert facts["segment.revenue.compute_and_networking"].value_normalized == 87_000e6
    assert facts["segment.operating_income.compute_and_networking"].label == "Compute and networking (operating income)"


def test_customer_concentration_labels():
    dims = (("us-gaap:ConcentrationRiskByBenchmarkAxis", "us-gaap:RevenueFromContractWithCustomerMember"),
            ("us-gaap:ConcentrationRiskByTypeAxis", "us-gaap:CustomerConcentrationRiskMember"),
            ("srt:MajorCustomersAxis", "acme:CustomerAMember"))
    facts = families(row("Customer A", value("us-gaap:ConcentrationRiskPercentage1", "c", "22", unit="pure", scale=-2, decimals=2)),
                     [dims_context("c", *dims, start="2026-04-27")])
    (fact,) = facts.values()
    assert (fact.label, fact.value_normalized, fact.normalized_unit) == ("Customer A (share of revenue)", pytest.approx(0.22), "ratio")


@pytest.mark.parametrize(
    ("qname", "proper", "expected"),
    [
        ("nvda:AICloudPartnershipCommitmentsMember", False, "AI cloud partnership commitments"),
        ("nvda:SBEnergyCorpMember", True, "SB Energy Corp"),
        ("acme:IfrsLineOfCreditFacilityMember", False, "Line of credit facility"),
        ("us-gaap:DataCenterForThirdPartyLeaseNotYetCommencedMember", False, "Data center for third party lease not yet commenced"),
    ],
)
def test_humanize(qname, proper, expected):
    assert concepts.humanize(qname, proper_name=proper) == expected


def test_member_labels_keep_proper_names_on_party_axes():
    assert concepts.member_label("srt:CounterpartyNameAxis", "nvda:SBEnergyCorpMember") == "SB Energy Corp"
    assert concepts.member_label("us-gaap:OtherCommitmentsAxis", "nvda:SupplyAndCapacityMember") == "Supply and capacity"


def test_convenience_translations_yield_to_the_reporting_currency():
    units = {"twd": "<xbrli:measure>iso4217:TWD</xbrli:measure>", "usd": "<xbrli:measure>iso4217:USD</xbrli:measure>",
             "eur": "<xbrli:measure>iso4217:EUR</xbrli:measure>"}
    body = (
        cover("fy", "20-F", "December 31, 2025", 2025, "FY")
        + row("Revenue", value("ifrs-full:Revenue", "fy", "3,809,054.3", unit="twd"))
        # The noncurrent-debt metric takes the bonds concept, so bank loans stay a debt disclosure (as at TSMC).
        + row("Bonds payable", value("ifrs-full:NoncurrentPortionOfNoncurrentBondsIssued", "end", "943,540", unit="twd"))
        + row("Long-term bank loans", value("ifrs-full:LongtermBorrowings", "end", "39,830", unit="twd"),
              value("ifrs-full:LongtermBorrowings", "end", "1,270", unit="usd"))
        + row("Euro notes", value("ifrs-full:BondsIssued", "euro", "1,000", unit="eur"))
    )
    doc = document(body, [context("fy", "2025-01-01", "2025-12-31"), context("end", instant="2025-12-31"),
                          dims_context("euro", ("ifrs-full:BorrowingsByNameAxis", "acme:EuroNotesMember"), instant="2025-12-31")],
                   units=units)
    facts = [f for f in extract.extract(ixbrl.parse_documents([("f.htm", doc.encode())]), "20-F").facts if f.category == "debt"]
    assert sorted((f.fact_key, f.currency, f.value_normalized) for f in facts) == [
        ("debt.bonds_issued.euro_notes", "EUR", 1_000e6), ("debt.longterm_borrowings", "TWD", 39_830e6)]
