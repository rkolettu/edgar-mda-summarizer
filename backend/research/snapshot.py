"""The per-company research snapshot: one JSON payload with every tab's data, built from stored facts in code.

Tabs read it as is; nothing here calls a model. It is rebuilt whenever the company's filings change, so switching
tabs or reloading the page never rereads a filing.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

import psycopg

from research import changes, concepts, interpret, metrics, store
from research.extract import PARSER_VERSION
from research.rows import fiscal_label, latest_by, reported_label, source

# Bump when the payload's shape or meaning changes; stored snapshots at an older version are rebuilt on read.
SNAPSHOT_VERSION = 3

CAPITAL_SECTIONS = [
    ("commitment", "Commitments"),
    ("guarantee", "Guarantees and credit support"),
    ("debt", "Debt and financing"),
    ("investment", "Investments"),
    ("capital_return", "Capital return"),
    ("unusual_item", "Unusual items"),
    ("customer_concentration", "Customer concentration"),
    ("backlog", "Remaining performance obligations"),
]
# Headline metrics shown in a capital section next to the disclosure facts behind them.
METRIC_SECTIONS = {
    "long_term_debt": "debt", "long_term_debt_noncurrent": "debt", "debt_current": "debt", "commercial_paper": "debt",
    "debt_issued": "debt", "debt_repaid": "debt", "buybacks": "capital_return", "dividends_paid": "capital_return",
}
MAX_ITEMS = 25
MAX_BACKGROUND = 40      # background-tier changes kept in the payload
SERIES_POINTS = 8
YEAR_DAYS = 365


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def _point(row: dict) -> dict:
    return {
        "value": row["value"],
        "period_start": _iso(row["period_start"]),
        "period_end": _iso(row["period_end"]),
        "fiscal_label": fiscal_label(row["fiscal_year"], row["fiscal_period"]),
        "filing": row["accession_number"],
        "form": row["form_type"],
    }


def _change(current: dict | None, base: dict | None) -> float | None:
    if not current or not base or not base["value"]:
        return None
    return (current["value"] - base["value"]) / abs(base["value"])


def _item(rows: list[dict], context: dict) -> dict | None:
    instant = rows[0]["period_type"] == "instant"
    if instant:
        by_end = latest_by(rows, lambda r: r["period_end"])
        points = [by_end[end] for end in sorted(by_end)]
        latest = points[-1]
        same_length = points
    else:
        # Flows compare like-for-like: the longest year-to-date span at the latest date, against a year earlier.
        by_span = latest_by(rows, lambda r: (r["period_start"], r["period_end"]))
        latest_end = max(end for _, end in by_span)
        latest = max((r for (_, end), r in by_span.items() if end == latest_end), key=lambda r: r["period_months"] or 0)
        same_length = sorted((r for r in by_span.values() if r["period_months"] == latest["period_months"]),
                             key=lambda r: r["period_end"])
    if latest["period_end"] < context["reference_end"]:
        return None  # last reported before the latest annual filing: stale

    earlier = [r for r in same_length if r["period_end"] < latest["period_end"]]
    if instant:
        prior = earlier[-1] if earlier else None
    else:
        prior = next((r for r in reversed(earlier) if abs((latest["period_end"] - r["period_end"]).days - YEAR_DAYS) <= 10), None)
    annual_end = context["annual_end"]
    annual = next((r for r in same_length if r["period_end"] == annual_end), None) if instant and annual_end != latest["period_end"] else None

    filing_ids = {r["filing_id"] for r in rows}
    # New: only the latest filing reports it, with no prior-period comparative, and an earlier filing exists that
    # could have reported it.
    is_new = (filing_ids == {context["latest_filing_id"]} and not any(r["is_comparative"] for r in rows)
              and context["earliest_end"] < context["latest_end"])
    latest_row = latest
    return {
        "key": latest_row["fact_key"],
        "label": latest_row["label"],
        "reported_label": reported_label(latest_row),
        "unit": latest_row["normalized_unit"],
        "currency": latest_row["currency"],
        "period_type": latest_row["period_type"],
        "latest": _point(latest),
        "prior": _point(prior) if prior else None,
        "annual": _point(annual) if annual else None,
        "change_vs_prior": _change(_point(latest), _point(prior) if prior else None),
        "change_vs_annual": _change(_point(latest), _point(annual) if annual else None),
        "comparison": "sequential" if instant else "year_over_year",
        "is_new": is_new,
        "subsequent_event": "subsequent_event" in (latest_row["triggers"] or []),
        "in_latest_filing": context["latest_filing_id"] in filing_ids,
        "series": [_point(r) for r in same_length[-SERIES_POINTS:]],
        "source": source(latest_row),
        "confidence": latest_row["confidence_level"],
    }


def capital(rows: list[dict], aliases: dict[str, str], context: dict) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    section_keys = {key for key, _ in CAPITAL_SECTIONS}
    for row in rows:
        section = row["category"] if row["canonical_metric"] is None and row["category"] in section_keys else METRIC_SECTIONS.get(row["canonical_metric"])
        # Amounts and percentages only; capacities in gigawatts or share counts belong to other views.
        if section is None or row["normalized_unit"] not in ("currency", "ratio", "currency_per_share"):
            continue
        key = aliases.get(row["fact_key"], row["fact_key"])
        groups[(section, key, row["currency"], row["normalized_unit"], row["period_type"])].append(row)

    by_section: dict[str, list[dict]] = defaultdict(list)
    for (section, key, *_), group in groups.items():
        item = _item(group, context)
        if item:
            item["key"] = key
            by_section[section].append(item)
    sections = []
    for key, label in CAPITAL_SECTIONS:
        items = sorted(by_section.get(key, []), key=lambda i: (i["unit"] != "currency", -abs(i["latest"]["value"] or 0)))
        if items:
            sections.append({"key": key, "label": label, "items": items[:MAX_ITEMS], "more": max(0, len(items) - MAX_ITEMS)})
    return sections


def breakdowns(rows: list[dict], aliases: dict[str, str], m: metrics.Metrics) -> list[dict]:
    """Revenue by segment, geography and product for the latest year and quarter, with year-over-year growth."""
    out = []
    for family, _, _ in concepts.BREAKDOWNS:
        family_rows = [r for r in rows if r["category"] == family and r["period_type"] == "duration"]
        if not family_rows:
            continue
        best = latest_by(family_rows, lambda r: (aliases.get(r["fact_key"], r["fact_key"]), r["fiscal_year"], r["fiscal_period"]))
        views = {}
        for kind, periods in (("annual", ("FY",)), ("quarterly", ("Q1", "Q2", "Q3", "Q4"))):
            candidates = [(fy, fp) for (_, fy, fp) in best if fp in periods and fy is not None]
            if not candidates:
                continue
            fiscal_year, period = max(candidates)
            revenue = m.get("revenue", fiscal_year, period)
            items = []
            for (key, fy, fp), row in best.items():
                if (fy, fp) != (fiscal_year, period):
                    continue
                prior = best.get((key, fy - 1, fp))
                items.append({
                    "key": key, "label": row["label"], "metric": key.split(".")[1], "value": row["value"],
                    "prior_year": prior["value"] if prior else None,
                    "growth": (row["value"] - prior["value"]) / abs(prior["value"]) if prior and prior["value"] else None,
                    "share_of_revenue": row["value"] / revenue.value if revenue and revenue.value and key.split(".")[1] == "revenue" else None,
                })
            items.sort(key=lambda i: (i["metric"] != "revenue", -abs(i["value"])))
            views[kind] = {"fiscal_year": fiscal_year, "fiscal_period": period, "label": fiscal_label(fiscal_year, period), "items": items}
        if views:
            out.append({"family": family, "label": concepts.FAMILY_LABELS[family], **views})
    return out


def earnings_quality(rows: list[dict], m: metrics.Metrics, periods: list[tuple[int, str]]) -> list[dict]:
    """The operating-to-net-income bridge per period, with the investment gains and unusual items reported for it."""
    out = []
    for fiscal_year, period in periods:
        bridge = metrics.earnings_bridge(m, fiscal_year, period)
        if bridge is None:
            continue
        items = latest_by(
            [r for r in rows if r["category"] in ("investment", "unusual_item", "non_operating") and r["period_type"] == "duration"
             and r["fiscal_year"] == fiscal_year and r["fiscal_period"] == period and r["normalized_unit"] == "currency"
             and not r["xbrl_concept"].split(":", 1)[-1].startswith("PaymentsToAcquire")],
            lambda r: r["fact_key"],
        )
        bridge["label"] = fiscal_label(fiscal_year, period)
        bridge["items"] = sorted(
            ({"key": r["fact_key"], "label": r["label"], "category": r["category"], "value": r["value"], "source": source(r)}
             for r in items.values()),
            key=lambda i: -abs(i["value"]),
        )
        out.append(bridge)
    return out


def _filing_ref(filing: dict | None) -> dict | None:
    if filing is None:
        return None
    return {"accession_number": filing["accession_number"], "form": filing["form_type"],
            "fiscal_label": fiscal_label(filing["fiscal_year"], filing["fiscal_period"]),
            "period_end": _iso(filing["period_end"]), "filing_date": _iso(filing["filing_date"])}


def _change_item(r: changes.ChangeRecord, by_id: dict[int, dict]) -> dict:
    base = by_id.get(r.base_filing_id)
    return {
        "id": changes.stable_id(r), "kind": r.kind, "change_type": r.change_type, "category": r.category,
        "category_label": changes.CATEGORY_LABELS.get(r.category, r.category.replace("_", " ").capitalize()),
        "label": r.label, "comparison": r.comparison, "value": r.value, "base_value": r.base_value,
        "annual_value": r.annual_value, "change": r.change, "unit": r.unit, "currency": r.currency,
        "period_label": r.period_label, "base_period_label": r.base_period_label,
        "base_filing": {"form": base["form_type"], "fiscal_label": fiscal_label(base["fiscal_year"], base["fiscal_period"])}
        if base else None,
        "text": r.text, "base_text": r.base_text, "triggers": [t["phrase"] for t in r.triggers],
        "flags": sorted(r.flags), "reasons": r.score.reasons, "score": r.score.score, "tier": r.score.tier,
        **{k: v for k, v in r.details.items() if k != "metric" and v is not None},
    }


def filing_changes(records: list[changes.ChangeRecord], filings: list[dict], revenue: float | None) -> dict:
    """The latest filing's changes for the Filing Changes tab: grouped by amount, most material first, with the
    lowest tier trimmed."""
    by_id = {f["filing_id"]: f for f in filings}
    bases = changes.Bases.of(filings)
    groups = changes.group([r for r in records if r.change_type != "repeated"], revenue)
    counts: dict[str, int] = defaultdict(int)
    items = []
    for primary, related in groups:
        lead = max((primary, *related), key=lambda r: r.score.score)
        counts[lead.score.tier] += 1
        counts[primary.change_type] += 1
        if lead.score.tier == "background" and counts["background"] > MAX_BACKGROUND:
            continue
        item = _change_item(primary, by_id)
        item.update(score=lead.score.score, tier=lead.score.tier)
        if lead is not primary:
            item["reasons"] = list(dict.fromkeys(primary.score.reasons + lead.score.reasons))
        item["related"] = [{k: v for k, v in _change_item(r, by_id).items() if k != "series"} for r in related]
        items.append(item)
    return {
        "filing": _filing_ref(bases.latest) if bases else None,
        "previous": _filing_ref(bases.previous) if bases else None,
        "annual": _filing_ref(bases.annual) if bases else None,
        "counts": dict(counts),
        "items": items,
        "hidden": max(0, counts["background"] - MAX_BACKGROUND),
    }


def build(conn: psycopg.Connection, company_id: int) -> tuple[dict, int | None, list[changes.ChangeRecord]]:
    company = store.find_company(conn, company_id=company_id)
    filings = store.company_filings(conn, company_id)
    originals = [f for f in filings if not f["form_type"].endswith("/A")]
    latest = originals[0] if originals else (filings[0] if filings else None)
    annual = next((f for f in originals if f["is_annual"]), None)
    rows = store.company_facts(conn, company_id)
    alias_map = store.aliases(conn, company_id)
    m = metrics.Metrics([r for r in rows if r["canonical_metric"]])

    context = {
        "latest_filing_id": latest["filing_id"] if latest else None,
        "annual_end": annual["period_end"] if annual else None,
        "reference_end": (annual or latest)["period_end"] if latest else date.min,
        "earliest_end": min((f["period_end"] for f in filings if f["period_end"]), default=date.max),
        "latest_end": latest["period_end"] if latest else date.min,
    }
    sections = store.company_sections(conn, company_id, changes.NARRATIVE_CATEGORIES)
    records = changes.compute(rows, sections, filings, alias_map, m, company["reporting_currency"])
    revenue = changes.anchors(m, rows, company["reporting_currency"]).revenue
    quarters = m.quarters()
    years = m.fiscal_years()
    bridge_periods = ([(years[-1], "FY")] if years else []) + ([quarters[-1]] if quarters else [])
    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "company": {k: company[k] for k in ("ticker", "name", "cik", "reporting_currency", "accounting_standard", "fiscal_year_end")},
        "filings": [
            {
                "accession_number": f["accession_number"], "form": f["form_type"], "filing_date": _iso(f["filing_date"]),
                "period_end": _iso(f["period_end"]), "fiscal_label": fiscal_label(f["fiscal_year"], f["fiscal_period"]),
                "is_annual": f["is_annual"], "confidence": f["confidence_level"], "source_url": f["source_url"],
                "missing": sorted(k for k, v in (f["coverage"] or {}).items() if isinstance(v, dict) and v.get("found") is False),
            }
            for f in filings
        ],
        "latest_filing": latest["accession_number"] if latest else None,
        "latest_annual": annual["accession_number"] if annual else None,
        "financials": {
            "currency": company["reporting_currency"],
            "annual": metrics.table(m, "annual"),
            "quarterly": metrics.table(m, "quarterly"),
            "breakdowns": breakdowns(rows, alias_map, m),
        },
        "capital": {"sections": capital(rows, alias_map, context)},
        "earnings_quality": {"bridges": earnings_quality(rows, m, bridge_periods)},
        "changes": filing_changes(records, filings, revenue),
        "insights": interpret.insights_section(conn, company_id, filings),
    }
    notes = payload["insights"].get("change_notes") or {}
    for item in payload["changes"]["items"]:
        if item["id"] in notes:
            item["why_it_matters"] = notes[item["id"]]
    return payload, latest["filing_id"] if latest else None, records


def rebuild(conn: psycopg.Connection, company_id: int) -> dict:
    store.bridge_aliases(conn, company_id)
    payload, as_of, records = build(conn, company_id)
    with conn.transaction():
        store.save_changes(conn, company_id, records)
        store.save_snapshot(conn, company_id, as_of, SNAPSHOT_VERSION, PARSER_VERSION, payload)
    return payload
