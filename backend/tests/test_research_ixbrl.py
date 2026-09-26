from pathlib import Path

import pytest

from research import ixbrl
from tests.ixbrl_fixture import NAMESPACES, context, continuation, cover, document, row, text_block, value

FIXTURES = Path(__file__).parent / "fixtures"
Q2 = context("q2", "2026-04-27", "2026-07-26")
YTD = context("ytd", "2026-01-26", "2026-07-26")
END = context("end", instant="2026-07-26")


def parse(*docs: str) -> ixbrl.IxbrlFiling:
    return ixbrl.parse_documents([(f"doc{i}.htm", d.encode()) for i, d in enumerate(docs)])


def fixture(*names: str) -> ixbrl.IxbrlFiling:
    return ixbrl.parse_documents([(name, (FIXTURES / name).read_bytes()) for name in names])


def only(filing: ixbrl.IxbrlFiling, concept: str, dims=(), **match) -> ixbrl.Fact:
    facts = [
        f for f in filing.facts
        if f.concept == concept and f.context.dimensions == dims and all(getattr(f.context.period, k) == v for k, v in match.items())
    ]
    assert len(facts) == 1, facts
    return facts[0]


@pytest.mark.parametrize(
    ("text", "fmt", "expected"),
    [
        ("96,221", "ixt:num-dot-decimal", 96221),
        ("1.234,5", "ixt:num-comma-decimal", 1234.5),
        ("1 234,5", "ixt:numspacecomma", 1234.5),
        ("5 918", "ixt:num-dot-decimal", 5918),
        ("—", "ixt:fixed-zero", 0),
        ("—", None, 0),
        ("five", "ixt-sec:numwordsen", 5),
        ("no", "ixt-sec:numwordsen", 0),
        ("two hundred fifty", "ixt-sec:numwordsen", 250),
        ("12.5", None, 12.5),
        ("n/a", "ixt:num-dot-decimal", None),
    ],
)
def test_display_formats(text, fmt, expected):
    assert ixbrl.parse_display_number(text, fmt) == expected


def test_scale_sign_and_percentages():
    body = (
        row("Supply and capacity", "$", value("us-gaap:OtherCommitment", "end", "279", scale=9, decimals=-9))
        + row("Other, net", "(", value("us-gaap:OtherNonoperatingIncomeExpense", "q2", "267", sign="-"), ")")
        + row("Customer A", value("us-gaap:ConcentrationRiskPercentage1", "q2", "22", unit="pure", scale=-2, decimals=2))
    )
    filing = parse(document(body, [Q2, END]))
    commitment = only(filing, "us-gaap:OtherCommitment")
    assert commitment.value == 279e9 and commitment.display_value == 279 and commitment.scale == 9
    other = only(filing, "us-gaap:OtherNonoperatingIncomeExpense")
    assert other.value == -267e6 and other.display_value == -267
    assert only(filing, "us-gaap:ConcentrationRiskPercentage1").value == pytest.approx(0.22)
    assert commitment.primary.row_label == "Supply and capacity"
    assert commitment.unit == "iso4217:USD"


def test_cover_page_and_dimensions():
    dims = (("us-gaap:OtherCommitmentsAxis", "acme:SupplyAndCapacityCommitmentsMember"),)
    body = cover("ytd", "10-Q", "July 26, 2026", 2027, "Q2") + row(
        "Supply", value("us-gaap:OtherCommitment", "supply", "279", scale=9)
    )
    filing = parse(document(body, [YTD, context("supply", instant="2026-07-26", dims=dims)]))
    assert filing.dei_text("DocumentType") == "10-Q"
    assert filing.dei_context.period == ixbrl.Period(ixbrl.date(2026, 1, 26), ixbrl.date(2026, 7, 26))
    assert only(filing, "us-gaap:OtherCommitment", dims=dims).value == 279e9


def test_prefixes_follow_namespaces_not_document_choices():
    prefixes = {**NAMESPACES, "gaap": NAMESPACES["us-gaap"]}
    del prefixes["us-gaap"]
    body = row("Revenue", value("gaap:Revenues", "q2", "100"))
    filing = parse(document(body, [Q2], prefixes=prefixes))
    assert filing.facts[0].concept == "us-gaap:Revenues"


def test_text_block_continuations_nesting_and_fact_ownership():
    inner_table = text_block("us-gaap:OtherCommitmentsTableTextBlock", "end",
                             row("Supply and capacity", value("us-gaap:OtherCommitment", "end", "279", scale=9)), "table")
    body = (
        text_block("us-gaap:CommitmentsAndContingenciesDisclosureTextBlock", "end",
                   "<p>Note 13 - Commitments and Contingencies</p><p>Purchase obligations grew.</p>" + inner_table, "note", "c1")
        + "<p>Page 20</p>"
        + continuation("c1", "<p>Guarantees of " + value("us-gaap:GuaranteeObligationsMaximumExposure", "end", "105", scale=9)
                       + " billion were issued.</p>", "c2")
        + continuation("c2", "<p>Litigation remains pending.</p>")
    )
    filing = parse(document(body, [END]))
    note, table = filing.text_blocks
    assert note.text.startswith("Note 13 - Commitments and Contingencies")
    assert "Guarantees of 105 billion were issued." in note.text and note.text.endswith("Litigation remains pending.")
    assert "Page 20" not in note.text
    assert table.parent_id == "note" and note.parent_id is None
    assert only(filing, "us-gaap:OtherCommitment").primary.text_block_id == "table"
    guarantee = only(filing, "us-gaap:GuaranteeObligationsMaximumExposure")
    assert guarantee.primary.text_block_id == "note"
    assert guarantee.primary.row_text == "Guarantees of 105 billion were issued."


def test_multi_document_set_resolves_contexts_across_documents():
    primary = document(cover("fy", "40-F", "December 31, 2025", 2025, "FY"), [context("fy", "2025-01-01", "2025-12-31")])
    exhibit = document(row("Gross revenues", value("ifrs-full:RevenueFromContractsWithCustomers", "fy", "52 377")), header=False)
    filing = parse(primary, exhibit)
    fact = only(filing, "ifrs-full:RevenueFromContractsWithCustomers")
    assert fact.value == 52_377e6 and fact.primary.document == "doc1.htm"
    assert filing.warnings == []


def test_duplicates_merge_and_conflicts_are_flagged():
    body = (
        row("Revenue", value("us-gaap:Revenues", "q2", "96,221", fid="a"))
        + "<p>Revenue was $" + value("us-gaap:Revenues", "q2", "96.2", scale=9, decimals=-8, fid="b") + " billion.</p>"
        + row("Net income", value("us-gaap:NetIncomeLoss", "q2", "59,688"))
        + row("Net income", value("us-gaap:NetIncomeLoss", "q2", "59,000"))
    )
    filing = parse(document(body, [Q2]))
    revenue = only(filing, "us-gaap:Revenues")
    assert not revenue.conflicting and [o.element_id for o in revenue.occurrences] == ["a", "b"]
    assert revenue.value == 96_221e6
    assert only(filing, "us-gaap:NetIncomeLoss").conflicting
    assert any("different amounts" in w for w in filing.warnings)


def test_nil_and_undefined_contexts_are_skipped():
    body = (
        '<ix:nonFraction name="us-gaap:Revenues" contextRef="q2" unitRef="usd" xsi:nil="true" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
        + value("us-gaap:NetIncomeLoss", "missing", "1")
    )
    filing = parse(document(body, [Q2]))
    assert filing.facts == []
    assert any("undefined" in w for w in filing.warnings)


def test_malformed_document_is_reported_not_fatal():
    filing = ixbrl.parse_documents([("broken.htm", b"")])
    assert filing.facts == [] and filing.warnings


def test_nvidia_q2_commitments_and_guarantee_from_real_filing():
    filing = fixture("nvda-10q-2026q2.htm")
    assert filing.dei_text("DocumentFiscalPeriodFocus") == "Q2"
    supply = [f for f in filing.facts if f.concept == "us-gaap:OtherCommitment"
              and ("us-gaap:OtherCommitmentsAxis", "nvda:SupplyAndCapacityCommitmentsMember") in f.context.dimensions]
    assert {f.context.period.end.isoformat(): f.value for f in supply} == {"2026-07-26": 279e9, "2026-04-26": 119e9}
    blocks = {b.id: b.concept for b in filing.text_blocks}
    current = next(f for f in supply if f.context.period.end.isoformat() == "2026-07-26")
    assert blocks[current.primary.text_block_id] == "us-gaap:OtherCommitmentsTableTextBlock"
    guarantees = {f.value for f in filing.facts if f.concept == "us-gaap:GuaranteeObligationsMaximumExposure"}
    assert 105e9 in guarantees and 108.5e9 in guarantees
    revenue = only(filing, "us-gaap:Revenues", start=ixbrl.date(2026, 4, 27), end=ixbrl.date(2026, 7, 26))
    assert revenue.value == 96_221e6 and revenue.primary.row_label == "Revenue"


def test_tsmc_and_suncor_real_filings():
    tsmc = fixture("tsm-20f-2025.htm")
    assert {ixbrl.local_name(f.concept) for f in tsmc.facts} >= {"Revenue", "ProfitLossAttributableToOwnersOfParent"}
    assert {f.unit for f in tsmc.facts if f.concept == "ifrs-full:Assets"} >= {"iso4217:TWD"}
    suncor = fixture("su-40f-2025.htm", "su-40f-2025-ex99-2.htm")
    assert suncor.dei_text("DocumentType") == "40-F" and suncor.warnings == []
    net = [f for f in suncor.facts if f.concept == "ifrs-full:ProfitLoss" and not f.context.dimensions]
    assert {f.value for f in net} >= {5_918e6}
