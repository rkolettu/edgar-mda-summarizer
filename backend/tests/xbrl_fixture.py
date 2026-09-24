"""Builds a companyfacts payload shaped like data.sec.gov/api/xbrl/companyfacts/CIK##########.json."""

from __future__ import annotations

from datetime import date, timedelta

FY_ENDS = ["2019-09-28", "2020-09-26", "2021-09-25", "2022-09-24", "2023-09-30", "2024-09-28", "2025-09-27"]


def _start(end: str) -> str:
    # 52/53-week fiscal years: start the day after the prior fiscal year end.
    idx = FY_ENDS.index(end)
    if idx == 0:
        return (date.fromisoformat(end) - timedelta(days=364)).isoformat()
    return (date.fromisoformat(FY_ENDS[idx - 1]) + timedelta(days=1)).isoformat()


def _filed(end: str) -> str:
    return (date.fromisoformat(end) + timedelta(days=35)).isoformat()


def annual(end: str, val: float, filed: str | None = None, form: str = "10-K") -> dict:
    return {"start": _start(end), "end": end, "val": val, "form": form, "filed": filed or _filed(end), "fy": int(end[:4]), "fp": "FY"}


def instant(end: str, val: float) -> dict:
    return {"end": end, "val": val, "form": "10-K", "filed": _filed(end), "fy": int(end[:4]), "fp": "FY"}


def quarter(start: str, end: str, val: float) -> dict:
    return {"start": start, "end": end, "val": val, "form": "10-Q", "filed": _filed(end), "fy": int(end[:4]), "fp": "Q1"}


def concept(entries: list[dict], unit: str = "USD") -> dict:
    return {"label": "x", "description": "x", "units": {unit: entries}}


B = 1e9

REVENUE = {"2021-09-25": 365.8, "2022-09-24": 394.3, "2023-09-30": 383.3, "2024-09-28": 391.0, "2025-09-27": 416.2}


def apple_companyfacts() -> dict:
    revenue_new = [annual(end, v * B) for end, v in REVENUE.items()]
    # A later 10-K restated FY2024 revenue; the latest filing must win.
    revenue_new.append(annual("2024-09-28", 391.035 * B, filed="2025-10-31"))
    # Noise that must be ignored: a quarterly 10-Q figure and a Q4-only duration inside a 10-K.
    revenue_new.append(quarter("2025-06-29", "2025-09-27", 102.5 * B))
    revenue_new.append({**annual("2025-09-27", 102.5 * B), "start": "2025-06-29"})

    us_gaap = {
        "SalesRevenueNet": concept([annual("2019-09-28", 260.2 * B), annual("2020-09-26", 274.5 * B)]),
        "RevenueFromContractWithCustomerExcludingAssessedTax": concept(revenue_new),
        "GrossProfit": concept([annual(e, v * B) for e, v in {"2021-09-25": 152.8, "2022-09-24": 170.8, "2023-09-30": 169.1, "2024-09-28": 180.7, "2025-09-27": 195.2}.items()]),
        "OperatingIncomeLoss": concept([annual(e, v * B) for e, v in {"2021-09-25": 108.9, "2022-09-24": 119.4, "2023-09-30": 114.3, "2024-09-28": 123.2, "2025-09-27": 133.1}.items()]),
        "NetIncomeLoss": concept([annual(e, v * B) for e, v in {"2021-09-25": 94.7, "2022-09-24": 99.8, "2023-09-30": 97.0, "2024-09-28": 93.7, "2025-09-27": 112.0}.items()]),
        "NetCashProvidedByUsedInOperatingActivities": concept([annual(e, v * B) for e, v in {"2021-09-25": 104.0, "2022-09-24": 122.2, "2023-09-30": 110.5, "2024-09-28": 118.3, "2025-09-27": 111.5}.items()]),
        "PaymentsToAcquirePropertyPlantAndEquipment": concept([annual(e, v * B) for e, v in {"2021-09-25": 11.1, "2022-09-24": 10.7, "2023-09-30": 11.0, "2024-09-28": 9.4, "2025-09-27": 12.7}.items()]),
        "PaymentsForRepurchaseOfCommonStock": concept([annual(e, v * B) for e, v in {"2023-09-30": 77.6, "2024-09-28": 95.0, "2025-09-27": 90.7}.items()]),
        "PaymentsOfDividends": concept([annual(e, v * B) for e, v in {"2023-09-30": 15.0, "2024-09-28": 15.2, "2025-09-27": 15.4}.items()]),
        "ResearchAndDevelopmentExpense": concept([annual(e, v * B) for e, v in {"2023-09-30": 29.9, "2024-09-28": 31.4, "2025-09-27": 34.5}.items()]),
        "RepaymentsOfLongTermDebt": concept([annual(e, v * B) for e, v in {"2025-09-27": 0.0}.items()]),
        "EarningsPerShareDiluted": concept([annual(e, v) for e, v in {"2021-09-25": 5.61, "2022-09-24": 6.11, "2023-09-30": 6.13, "2024-09-28": 6.08, "2025-09-27": 7.46}.items()], unit="USD/shares"),
        "CashAndCashEquivalentsAtCarryingValue": concept([instant(e, v * B) for e, v in {"2024-09-28": 29.9, "2025-09-27": 35.9}.items()]),
        "LongTermDebt": concept([instant("2025-09-27", 90.7 * B)]),
    }
    return {"cik": 320193, "entityName": "Apple Inc.", "facts": {"us-gaap": us_gaap}}


def bank_companyfacts() -> dict:
    """No revenue or gross profit tags; net income anchors the fiscal years."""
    ends = ["2023-12-31", "2024-12-31"]
    return {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": concept(
                    [{"start": f"{e[:4]}-01-01", "end": e, "val": v * B, "form": "10-K", "filed": f"{int(e[:4]) + 1}-02-15"} for e, v in zip(ends, [49.6, 58.5])]
                ),
            }
        }
    }
