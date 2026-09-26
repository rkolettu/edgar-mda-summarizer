"""Compares a company's latest filing with the reports before it and scores every change (no model calls).

Bases: the previous report (sequential, for balances), the latest annual report (for balances in an interim filing,
and for a 10-Q's risk factors), and the same period a year earlier (for amounts over a period). Interim filings are
condensed, so a line missing from a 10-Q counts as removed only when the previous filing was also an interim one,
and a 10-Q's risk factors, which list only updates, are compared with the annual report without looking for
removals.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

import figures
from research import concepts, materiality, metrics, narrative
from research.rows import fiscal_label, latest_by, reported_label, source

CHANGE_THRESHOLD = 0.05      # relative moves below this are repeats
POINTS_NOISE = 0.01          # ratio moves below one percentage point are repeats
DAYS_NOISE = 5
WORKING_CAPITAL_SPREAD = 0.20
YEAR_DAYS = 365
MAX_NARRATIVE = 60
NARRATIVE_FLOOR = 0.25       # language changes scoring below this are dropped rather than stored
LABEL_CHARS = 140
# Items reporting the same amount about the same thing (a tagged guarantee, the note sentence and the MD&A passage
# about it) are shown as one. Amounts within this tolerance match; only amounts above the floor (share of revenue)
# are matched, and wording must name the value's subject, since round amounts often coincide.
GROUP_TOLERANCE = 0.005
GROUP_FLOOR_SHARE = 0.005
GENERIC_WORDS = {
    "total", "other", "amount", "amounts", "future", "current", "noncurrent", "value", "balance", "carrying", "segment",
    "income", "expense", "related", "additional", "including", "portion", "commitment", "commitments", "obligations",
    "share", "shares", "equity", "financial", "securities", "operating", "payments", "proceeds", "during",
}
# Several new lines under a concept the company never tagged before are a table itemized for the first time (a
# bond list), not several new items.
FIRST_ITEMIZED_MIN = 3
# Companies re-letter anonymized customers every period ("Customer A" now need not be last quarter's), so their shares
# are compared as a set.
ANONYMOUS_CUSTOMER = re.compile(r"(?:^|_)(?:customer|client)_(?:[a-z]|\d+|one|two|three|four|five|six|seven|eight|nine|ten)$")

# Headline statement lines worth a change row; the rest of the statements stay in the Financials tab.
HEADLINE_METRICS = {
    "revenue", "gross_profit", "operating_income", "net_income", "nonoperating_income", "operating_cash_flow", "capex",
    "cash", "marketable_securities", "long_term_debt", "debt_issued", "inventory", "accounts_receivable",
    "contract_liabilities", "buybacks", "dividends_paid",
}
NARRATIVE_CATEGORIES = ("risk_factors", "subsequent_events", "guarantees", "commitments", "contingencies",
                        "acquisitions", "debt", "customer_concentration", "management_discussion")
# Note categories score like the matching disclosure family.
STRATEGIC_KEY = {"commitments": "commitment", "guarantees": "guarantee"}
CATEGORY_LABELS = {
    **concepts.FAMILY_LABELS, "financial_metric": "Financial statements", "derived_metric": "Ratios and working capital",
    "risk_factors": "Risk factors", "management_discussion": "Management discussion", "commitments": "Commitments",
    "contingencies": "Contingencies", "guarantees": "Guarantees", "subsequent_events": "Subsequent events",
    "acquisitions": "Acquisitions", "debt": "Debt and financing",
}
DERIVED = [
    ("gross_margin", "Gross margin", "points"),
    ("operating_margin", "Operating margin", "points"),
    ("net_margin", "Net margin", "points"),
    ("capex_intensity", "Capex as % of revenue", "points"),
    ("effective_tax_rate", "Effective tax rate", "points"),
    ("receivable_days", "Receivable days", "days"),
    ("inventory_days", "Inventory days", "days"),
]


@dataclass
class ChangeRecord:
    kind: str                      # numeric | derived | narrative
    change_type: str               # new | changed | removed | repeated
    category: str
    label: str
    comparison: str                # sequential | vs_annual | annual_vs_annual | year_over_year
    filing_id: int
    base_filing_id: int | None = None
    fact_key: str | None = None
    fact_id: int | None = None
    base_fact_id: int | None = None
    section_id: int | None = None
    value: float | None = None
    base_value: float | None = None
    annual_value: float | None = None
    change: float | None = None    # relative change; percentage points for ratios; days for day counts
    unit: str = "currency"
    currency: str | None = None
    period_type: str | None = None
    period_label: str | None = None
    base_period_label: str | None = None
    text: str | None = None
    base_text: str | None = None
    triggers: list[dict] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    details: dict = field(default_factory=dict)
    score: materiality.Score | None = None


@dataclass
class Bases:
    latest: dict
    previous: dict | None     # the report just before the latest
    annual: dict | None       # the latest annual report before the latest filing

    @classmethod
    def of(cls, filings: list[dict]) -> Bases | None:
        originals = sorted((f for f in filings if not f["form_type"].endswith("/A") and f["period_end"]),
                           key=lambda f: (f["period_end"], f["filing_date"]), reverse=True)
        if not originals:
            return None
        latest = originals[0]
        earlier = [f for f in originals if f["period_end"] < latest["period_end"]]
        return cls(latest, earlier[0] if earlier else None, next((f for f in earlier if f["is_annual"]), None))

    def comparison_with(self, base: dict | None) -> str:
        if base is not None and base["is_annual"]:
            return "annual_vs_annual" if self.latest["is_annual"] else "vs_annual"
        return "sequential"


def _label(row: dict) -> str:
    return fiscal_label(row["fiscal_year"], row["fiscal_period"]) or row["period_end"].isoformat()


def _filing_label(filing: dict | None) -> str | None:
    return fiscal_label(filing["fiscal_year"], filing["fiscal_period"]) if filing else None


def _relative(value: float, base: float) -> float | None:
    return (value - base) / abs(base) if base else None


# --- numbers ---


def _current_flow(current_rows: list[dict], by_span: dict) -> tuple[dict, dict | None]:
    """The discrete quarter when the filing reports one with a year-earlier comparable, else the longest span."""
    latest_end = max(r["period_end"] for r in current_rows)
    at_end = sorted((r for r in current_rows if r["period_end"] == latest_end),
                    key=lambda r: (r["period_months"] != 3, -(r["period_months"] or 0)))

    def year_earlier(row: dict) -> dict | None:
        return next((r for r in by_span.values() if r["period_months"] == row["period_months"]
                     and abs((row["period_end"] - r["period_end"]).days - YEAR_DAYS) <= 10), None)

    for row in at_end:
        base = year_earlier(row)
        if base is not None:
            return row, base
    return max(at_end, key=lambda r: r["period_months"] or 0), None


def _anonymous_basis(row: dict) -> str | None:
    """'accounts receivable' or 'revenue' for an anonymized customer's share; None for any other row."""
    if row["category"] != "customer_concentration" or row["normalized_unit"] != "ratio":
        return None
    parts = row["fact_key"].split(".")
    if not any(ANONYMOUS_CUSTOMER.search(p) for p in parts[2:]):
        return None
    rest = " ".join(p for p in parts[2:] if not ANONYMOUS_CUSTOMER.search(p))
    if "receivable" in rest:
        return "accounts receivable"
    if "revenue" in rest or "sales" in rest:
        return "revenue"
    return "purchases" if "purchase" in rest or "cost" in rest else "other"


def anonymous_customers(groups: dict[str, list[dict]], bases: Bases) -> list[ChangeRecord]:
    latest = bases.latest
    primary = bases.annual if latest["is_annual"] else bases.previous
    records = []

    def shares(rows: list[dict], filing_id: int) -> tuple[list[dict], str | None]:
        """The filing's own shares at its latest date, largest first."""
        own = [r for r in rows if r["filing_id"] == filing_id and not r["is_comparative"]]
        if not own:
            return [], None
        end = max(r["period_end"] for r in own)
        months = max((r["period_months"] or 0) for r in own if r["period_end"] == end)
        at_end = latest_by([r for r in own if r["period_end"] == end and (r["period_months"] or 0) == months],
                           lambda r: r["fact_key"])
        ranked = sorted(at_end.values(), key=lambda r: -r["value"])
        return ranked, _label(ranked[0])

    for basis, rows in groups.items():
        current, label = shares(rows, latest["filing_id"])
        if not current:
            continue
        # Compare with the primary base filing, or the latest earlier filing that disclosed shares on this basis.
        earlier = sorted({r["filing_id"]: r["period_end"] for r in rows
                          if r["filing_id"] != latest["filing_id"] and not r["is_comparative"]}.items(),
                         key=lambda item: item[1], reverse=True)
        earlier_ids = [filing_id for filing_id, _ in earlier]
        base_id = primary["filing_id"] if primary and primary["filing_id"] in earlier_ids else next(iter(earlier_ids), None)
        base, base_label = shares(rows, base_id) if base_id else ([], None)
        top, base_top = current[0]["value"], base[0]["value"] if base else None

        def listing(items):
            return ", ".join(f"{r['value'] * 100:.0f}%" for r in items)

        note = f"{len(current)} customers disclosed ({listing(current)})"
        if base:
            note += f"; previously {len(base)} ({listing(base)})"
            change = top - base_top
            change_type = "changed" if abs(change) >= POINTS_NOISE or len(base) != len(current) else "repeated"
        else:
            change, change_type = None, "new"
        records.append(ChangeRecord(
            kind="numeric", change_type=change_type, category="customer_concentration",
            label=f"Largest customer's share of {basis}", comparison=bases.comparison_with(primary) if base else "sequential",
            filing_id=latest["filing_id"], base_filing_id=base[0]["filing_id"] if base else None,
            fact_key=f"customer_concentration.anonymous.{basis.replace(' ', '_')}", value=top, base_value=base_top,
            change=change, unit="ratio", period_type=current[0]["period_type"], period_label=label,
            base_period_label=base_label, details={"note": note, "count": len(current), "base_count": len(base) or None,
                                                   "source": source(current[0])},
        ))
    return records


def numeric_changes(rows: list[dict], aliases: dict[str, str], bases: Bases) -> list[ChangeRecord]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    anonymous: dict[str, list[dict]] = defaultdict(list)
    concept_of: dict[str, str] = {}
    for row in rows:
        metric = row["canonical_metric"]
        if (metric and metric not in HEADLINE_METRICS) or (not metric and row["category"] not in concepts.FAMILY_LABELS):
            continue
        if row["normalized_unit"] not in ("currency", "ratio"):
            continue
        basis = _anonymous_basis(row)
        if basis:
            anonymous[basis].append(row)
            continue
        key = aliases.get(row["fact_key"], row["fact_key"])
        concept_of.setdefault(key, row["xbrl_concept"])
        groups[(key, row["currency"], row["normalized_unit"], row["period_type"])].append(row)

    latest = bases.latest
    records = []
    for (key, currency, unit, period_type), group in groups.items():
        category = "financial_metric" if group[0]["canonical_metric"] else group[0]["category"]
        current_rows = [r for r in group if r["filing_id"] == latest["filing_id"] and not r["is_comparative"]]
        if not current_rows:
            removed = _removed(group, key, category, bases, currency, unit)
            if removed:
                records.append(removed)
            continue
        # Earlier values: from earlier filings, or the prior periods the latest filing repeats.
        prior_rows = [r for r in group if r["filing_id"] != latest["filing_id"] or r["is_comparative"]]

        annual = None
        if period_type == "instant":
            by_end = latest_by(group, lambda r: r["period_end"])
            current = max(current_rows, key=lambda r: r["period_end"])
            primary = bases.annual if latest["is_annual"] else bases.previous
            comparison = bases.comparison_with(primary)
            base = by_end.get(primary["period_end"]) if primary else None
            if base is None:
                earlier = [r["period_end"] for r in prior_rows if r["period_end"] < current["period_end"]]
                base = by_end[max(earlier)] if earlier else None
                comparison = "sequential"
            if bases.annual and not latest["is_annual"] and base is not None:
                annual = by_end.get(bases.annual["period_end"])
            series = [by_end[end] for end in sorted(by_end)][-6:]
        else:
            by_span = latest_by(group, lambda r: (r["period_start"], r["period_end"]))
            current, base = _current_flow(current_rows, by_span)
            comparison = "year_over_year"
            series = sorted((r for r in by_span.values() if r["period_months"] == current["period_months"]),
                            key=lambda r: r["period_end"])[-6:]

        if base is None:
            if prior_rows or bases.previous is None:
                continue  # earlier values exist but none is comparable, or no earlier filing could have reported it
            change_type, change = "new", None
        elif unit == "ratio":
            change = current["value"] - base["value"]
            change_type = "changed" if abs(change) >= POINTS_NOISE else "repeated"
        elif base["value"] == 0:
            change = None  # up from zero, or zero both times
            change_type = "changed" if current["value"] else "repeated"
        else:
            change = _relative(current["value"], base["value"])
            change_type = "changed" if abs(change) >= CHANGE_THRESHOLD else "repeated"

        flags = {"subsequent_event"} if "subsequent_event" in (current["triggers"] or []) else set()
        if category == "debt" and change_type == "new":
            flags.add("new_financing")
        details = {"series": [{"value": r["value"], "label": _label(r)} for r in series],
                   "reported_label": reported_label(current), "source": source(current),
                   "metric": group[0]["canonical_metric"]}
        if base is not None and base["label"] != current["label"]:
            details["base_label"] = base["label"]
        records.append(ChangeRecord(
            kind="numeric", change_type=change_type, category=category, label=current["label"],
            comparison=comparison, filing_id=latest["filing_id"], base_filing_id=base["filing_id"] if base else None,
            fact_key=key, fact_id=current["fact_id"], base_fact_id=base["fact_id"] if base else None,
            value=current["value"], base_value=base["value"] if base else None,
            annual_value=annual["value"] if annual else None, change=change, unit=unit, currency=currency,
            period_type=period_type, period_label=_label(current), base_period_label=_label(base) if base else None,
            flags=flags, details=details,
        ))

    earlier_concepts = {r["xbrl_concept"] for r in rows if r["filing_id"] != latest["filing_id"]}
    first_tagged: dict[tuple, list[ChangeRecord]] = defaultdict(list)
    for record in records:
        if record.change_type == "new" and concept_of[record.fact_key] not in earlier_concepts:
            first_tagged[(record.category, concept_of[record.fact_key], record.currency)].append(record)
    for (category, concept, _), batch in first_tagged.items():
        if len(batch) >= FIRST_ITEMIZED_MIN:
            for record in batch:
                record.details["first_itemized"] = f"{category}:{concept}"
                record.details["note"] = f"One of {len(batch)} lines of this kind itemized for the first time in this filing"

    # A line dropped in the same filing that adds lines under the same concept, or with a similar name, was probably
    # renamed or split.
    added = [r for r in records if r.change_type == "new"]
    for record in records:
        if record.change_type != "removed":
            continue
        similar = [r.label for r in added if r.category == record.category and (
            concept_of[r.fact_key] == concept_of[record.fact_key] or len(stems(r.label) & stems(record.label)) >= 2)]
        if similar:
            record.details["possibly_replaced_by"] = similar[:4]
    return records + anonymous_customers(anonymous, bases)


def _removed(group, key, category, bases: Bases, currency, unit) -> ChangeRecord | None:
    """A disclosure the comparable earlier report carried and the latest one dropped entirely."""
    latest = bases.latest
    if latest["is_annual"]:
        base_filing = bases.annual
    else:
        base_filing = bases.previous if bases.previous and not bases.previous["is_annual"] else None
    if base_filing is None or group[0]["canonical_metric"] or any(r["filing_id"] == latest["filing_id"] for r in group):
        return None
    base_rows = [r for r in group if r["filing_id"] == base_filing["filing_id"] and not r["is_comparative"]]
    if not base_rows:
        return None
    base = max(base_rows, key=lambda r: r["period_end"])
    return ChangeRecord(
        kind="numeric", change_type="removed", category=category, label=base["label"],
        comparison=bases.comparison_with(base_filing), filing_id=latest["filing_id"],
        base_filing_id=base_filing["filing_id"], fact_key=key, base_fact_id=base["fact_id"], base_value=base["value"],
        unit=unit, currency=currency, period_type=base["period_type"], base_period_label=_label(base),
        details={"reported_label": reported_label(base), "source": source(base)},
    )


# --- ratios and working capital ---


def derived_changes(m: metrics.Metrics, bases: Bases, currency: str | None) -> list[ChangeRecord]:
    latest = bases.latest
    if latest["is_annual"]:
        years = m.fiscal_years()
        if not years:
            return []
        fiscal_year, period, kind = years[-1], "FY", "annual"
    else:
        quarters = m.quarters()
        if not quarters:
            return []
        (fiscal_year, period), kind = quarters[-1], "quarterly"
    current = metrics.column_values(m, fiscal_year, period, kind)
    prior = metrics.column_values(m, fiscal_year - 1, period, kind)
    label, base_label = fiscal_label(fiscal_year, period), fiscal_label(fiscal_year - 1, period)
    records = []

    def add(key, name, unit, value, base, details=None):
        delta = value - base
        if abs(delta) < (DAYS_NOISE if unit == "days" else POINTS_NOISE):
            return
        records.append(ChangeRecord(
            kind="derived", change_type="changed", category="derived_metric", label=name, comparison="year_over_year",
            filing_id=latest["filing_id"], fact_key=f"derived.{key}", value=value, base_value=base, change=delta,
            unit=unit, currency=currency, period_label=label, base_period_label=base_label, details=details or {},
        ))

    for key, name, unit in DERIVED:
        if current[key] is not None and prior[key] is not None:
            add(key, name, unit, current[key].value, prior[key].value)

    shares = []
    for fy in (fiscal_year, fiscal_year - 1):
        bridge = metrics.earnings_bridge(m, fy, period)
        share = bridge and bridge["non_operating_share_of_pretax"]
        # A thin or negative pretax result makes the share meaningless.
        shares.append(share if share is not None and bridge["pretax_income"] > 0 and abs(share) <= 1 else None)
    if None not in shares:
        add("non_operating_share", "Non-operating income as % of pretax income", "points", *shares)

    revenue_growth = current["revenue_growth"]
    for key, name in (("accounts_receivable", "Receivables"), ("inventory", "Inventory")):
        now, before = current[key], prior[key]
        if revenue_growth is None or now is None or before is None or not before.value:
            continue
        growth = (now.value - before.value) / abs(before.value)
        if growth - revenue_growth.value >= WORKING_CAPITAL_SPREAD:
            add(f"{key}_vs_revenue", f"{name} growing faster than revenue", "points", growth, revenue_growth.value,
                {"note": f"{name} {growth * 100:+.0f}% vs revenue {revenue_growth.value * 100:+.0f}% year over year",
                 "values": "growth"})
    return records


# --- language ---


def _first_sentence(text: str, heading: str | None) -> str:
    if heading and text.startswith(heading) and len(text) > len(heading) + 20:
        text = text[len(heading):].lstrip(" .:–—-")
    first = narrative.sentences(text)[:1] or [text]
    first = first[0]
    return first if len(first) <= LABEL_CHARS else first[: LABEL_CHARS - 1].rsplit(" ", 1)[0] + "…"


def _section_texts(sections: list[dict]) -> dict[tuple[int, str], dict]:
    """One text per filing and category (several notes can share a category), in document order."""
    merged: dict[tuple[int, str], dict] = {}
    for s in sorted(sections, key=lambda s: (s["filing_id"], s["ordinal"])):
        slot = (s["filing_id"], s["category"])
        if slot in merged:
            merged[slot]["text"] += "\n\n" + s["text"]
        else:
            merged[slot] = dict(s)
    return merged


def narrative_changes(sections: list[dict], filings: list[dict], bases: Bases) -> list[ChangeRecord]:
    latest = bases.latest
    texts = _section_texts(sections)
    earlier = sorted((f for f in filings if not f["form_type"].endswith("/A") and f["period_end"]
                      and f["period_end"] < latest["period_end"]), key=lambda f: f["period_end"], reverse=True)
    records = []
    for category in NARRATIVE_CATEGORIES:
        new = texts.get((latest["filing_id"], category))
        if not new:
            continue
        carried: set[str] = set()
        if category == "risk_factors" and not latest["is_annual"]:
            # A 10-Q lists only updates to the annual risk factors; what the previous 10-Q already added is marked.
            base_filing = bases.annual
            previous = bases.previous
            if previous and not previous["is_annual"] and (previous["filing_id"], category) in texts:
                carried = {narrative.fingerprints(s)[0] for s in narrative.sentences(texts[(previous["filing_id"], category)]["text"])}
        else:
            base_filing = next((f for f in earlier if (f["filing_id"], category) in texts), None)
        base = texts.get((base_filing["filing_id"], category)) if base_filing else None
        if base is None and category != "subsequent_events":
            continue
        # Removals only mean something between reports of the same kind (annual and annual, interim and interim).
        detect_removed = base_filing is not None and base_filing["is_annual"] == latest["is_annual"]
        result = narrative.diff(new["text"], base["text"] if base else "", detect_removed=detect_removed)
        for passage in result.passages:
            if category == "management_discussion":
                # MD&A is rewritten every period: only flagged language is a candidate, sentence by sentence.
                units = _flagged_sentences(passage)
            elif passage.kind == "numbers" and category not in ("risk_factors", "subsequent_events"):
                continue  # changed amounts in notes are covered by the tagged values
            else:
                units = [passage]
            for unit in units:
                records.append(_narrative_record(unit, category, new, base_filing, carried, bases))
    return records


def _flagged_sentences(passage: narrative.Passage) -> list[narrative.Passage]:
    if passage.change_type == "changed":
        return [passage] if passage.triggers or passage.modality_shift else []
    return [narrative.Passage(passage.change_type, sentence, triggers=found, position=passage.position)
            for sentence in narrative.sentences(passage.text) if (found := narrative.triggers(sentence))]


def _narrative_record(passage: narrative.Passage, category: str, new: dict, base_filing: dict | None,
                      carried: set[str], bases: Bases) -> ChangeRecord:
    flags = set()
    if passage.modality_shift:
        flags.add("hypothetical_to_realized")
    if category == "subsequent_events" and passage.change_type == "new":
        flags.add("subsequent_event")
    details = {"wording": passage.kind, "document_url": new["document_url"], "heading": new["heading"]}
    if carried and passage.change_type == "new" and all(
            narrative.fingerprints(s)[0] in carried for s in narrative.sentences(passage.text)):
        details["first_disclosed"] = _filing_label(bases.previous)
    # Risk factors are qualitative, and a passage can run several together, so amounts quoted in them do not size
    # the change.
    amounts = [] if category == "risk_factors" else [
        c["value"] for c in figures.extract_claims(passage.text) if c["kind"] == "amount"]
    return ChangeRecord(
        kind="narrative", change_type=passage.change_type, category=category,
        label=_first_sentence(passage.text, new["heading"]), comparison=bases.comparison_with(base_filing),
        filing_id=bases.latest["filing_id"], base_filing_id=base_filing["filing_id"] if base_filing else None,
        section_id=new["section_id"], value=max(amounts) if amounts else None, unit="text", text=passage.text,
        base_text=passage.base_text, triggers=passage.triggers, flags=flags,
        period_label=_filing_label(bases.latest), base_period_label=_filing_label(base_filing), details=details,
    )


# --- scoring ---


def anchors(m: metrics.Metrics, rows: list[dict], currency: str | None) -> materiality.Anchors:
    years = m.fiscal_years()
    revenue = m.get("revenue", years[-1], "FY") if years else None
    operating = m.get("operating_income", years[-1], "FY") if years else None
    assets = [r for r in rows if r["canonical_metric"] == "total_assets" and r["currency"] == currency]
    latest_assets = max(assets, key=lambda r: (r["period_end"], r["filing_date"]))["value"] if assets else None
    return materiality.Anchors(currency, revenue.value if revenue else None, operating.value if operating else None,
                               latest_assets)


def _candidate(record: ChangeRecord) -> materiality.Candidate:
    change_type = record.change_type
    if record.details.get("first_disclosed") or record.details.get("first_itemized"):
        # New since the annual report but already in the previous quarter's; or newly itemized detail.
        change_type = "changed"
    if (record.kind == "narrative" and change_type == "new" and record.category != "risk_factors"
            and not record.value and not record.triggers):
        change_type = "changed"  # new wording in a note that states no amount and uses no flagged terms
    if record.kind == "narrative":
        return materiality.Candidate(
            STRATEGIC_KEY.get(record.category, record.category), change_type,
            unit="currency" if record.value else "text", amount=record.value, currency=record.currency,
            triggers=record.triggers, flags=record.flags,
        )
    amount = record.value if record.value is not None else record.base_value
    return materiality.Candidate(
        record.category, change_type, unit=record.unit, amount=amount, base_amount=record.base_value,
        change=record.change, currency=record.currency, triggers=record.triggers, flags=record.flags,
        # Statement lines and amounts over a period (revenue by segment) matter by how much they moved; disclosed
        # balances (commitments, guarantees, debt) by their size.
        magnitude_basis="delta" if record.category == "financial_metric" or record.period_type == "duration" else "level",
    )


def compute(rows: list[dict], sections: list[dict], filings: list[dict], aliases: dict[str, str],
            m: metrics.Metrics, currency: str | None) -> list[ChangeRecord]:
    """Every change in the latest filing, scored and ranked. Repeated numeric lines are included (they set the facts'
    disclosure status) and are left out of what is stored and shown."""
    bases = Bases.of(filings)
    if bases is None:
        return []
    scale = anchors(m, rows, currency)
    records = numeric_changes(rows, aliases, bases)
    # A ratio the company reports itself (an effective tax rate) replaces the computed one.
    reported = {r.label.lower() for r in records if r.unit == "ratio"}
    records += [r for r in derived_changes(m, bases, currency) if r.label.lower() not in reported]
    language = narrative_changes(sections, filings, bases)
    for record in language:
        record.currency = currency  # amounts quoted in a filing's text are in its reporting currency
    for record in records + language:
        record.score = materiality.score(_candidate(record), scale)
    language = sorted((r for r in language if r.score.score >= NARRATIVE_FLOOR), key=lambda r: -r.score.score)
    records += language[:MAX_NARRATIVE]
    records.sort(key=lambda r: -r.score.score)
    return records


def stems(text: str) -> set[str]:
    """Distinctive word stems, for matching a label with wording ('guarantee' and 'guarantees')."""
    return {w[:6] for w in re.findall(r"[a-z]{5,}", text.lower()) if w not in GENERIC_WORDS}


def _amounts(record: ChangeRecord, as_primary: bool) -> list[float]:
    if record.kind == "narrative":
        values = [record.value]
    elif record.unit == "currency" and record.kind == "numeric":
        values = [record.value, record.base_value] if as_primary else [record.value]
    else:
        return []
    return [v for v in values if v]


def group(records: list[ChangeRecord], revenue: float | None) -> list[tuple[ChangeRecord, list[ChangeRecord]]]:
    """Folds items that report the same amount into one, led by the tagged value (numbers before wording), ranked by
    the highest score in each group."""
    floor = GROUP_FLOOR_SHARE * abs(revenue) if revenue else 0.0
    groups: list[tuple[ChangeRecord, list[ChangeRecord]]] = []

    def same_subject(record: ChangeRecord, primary: ChangeRecord) -> bool:
        if primary.kind == "narrative" or primary.currency != record.currency:
            return False
        if record.details.get("first_itemized"):
            return record.details["first_itemized"] == primary.details.get("first_itemized")
        if record.kind == "narrative":
            return bool(stems(primary.label) & stems(record.text or ""))
        return record.category == primary.category and record.change_type == primary.change_type

    for record in sorted(records, key=lambda r: (r.kind == "narrative", -r.score.score)):
        amounts = [a for a in _amounts(record, as_primary=False) if abs(a) >= floor]
        if record.details.get("first_itemized"):
            home = next((g for g in groups if same_subject(record, g[0])), None)
        else:
            home = next((g for g in groups if same_subject(record, g[0]) and any(
                abs(a - b) <= GROUP_TOLERANCE * max(abs(a), abs(b)) for a in amounts for b in _amounts(g[0], as_primary=True)
            )), None) if amounts else None
        if home is None:
            groups.append((record, []))
        else:
            home[1].append(record)
    return sorted(groups, key=lambda g: -max(r.score.score for r in (g[0], *g[1])))
