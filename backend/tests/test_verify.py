import pytest

from verify import annotate, normalize, quote_in_source, segment_check

SOURCE = normalize(
    "Services net sales increased 14% during 2025 compared to 2024 due primarily to higher net sales "
    "from advertising, the App Store® and cloud services. Gross margin percentage was 46.9%."
)


@pytest.mark.parametrize(
    "quote",
    [
        "Services net sales increased 14% during 2025 compared to 2024",
        "services   NET sales increased 14 % during 2025 compared to 2024",
        "“Services net sales increased 14% during 2025 compared to 2024 due primarily to higher net sales”",
        "Services net sales increased 14% during 2025 ... from advertising, the App Store and cloud services",
        "Services net sales increased 14% during 2025 … Gross margin percentage was 46.9%",
    ],
)
def test_verbatim_quotes_verify(quote):
    assert quote_in_source(quote, SOURCE)


@pytest.mark.parametrize(
    "quote",
    [
        "Services net sales increased 15% during 2025 compared to 2024",
        "Services revenue rose sharply thanks to advertising growth",
        "Gross margin 46.9%",
        "",
        "Services net sales increased 14% during 2025 ... driven by record iPhone demand in China",
    ],
)
def test_paraphrased_or_fabricated_quotes_fail(quote):
    assert not quote_in_source(quote, SOURCE)


def test_annotate_adds_verified_flag():
    out = annotate([{"headline": "h", "detail": "d", "evidence": "Gross margin percentage was 46.9%."}], SOURCE)
    assert out == [{"headline": "h", "detail": "d", "evidence": "Gross margin percentage was 46.9%.", "verified": True}]


def test_segment_check_reconciles_within_tolerance():
    result = segment_check([{"name": "A", "value": 300.0}, {"name": "B", "value": 110.0}], 416.2)
    assert result["reconciles"] is True
    assert result["difference"] == pytest.approx(410 / 416.2 - 1)


def test_segment_check_flags_double_counting():
    result = segment_check([{"name": "Americas", "value": 170.0}, {"name": "iPhone", "value": 209.6}, {"name": "Services", "value": 109.2}], 416.2)
    assert result["reconciles"] is False


def test_segment_check_needs_both_numbers():
    assert segment_check([], 416.2) is None
    assert segment_check([{"name": "A", "value": 1.0}], None) is None
