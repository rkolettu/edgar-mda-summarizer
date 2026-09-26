import pytest
from fastapi import HTTPException

import sec
from tests.conftest import MDNA_BODY

BANK_CIK = 19617
BANK_ACCESSION = "0000019617-26-000044"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/19617/000001961726000044/0000019617-26-000044-index.htm"
EX13_URL = "https://www.sec.gov/Archives/edgar/data/19617/000001961726000044/corp-ex13.htm"
FILING = {"accession_number": BANK_ACCESSION}


def text_of(html: str) -> str:
    return sec.html_to_text(html)


def test_skips_cross_reference_before_real_heading():
    text = text_of(
        "<p>Item 1. Business. Our strategy is discussed in Part II, Item 7. Management's Discussion and Analysis of "
        "Financial Condition, which you should read.</p>" + "<p>Business detail.</p>" * 200 +
        f"<p>Item 7. Management's Discussion and Analysis</p><p>{MDNA_BODY}</p><p>Item 8. Financial Statements</p>"
    )
    section = sec.extract_item7(text)
    assert section.startswith("Item 7. Management's Discussion and Analysis Net sales increased")
    assert "Business detail" not in section


def test_cross_reference_to_item8_does_not_truncate():
    text = text_of(
        f"<p>Item 7. Management's Discussion and Analysis</p><p>{MDNA_BODY}</p>"
        "<p>For more detail, see Item 8. Financial Statements and Supplementary Data, Note 4.</p>"
        "<p>Liquidity remained strong with $132 billion of cash and marketable securities.</p>"
        "<p>Item 8. Financial Statements and Supplementary Data</p>"
    )
    section = sec.extract_item7(text)
    assert "Liquidity remained strong" in section


def test_item8_heading_without_period():
    text = text_of(f"<p>Item 7 Management's Discussion and Analysis</p><p>{MDNA_BODY}</p><p>Item 8 Financial Statements</p>")
    assert sec.extract_item7(text) is not None


def test_short_section_is_rejected():
    text = text_of("<p>Item 7. Management's Discussion and Analysis</p><p>See the annual report.</p><p>Item 8. Financial Statements</p>")
    assert sec.extract_item7(text) is None


def bank_10k_text():
    return text_of(
        "<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations. "
        "The information required by this item is incorporated herein by reference to the 2025 Annual Report.</p>"
        "<p>Item 8. Financial Statements and Supplementary Data</p>"
    )


def index_html(rows):
    body = "".join(
        f'<tr><td>{i}</td><td>{desc}</td><td><a href="{href}">{href.rsplit("/", 1)[-1]}</a></td><td>{kind}</td><td>1</td></tr>'
        for i, (desc, href, kind) in enumerate(rows, 1)
    )
    return f'<table class="tableFile" summary="Document Format Files"><tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>{body}</table>'


def ex13_html():
    return (
        "<p>Contents: Management's discussion and analysis of financial condition 50 "
        "Report of independent registered public accounting firm 160</p>"
        "<p>Management's discussion and analysis of financial condition and results of operations</p>"
        f"<p>{MDNA_BODY}</p><p>Net interest income rose 9%.</p>"
        "<p>Management's report on internal control over financial reporting</p><p>Controls text.</p>"
        "<p>Report of Independent Registered Public Accounting Firm</p>"
    )


def test_exhibit13_fallback(fake_sec):
    fake_sec.add_text(INDEX_URL, index_html([
        ("10-K", "/ix?doc=/Archives/edgar/data/19617/000001961726000044/corp-10k.htm", "10-K"),
        ("Annual report", "/Archives/edgar/data/19617/000001961726000044/corp-ex13.htm", "EX-13"),
        ("Subsidiaries", "/Archives/edgar/data/19617/000001961726000044/corp-ex21.htm", "EX-21"),
    ]))
    fake_sec.add_text(EX13_URL, ex13_html())

    mdna = sec.extract_mdna(BANK_CIK, FILING, bank_10k_text(), "https://doc")
    assert mdna["source"] == "exhibit13"
    assert mdna["url"] == EX13_URL
    assert mdna["text"].startswith("Management's discussion and analysis of financial condition and results")
    assert "Net interest income rose 9%" in mdna["text"]
    assert "Controls text" not in mdna["text"]


def test_item7_points_to_inline_mdna_later_in_10k(fake_sec):
    filing_text = text_of(
        "<p>Item 7. Management's Discussion and Analysis of Financial Condition. 33 "
        "Item 8. Financial Statements. 34</p>"
        "<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations. "
        "Management's discussion and analysis appears on pages 46-160.</p>"
        "<p>Item 8. Financial Statements and Supplementary Data.</p>"
        "<p>Management's discussion and analysis</p>"
        "<p>The following is Management's discussion and analysis of the financial condition and results of operations.</p>"
        f"<p>{MDNA_BODY}</p>"
        "<p>Management's report on internal control over financial reporting</p>"
        "<p>Audited financial statements.</p>"
    )
    mdna = sec.extract_mdna(BANK_CIK, FILING, filing_text, "https://doc")
    assert mdna["source"] == "item7"
    assert mdna["url"] == "https://doc"
    assert "Net sales increased 8%" in mdna["text"]
    assert "Audited financial statements" not in mdna["text"]
    assert "Management's discussion and analysis appears on pages" not in mdna["text"]
    assert fake_sec.calls == []


def test_exhibit_type_match_is_prefix(fake_sec):
    fake_sec.add_text(INDEX_URL, index_html([("Annual report", "/Archives/edgar/data/19617/000001961726000044/corp-ex13.htm", "EX-13.1")]))
    assert sec.find_exhibit(BANK_CIK, BANK_ACCESSION, "EX-13") == EX13_URL


def test_no_exhibit_rejects_unrelated_filing_text(fake_sec):
    fake_sec.add_text(INDEX_URL, index_html([("10-K", "/Archives/edgar/data/19617/000001961726000044/corp-10k.htm", "10-K")]))
    with pytest.raises(HTTPException, match="Could not isolate MD&A") as exc:
        sec.extract_mdna(BANK_CIK, FILING, bank_10k_text(), "https://doc")
    assert exc.value.status_code == 422


def test_missing_index_page_rejects_unrelated_filing_text(fake_sec):
    with pytest.raises(HTTPException, match="Could not isolate MD&A"):
        sec.extract_mdna(BANK_CIK, FILING, bank_10k_text(), "https://doc")


def test_unparseable_exhibit_does_not_claim_to_be_mdna(fake_sec):
    fake_sec.add_text(INDEX_URL, index_html([("Annual report", "/Archives/edgar/data/19617/000001961726000044/corp-ex13.htm", "EX-13")]))
    fake_sec.add_text(EX13_URL, "<p>Annual report without a recognizable MD&A section.</p>")
    with pytest.raises(HTTPException, match="Could not isolate MD&A"):
        sec.extract_mdna(BANK_CIK, FILING, bank_10k_text(), "https://doc")


def test_extracts_item_1a_risk_factors():
    from tests.conftest import ten_k_html

    risks = sec.extract_risk_factors(text_of(ten_k_html()))
    assert risks.startswith("Item 1A. Risk Factors The Company's operations are subject to tariffs")
    assert "Unresolved Staff Comments" not in risks


def test_risk_factors_capped():
    from tests.conftest import ten_k_html

    risks = sec.extract_risk_factors(text_of(ten_k_html(risk_body="Risk sentence about demand. " * 5000)))
    assert len(risks) == sec.RISK_FACTORS_CHARS


def test_smaller_reporting_company_without_risk_factors():
    text = text_of("<p>Item 1A. Risk Factors</p><p>Not applicable.</p><p>Item 1B. Unresolved Staff Comments</p>")
    assert sec.extract_risk_factors(text) is None


def test_heading_followed_by_intro_cross_reference_is_not_toc():
    text = text_of(
        "<p>Item 7. Management's Discussion and Analysis</p>"
        "<p>Read this with Item 8. Financial Statements and Supplementary Data.</p>"
        f"<p>{MDNA_BODY}</p><p>Item 8. Financial Statements</p>"
    )
    section = sec.extract_item7(text)
    assert section is not None and "Net sales increased" in section


def test_toc_entry_detection():
    toc = text_of("<p>Item 1A. Risk Factors 12 Item 1B. Unresolved Staff Comments 25</p>")
    start = sec.ITEM1A_START.search(toc)
    assert sec.is_toc_entry(toc, start.end())


def test_split_item_heading_as_in_manhattan_associates():
    text = text_of(
        "<p>Item 7 Management's Discussion and Analysis 29 Item 7A Quantitative 40 Item 8 Financial Statements 41</p>"
        f"<p>It em 7. Management's Discussion and Analysis of Financial Condition and Results of Operations {MDNA_BODY}</p>"
        "<p>It em 7A. Quantitative and Qualitative Disclosures About Market Risk</p>"
        "<p>It em 8. Financial Statements and Supplementary Data</p>"
    )
    section = sec.extract_item7(text)
    assert section.startswith("It em 7. Management's Discussion")
    assert "Quantitative and Qualitative Disclosures" not in section


def test_split_quarterly_heading_as_in_manhattan_associates():
    text = text_of(
        "<p>Item 2. Management's Discussion and Analysis 15 Item 3. Quantitative 28</p>"
        f"<p>I tem 2. Management's Discussion and Analysis of Financial Condition and Results of Operations. {MDNA_BODY}</p>"
        "<p>I tem 3. Quantitative and Qualitative Disclosures About Market Risk</p>"
    )
    section = sec.extract_section(text, sec.TENQ_MDNA_START, sec.TENQ_MDNA_END)
    assert section.startswith("I tem 2. Management's Discussion")
    assert "Quantitative and Qualitative Disclosures" not in section


def test_ubs_20f_embedded_annual_report(fake_sec):
    filing = {"form": "20-F", "accession_number": "0001610520-26-000023", "primary_doc": "ubs.htm"}
    url = sec.archive_url(1610520, filing["accession_number"], filing["primary_doc"])
    fake_sec.add_text(url, (
        "<p>Item 5. Operating and Financial Review and Prospects. Incorporated by reference to the annual report.</p>"
        "<p>Item 6. Directors, Senior Management and Employees</p>"
        "<p>Risk factors Certain risks, including those described below, may affect our business. " + "Risk detail. " * 100 + "</p>"
        "<p>Annual Report 2025 | Financial and operating performance | Accounting and financial reporting 62 "
        "Financial and operating performance Management report " + "Operating profit increased. " * 250 + "</p>"
        "<p>Annual Report 2025 | Risk, capital, liquidity and funding, and balance sheet 86 Risk, capital</p>"
    ))
    result = sec.load_20f(1610520, filing)
    assert result["mdna"]["source"] == "operating_review"
    assert "Operating profit increased" in result["mdna"]["text"]
    assert "Incorporated by reference" not in result["mdna"]["text"]
    assert result["risk_factors"].startswith("Risk factors Certain risks")


def test_40f_uses_only_referenced_mdna_exhibit(fake_sec):
    filing = {"form": "40-F", "accession_number": BANK_ACCESSION, "primary_doc": "bank40f.htm"}
    url = sec.archive_url(BANK_CIK, BANK_ACCESSION, filing["primary_doc"])
    exhibit = sec.archive_url(BANK_CIK, BANK_ACCESSION, "mdna.htm")
    fake_sec.add_text(url, "<p>Exhibit 99.2: Management's Discussion and Analysis is incorporated by reference.</p>")
    fake_sec.add_text(INDEX_URL, index_html([
        ("Annual financial statements", "/Archives/edgar/data/19617/000001961726000044/statements.htm", "EX-99.3"),
        ("Management discussion", "/Archives/edgar/data/19617/000001961726000044/mdna.htm", "EX-99.2"),
    ]))
    fake_sec.add_text(exhibit, "<p>Management's Discussion and Analysis This Management's Discussion and Analysis (MD&A) presents Canadian dollars. " + MDNA_BODY + "</p>")
    result = sec.load_40f(BANK_CIK, filing)
    assert result["mdna"]["url"] == exhibit
    assert result["mdna"]["source"] == "mdna_exhibit"
    assert result["currency"] == "CAD"


def test_40f_rejects_financial_statement_exhibit(fake_sec):
    filing = {"form": "40-F", "accession_number": BANK_ACCESSION, "primary_doc": "bank40f.htm"}
    url = sec.archive_url(BANK_CIK, BANK_ACCESSION, filing["primary_doc"])
    exhibit = sec.archive_url(BANK_CIK, BANK_ACCESSION, "mdna.htm")
    fake_sec.add_text(url, "<p>Management's Discussion and Analysis is in Exhibit 99.2.</p>")
    fake_sec.add_text(INDEX_URL, index_html([("Statements", "/Archives/edgar/data/19617/000001961726000044/mdna.htm", "EX-99.2")]))
    fake_sec.add_text(exhibit, "<p>Consolidated statements of income. " + MDNA_BODY + "</p>")
    with pytest.raises(HTTPException, match="Could not verify"):
        sec.load_40f(BANK_CIK, filing)


def test_40f_prefers_exhibit_index_row_over_a_sentence_listing_several_exhibits(fake_sec):
    # Suncor's cover sentence lists the AIF, statements and MD&A "included as Exhibit 99-1, Exhibit 99-2, Exhibit 99-3".
    filing = {"form": "40-F", "accession_number": BANK_ACCESSION, "primary_doc": "bank40f.htm"}
    url = sec.archive_url(BANK_CIK, BANK_ACCESSION, filing["primary_doc"])
    aif = sec.archive_url(BANK_CIK, BANK_ACCESSION, "aif.htm")
    exhibit = sec.archive_url(BANK_CIK, BANK_ACCESSION, "mdna.htm")
    fake_sec.add_text(url, (
        "<p>The Annual Information Form, Audited Consolidated Financial Statements, Management's Discussion and Analysis for "
        "the year ended December 31, 2025, included as Exhibit 99-1, Exhibit 99-2, Exhibit 99-3, are incorporated.</p>"
        "<table><tr><td>99-1</td><td>Annual Information Form</td></tr>"
        "<tr><td>99-3</td><td>\u200b Management's Discussion and Analysis for the fiscal year ended December 31, 2025</td></tr></table>"
    ))
    fake_sec.add_text(INDEX_URL, index_html([
        ("AIF", "/Archives/edgar/data/19617/000001961726000044/aif.htm", "EX-99.1"),
        ("MD&A", "/Archives/edgar/data/19617/000001961726000044/mdna.htm", "EX-99.3"),
    ]))
    fake_sec.add_text(aif, "<p>Annual Information Form. " + MDNA_BODY + "</p>")
    fake_sec.add_text(exhibit, (
        "<p>Management's Discussion and Analysis</p><p>\u200bFebruary 25, 2026\u200b</p>"
        "<p>This Management's Discussion and Analysis (MD&A) is in Canadian dollars. " + MDNA_BODY + "</p>"
    ))
    result = sec.load_40f(BANK_CIK, filing)
    assert result["mdna"]["url"] == exhibit
    assert "\u200b" not in result["mdna"]["text"]


def test_40f_falls_back_to_the_next_candidate_exhibit(fake_sec):
    filing = {"form": "40-F", "accession_number": BANK_ACCESSION, "primary_doc": "bank40f.htm"}
    url = sec.archive_url(BANK_CIK, BANK_ACCESSION, filing["primary_doc"])
    wrong = sec.archive_url(BANK_CIK, BANK_ACCESSION, "statements.htm")
    exhibit = sec.archive_url(BANK_CIK, BANK_ACCESSION, "mdna.htm")
    fake_sec.add_text(url, (
        "<table><tr><td>99.3</td><td>Management's Discussion and Analysis</td></tr></table>"
        "<p>Exhibit 99.2: Management's Discussion and Analysis is incorporated by reference.</p>"
    ))
    fake_sec.add_text(INDEX_URL, index_html([
        ("Statements", "/Archives/edgar/data/19617/000001961726000044/statements.htm", "EX-99.3"),
        ("MD&A", "/Archives/edgar/data/19617/000001961726000044/mdna.htm", "EX-99.2"),
    ]))
    fake_sec.add_text(wrong, "<p>Consolidated statements of income. " + MDNA_BODY + "</p>")
    fake_sec.add_text(exhibit, "<p>Management's Discussion and Analysis This Management's Discussion and Analysis covers 2025. " + MDNA_BODY + "</p>")
    assert sec.load_40f(BANK_CIK, filing)["mdna"]["url"] == exhibit


TSMC_ITEM5_BODY = (
    "Net revenue increased 31.6% to NT$3,809.05 billion in 2025 from NT$2,894.31 billion in 2024. "
    "Gross margin was 59.9%, and capital expenditures were NT$1,269.9 billion (US$40.1 billion). "
) * 40


def tsmc_style_20f(item5_heading="ITEM 5. OPERATING AND FINANCIAL REVIEWS AND PROSPECTS"):
    return (
        "<p>ITEM 3. KEY INFORMATION 3 ITEM 4. INFORMATION ON THE COMPANY 14 ITEM 4A. UNRESOLVED STAFF COMMENTS 26 "
        "ITEM 5. OPERATING AND FINANCIAL REVIEWS AND PROSPECTS 26 ITEM 6. DIRECTORS, SENIOR MANAGEMENT AND EMPLOYEES 37</p>"
        "<p>ITEM 3. KEY INFORMATION Capitalization and Indebtedness Not applicable. Risk Factors We wish to caution readers "
        "about the following important factors. " + "Export controls could limit sales to certain customers. " * 60 +
        'See "Item 5. Operating and Financial Reviews and Prospects – Taxation" for further discussion.</p>'
        "<p>ITEM 4. INFORMATION ON THE COMPANY Our History and Structure. We manufacture semiconductors.</p>"
        f"<p>ITEM 4A. UNRESOLVED STAFF COMMENTS None. {item5_heading} The following discussion covers 2025 and 2024. "
        + TSMC_ITEM5_BODY + "</p><p>ITEM 6. DIRECTORS, SENIOR MANAGEMENT AND EMPLOYEES Directors.</p>"
    )


def load_20f_text(fake_sec, html):
    filing = {"form": "20-F", "accession_number": "0001628280-26-025362", "primary_doc": "tsm-20251231.htm"}
    fake_sec.add_text(sec.archive_url(1046179, filing["accession_number"], filing["primary_doc"]), html)
    return sec.load_20f(1046179, filing)


def test_20f_plural_reviews_heading_as_in_tsmc(fake_sec):
    result = load_20f_text(fake_sec, tsmc_style_20f())
    assert result["mdna"]["text"].startswith("ITEM 5. OPERATING AND FINANCIAL REVIEWS AND PROSPECTS The following")
    assert "DIRECTORS" not in result["mdna"]["text"]
    assert result["currency"] == "TWD"
    assert result["risk_factors"].startswith("Risk Factors We wish to caution")
    assert "Our History and Structure" not in result["risk_factors"]


def test_20f_heading_with_words_split_by_markup(fake_sec):
    result = load_20f_text(fake_sec, tsmc_style_20f("ITEM 5. OPERATING AND FINAN CIAL REVIEW AND PROSPECTS"))
    assert "NT$3,809.05 billion" in result["mdna"]["text"]


def test_quoted_section_reference_is_not_a_heading():
    body = "Revenue grew on strong demand for oncology medicines. " * 60
    text = text_of(
        '<p>These statements are prepared under IFRS. "Item 5. Operating and Financial Review and Prospects," together with '
        "the pipeline sections, discusses results. " + "Pipeline detail. " * 300 + "</p>"
        "<p>Item 4A. Unresolved Staff Comments Not applicable. Item 5. Operating and Financial Review and Prospects You should "
        "read the following discussion with our financial statements included at Item 18. of this annual report. " + body + "</p>"
        "<p>Item 6. Directors, Senior Management and Employees</p>"
    )
    section = sec.extract_section(text, sec.TWENTYF_START, sec.TWENTYF_END)
    assert section.startswith("Item 5. Operating and Financial Review and Prospects You should read")
    assert "Pipeline detail" not in section


@pytest.mark.parametrize("text, expected", [
    ("Revenues were RMB134.5 billion (US$18.4 billion), up from RMB133.1 billion. " * 5, "CNY"),
    ("Net revenue was NT$3,809.05 billion (US$120.4 billion) versus NT$2,894.31 billion. " * 5, "TWD"),
    ("Revenue was $416.2 billion and Services revenue was $109.2 billion. " * 5, "USD"),
    ("Sales in Europe grew 4% to €21.3 billion from €20.5 billion. " * 5, "EUR"),
    ("Operating income was ¥4,795.6 billion. Europe and European markets were stable. " * 5, "JPY"),
    ("Reference is made to the annual report. Sales of $1 were minor.", "unknown"),
])
def test_detect_currency(text, expected):
    assert sec.detect_currency(text) == expected


def test_item7_heading_with_pipe_separator_as_in_aig():
    text = text_of(
        "<p>ITEM 6 [Reserved] 33 ITEM 7 Management's Discussion and Analysis of Financial Condition and Results of Operations 34 "
        "ITEM 7A Quantitative and Qualitative Disclosures About Market Risk 110</p>"
        f"<p>ITEM 7 | Management's Discussion and Analysis of Financial Condition and Results of Operations</p><p>{MDNA_BODY}</p>"
        "<p>ITEM 7A | Quantitative and Qualitative Disclosures About Market Risk</p>"
    )
    assert sec.extract_item7(text).startswith("ITEM 7 | Management's Discussion")


def test_item7_heading_with_company_name_as_in_bank_of_america():
    text = text_of(
        "<p>Item 7. Bank of America Corporation and Subsidiaries Management's Discussion and Analysis of Financial Condition "
        f"and Results of Operations</p><p>{MDNA_BODY}</p><p>Item 7A. Quantitative and Qualitative Disclosures about Market Risk</p>"
    )
    assert "Net sales increased 8%" in sec.extract_item7(text)


def annual_report_style_10k():
    return text_of(
        "<p>CONTENTS Overview 4 MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS 8 "
        "Executive Summary 8 Recent Developments 11</p>"
        "<p>Our results are discussed in the section titled Management's Discussion and Analysis of Financial Condition "
        'and Results of Operations. See "Management\'s Discussion and Analysis" for segment detail. ' + "Business detail. " * 200 + "</p>"
        "<p>Reports may be viewed at www.sec.gov.</p>"
        f"<p>MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS EXECUTIVE SUMMARY</p><p>{MDNA_BODY}</p>"
        "<p>MANAGEMENT'S DISCUSSION OF FINANCIAL RESPONSIBILITY Management is responsible for the statements.</p>"
        "<p>REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM</p><p>Audited financial statements.</p>"
        "<p>Form 10-K Cross-Reference Index 7. Management's Discussion and Analysis of Financial Condition and Results of "
        "Operations 8-36, 64-120 7A. Quantitative and Qualitative Disclosures About Market Risk 90-110</p>"
    )


def test_annual_report_style_10k_without_item7_heading(fake_sec):
    mdna = sec.extract_mdna(BANK_CIK, FILING, annual_report_style_10k(), "https://doc")
    assert mdna["source"] == "item7"
    assert mdna["text"].startswith("MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS EXECUTIVE")
    assert "Net sales increased 8%" in mdna["text"]
    assert "Business detail" not in mdna["text"]
    assert "Audited financial statements" not in mdna["text"]


def test_heading_position_rules():
    text = "Reports may be viewed at www.sec.gov. Management's Discussion and Analysis Overview Our results improved."
    start = text.index("Management's")
    assert sec.is_heading_position(text, start, start + 37)
    reference = "as described in the section titled Management's Discussion and Analysis of results."
    start = reference.index("Management's")
    assert not sec.is_heading_position(reference, start, start + 37)
    toc = "About Us 4 Management's Discussion and Analysis 7 Consolidated Results 8 Segment Operations 9"
    start = toc.index("Management's")
    assert not sec.is_heading_position(toc, start, start + 37)
    assert sec.MDNA_TITLE.search("MANAGEMENT'S DISCUSSION OF FINANCIAL RESPONSIBILITY") is None


def test_exhibit13_section_named_by_item7_pointer_as_in_wells_fargo(fake_sec):
    fake_sec.add_text(INDEX_URL, index_html([
        ("Annual report", "/Archives/edgar/data/19617/000001961726000044/corp-ex13.htm", "EX-13"),
    ]))
    fake_sec.add_text(EX13_URL, (
        "<p>Exhibit 13 Financial Review 2 Overview 2 Earnings Performance 5 Risk Management 20</p>"
        "<p>This Annual Report, including the Financial Review and the Financial Statements, contains forward-looking statements. "
        + "Forward-looking detail. " * 100 + "</p>"
        f"<p>Financial Review Overview</p><p>{MDNA_BODY}</p>"
        "<p>Management's Report on Internal Control over Financial Reporting</p><p>Controls text.</p>"
    ))
    filing_text = text_of(
        "<p>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS Information in "
        'response to this Item 7 can be found in the 2025 Annual Report to Shareholders under "Financial Review." That '
        "information is incorporated into this Item by reference.</p><p>ITEM 8. FINANCIAL STATEMENTS</p>"
    )
    mdna = sec.extract_mdna(BANK_CIK, FILING, filing_text, "https://doc")
    assert mdna["source"] == "exhibit13"
    assert mdna["text"].startswith("Financial Review Overview")
    assert "Forward-looking detail" not in mdna["text"]
    assert "Controls text" not in mdna["text"]


def test_exhibit13_management_discussion_title_as_in_ibm(fake_sec):
    fake_sec.add_text(INDEX_URL, index_html([
        ("Annual report", "/Archives/edgar/data/19617/000001961726000044/corp-ex13.htm", "EX-13"),
    ]))
    fake_sec.add_text(EX13_URL, (
        "<p>Exhibit 13 5 MANAGEMENT DISCUSSION NOTES TO FINANCIAL STATEMENTS Overview 6 Policies 7 Snapshot 8</p>"
        f"<p>Table of Contents 6 Management Discussion International Business Machines Corporation OVERVIEW</p><p>{MDNA_BODY}</p>"
        "<p>Management's Report on Internal Control Over Financial Reporting</p>"
    ))
    filing_text = text_of(
        "<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations: Refer to pages 6 "
        "through 38 of the 2025 Annual Report.</p><p>Item 8. Financial Statements</p>"
    )
    mdna = sec.extract_mdna(BANK_CIK, FILING, filing_text, "https://doc")
    assert mdna["text"].startswith("Management Discussion International Business Machines")


def test_predecessor_registrant_from_successor_8k12b(fake_sec):
    successor = {"cik": 2115436, "filings": {"recent": {
        "form": ["8-K12B"], "accessionNumber": ["0001193125-26-291990"], "primaryDocument": ["d8k12b.htm"],
        "filingDate": ["2026-07-01"], "reportDate": ["2026-07-01"],
    }}}
    fake_sec.add_text(
        sec.archive_url(2115436, "0001193125-26-291990", "d8k12b.htm"),
        "<p>Explanatory Note On July 1, 2026, Exxon Mobil Corporation, a New Jersey corporation and the predecessor "
        'registrant ("ExxonMobil"), completed its previously announced redomiciliation reorganization.</p>',
    )
    fake_sec.add_text(
        sec.COMPANY_SEARCH_URL.format(name="Exxon+Mobil+Corp"),
        "<feed><company-info><cik>0000034088</cik><conformed-name>EXXON MOBIL CORP</conformed-name></company-info></feed>",
    )
    assert sec.find_predecessor_cik(successor) == 34088


def test_no_predecessor_without_reorganization_filing(fake_sec):
    assert sec.find_predecessor_cik({"cik": 1, "filings": {"recent": {"form": ["8-K"]}}}) is None


REVIEW_BODY = "In 2025, we recorded net income of US$1,983 million, compared to US$2,100 million in 2024. " * 200


def index_style_20f():
    return (
        "<p>TABLE OF CONTENTS III. OPERATING AND FINANCIAL REVIEW AND PROSPECTS 129 Overview 129 Results of Operations 133 "
        "IV. CORPORATE GOVERNANCE 160</p>"
        "<p>See Operating and Financial Review and Prospects—Liquidity and Capital Resources. " + "Business detail. " * 400 + "</p>"
        "<p>Business overview Corporate governance Financial statements Operating and financial review and prospects General "
        "facts Financial statements Other information " + "Governance detail. " * 1200 + "</p>"
        f"<p>Table of Contents OPERATING AND FINANCIAL REVIEW AND PROSPECTS Overview {REVIEW_BODY}</p>"
        "<p>IV. CORPORATE GOVERNANCE Board of Directors. " + "Board detail. " * 100 + "</p>"
        "<p>Form 20-F cross reference 4A Unresolved staff comments None 5 Operating and financial review and prospects "
        "5A Operating results Results of Operations 133 5B Liquidity and capital resources 150 6 Directors, senior management</p>"
    )


def test_20f_indexing_an_integrated_annual_report_as_in_vale(fake_sec):
    result = load_20f_text(fake_sec, index_style_20f())
    assert result["mdna"]["source"] == "annual_report"
    assert result["mdna"]["text"].startswith("OPERATING AND FINANCIAL REVIEW AND PROSPECTS Overview In 2025")
    assert "Governance detail" not in result["mdna"]["text"]
    assert "Board detail" not in result["mdna"]["text"]
    assert result["currency"] == "USD"


def test_cross_reference_index_is_not_the_review():
    assert sec.looks_like_index("A. Operating results 23-30, 36-41, 45-88, 276-288 B. Liquidity 12 C. Research 14 D. Trends 88")
    assert sec.looks_like_index(
        "5A Operating Results Business overview—Strategy; General facts—Alternative measures; Operating and financial "
        "review—Results of segments; Financial statements—Note 2; Operating and financial review—Liquidity; Other—Risks;"
    )
    assert not sec.looks_like_index(REVIEW_BODY)


def test_20f_review_in_annual_report_exhibit_as_in_astrazeneca(fake_sec):
    accession = "0001104659-26-019130"
    index_url = sec.FILING_INDEX_URL.format(cik=901832, accession_no_dashes=accession.replace("-", ""), accession=accession)
    exhibit_url = "https://www.sec.gov/Archives/edgar/data/901832/000110465926019130/azn-ex15d1.htm"
    fake_sec.add_text(index_url, index_html([("Annual Report", "/Archives/edgar/data/901832/000110465926019130/azn-ex15d1.htm", "EX-15.1")]))
    nav = "Strategic Report Corporate Governance Financial Statements Sustainability Statement Additional Information "
    fake_sec.add_text(exhibit_url, (
        f"<p>{nav}Financial Review Business background and results overview {REVIEW_BODY}</p>"
        f"<p>{nav}Financial Review Financial Review continued {REVIEW_BODY}</p>"
        "<p>Corporate Governance Contents Chair's Introduction. " + "Governance detail. " * 100 + "</p>"
    ))
    filing = {"form": "20-F", "accession_number": accession, "primary_doc": "azn-20f.htm"}
    fake_sec.add_text(sec.archive_url(901832, accession, "azn-20f.htm"), (
        '<p>ITEM 5. OPERATING AND FINANCIAL REVIEW AND PROSPECTS The information set forth under the headings "Strategic '
        'Report—Financial Review" on pages 50 to 64 of the Annual Report included as exhibit 15.1 to this Form 20-F is '
        "incorporated by reference.</p><p>ITEM 6. DIRECTORS, SENIOR MANAGEMENT AND EMPLOYEES</p>"
    ))
    result = sec.load_20f(901832, filing)
    assert result["mdna"]["url"] == exhibit_url
    assert result["document_url"].endswith("azn-20f.htm")
    assert result["mdna"]["text"].startswith("Financial Review Business background")
    assert "Governance detail" not in result["mdna"]["text"]


def test_business_and_spaced_risk_factor_headings():
    filler = "We design software and cloud services for businesses and consumers around the world. " * 40
    html = (
        "<html><body><p>Item 1. Business 3</p><p>Item 1A. Risk Factors 14</p><p>Item 1B. Unresolved Staff Comments 29</p>"
        f"<p>ITEM 1. B USINESS</p><p>GENERAL</p><p>{filler}</p>"
        f"<p>ITEM 1A. RIS K FACTORS</p><p>{filler}</p><p>ITEM 1B. UNRESOL VED STAFF COMMENTS</p><p>None.</p>"
        "<p>ITEM 2. PROPERTIES</p></body></html>"
    )
    text = sec.html_to_text(html)
    assert sec.extract_business(text).startswith("ITEM 1. B USINESS GENERAL We design")
    assert sec.extract_risk_factors(text).startswith("ITEM 1A. RIS K FACTORS We design")
    with sec.keeping_lines():
        lines = sec.html_to_text(html)
    assert sec.extract_business(lines).startswith("ITEM 1. B USINESS\nGENERAL\nWe design")
    assert "\n" not in sec.html_to_text(html)  # the legacy summary still reads one line
