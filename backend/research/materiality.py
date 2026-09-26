"""Deterministic materiality scoring for candidate changes, before any model sees them.

score = 35% magnitude + 25% change + 20% strategic importance + 10% language + 10% novelty, plus bonuses, capped
at 1. Magnitude is relative to the company's own revenue, operating income and assets, so the same rules work for
a $5B company and a $5T one; the one absolute trigger ($10B) applies only to US dollar reporters because amounts
are never converted between currencies. Every score keeps its components and plain-language reasons, so a reader
(and later the model) can see why an item ranks where it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WEIGHTS = {"magnitude": 0.35, "change": 0.25, "strategic": 0.20, "language": 0.10, "novelty": 0.10}
# Share of each anchor at which an amount counts as material (scores 0.7; twice the share scores 1.0).
THRESHOLDS = {"revenue": 0.05, "operating_income": 0.10, "total_assets": 0.10}
ABSOLUTE_USD = 10e9
# A percentage change needs a meaningful amount behind it: at least this share of revenue or this many dollars.
CHANGE_FLOOR_SHARE = 0.005
CHANGE_FLOOR_USD = 1e9
# Changes in ratios and day counts that count as material (score 0.7).
POINTS_THRESHOLD = 0.05          # five percentage points of margin, capital intensity or concentration
DAYS_THRESHOLD = 15
CONCENTRATION_THRESHOLD = 0.10   # a customer or region at 10% of revenue
TIERS = (("top", 0.70), ("notable", 0.45))

NOVELTY = {"new": 1.0, "changed": 0.6, "removed": 0.5, "repeated": 0.1}
STRATEGIC = {
    "guarantee": 0.9, "acquisitions": 0.9, "subsequent_events": 0.9, "commitment": 0.7, "customer_concentration": 0.7,
    "contingencies": 0.6, "debt": 0.6, "investment": 0.6, "unusual_item": 0.6, "risk_factors": 0.5, "segment": 0.5,
    "geography": 0.5, "product": 0.4, "backlog": 0.5, "management_discussion": 0.4, "capital_return": 0.4,
    "non_operating": 0.5, "tax": 0.3, "financial_metric": 0.6, "derived_metric": 0.6,
}
BONUSES = {
    "subsequent_event": 0.10, "new_guarantee": 0.10, "new_financing": 0.10, "hypothetical_to_realized": 0.10,
    "material_weakness": 0.10, "critical_audit_matter": 0.05, "over_10b": 0.05,
}


@dataclass
class Anchors:
    """The company's own scale: latest fiscal year revenue and operating income, latest total assets."""

    currency: str | None
    revenue: float | None = None
    operating_income: float | None = None
    total_assets: float | None = None

    def shares(self, amount: float) -> dict[str, float]:
        out = {}
        if self.revenue:
            out["revenue"] = abs(amount) / abs(self.revenue)
        if self.operating_income is not None and self.revenue:
            # A thin or negative operating result would make every amount look huge; floor it at 2% of revenue.
            out["operating_income"] = abs(amount) / max(abs(self.operating_income), 0.02 * abs(self.revenue))
        if self.total_assets:
            out["total_assets"] = abs(amount) / abs(self.total_assets)
        return out


@dataclass
class Candidate:
    category: str                      # family or section category
    change_type: str                   # new | changed | removed | repeated
    unit: str = "currency"             # currency | ratio | points | days | text
    amount: float | None = None        # the latest amount (currency units), or ratio for concentration
    base_amount: float | None = None
    change: float | None = None        # relative change; points for ratios and derived metrics; days
    currency: str | None = None
    triggers: list[dict] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)   # subsequent_event, hypothetical_to_realized, ...
    # Balances like commitments matter by their level; income statement lines by how much they moved, or every large
    # line of a large company would rank as material every quarter.
    magnitude_basis: str = "level"                 # level | delta


@dataclass
class Score:
    score: float
    tier: str
    components: dict
    reasons: list[str]


def _curve(ratio: float) -> float:
    """0 at nothing, 0.7 at the threshold, 1.0 at twice the threshold."""
    if ratio <= 1:
        return 0.7 * ratio
    return min(1.0, 0.7 + 0.3 * (ratio - 1))


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%" if abs(value) >= 0.01 else f"{value * 100:.1f}%"


def score(candidate: Candidate, anchors: Anchors) -> Score:
    reasons: list[str] = []
    bonuses: dict[str, float] = {}

    # Magnitude
    magnitude = 0.0
    if candidate.unit == "currency" and candidate.amount is not None:
        basis = candidate.amount
        if candidate.magnitude_basis == "delta" and candidate.base_amount is not None:
            basis = candidate.amount - candidate.base_amount
        shares = anchors.shares(basis) if anchors.currency == candidate.currency else {}
        if shares:
            anchor, share = max(shares.items(), key=lambda kv: kv[1] / THRESHOLDS[kv[0]])
            magnitude = _curve(share / THRESHOLDS[anchor])
            if share >= THRESHOLDS[anchor] / 2:
                what = "a change of " if basis is not candidate.amount else ""
                reasons.append(f"{what}{_pct(share)} of {anchor.replace('_', ' ')}")
        if candidate.currency == "USD" and abs(basis) >= ABSOLUTE_USD:
            bonuses["over_10b"] = BONUSES["over_10b"]
    elif candidate.unit == "ratio" and candidate.amount is not None:
        magnitude = _curve(abs(candidate.amount) / CONCENTRATION_THRESHOLD)
    elif candidate.unit in ("points", "days") and candidate.change is not None:
        threshold = POINTS_THRESHOLD if candidate.unit == "points" else DAYS_THRESHOLD
        magnitude = _curve(abs(candidate.change) / threshold)

    # Change
    if candidate.change_type == "new":
        change = 1.0
        reasons.append("new in this filing")
    elif candidate.change_type == "removed":
        change = 0.6
        reasons.append("no longer disclosed")
    elif candidate.change_type == "changed" and candidate.change is not None and candidate.unit in ("points", "days", "ratio"):
        # A ratio's change is in percentage points.
        threshold = DAYS_THRESHOLD if candidate.unit == "days" else POINTS_THRESHOLD
        change = _curve(abs(candidate.change) / threshold)
        reasons.append(f"{candidate.change:+.0f} days" if candidate.unit == "days" else f"{candidate.change * 100:+.1f} pts")
    elif candidate.change_type == "changed" and (candidate.change is not None or candidate.base_amount == 0):
        if candidate.change is None:
            change = 1.0
            reasons.append("from zero")
        else:
            change = _curve(abs(candidate.change) / 0.5)
            if abs(candidate.change) >= 0.1:
                reasons.append(f"{candidate.change * 100:+.0f}%")
        if candidate.unit == "currency" and candidate.amount is not None:
            delta = abs(candidate.amount - (candidate.base_amount or 0))
            big_enough = (anchors.revenue and anchors.currency == candidate.currency
                          and delta >= CHANGE_FLOOR_SHARE * abs(anchors.revenue)) or (
                candidate.currency == "USD" and delta >= CHANGE_FLOOR_USD)
            if not big_enough:
                change *= 0.3  # a large percentage of a small amount
    elif candidate.change_type == "changed":
        change = 0.5  # reworded language
    else:
        change = 0.0

    strategic = STRATEGIC.get(candidate.category, 0.5)
    language = max((t["weight"] for t in candidate.triggers), default=0.0)
    if candidate.triggers:
        reasons.append("mentions " + ", ".join(f"“{t['phrase']}”" for t in candidate.triggers[:2]))
    novelty = NOVELTY.get(candidate.change_type, 0.0)

    for flag in candidate.flags:
        if flag in BONUSES:
            bonuses[flag] = BONUSES[flag]
    if candidate.change_type == "new" and candidate.category == "guarantee":
        bonuses["new_guarantee"] = BONUSES["new_guarantee"]
    if any(t["phrase"] == "material weakness" for t in candidate.triggers):
        bonuses["material_weakness"] = BONUSES["material_weakness"]
    if any(t["phrase"] == "critical audit matter" for t in candidate.triggers):
        bonuses["critical_audit_matter"] = BONUSES["critical_audit_matter"]
    if "subsequent_event" in bonuses:
        reasons.append("subsequent event")
    if "hypothetical_to_realized" in bonuses:
        reasons.append("was hypothetical, now described as having happened")

    components = {"magnitude": magnitude, "change": change, "strategic": strategic, "language": language, "novelty": novelty}
    total = sum(WEIGHTS[k] * v for k, v in components.items()) + sum(bonuses.values())
    total = round(min(1.0, total), 3)
    tier = next((name for name, floor in TIERS if total >= floor), "background")
    return Score(total, tier, {**{k: round(v, 3) for k, v in components.items()}, "bonuses": bonuses}, reasons)
