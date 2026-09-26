"""Foreign private issuers: integrated annual reports read through their Form 20-F cross-reference table, 40-F
document sets identified by title, JPMorgan-style 10-Qs, and tagged 6-Ks in discovery."""

from research import ingest, reports
from tests.conftest import submissions_payload

PROSE = ("Management discusses the drivers of the year's results and the outlook for the business in detail. " * 12).strip()


def report_page(number: int, chapter: str, body: str) -> str:
    return f"Annual Report 2025 |\n{chapter}\n{number}\n{body}\n"


def integrated_report(risk_reference: str = "Annual Report, Risk factors (40-45)") -> str:
    """A 20-F wrapper numbered on its own (pages 1-22, with the cross-reference table on page 3) and the annual report
    it contains (pages 2-60), whose running header repeats on every page next to the page number."""
    table = "\n".join([
        "Form 20-F item", "Item 3. Key Information", "D. Risk factors", risk_reference,
        "Item 4. Information on the Company", "A. History and development of the company", "Annual Report, Our history (8)",
        "B. Business overview",
        "Annual Report, Our strategy (10-20), Note 2 to the Financial Statements (Segment reporting) (52-53)",
        "C. Organizational structure", "Annual Report, Our structure (9)",
        "Item 5. Operating and Financial Review and Prospects", "A. Operating results",
        "1: Annual Report, Our key figures (6), Financial review (30-38), Risk factors (40-45). A discussion of 2024 "
        "compared with 2023 is in the annual report filed on Form 20-F on March 17, 2025.",
        "B. Liquidity and capital resources", "Annual Report, Liquidity (39)",
        "D. Trend information", "Annual Report, Outlook (22)", "E. Critical accounting estimates", "Not applicable.",
        "Item 8. Financial Information", "A. Consolidated statements and other financial information",
        "Annual Report, Financial statements (48-60)", "B. Significant changes", "None.",
    ])
    wrapper = [f"Wrapper page {n}\n" + ("Cover text. " * 110) + (f"\n{table}" if n == 3 else "") + f"\nForm 20-F 2025\n{n}\n"
               for n in range(1, 23)]
    chapters = {6: "Our key figures", 8: "Our history", 9: "Our structure", 22: "Outlook", 39: "Liquidity"}
    pages = []
    for n in range(2, 61):
        chapter = ("Strategy" if 10 <= n <= 20 else "Financial review" if 30 <= n <= 38 else "Risk factors" if 40 <= n <= 45
                   else "Financial statements" if n >= 48 else chapters.get(n, "Other"))
        # A table row next to a repeated label puts a stray number beside a frequent line on some pages.
        table_row = "\nTotal\n7\n" if n % 5 == 0 else ""
        pages.append(report_page(n, f"Section | {chapter}", f"{chapter} text on page {n}. {PROSE}{table_row}"))
    return "".join(wrapper) + "".join(pages)


def test_page_map_follows_the_report_not_the_wrapper():
    text = integrated_report()
    pages = reports.page_map(text)
    assert [p.number for p in pages] == list(range(2, 61))
    assert "Financial review text on page 30" in text[pages[28].start:pages[28].end]


def test_cross_reference_table_resolves_items_to_pages():
    table = reports.cross_reference_table(integrated_report())
    items = reports.item_references(table)
    assert [(r.first, r.last) for r in items["risk_factors"]] == [(40, 45)]
    assert [(r.title, r.first, r.last) for r in items["operating_results"]][:3] == [
        ("1: Annual Report, Our key figures", 6, 6), ("Financial review", 30, 38), ("Risk factors", 40, 45)]
    # Dates and "Form 20-F" are not page numbers.
    assert all(r.first not in (17, 20) or r.title for r in items["operating_results"])
    assert reports.statements_start(items) == 48


def test_cross_referenced_sections_keep_risk_out_and_lead_with_the_review():
    sections = reports.cross_referenced_sections(integrated_report())
    risk, mdna, business = sections["risk_factors"], sections["management_discussion"], sections["business"]
    # The chapter line of the running header repeats on the chapter's pages and is stripped with it.
    assert risk.startswith("Risk factors text on page 40") and "page 45" in risk
    assert mdna.startswith("Financial review text on page 30")
    assert "Our key figures text on page 6" in mdna and "Outlook text on page 22" in mdna
    assert "Risk factors text" not in mdna
    assert business.startswith("Strategy text on page 10") and "page 20" in business
    # Note references and the financial statements are left out; the running header is not repeated.
    assert "Financial statements text" not in business and "Annual Report 2025 |" not in business


def test_a_single_cited_page_extends_over_its_continued_pages():
    text = integrated_report("Annual Report, Risk factors (40)").replace(
        "Risk factors text on page 40.", "Risk factors\nRisk factors text on page 40.")
    # Pages 41-45 title themselves "Risk factors (continued)".
    for n in range(41, 46):
        text = text.replace(f"Risk factors text on page {n}.", f"Risk factors (continued)\nRisk factors text on page {n}.")
    risk = reports.cross_referenced_sections(text)["risk_factors"]
    assert "page 40" in risk and "page 45" in risk


# --- 40-F document sets ---

def aif(pointer_risks: bool = True) -> str:
    risks = ("A discussion of risks affecting us is set out under Risk Factors That May Affect Future Results in our "
             "MD&A, which is incorporated by reference.\n" + "See the MD&A. " * 150) if pointer_risks else (PROSE + "\n") * 30
    return "\n".join([
        "ANNUAL INFORMATION FORM", "February 25, 2026", "Table of Contents", "General Development of the Business", "4",
        "Risk Factors", "20", "Dividends", "22",
        "General Development of the Business", (PROSE + "\n") * 10, "Description of the Business", (PROSE + "\n") * 15,
        "Risk Factors", risks, "Dividends", (PROSE + "\n") * 10,
    ])


def mdna(prefix: str = "") -> str:
    return prefix + "\n".join([
        "Management's Discussion", "and Analysis", "February 25, 2026",
        "This Management's Discussion and Analysis (MD&A) should be read in conjunction with the financial statements.",
        (PROSE + "\n") * 40, "Risk Factors That May Affect Future Results", (PROSE + "\n") * 15,
        "Glossary", "AIF", "Annual Information Form", "MD&A", "Management's Discussion and Analysis", (PROSE + "\n") * 5,
    ])


STATEMENTS = "Management's Statement of Responsibility for Financial Reporting\n" + (PROSE + "\n") * 30


def test_fortyf_exhibits_are_identified_by_title():
    documents = [reports.Document("99.1", aif()), reports.Document("99.2", STATEMENTS), reports.Document("99.3", mdna())]
    found = reports.fortyf_sections(documents, 60_000, 80_000)
    assert found["management_discussion"][0] == "99.3"
    # The glossary's "AIF / Annual Information Form" does not end the MD&A.
    assert found["management_discussion"][1].rstrip().endswith(PROSE)
    assert found["business"][0] == "99.1" and found["business"][1].startswith("General Development of the Business")
    assert "Description of the Business" in found["business"][1] and "Risk Factors" not in found["business"][1]
    # The annual information form only points to the MD&A for its risk factors, so the MD&A's section is used.
    assert found["risk_factors"][0] == "99.3"
    assert found["risk_factors"][1].startswith("Risk Factors That May Affect Future Results")


def test_fortyf_parts_inside_one_document():
    """Canadian Natural files its annual information form, statements and MD&A inside the 40-F itself."""
    combined = "FORM 40-F\n" + aif(pointer_risks=False) + "\nReport of Independent Registered Public Accounting Firm\n" + \
        (PROSE + "\n") * 30 + mdna()
    found = reports.fortyf_sections([reports.Document("40-F", combined)], 60_000, 80_000)
    assert found["management_discussion"][1].startswith("Management's Discussion\nand Analysis")
    assert found["risk_factors"][1].startswith("Risk Factors\n") and "incorporated by reference" not in found["risk_factors"][1]
    assert found["business"][1].startswith("General Development of the Business")


def test_interim_statements_end_a_quarterly_mdna():
    report = mdna() + "\nINTERIM CONSOLIDATED BALANCE SHEET\n" + "Assets 1,000\n" * 3000
    parts = reports.document_parts([reports.Document("6-K", report)])
    assert "INTERIM CONSOLIDATED BALANCE SHEET" not in parts.mdna[1]


def test_tenq_mdna_from_its_contents():
    """JPMorgan's 10-Q lists the MD&A's sections under Item 2 and starts its body with the first of them."""
    text = "\n".join([
        "Part I - Financial information", "Item 1.", "Financial Statements.", "94",
        "Item 2.", "Management's Discussion and Analysis of Financial Condition and Results of Operations.",
        "Consolidated Financial Highlights", "3", "Executive Overview", "5", "Consolidated Balance Sheets Analysis", "15",
        "Item 3.", "Quantitative and Qualitative Disclosures About Market Risk.", "201", "Item 4.", "Controls", "201",
        "JPMorgan Chase & Co.", "Consolidated financial highlights (unaudited)", (PROSE + "\n") * 150,
        "Consolidated balance sheets analysis", (PROSE + "\n") * 80,
        "Consolidated statements of income (unaudited)", "Revenue 100",
    ])
    mdna_text = reports.mdna_from_contents(text)
    assert mdna_text.startswith("Consolidated financial highlights (unaudited)")
    assert "Consolidated balance sheets analysis" in mdna_text and "Revenue 100" not in mdna_text


# --- discovery ---

def rows(*filings):
    payload = submissions_payload("x", [
        {"form": f, "accessionNumber": a, "primaryDocument": "d.htm", "filingDate": fd, "reportDate": rd}
        for f, a, fd, rd, _ in filings])
    payload["filings"]["recent"]["isInlineXBRL"] = [int(tagged) for *_, tagged in filings]
    return payload


def test_tagged_six_ks_are_interim_reports_and_a_same_day_one_joins_its_annual_report():
    payload = rows(
        ("6-K", "q2", "2026-08-27", "2026-07-31", True),
        ("6-K", "press", "2026-08-27", "2026-07-31", False),   # untagged press release: not read
        ("6-K", "q1", "2026-05-28", "2026-04-30", True),
        ("6-K", "statements", "2026-02-04", "2025-12-31", True),  # the annual statements, furnished with the 40-F
        ("40-F", "annual25", "2026-02-04", "2025-12-31", True),
        ("40-F", "annual24", "2025-02-04", "2024-12-31", True),
    )
    found = ingest.discover(payload, annual=2)
    assert [(f["form"], f["accession_number"]) for f in found] == [
        ("40-F", "annual24"), ("40-F", "annual25"), ("6-K", "q1"), ("6-K", "q2")]
    assert [c["accession_number"] for c in found[1]["companions"]] == ["statements"]


def test_history_pages_are_read_until_enough_annual_reports(monkeypatch):
    recent = rows(*[("424B2", f"n{i}", "2026-06-01", "2026-06-01", False) for i in range(5)],
                  ("40-F", "annual25", "2025-12-03", "2025-10-31", True))
    recent["filings"]["files"] = [{"name": "page-001.json"}]
    older = rows(("40-F", "annual24", "2024-12-04", "2024-10-31", True), ("40-F", "annual23", "2023-12-01", "2023-10-31", True))
    fetched = []

    class Response:
        def json(self):
            return older["filings"]["recent"]

    monkeypatch.setattr(ingest.sec, "sec_get", lambda url: fetched.append(url) or Response())
    history = ingest.with_history(recent, annual=3)
    assert fetched == ["https://data.sec.gov/submissions/page-001.json"]
    assert [f["accession_number"] for f in ingest.discover(history, annual=3)] == ["annual23", "annual24", "annual25"]
