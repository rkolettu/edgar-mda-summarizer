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
