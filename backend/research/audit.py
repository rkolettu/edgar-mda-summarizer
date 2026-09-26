"""The omission audit (call C): did the summary leave out anything material?

Code lists what a reader must not miss: every top-tier filing change, anything flagged as a subsequent event, new
guarantee, new financing or language that moved from hypothetical to realized, and sentences in the latest filings
that say a serious event has already happened (a material weakness, going concern doubt, a restatement, a subpoena,
a default). It marks what the summary already cites. Only the rest goes to a model, which answers per item: covered
after all (naming the summary point), missing (writing the point, citing the item), or not material (saying why).
When nothing is left over no model is called. Every addition is checked like the summary itself.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from figures import check_figures
from research import interpret, narrative
from research.rows import fiscal_label

MUST_REVIEW_FLAGS = {"subsequent_event", "new_guarantee", "new_financing", "hypothetical_to_realized"}
SEVERE_WEIGHT = 0.6                 # trigger phrases at or above this weight, when the sentence says it happened
MAX_CHANGES = 12
MAX_LANGUAGE = 6
MAX_ADDITIONS = 3
LANGUAGE_CATEGORIES = ("management_discussion", "risk_factors", "subsequent_events", "contingencies", "commitments",
                       "guarantees", "debt")
# "We did not identify any material weakness" is not a material weakness.
NEGATION = re.compile(r"\b(?:no|not|none|never|neither|nor|without)\b|n't\b", re.IGNORECASE)
DECISIONS = ("covered", "add", "not_material")


class Decision(BaseModel):
    ref: str
    decision: str
    covered_by: str
    reason: str


class Audit(BaseModel):
    decisions: list[Decision]
    additions: list[interpret.Point]


AUDIT_PROMPT = """
You check an equity research summary for omissions. Code flagged the items under "FLAGGED ITEMS" as material, and
the summary does not cite them. Decide for each flagged item (one decision per item id):
- "covered": a summary point already conveys it; put that point's id (T1, R2, E1, ...) in "covered_by".
- "add": an investor would need it and the summary misses it; write it into "additions".
- "not_material": it does not change the picture (a routine fluctuation, a duplicate of another item, boilerplate);
  say why in "reason".

Rules:
1. Use only the facts given. Every number you write must appear in the input exactly as written, with the same
   rounding; do not calculate new numbers.
2. Each addition cites, in "refs", the flagged item ids it covers. At most 3 additions, most important first; one
   addition may cover several related items.
3. Be neutral: explain what it is and why it matters without recommending anything or calling it good or bad.
   Distinguish what has happened from what could happen.
4. "reason" is one short sentence for every decision.
"""


@dataclass
class Candidate:
    id: str
    kind: str                   # change | language
    key: str                    # the change's stable id, or a hash of the sentence
    label: str
    category: str
    description: str            # what the model reads
    score: float
    reasons: list[str] = field(default_factory=list)
    covered_by: list[str] = field(default_factory=list)   # summary headlines that cite it
    text: str | None = None     # the filing sentence, for language items


def _summary_points(synth: dict) -> list[tuple[str, dict]]:
    """(id, point) for every statement of the summary the reader sees: takeaways, ranked risks, earnings points."""
    points = [(f"T{n}", p) for n, p in enumerate(synth.get("takeaways", []), 1)]
    points += [(f"R{n}", p) for n, p in enumerate(synth.get("risks", []), 1)]
    points += [(f"E{n}", p) for n, p in enumerate(synth.get("earnings_quality", {}).get("points", []), 1)]
    return points


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]{5,}", text.lower())}


def change_candidates(payload: dict, synth: dict) -> list[Candidate]:
    cited: dict[str, list[str]] = {}
    metrics: dict[str, list[str]] = {}
    for _, point in _summary_points(synth):
        for ref in point.get("refs", []):
            if ref["type"] == "change":
                cited.setdefault(ref["key"], []).append(point["headline"])
            elif ref["type"] == "metric":
                metrics.setdefault(ref["label"].lower(), []).append(point["headline"])
    out = []
    for item in payload["changes"]["items"]:
        if item["tier"] != "top" and not MUST_REVIEW_FLAGS & set(item.get("flags", [])):
            continue
        covered = cited.get(item["id"], []) + metrics.get(item["label"].lower(), [])
        currency = item.get("currency")
        if item["kind"] == "narrative":
            what = f"{item['change_type']} wording in {item['category_label']}: \"{item['text'][:500]}\""
        elif item["change_type"] == "removed":
            what = (f"{item['label']} no longer disclosed; was {interpret._value(item['base_value'], item['unit'], currency)} "
                    f"({item.get('base_period_label')})")
        else:
            base = (f" from {interpret._value(item['base_value'], item['unit'], currency)} ({item.get('base_period_label')})"
                    if item.get("base_value") is not None else "")
            what = (f"{item['change_type']}: {item['label']} {interpret._value(item['value'], item['unit'], currency)} "
                    f"({item.get('period_label')}){base}{interpret._change(item)}")
        flags = f" [{', '.join(item['flags'])}]" if item.get("flags") else ""
        out.append(Candidate(
            id="", kind="change", key=item["id"], label=item["label"], category=item["category_label"],
            description=f"[filing change, {item['category_label']}, score {item['score']:.2f}{flags}] {what}. "
                        f"Why flagged: {'; '.join(item.get('reasons', []))}",
            score=item["score"], reasons=item.get("reasons", []), covered_by=list(dict.fromkeys(covered)),
        ))
    return sorted(out, key=lambda c: -c.score)


def language_candidates(sections: list[dict], filings: list[dict], synth: dict, extractions: list[tuple[dict, dict]]) -> list[Candidate]:
    """Sentences that say a serious event has happened, one per trigger phrase, latest filing first."""
    by_id = {f["filing_id"]: f for f in filings}
    covered_stems = _stems(" ".join(f"{p['headline']} {p['detail']}" for _, p in _summary_points(synth)))
    seen: dict[str, Candidate] = {}
    order = {f["filing_id"]: n for n, (f, _) in enumerate(extractions)}
    for section in sorted(sections, key=lambda s: (order.get(s["filing_id"], 99), s["ordinal"])):
        filing = by_id[section["filing_id"]]
        for sentence in narrative.sentences(section["text"]):
            if NEGATION.search(sentence):
                continue
            for trigger in narrative.triggers(sentence):
                if not trigger["realized"] or trigger["weight"] < SEVERE_WEIGHT or trigger["phrase"] in seen:
                    continue
                where = f"{filing['form_type']} {fiscal_label(filing['fiscal_year'], filing['fiscal_period'])}"
                category = section["category"].replace("_", " ")
                covered = _stems(trigger["phrase"]) <= covered_stems  # the summary names it
                seen[trigger["phrase"]] = Candidate(
                    id="", kind="language", key=hashlib.sha1(sentence.encode()).hexdigest()[:16],
                    label=f"“{trigger['phrase']}” in the {where} {category}", category=category.capitalize(),
                    text=sentence[:600],
                    description=f"[filing language, {where}, {category}, mentions \"{trigger['phrase']}\" as having "
                                f"happened] \"{sentence[:600]}\"",
                    score=trigger["weight"], reasons=[f"says {trigger['phrase']} has happened"],
                    covered_by=["(summary wording)"] if covered else [],
                )
    return sorted(seen.values(), key=lambda c: -c.score)


def candidates(payload: dict, synth: dict, sections: list[dict], filings: list[dict],
               extractions: list[tuple[dict, dict]]) -> list[Candidate]:
    changes = change_candidates(payload, synth)
    language = language_candidates(sections, filings, synth, extractions)
    # Covered items all count toward the check; the uncovered ones sent to the model are capped per kind.
    chosen = [c for c in changes if c.covered_by] + [c for c in changes if not c.covered_by][:MAX_CHANGES]
    chosen += [c for c in language if c.covered_by] + [c for c in language if not c.covered_by][:MAX_LANGUAGE]
    for n, candidate in enumerate(chosen, 1):
        candidate.id = f"X{n}"
    return chosen


def audit_input(payload: dict, synth: dict, open_items: list[Candidate]) -> str:
    company, changes = payload["company"], payload["changes"]
    lines = [f"COMPANY: {company['name']} ({company['ticker']}). Latest filing: {changes['filing']['form']} for "
             f"{changes['filing']['fiscal_label']}. Reporting currency: {payload['financials']['currency']}.",
             "\nTHE SUMMARY AS WRITTEN (T = takeaway, R = ranked risk, E = earnings quality point)"]
    for pid, point in _summary_points(synth):
        lines.append(f"{pid} {point['headline']}: {point['detail']}")
    lines.append("\nFLAGGED ITEMS THE SUMMARY DOES NOT CITE")
    lines += [f"{c.id} {c.description}" for c in open_items]
    return "\n".join(lines)


def verify(result: Audit, source_text: str, payload: dict, synth: dict, items: list[Candidate]) -> dict:
    index = interpret._synthesis_index(payload, source_text)
    by_id = {c.id: c for c in items}
    points = dict(_summary_points(synth))
    decisions: dict[str, dict] = {}
    for d in result.decisions:
        candidate = by_id.get(d.ref)
        if candidate is None or candidate.covered_by or d.ref in decisions:
            continue
        decision = d.decision if d.decision in DECISIONS else "unresolved"
        covered_by = points.get(d.covered_by.strip())
        if decision == "covered" and covered_by is None:
            decision = "unresolved"  # names a summary point that does not exist
        decisions[d.ref] = {"decision": decision, "reason": d.reason,
                            "covered_by": covered_by["headline"] if covered_by and decision == "covered" else None}

    additions = []
    for p in result.additions[:MAX_ADDITIONS]:
        refs = [r for r in dict.fromkeys(p.refs) if r in by_id and not by_id[r].covered_by]
        if not refs:
            continue  # an addition that covers no flagged item
        figures = {fld: check_figures(getattr(p, fld), index) for fld in ("headline", "detail")}
        traced = all(s["verified"] for spans in figures.values() for s in spans)
        additions.append({
            "headline": p.headline, "detail": p.detail, "figures": figures, "verified": True,
            "status": "verified" if traced else "partial",
            "refs": [{"type": "audit", "id": r, "label": by_id[r].label, "category": by_id[r].category} for r in refs],
        })
        for r in refs:
            decisions.setdefault(r, {"decision": "add", "reason": "", "covered_by": None})
    return _record(items, decisions, additions)


def _record(items: list[Candidate], decisions: dict[str, dict], additions: list[dict]) -> dict:
    rows = []
    for c in items:
        if c.covered_by:
            row = {"decision": "covered", "by": "code", "covered_by": c.covered_by[0], "reason": None}
        else:
            row = {**decisions.get(c.id, {"decision": "unresolved", "reason": None, "covered_by": None}), "by": "model"}
        rows.append({"id": c.id, "kind": c.kind, "key": c.key, "label": c.label, "category": c.category,
                     "score": round(c.score, 3), "reasons": c.reasons, "text": c.text, **row})
    counts = {k: sum(r["decision"] == k for r in rows) for k in (*DECISIONS, "unresolved")}
    return {"checked": len(rows), "counts": counts, "items": rows, "additions": additions}


def all_covered(items: list[Candidate]) -> dict:
    """The record when the summary already cites every flagged item (no model call)."""
    return _record(items, {}, [])
