import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from research import ingest, service, snapshot, store
from tests.conftest import submissions_payload
from tests.ixbrl_fixture import context, cover, document, row, text_block, value
from tests.test_research_ingest import CIK, SUBMISSIONS_URL, archive, index_page

COMMITMENTS = "us-gaap:OtherCommitmentsAxis"


def commitment(ctx: str, amount: str) -> str:
    return value("us-gaap:OtherCommitment", ctx, amount, scale=9, decimals=-8)


def commitments_note(ctx: str, *paragraphs: str) -> str:
    inner = "<p>Commitments and Contingencies</p>" + "".join(f"<p>{p}</p>" for p in paragraphs)
    return text_block("us-gaap:CommitmentsAndContingenciesDisclosureTextBlock", ctx, inner, f"note-{ctx}")


SUPPLY_SENTENCE = "We entered into supply commitments to secure manufacturing capacity for our data center products."


def member(cid: str, name: str, instant: str, *extra) -> str:
    return context(cid, instant=instant, dims=((COMMITMENTS, f"acme:{name}Member"), *extra))


def annual_2026() -> str:
    end = "2026-01-25"
    body = (
        cover("fy", "10-K", "January 25, 2026", 2026, "FY", fiscal_year_end="--01-25")
        + row("Revenue", value("us-gaap:Revenues", "fy", "215,938"), value("us-gaap:Revenues", "fy25", "130,497"))
        + row("Cost of revenue", value("us-gaap:CostOfRevenue", "fy", "62,475"))
        + row("Operating income", value("us-gaap:OperatingIncomeLoss", "fy", "130,387"))
        + row("Net income", value("us-gaap:NetIncomeLoss", "fy", "120,067"))
        + row("Operating cash flow", value("us-gaap:NetCashProvidedByUsedInOperatingActivities", "fy", "102,718"))
        + row("Total assets", value("us-gaap:Assets", "end", "206,803"))
        + row("Long-term debt", value("us-gaap:LongTermDebt", "end", "8,468"))
        + row("Supply", commitment("supply", "95.2")) + row("Investments", commitment("invest", "11.4"))
    )
    return document(body, [
        context("fy", "2025-01-27", end), context("fy25", "2024-01-29", "2025-01-26"), context("end", instant=end),
        member("supply", "ManufacturingSupplyAndCapacity", end), member("invest", "InvestmentCommitments", end),
    ])


def q3_2026() -> str:
    end = "2025-10-26"
    body = (
        cover("ytd", "10-Q", "October 26, 2025", 2026, "Q3", fiscal_year_end="--01-25")
        + row("Revenue", value("us-gaap:Revenues", "q", "57,006"), value("us-gaap:Revenues", "ytd", "147,811"))
        + row("Operating cash flow", value("us-gaap:NetCashProvidedByUsedInOperatingActivities", "ytd", "66,530"))
    )
    return document(body, [context("ytd", "2025-01-27", end), context("q", "2025-07-28", end)])


def q1_2027() -> str:
    end = "2026-04-26"
    body = (
        cover("q", "10-Q", "April 26, 2026", 2027, "Q1", fiscal_year_end="--01-25")
        + row("Revenue", value("us-gaap:Revenues", "q", "81,615"))
        + row("Operating cash flow", value("us-gaap:NetCashProvidedByUsedInOperatingActivities", "q", "50,300"))
        + row("Supply", commitment("supply", "119")) + row("Investments", commitment("invest", "27"))
        + row("Other", commitment("other", "6"))
        + commitments_note("q", SUPPLY_SENTENCE, "As of April 26, 2026, these supply and capacity commitments were $119 billion.")
    )
    return document(body, [
        context("q", "2026-01-26", end), member("supply", "ManufacturingSupplyAndCapacity", end),
        member("invest", "InvestmentCommitments", end), member("other", "OtherCommitments", end),
    ])


def q2_2027() -> str:
    end, prior = "2026-07-26", "2026-04-26"
    guarantee = ("us-gaap:GuaranteeObligationsByNatureAxis", "us-gaap:FinancialGuaranteeMember")
    body = (
        cover("ytd", "10-Q", "July 26, 2026", 2027, "Q2", fiscal_year_end="--01-25")
        + row("Revenue", value("us-gaap:Revenues", "q", "96,221"), value("us-gaap:Revenues", "ytd", "177,836"))
        + row("Operating cash flow", value("us-gaap:NetCashProvidedByUsedInOperatingActivities", "ytd", "74,400"))
        + row("Long-term debt", value("us-gaap:LongTermDebt", "end", "33,366"))
        # The category is renamed; the prior quarter's $119B reappears under the new name.
        + row("Supply and capacity", commitment("supply", "279"), commitment("supply_prior", "119"))
        + row("Equity investments", commitment("equity", "25"))
        + row("Total", commitment("total", "366"))
        + row("Financial guarantees", value("us-gaap:GuaranteeObligationsMaximumExposure", "guarantee", "105", scale=9))
        + commitments_note(
            "q", SUPPLY_SENTENCE, "As of July 26, 2026, these supply and capacity commitments were $279 billion.",
            "We entered into land, power, and shell guarantees of $105 billion for AI cloud partners, providing credit "
            "support for their data center leases.")
    )
    return document(body, [
        context("ytd", "2026-01-26", end), context("q", "2026-04-27", end), context("end", instant=end),
        member("supply", "SupplyAndCapacityCommitments", end), member("supply_prior", "SupplyAndCapacityCommitments", prior),
        member("equity", "EquityInvestmentCommitments", end), member("total", "FuturePurchaseAndOtherCommitments", end),
        context("guarantee", instant=end, dims=(guarantee,)),
    ])


FILINGS = [
    ("10-Q", "0001045810-26-000075", "q2.htm", "2026-08-26", "2026-07-26", q2_2027),
    ("10-Q", "0001045810-26-000052", "q1.htm", "2026-05-20", "2026-04-26", q1_2027),
    ("10-K", "0001045810-26-000021", "k26.htm", "2026-02-25", "2026-01-25", annual_2026),
    ("10-Q", "0001045810-25-000230", "q3.htm", "2025-11-19", "2025-10-26", q3_2026),
]


@pytest.fixture
def company_sec(fake_sec, monkeypatch):
    monkeypatch.setattr(ingest, "PAUSE_SECONDS", 0)
    fake_sec.add_json(SUBMISSIONS_URL, submissions_payload("NVIDIA CORP", [
        {"form": f, "accessionNumber": a, "primaryDocument": d, "filingDate": fd, "reportDate": rd} for f, a, d, fd, rd, _ in FILINGS
    ]))
    for form, accession, doc, _, _, build in FILINGS:
        fake_sec.add_text(archive(accession, doc), build())
        url, page = index_page(CIK, accession, [(form, doc, form, True)])
        fake_sec.add_text(url, page)
    return fake_sec


@pytest.fixture
def payload(research_conn, company_sec):
    ingest.ingest_company(research_conn, "NVDA")
    return store.load_snapshot(research_conn, store.find_company(research_conn, ticker="NVDA")["company_id"])["payload"]


def items(payload, section):
    return {i["label"]: i for s in payload["capital"]["sections"] if s["key"] == section for i in s["items"]}


def test_renamed_categories_are_linked(research_conn, payload):
    company_id = store.find_company(research_conn, ticker="NVDA")["company_id"]
    links = {(o.rsplit(".", 1)[1], n.rsplit(".", 1)[1], m) for o, n, m in research_conn.execute(
        "SELECT old_key, new_key, method FROM member_aliases WHERE company_id = %s", (company_id,)).fetchall()}
    assert links == {
        ("manufacturing_supply_and_capacity", "supply_and_capacity_commitments", "comparative_period"),
        ("investment_commitments", "equity_investment_commitments", "dropped_words"),
    }


def test_capital_items_compare_latest_prior_and_annual(payload):
    commitments = items(payload, "commitment")
    supply = commitments["Supply and capacity commitments"]
    assert (supply["latest"]["value"], supply["prior"]["value"], supply["annual"]["value"]) == (279e9, 119e9, 95.2e9)
    assert supply["change_vs_prior"] == pytest.approx(160 / 119)
    assert supply["change_vs_annual"] == pytest.approx(279 / 95.2 - 1)
    assert supply["latest"]["fiscal_label"] == "Q2 FY2027" and supply["reported_label"] == "Supply and capacity"
    assert not supply["is_new"] and supply["in_latest_filing"]
    assert [p["value"] for p in supply["series"]] == [95.2e9, 119e9, 279e9]

    equity = commitments["Equity investment commitments"]
    assert (equity["prior"]["value"], equity["annual"]["value"]) == (27e9, 11.4e9)
    # A generic name match ("Other commitments" inside "Future purchase and other commitments") is not a rename.
    assert commitments["Future purchase and other commitments"]["is_new"]
    assert commitments["Future purchase and other commitments"]["prior"] is None
    assert not commitments["Other commitments"]["in_latest_filing"]

    guarantee = items(payload, "guarantee")["Financial guarantee"]
    assert guarantee["is_new"] and guarantee["latest"]["value"] == 105e9

    debt = items(payload, "debt")["Long-term debt, including current portion"]
    assert (debt["latest"]["value"], debt["prior"]["value"]) == (33_366e6, 8_468e6)


def test_filing_changes_rank_what_is_new_or_moved(research_conn, payload):
    changes = payload["changes"]
    assert (changes["filing"]["fiscal_label"], changes["previous"]["fiscal_label"], changes["annual"]["fiscal_label"]) == (
        "Q2 FY2027", "Q1 FY2027", "FY2026")
    by_label = {i["label"]: i for i in changes["items"]}
    assert "repeated" not in {i["change_type"] for i in changes["items"]}

    guarantee = changes["items"][0]
    assert (guarantee["label"], guarantee["change_type"], guarantee["tier"]) == ("Financial guarantee", "new", "top")
    # The note's sentence about the same $105B is folded into the tagged value.
    assert [r["kind"] for r in guarantee["related"]] == ["narrative"]
    assert "shell guarantees of $105 billion" in guarantee["related"][0]["text"]
    assert "credit support" in guarantee["related"][0]["triggers"]

    supply = by_label["Supply and capacity commitments"]
    assert (supply["change_type"], supply["value"], supply["base_value"], supply["annual_value"]) == (
        "changed", 279e9, 119e9, 95.2e9)
    assert supply["change"] == pytest.approx(160 / 119) and supply["tier"] == "top"
    assert (supply["comparison"], supply["base_period_label"]) == ("sequential", "Q1 FY2027")
    assert [p["value"] for p in supply["series"]] == [95.2e9, 119e9, 279e9]

    other = by_label["Other commitments"]
    assert other["change_type"] == "removed" and other["possibly_replaced_by"] == ["Future purchase and other commitments"]
    assert "Revenue" not in by_label  # no filing reports the quarter a year earlier, so nothing comparable

    company_id = store.find_company(research_conn, ticker="NVDA")["company_id"]
    stored = dict(research_conn.execute(
        "SELECT label, tier FROM filing_changes WHERE company_id = %s AND kind = 'numeric'", (company_id,)).fetchall())
    assert stored["Supply and capacity commitments"] == "top"
    status = research_conn.execute(
        "SELECT disclosure_status, materiality_score FROM facts WHERE company_id = %s AND fact_key LIKE %s "
        "AND period_end = '2026-07-26' AND NOT is_comparative", (company_id, "%supply_and_capacity%")).fetchone()
    assert status[0] == "changed" and status[1] >= 0.7


def test_financial_tables(payload):
    annual, quarterly = payload["financials"]["annual"], payload["financials"]["quarterly"]
    assert [c["fiscal_year"] for c in annual["columns"]] == [2025, 2026]
    rows = {r["key"]: r for r in annual["rows"]}
    assert rows["revenue_growth"]["values"][1]["v"] == pytest.approx(215_938 / 130_497 - 1)
    assert rows["gross_margin"]["values"][1]["v"] == pytest.approx((215_938 - 62_475) / 215_938)

    assert [(c["fiscal_year"], c["fiscal_period"]) for c in quarterly["columns"]] == [
        (2026, "Q3"), (2026, "Q4"), (2027, "Q1"), (2027, "Q2")]
    q_rows = {r["key"]: r for r in quarterly["rows"]}
    assert q_rows["revenue"]["values"][1] == {"v": pytest.approx(215_938e6 - 147_811e6), "derived": True}
    assert q_rows["operating_cash_flow"]["values"][3] == {"v": pytest.approx(24_100e6), "derived": True}
    assert "fact_id" in q_rows["revenue"]["values"][3]


def test_snapshot_describes_company_and_filings(payload):
    assert payload["company"]["ticker"] == "NVDA" and payload["company"]["reporting_currency"] == "USD"
    assert payload["latest_filing"] == "0001045810-26-000075" and payload["latest_annual"] == "0001045810-26-000021"
    assert payload["filings"][0]["fiscal_label"] == "Q2 FY2027"
    assert payload["earnings_quality"]["bridges"][0]["label"] == "FY2026"


def test_service_ingests_once_then_serves_from_the_database(research_conn, company_sec):
    first = service.get_snapshot("NVDA")
    calls = len(company_sec.calls)
    assert first["company"]["ticker"] == "NVDA"
    assert service.get_snapshot("nvda") == first
    assert len(company_sec.calls) == calls


def test_stale_snapshot_rechecks_edgar_and_survives_an_outage(research_conn, company_sec):
    first = service.get_snapshot("NVDA")
    research_conn.execute("UPDATE research_snapshots SET checked_at = now() - interval '2 days'")
    calls = len(company_sec.calls)
    assert service.get_snapshot("NVDA") == first
    assert [url for url, _ in company_sec.calls[calls:]] == [SUBMISSIONS_URL]

    research_conn.execute("UPDATE research_snapshots SET checked_at = now() - interval '2 days'")
    company_sec.routes[SUBMISSIONS_URL] = (500, "down")
    assert service.get_snapshot("NVDA") == first


def test_storage_brake_refuses_new_companies_only(research_conn, company_sec, monkeypatch):
    service.get_snapshot("NVDA")
    monkeypatch.setattr(store, "storage_bytes", lambda conn: 10**12)
    assert service.get_snapshot("NVDA")["company"]["ticker"] == "NVDA"
    with pytest.raises(HTTPException) as exc:
        service.get_snapshot("AAPL")
    assert exc.value.status_code == 503


def test_eviction_keeps_showcase_and_recent_companies(research_conn):
    for cik, ticker, showcase, viewed in ((1, "OLD", False, "3 days"), (2, "NEW", False, "1 hour"), (3, "SHOW", True, "9 days")):
        research_conn.execute(
            "INSERT INTO companies (cik, ticker, is_showcase, last_viewed_at) VALUES (%s, %s, %s, now() - %s::interval)",
            (cik, ticker, showcase, viewed))
    assert store.evict_companies(research_conn, keep=1) == 1
    assert {t for (t,) in research_conn.execute("SELECT ticker FROM companies").fetchall()} == {"NEW", "SHOW"}


def test_snapshot_endpoint(research_conn, company_sec, fake_gemini):
    client = TestClient(main.app)
    res = client.get("/api/research/NVDA")
    assert res.status_code == 200 and res.json()["financials"]["currency"] == "USD"
    assert client.get("/api/research/ZZZZZZ").status_code == 404


def test_outdated_snapshot_version_is_rebuilt(research_conn, company_sec, monkeypatch):
    service.get_snapshot("NVDA")
    monkeypatch.setattr(snapshot, "SNAPSHOT_VERSION", snapshot.SNAPSHOT_VERSION + 1)
    assert service.get_snapshot("NVDA")["snapshot_version"] == snapshot.SNAPSHOT_VERSION


def test_snapshot_is_json_serializable_and_compact(payload):
    import json

    assert len(json.dumps(payload)) < 200_000
