import pytest

import sec


@pytest.mark.parametrize(
    "query, expected",
    [
        ("apple", ["AAPL", "APLE"]),
        ("AAPL", ["AAPL"]),
        ("aap", ["AAPL"]),
        ("app", ["APP", "AAPL", "APLE"]),
        ("alphabet", ["GOOGL", "GOOG"]),
        ("brk.b", ["BRK-B"]),
        ("berkshire", ["BRK-B"]),
        ("jp morgan", ["JPM"]),
        ("chase", ["JPM"]),
        ("ma", ["MA"]),
        ("zzzz", []),
        ("  ", []),
    ],
)
def test_search_ranking(client, query, expected):
    res = client.get("/api/search", params={"q": query, "limit": 5})
    assert res.status_code == 200
    assert [r["ticker"] for r in res.json()] == expected


@pytest.mark.parametrize("query, ticker", [("apple", "AAPL"), ("Microsoft", "MSFT"), ("brk.b", "BRK-B"), ("nvda", "NVDA")])
def test_resolve_company(fake_sec, query, ticker):
    assert sec.resolve_company(query)["ticker"] == ticker


def test_resolve_unknown_company(fake_sec):
    with pytest.raises(Exception) as exc:
        sec.resolve_company("zzzz")
    assert "No SEC-registered company matches" in exc.value.detail
