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
