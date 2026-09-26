from datetime import date

import pytest

from research import changes, materiality, metrics, narrative

# --- narrative diffs ---

BASE_RISK = (
    "Our business depends on a small number of customers. We may be unable to obtain export licenses. "
    "In fiscal year 2025, revenue from customers in China was 13% of total revenue. "
    "Competition in our markets is intense and could reduce demand for our products. "
    "Our operations in Taiwan could be disrupted by natural disasters or geopolitical tension."
)


def test_diff_classifies_new_reworded_number_and_rollover_sentences():
    new = (
        "Our business depends on a small number of customers. We may be unable to obtain export licenses. "
        "In fiscal year 2026, revenue from customers in China was 5% of total revenue. "
        "Competition in all of our markets is intense and could reduce demand for our products. "
        "Commitments, guarantees and other arrangements expose us to counterparty risk and extended payment terms."
    )
    result = narrative.diff(new, BASE_RISK)
    by_type = {(p.change_type, p.kind): p for p in result.passages}
    assert result.repeated == 2
    assert by_type[("changed", "numbers")].base_text.startswith("In fiscal year 2025")
    assert by_type[("changed", "wording")].text.startswith("Competition in all")
    new_passage = by_type[("new", "wording")]
    assert new_passage.text.startswith("Commitments, guarantees")
    assert {t["phrase"] for t in new_passage.triggers} >= {"extended payment terms", "counterparty risk", "guarantee"}
    assert by_type[("removed", "wording")].text.startswith("Our operations in Taiwan")


def test_year_rollover_is_a_repeat_and_removals_can_be_ignored():
    new = BASE_RISK.replace("fiscal year 2025", "fiscal year 2026").replace(
        "Our operations in Taiwan could be disrupted by natural disasters or geopolitical tension.", "")
    assert [p.change_type for p in narrative.diff(new, BASE_RISK).passages] == ["removed"]
    rolled = narrative.diff(new, BASE_RISK, detect_removed=False)
    assert rolled.passages == [] and rolled.repeated == 4


def test_sentences_do_not_break_after_abbreviations():
    text = "We are foreclosed from the China market by U.S. Government rules today. Sales to Acme Inc. Were strong this quarter."
    assert narrative.sentences(text) == [
        "We are foreclosed from the China market by U.S. Government rules today.",
        "Sales to Acme Inc. Were strong this quarter.",
    ]


def test_line_breaks_end_sentences_unless_the_text_wraps():
    text = ("Net carrying amount $ 8,470 $ 8,468 Less short-term portion (1,000) (999)\n"
            "As of April 26, 2026 and January 25, 2026, the estimated fair value of debt was $7.4 billion.\n"
            "Our results of operations could be adversely\naffected by lower demand for our products.")
    assert narrative.sentences(text) == [
        "As of April 26, 2026 and January 25, 2026, the estimated fair value of debt was $7.4 billion.",
        "Our results of operations could be adversely affected by lower demand for our products.",
    ]


def test_triggers_weigh_realized_language_above_hypothetical():
    realized = narrative.triggers("We identified a material weakness in our internal control over financial reporting.")
    hypothetical = narrative.triggers("If we fail to maintain effective controls, a material weakness could arise in the future.")
    assert realized[0]["weight"] == 1.0 and realized[0]["realized"]
    assert hypothetical[0]["weight"] == 0.5 and not hypothetical[0]["realized"]
    assert narrative.modality_shift("We entered into guarantees of the lease.", "We may enter into guarantees of leases.")


def test_tabular_text_is_recognized():
    assert narrative.is_tabular("Debt Term Rate Jul 26, 2026 Jan 25, 2026 3.20% 1,000 1,000 1.55% 2.0 1,250 1,250")
    assert not narrative.is_tabular("As of July 26, 2026, our commercial paper program had a capacity of $25.0 billion.")


# --- materiality ---

ANCHORS = materiality.Anchors("USD", revenue=216e9, operating_income=130e9, total_assets=207e9)


def test_materiality_ranks_large_new_guarantees_above_repeated_boilerplate():
    guarantee = materiality.score(materiality.Candidate("guarantee", "new", amount=105e9, currency="USD",
                                                        flags={"subsequent_event"}), ANCHORS)
    supply = materiality.score(materiality.Candidate("commitment", "changed", amount=279e9, base_amount=119e9,
                                                     change=160 / 119, currency="USD"), ANCHORS)
    small = materiality.score(materiality.Candidate("commitment", "changed", amount=0.2e9, base_amount=0.1e9,
                                                    change=1.0, currency="USD"), ANCHORS)
    boilerplate = materiality.score(materiality.Candidate("risk_factors", "repeated", unit="text"), ANCHORS)
    assert guarantee.tier == "top" and guarantee.score == 1.0 and "subsequent event" in guarantee.reasons
    assert supply.tier == "top" and "+134%" in supply.reasons
    assert small.tier == "background"  # a doubling of a small amount
    assert boilerplate.tier == "background" and boilerplate.score < 0.2


def test_statement_lines_are_sized_by_their_change_and_amounts_are_not_converted():
    level = materiality.score(materiality.Candidate("financial_metric", "changed", amount=100e9, base_amount=98e9,
                                                    change=0.02, currency="USD"), ANCHORS)
    delta = materiality.score(materiality.Candidate("financial_metric", "changed", amount=100e9, base_amount=98e9,
                                                    change=0.02, currency="USD", magnitude_basis="delta"), ANCHORS)
    assert delta.components["magnitude"] < level.components["magnitude"]
    other_currency = materiality.score(materiality.Candidate("guarantee", "new", amount=105e9, currency="TWD"), ANCHORS)
    assert other_currency.components["magnitude"] == 0 and "over_10b" not in other_currency.components["bonuses"]


def test_ratio_changes_are_scored_in_points():
    score = materiality.score(materiality.Candidate("customer_concentration", "changed", unit="ratio", amount=0.22,
                                                    base_amount=0.30, change=-0.08), ANCHORS)
    assert "-8.0 pts" in score.reasons and score.components["change"] > 0.7


# --- comparison engine ---

FILINGS = [
    {"filing_id": 4, "accession_number": "q2", "form_type": "10-Q", "filing_date": date(2026, 8, 26),
     "period_end": date(2026, 7, 26), "fiscal_year": 2027, "fiscal_period": "Q2", "is_annual": False},
    {"filing_id": 3, "accession_number": "q1", "form_type": "10-Q", "filing_date": date(2026, 5, 20),
     "period_end": date(2026, 4, 26), "fiscal_year": 2027, "fiscal_period": "Q1", "is_annual": False},
    {"filing_id": 2, "accession_number": "k", "form_type": "10-K", "filing_date": date(2026, 2, 25),
     "period_end": date(2026, 1, 25), "fiscal_year": 2026, "fiscal_period": "FY", "is_annual": True},
    {"filing_id": 1, "accession_number": "q3", "form_type": "10-Q", "filing_date": date(2025, 11, 19),
     "period_end": date(2025, 10, 26), "fiscal_year": 2026, "fiscal_period": "Q3", "is_annual": False},
]
BY_ID = {f["filing_id"]: f for f in FILINGS}
FISCAL = {date(2026, 7, 26): (2027, "Q2"), date(2026, 4, 26): (2027, "Q1"), date(2026, 1, 25): (2026, "FY"),
          date(2025, 10, 26): (2026, "Q3"), date(2025, 7, 27): (2026, "Q2")}
_ids = iter(range(1, 10_000))


def fact(filing_id, key, value, end, *, start=None, category="commitment", concept="us-gaap:OtherCommitment",
         unit="currency", comparative=False, label=None, months=None, metric=None, triggers=()):
    filing = BY_ID[filing_id]
    fy, fp = FISCAL.get(end, (None, None))
    return {
        "fact_id": next(_ids), "fact_key": key, "fact_type": "disclosure", "category": category, "subcategory": None,
        "canonical_metric": metric, "label": label or key.rsplit(".", 1)[-1].replace("_", " ").capitalize(),
        "reported_label": None, "xbrl_concept": concept, "dimensions": {}, "value": value, "normalized_unit": unit,
        "currency": "USD" if unit == "currency" else None, "period_type": "duration" if start else "instant",
        "period_start": start, "period_end": end, "fiscal_year": fy, "fiscal_period": fp, "period_months": months,
        "is_comparative": comparative, "confidence_level": "high", "triggers": list(triggers),
        "filing_id": filing_id, "accession_number": filing["accession_number"], "form_type": filing["form_type"],
        "filing_date": filing["filing_date"], "is_annual": filing["is_annual"], "source_url": None,
        "source_text": None, "document_url": None, "xbrl_element_id": None, "heading": None,
    }


Q2, Q1, FY, Q3 = date(2026, 7, 26), date(2026, 4, 26), date(2026, 1, 25), date(2025, 10, 26)


def numeric(rows, aliases=None):
    records = changes.numeric_changes(rows, aliases or {}, changes.Bases.of(FILINGS))
    return {r.label: r for r in records}


def test_bases_are_previous_report_and_latest_annual():
    bases = changes.Bases.of(FILINGS)
    assert (bases.latest["accession_number"], bases.previous["accession_number"], bases.annual["accession_number"]) == (
        "q2", "q1", "k")


def test_balances_compare_sequentially_with_the_annual_alongside():
    rows = [
        fact(2, "commitment.supply", 95.2e9, FY), fact(3, "commitment.supply", 119e9, Q1),
        fact(4, "commitment.supply", 279e9, Q2), fact(4, "commitment.supply", 119e9, Q1, comparative=True),
        fact(3, "commitment.invest", 27e9, Q1), fact(4, "commitment.invest", 26.5e9, Q2),
    ]
    by_label = numeric(rows)
    supply = by_label["Supply"]
    assert (supply.change_type, supply.comparison, supply.base_value, supply.annual_value) == (
        "changed", "sequential", 119e9, 95.2e9)
    assert supply.change == pytest.approx(160 / 119)
    assert [p["value"] for p in supply.details["series"]] == [95.2e9, 119e9, 279e9]
    assert by_label["Invest"].change_type == "repeated"  # under 5%


def test_new_removed_and_possibly_renamed_lines():
    rows = [
        fact(3, "commitment.operating_lease_not_yet_commenced", 32.4e9, Q1),
        fact(4, "commitment.data_center_lease_not_yet_commenced", 25e9, Q2),
        fact(4, "guarantee.financial", 105e9, date(2026, 8, 31), category="guarantee",
             concept="us-gaap:GuaranteeObligationsMaximumExposure", triggers=["subsequent_event"]),
    ]
    by_label = numeric(rows)
    guarantee = by_label["Financial"]
    assert guarantee.change_type == "new" and "subsequent_event" in guarantee.flags
    assert guarantee.period_label == "2026-08-31"  # a date after the period end shows as a date
    removed = by_label["Operating lease not yet commenced"]
    assert removed.change_type == "removed" and removed.base_value == 32.4e9
    assert removed.details["possibly_replaced_by"] == ["Data center lease not yet commenced"]


def test_a_line_missing_from_a_10q_is_not_removed_when_the_previous_report_was_annual():
    filings = [f for f in FILINGS if f["filing_id"] != 4]
    rows = [fact(2, "commitment.detail_only_in_10k", 5e9, FY), fact(3, "commitment.supply", 119e9, Q1)]
    records = changes.numeric_changes(rows, {}, changes.Bases.of(filings))
    assert all(r.change_type != "removed" for r in records)


def test_flows_compare_with_the_same_period_a_year_earlier_preferring_the_quarter():
    rows = [
        fact(4, "investment.purchases", 30e9, Q2, start=date(2026, 4, 27), months=3, category="investment"),
        fact(4, "investment.purchases", 42.4e9, Q2, start=date(2026, 1, 26), months=6, category="investment"),
        fact(4, "investment.purchases", 1e9, date(2025, 7, 27), start=date(2025, 4, 28), months=3,
             category="investment", comparative=True),
        fact(4, "investment.purchases", 0.0, date(2025, 7, 27), start=date(2025, 1, 27), months=6,
             category="investment", comparative=True),
    ]
    purchases = numeric(rows)["Purchases"]
    assert (purchases.comparison, purchases.value, purchases.base_value) == ("year_over_year", 30e9, 1e9)
    assert purchases.base_period_label == "Q2 FY2026"


def test_zero_to_zero_is_repeated_and_zero_to_amount_changed():
    rows = [
        fact(3, "debt.cp", 0.0, Q1, category="debt"), fact(4, "debt.cp", 0.0, Q2, category="debt"),
        fact(3, "debt.notes", 0.0, Q1, category="debt"), fact(4, "debt.notes", 4e9, Q2, category="debt"),
    ]
    by_label = numeric(rows)
    assert by_label["Cp"].change_type == "repeated"
    assert by_label["Notes"].change_type == "changed" and by_label["Notes"].change is None
    score = materiality.score(changes._candidate(by_label["Notes"]), ANCHORS)
    assert "from zero" in score.reasons


def test_anonymized_customers_are_compared_as_a_set():
    def share(filing_id, letter, value, end, comparative=False):
        return fact(filing_id, f"customer_concentration.concentration_risk_percentage_1.customer_{letter}.accounts_receivable",
                    value, end, category="customer_concentration", unit="ratio", comparative=comparative,
                    concept="us-gaap:ConcentrationRiskPercentage1")

    rows = [share(3, "one", 0.30, Q1), share(3, "two", 0.18, Q1), share(3, "three", 0.16, Q1),
            share(4, "a", 0.22, Q2), share(4, "b", 0.14, Q2), share(4, "c", 0.13, Q2), share(4, "d", 0.11, Q2),
            share(4, "f", 0.25, FY, comparative=True)]
    records = numeric(rows)
    assert list(records) == ["Largest customer's share of accounts receivable"]
    record = records["Largest customer's share of accounts receivable"]
    assert (record.value, record.base_value, record.change_type) == (0.22, 0.30, "changed")
    assert record.change == pytest.approx(-0.08)
    assert record.details["note"] == "4 customers disclosed (22%, 14%, 13%, 11%); previously 3 (30%, 18%, 16%)"


def test_many_lines_of_a_never_tagged_concept_are_first_itemized():
    rows = [fact(3, "debt.total", 10e9, Q1, category="debt", concept="us-gaap:LongTermDebt")]
    rows += [fact(4, f"debt.bond_{n}", 1e9 + n, Q2, category="debt", concept="ifrs-full:BondsIssued") for n in range(4)]
    records = numeric(rows)
    bonds = [r for r in records.values() if r.fact_key.startswith("debt.bond")]
    assert len(bonds) == 4 and all(r.details["first_itemized"] == "debt:ifrs-full:BondsIssued" for r in bonds)
    for r in bonds:
        r.score = materiality.score(changes._candidate(r), ANCHORS)
    groups = changes.group(bonds, 216e9)
    assert len(groups) == 1 and len(groups[0][1]) == 3


def section(filing_id, category, text, section_id=None):
    return {"section_id": section_id or filing_id * 10, "filing_id": filing_id, "category": category, "heading": None,
            "document_url": f"https://www.sec.gov/{filing_id}.htm", "ordinal": 1, "text": text}


def test_interim_risk_factors_compare_with_the_annual_and_mark_carried_updates():
    carried = "We intend to assign certain data center leases to third parties and may remain liable for them."
    added = "Commitments, guarantees, and other arrangements expose us to counterparty risk and credit support obligations."
    sections = [
        section(2, "risk_factors", BASE_RISK),
        section(3, "risk_factors", carried),
        section(4, "risk_factors", f"{carried} {added}"),
    ]
    records = changes.narrative_changes(sections, FILINGS, changes.Bases.of(FILINGS))
    assert [r.change_type for r in records] == ["new"]  # removals are not looked for against the annual report
    record = records[0]
    assert record.comparison == "vs_annual" and record.base_period_label == "FY2026"
    assert record.text.startswith(carried) and added in record.text
    assert "first_disclosed" not in record.details  # the passage includes language the previous 10-Q lacked

    only_carried = changes.narrative_changes(
        [section(2, "risk_factors", BASE_RISK), section(3, "risk_factors", carried), section(4, "risk_factors", carried)],
        FILINGS, changes.Bases.of(FILINGS))
    assert only_carried[0].details["first_disclosed"] == "Q1 FY2027"


def test_notes_skip_tables_and_mdna_keeps_only_flagged_language():
    q1_note = "Commitments We have supply commitments. As of April 26, 2026, these commitments were $119 billion."
    q2_note = ("Commitments We have supply commitments. As of July 26, 2026, these commitments were $279 billion. "
               "We entered into land, power, and shell guarantees of $105 billion for AI cloud partners. "
               "Term Rate 2026 2027 3.20% 1,000 1,000 1.55% 2.0 1,250 1,250 2,500 3,750")
    q1_mdna = "Revenue grew because of data center demand across all regions this quarter."
    q2_mdna = ("Revenue grew because of data center demand across all regions this quarter. "
               "Our new marketing campaign launched in several regions during the quarter. "
               "We recorded an impairment of $2.1 billion on a private investment during the quarter.")
    sections = [section(3, "commitments", q1_note, 31), section(4, "commitments", q2_note, 41),
                section(3, "management_discussion", q1_mdna, 32), section(4, "management_discussion", q2_mdna, 42)]
    records = changes.narrative_changes(sections, FILINGS, changes.Bases.of(FILINGS))
    texts = [r.text for r in records]
    assert any(t.startswith("We entered into land, power, and shell guarantees") for t in texts)
    assert not any("3.20%" in t for t in texts)
    assert not any("marketing campaign" in t and "impairment" not in t for t in texts)
    mdna = next(r for r in records if r.category == "management_discussion")
    assert mdna.value == 2.1e9 and mdna.triggers[0]["phrase"] == "impairment"


def test_grouping_folds_wording_into_the_tagged_value_but_not_coincidences():
    guarantee = changes.ChangeRecord("numeric", "new", "guarantee", "Financial guarantee", "sequential", 4,
                                     value=105e9, currency="USD")
    note = changes.ChangeRecord("narrative", "new", "commitments", "We entered into guarantees", "sequential", 4,
                                value=105e9, currency="USD", unit="text",
                                text="We entered into land, power, and shell guarantees of $105 billion.")
    lease = changes.ChangeRecord("numeric", "new", "commitment", "Data center lease not yet commenced", "sequential", 4,
                                 value=25e9, currency="USD")
    debt = changes.ChangeRecord("numeric", "changed", "financial_metric", "Debt issued", "year_over_year", 4,
                                value=24.9e9, base_value=0.0, currency="USD")
    paper = changes.ChangeRecord("narrative", "changed", "debt", "Commercial paper", "sequential", 4, value=25e9,
                                 currency="USD", unit="text", text="Our commercial paper program had a capacity of $25.0 billion.")
    records = [guarantee, note, lease, debt, paper]
    for r in records:
        r.score = materiality.score(changes._candidate(r), ANCHORS)
    groups = {g[0].label: [r.label for r in g[1]] for g in changes.group(records, 216e9)}
    assert groups["Financial guarantee"] == ["We entered into guarantees"]
    assert groups["Data center lease not yet commenced"] == [] and groups["Debt issued"] == []
    assert "Commercial paper" in groups


def test_derived_changes_use_the_latest_quarter_year_over_year():
    def m_row(metric, value, fy, fp, start, end):
        return {"canonical_metric": metric, "fiscal_year": fy, "fiscal_period": fp, "period_start": start,
                "period_end": end, "filing_date": date(2026, 8, 26), "fact_id": next(_ids), "value": value,
                "period_type": "duration"}

    rows = []
    for fy, rev, op, rec in ((2027, 96e9, 64e9, None), (2026, 46.7e9, 28.4e9, None)):
        end = date(fy - 1, 7, 26)
        rows += [m_row("revenue", rev, fy, "Q2", date(fy - 1, 4, 27), end),
                 m_row("operating_income", op, fy, "Q2", date(fy - 1, 4, 27), end)]
    m = metrics.Metrics(rows)
    records = {r.label: r for r in changes.derived_changes(m, changes.Bases.of(FILINGS), "USD")}
    margin = records["Operating margin"]
    assert margin.change == pytest.approx(64 / 96 - 28.4 / 46.7)
    assert (margin.period_label, margin.base_period_label, margin.unit) == ("Q2 FY2027", "Q2 FY2026", "points")
