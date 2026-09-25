from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import sec
from research import db, ingest, store
from tests.conftest import MDNA_BODY, RISK_BODY, TENQ_MDNA_BODY, submissions_payload
from tests.ixbrl_fixture import context, cover, document, row, text_block, value

FIXTURES = Path(__file__).parent / "fixtures"
CIK = 1045810
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0001045810.json"


def archive(accession: str, name: str) -> str:
    return sec.archive_url(CIK, accession, name)


def index_page(cik: int, accession: str, rows: list[tuple[str, str, str, bool]]) -> tuple[str, str]:
    """EDGAR's filing index: (description, document, type, inline XBRL?) rows."""
    base = f"/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    body = "".join(
        f"<tr><td>{i}</td><td>{desc}</td><td><a href=\"{'/ix?doc=' if ixbrl else ''}{base}{doc}\">{doc}</a>"
        f"{' <span>iXBRL</span>' if ixbrl else ''}</td><td>{kind}</td><td>1</td></tr>"
        for i, (desc, doc, kind, ixbrl) in enumerate(rows, 1)
    )
    url = sec.FILING_INDEX_URL.format(cik=cik, accession_no_dashes=accession.replace("-", ""), accession=accession)
    return url, f'<table class="tableFile"><tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>{body}</table>'


def annual_doc(fy: int, start: str, end: str, revenue: str, amendment: bool = False) -> str:
    body = (
        cover("fy", "10-K", end, fy, "FY", amendment=amendment, fiscal_year_end="--01-31")
        + f"<p>Item 1A. Risk Factors</p><p>{RISK_BODY}</p><p>Item 1B. Unresolved Staff Comments</p><p>None.</p>"
        + f"<p>Item 7. Management's Discussion and Analysis of Financial Condition</p><p>{MDNA_BODY}</p>"
        + "<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p><p>Item 8. Financial Statements</p>"
        + row("Revenue", value("us-gaap:Revenues", "fy", revenue))
        + row("Total assets", value("us-gaap:Assets", "end", "206,803"))
        + text_block("us-gaap:CommitmentsAndContingenciesDisclosureTextBlock", "end",
                     "<p>Note 13 - Commitments</p>" + row("Supply and capacity", value("us-gaap:PurchaseObligation", "end", "95.2", scale=9)),
                     "note13")
    )
    return document(body, [context("fy", start, end), context("end", instant=end)])


def quarter_doc(fy: int, fp: str, start: str, q_start: str, end: str, revenue: str, amendment: bool = False) -> str:
    body = (
        cover("ytd", "10-Q", end, fy, fp, amendment=amendment, fiscal_year_end="--01-31")
        + f"<p>Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations</p><p>{TENQ_MDNA_BODY}</p>"
        + "<p>Item 3. Quantitative and Qualitative Disclosures About Market Risk</p><p>Item 4. Controls and Procedures</p>"
        + "<p>Part II Item 1A. Risk Factors</p><p>" + "Export controls now restrict shipments of certain products. " * 10 + "</p>"
        + "<p>Item 2. Unregistered Sales of Equity Securities</p>"
        + row("Revenue", value("us-gaap:Revenues", "q", revenue))
        + row("Total assets", value("us-gaap:Assets", "end", "320,272"))
    )
    return document(body, [context("ytd", start, end), context("q", q_start, end), context("end", instant=end)])


FILINGS = [
    # (form, accession, document, filing date, report date, html); newest first, as EDGAR lists them.
    ("8-K", "0001045810-26-000090", "8k.htm", "2026-08-30", "2026-08-30", None),
    ("10-Q", "0001045810-26-000075", "q2.htm", "2026-08-26", "2026-07-26",
     quarter_doc(2027, "Q2", "2026-01-26", "2026-04-27", "2026-07-26", "96,221")),
    ("10-Q/A", "0001045810-26-000060", "q1a.htm", "2026-06-01", "2026-04-26",
     quarter_doc(2027, "Q1", "2026-01-26", "2026-01-26", "2026-04-26", "81,600", amendment=True)),
    ("10-Q", "0001045810-26-000052", "q1.htm", "2026-05-20", "2026-04-26",
     quarter_doc(2027, "Q1", "2026-01-26", "2026-01-26", "2026-04-26", "81,615")),
    ("10-K", "0001045810-26-000021", "k26.htm", "2026-02-25", "2026-01-25",
     annual_doc(2026, "2025-01-27", "2026-01-25", "215,938")),
    ("10-Q", "0001045810-25-000230", "q3.htm", "2025-11-19", "2025-10-26",
     quarter_doc(2026, "Q3", "2025-01-27", "2025-07-28", "2025-10-26", "57,006")),
    ("10-K", "0001045810-25-000023", "k25.htm", "2025-02-26", "2025-01-26",
     annual_doc(2025, "2024-01-29", "2025-01-26", "130,497")),
    ("10-Q", "0001045810-24-000316", "old.htm", "2024-11-20", "2024-10-27", None),
]


@pytest.fixture
def nvda_sec(fake_sec):
    fake_sec.add_json(SUBMISSIONS_URL, submissions_payload("NVIDIA CORP", [
        {"form": f, "accessionNumber": a, "primaryDocument": d, "filingDate": fd, "reportDate": rd}
        for f, a, d, fd, rd, _ in FILINGS
    ]))
    for form, accession, doc, _, _, html in FILINGS:
        if html is None:
            continue
        fake_sec.add_text(archive(accession, doc), html)
        url, page = index_page(CIK, accession, [(form, doc, form, True), ("Exhibit 31.1", "ex31.htm", "EX-31.1", False)])
        fake_sec.add_text(url, page)
    return fake_sec


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(ingest, "PAUSE_SECONDS", 0)


def rows(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


def test_migrations_apply_once(research_conn):
    assert db.apply_migrations(research_conn) == []
    assert rows(research_conn, "SELECT version, name FROM schema_migrations") == [(1, "001_core")]


def test_discover_keeps_latest_annuals_and_later_filings_oldest_first():
    payload = submissions_payload("x", [
        {"form": f, "accessionNumber": a, "primaryDocument": d, "filingDate": fd, "reportDate": rd}
        for f, a, d, fd, rd, _ in FILINGS
    ])
    forms = [(f["form"], f["report_date"]) for f in ingest.discover(payload, annual=2)]
    assert forms == [
        ("10-K", "2025-01-26"), ("10-Q", "2025-10-26"), ("10-K", "2026-01-25"), ("10-Q", "2026-04-26"),
        ("10-Q/A", "2026-04-26"), ("10-Q", "2026-07-26"),
    ]
    assert [f["form"] for f in ingest.discover(payload, annual=1)] == ["10-K", "10-Q", "10-Q/A", "10-Q"]


def test_ingest_stores_facts_sections_and_sources(research_conn, nvda_sec):
    result = ingest.ingest_company(research_conn, "NVDA")
    assert [f["status"] for f in result["filings"]] == ["ingested"] * 6
    q2 = result["filings"][-1]
    assert q2["missing"] == ["commitments", "debt"] and q2["confidence"] < 1

    filings = rows(research_conn, """
        SELECT form_type, fiscal_year, fiscal_period, period_months, is_annual, reporting_currency, confidence_level
        FROM filings ORDER BY period_end, filing_date""")
    # The synthetic 10-K has no debt, tax or segment notes and no net income, so its confidence is only medium.
    assert filings[0] == ("10-K", 2025, "FY", 12, True, "USD", "medium")
    assert result["filings"][0]["missing"] == ["debt", "income_taxes", "segment_information"]
    assert filings[-1] == ("10-Q", 2027, "Q2", 6, False, "USD", "medium")

    revenue = rows(research_conn, """
        SELECT f.fiscal_year, f.fiscal_period, f.period_months, f.value_normalized, f.reported_label, s.source_text
        FROM facts f JOIN fact_sources s USING (fact_id)
        WHERE f.fact_key = 'metric.revenue' AND NOT f.is_comparative ORDER BY f.period_end""")
    assert [(r[0], r[1], r[2], float(r[3])) for r in revenue] == [
        (2025, "FY", 12, 130_497e6), (2026, "Q3", 3, 57_006e6), (2026, "FY", 12, 215_938e6),
        (2027, "Q1", 3, 81_615e6), (2027, "Q1", 3, 81_600e6), (2027, "Q2", 3, 96_221e6),
    ]
    assert revenue[-1][4:] == ("Revenue", "Revenue 96,221")

    sections = dict(rows(research_conn, """
        SELECT s.category, s.source_label FROM filing_sections s JOIN filings f USING (filing_id)
        WHERE f.accession_number = '0001045810-26-000021'"""))
    assert sections == {
        "management_discussion": "item7", "risk_factors": "risk_factors",
        "commitments": "us-gaap:CommitmentsAndContingenciesDisclosureTextBlock",
    }
    q2_risks = rows(research_conn, """
        SELECT s.source_label, left(s.text, 40) FROM filing_sections s JOIN filings f USING (filing_id)
        WHERE f.accession_number = '0001045810-26-000075' AND s.category = 'risk_factors'""")
    assert q2_risks == [("item1a_update", "Item 1A. Risk Factors Export controls no")]

    company = store.find_company(research_conn, ticker="nvda")
    assert (company["name"], company["reporting_currency"], company["fiscal_year_end"]) == ("NVIDIA CORP", "USD", "01-31")
    assert rows(research_conn, "SELECT count(*) FROM analysis_runs WHERE status = 'succeeded' AND filing_id IS NOT NULL") == [(6,)]


def test_reingest_skips_current_filings_and_force_keeps_ids(research_conn, nvda_sec):
    ingest.ingest_company(research_conn, "NVDA")
    ids = rows(research_conn, "SELECT accession_number, filing_id FROM filings ORDER BY 1")
    counts = rows(research_conn, "SELECT (SELECT count(*) FROM facts), (SELECT count(*) FROM filing_sections), (SELECT count(*) FROM fact_sources)")

    again = ingest.ingest_company(research_conn, "NVDA")
    assert {f["status"] for f in again["filings"]} == {"current"}

    forced = ingest.ingest_company(research_conn, "NVDA", force=True)
    assert {f["status"] for f in forced["filings"]} == {"ingested"}
    assert rows(research_conn, "SELECT accession_number, filing_id FROM filings ORDER BY 1") == ids
    assert rows(research_conn, "SELECT (SELECT count(*) FROM facts), (SELECT count(*) FROM filing_sections), (SELECT count(*) FROM fact_sources)") == counts


def test_amendment_links_to_its_original(research_conn, nvda_sec):
    ingest.ingest_company(research_conn, "NVDA")
    amendment = rows(research_conn, """
        SELECT a.form_type, a.is_amendment, o.accession_number FROM filings a JOIN filings o ON o.filing_id = a.amends_filing_id""")
    assert amendment == [("10-Q/A", True, "0001045810-26-000052")]


def test_section_text_is_kept_only_for_recent_filings(research_conn, nvda_sec):
    ingest.ingest_company(research_conn, "NVDA")
    kept = rows(research_conn, """
        SELECT f.form_type, f.period_end::text, bool_or(s.text IS NOT NULL), bool_and(s.text_hash <> '')
        FROM filings f JOIN filing_sections s USING (filing_id) GROUP BY f.filing_id ORDER BY f.period_end, f.filing_date""")
    assert [(form, end, has_text) for form, end, has_text, _ in kept] == [
        ("10-K", "2025-01-26", True), ("10-Q", "2025-10-26", False), ("10-K", "2026-01-25", True),
        ("10-Q", "2026-04-26", True), ("10-Q/A", "2026-04-26", False), ("10-Q", "2026-07-26", True),
    ]
    assert all(hashed for *_, hashed in kept)


def test_stage_lock_blocks_concurrent_runs_and_reclaims_abandoned_ones(research_conn):
    first = store.claim_stage(research_conn, "acc-1", "parse", 1)
    assert first is not None
    assert store.claim_stage(research_conn, "acc-1", "parse", 1) is None
    research_conn.execute("UPDATE analysis_runs SET started_at = now() - interval '1 hour' WHERE run_id = %s", (first,))
    second = store.claim_stage(research_conn, "acc-1", "parse", 1)
    assert second is not None and second != first
    store.finish_stage(research_conn, second, "succeeded")
    assert store.claim_stage(research_conn, "acc-1", "parse", 1) is None
    assert store.claim_stage(research_conn, "acc-1", "parse", 1, force=True) is not None


def test_failed_filing_is_recorded_and_retried(research_conn, nvda_sec):
    q1 = archive("0001045810-26-000052", "q1.htm")
    html = nvda_sec.routes.pop(q1)
    result = ingest.ingest_company(research_conn, "NVDA")
    statuses = {f["accession_number"]: f["status"] for f in result["filings"]}
    assert statuses.pop("0001045810-26-000052") == "failed" and set(statuses.values()) == {"ingested"}
    assert rows(research_conn, "SELECT status FROM analysis_runs WHERE accession_number = '0001045810-26-000052'") == [("failed",)]

    nvda_sec.routes[q1] = html
    retry = ingest.ingest_company(research_conn, "NVDA")
    assert {f["accession_number"]: f["status"] for f in retry["filings"]}["0001045810-26-000052"] == "ingested"


def test_40f_merges_tagged_exhibit_with_primary_document(research_conn, fake_sec):
    cik, accession = 311337, "0001104659-26-020411"
    tickers = fake_sec.routes[sec.TICKERS_URL][1]
    tickers["99"] = {"cik_str": cik, "ticker": "SU", "title": "SUNCOR ENERGY INC"}
    sec.load_companies.cache_clear()
    sec.load_ticker_map.cache_clear()
    fake_sec.add_json("https://data.sec.gov/submissions/CIK0000311337.json", submissions_payload("SUNCOR ENERGY INC", [
        {"form": "40-F", "accessionNumber": accession, "primaryDocument": "su-40f.htm", "filingDate": "2026-02-26", "reportDate": "2025-12-31"},
    ]))
    url, page = index_page(cik, accession, [
        ("40-F", "su-40f.htm", "40-F", True), ("Financial statements", "su-ex99d2.htm", "EX-99.2", True),
        ("MD&A", "su-ex99d3.htm", "EX-99.3", False),
    ])
    fake_sec.add_text(url, page)
    fake_sec.add_text(sec.archive_url(cik, accession, "su-40f.htm"), (FIXTURES / "su-40f-2025.htm").read_text())
    fake_sec.add_text(sec.archive_url(cik, accession, "su-ex99d2.htm"), (FIXTURES / "su-40f-2025-ex99-2.htm").read_text())

    result = ingest.ingest_company(research_conn, "SU")
    (filing,) = result["filings"]
    assert filing["status"] == "ingested" and "management_discussion" in filing["missing"]
    assert any("Narrative sections not isolated" in w for w in filing["warnings"])
    revenue = rows(research_conn, "SELECT value_normalized, currency, accounting_standard FROM facts WHERE fact_key = 'metric.revenue' AND NOT is_comparative")
    assert [(float(v), c, s) for v, c, s in revenue] == [(52_377e6, "CAD", "ifrs")]
    documents = rows(research_conn, "SELECT documents FROM filings")[0][0]
    assert [(d["type"], d["role"]) for d in documents] == [("40-F", "primary"), ("EX-99.2", "xbrl_financials"), ("EX-99.3", "exhibit")]


def test_research_endpoint_reads_stored_filings(research_conn, nvda_sec, fake_gemini):
    ingest.ingest_company(research_conn, "NVDA")
    client = TestClient(main.app)
    res = client.get("/api/research/NVDA/filings")
    assert res.status_code == 200
    body = res.json()
    assert body["company"]["ticker"] == "NVDA"
    assert [f["form_type"] for f in body["filings"]][:2] == ["10-Q", "10-Q/A"]
    revenue = next(m for m in body["latest_metrics"] if m["metric"] == "revenue")
    assert (revenue["value"], revenue["fiscal_period"], revenue["reported_label"]) == (96_221e6, "Q2", "Revenue")
    assert "s-maxage=300" in res.headers["cache-control"]

    assert client.get("/api/research/AAPL/filings").status_code == 404


def test_research_endpoint_without_database(monkeypatch, fake_sec, fake_gemini):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    assert TestClient(main.app).get("/api/research/NVDA/filings").status_code == 503


def test_cli_ingests_and_reports(research_conn, nvda_sec, capsys):
    assert ingest.main(["NVDA"]) == 0
    out = capsys.readouterr().out
    assert "NVDA (CIK 1045810)" in out and "10-Q   2026-07-26  ingested" in out and "Database size" in out


def test_watchlist_ignores_comments(tmp_path):
    path = tmp_path / "watchlist.txt"
    path.write_text("# showcase\nNVDA\n\nTSM  # 20-F\n")
    assert ingest.read_watchlist(path) == ["NVDA", "TSM"]
    assert "NVDA" in ingest.read_watchlist()
