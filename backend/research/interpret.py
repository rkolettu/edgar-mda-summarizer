"""The model stages: extraction once per filing (call A) and synthesis once per latest filing (call B).

Call A reads only selected text: the business description, management's discussion without its tables, and risk
factors as an outline plus the passages that are new or changed since the previous annual report (a quarterly
report's risk factor updates in full). Every item must quote the filing verbatim; the quote and each figure are
checked in code.

Call B never sees a filing. It reads what code already computed and ranked (financial tables, filing changes, the
earnings bridge) and call A's verified items, each under an id, and must cite ids for every statement; every number
it writes must appear in its input. Items without a valid id are dropped; figures that cannot be traced are flagged.

Outputs are stored once (model_outputs) and merged into the snapshot, so viewing a tab never calls a model.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

import verify
from figures import FigureIndex, check_figures
from research import llm, narrative, store
from research.rows import fiscal_label

# Bump when a stage's prompt, schema or inputs change; outputs at an older version are regenerated on request.
EXTRACT_VERSION = 1
SYNTH_VERSION = 1
AUDIT_VERSION = 1

LIMITS = {
    "business": 30_000,
    "management_discussion_annual": 45_000,
    "management_discussion_interim": 35_000,
    "risk_outline": 12_000,
    "risk_changes": 15_000,
    "risk_updates": 20_000,
}
MAX_CHANGES = 25
OUTLINE_LINE = (40, 400)


# --- schemas ---


class Item(BaseModel):
    headline: str
    detail: str
    evidence: str


class Driver(Item):
    direction: str


class Risk(Item):
    category: str
    company_specific: bool
    trend: str
    realized: bool


class Extraction(BaseModel):
    business_summary: str
    segments: list[Item]
    strategy: list[Item]
    drivers: list[Driver]
    outlook: list[Item]
    upside: list[Item]
    downside: list[Item]
    risks: list[Risk]
    non_operating: list[Item]


class Point(BaseModel):
    headline: str
    detail: str
    refs: list[str]


class RiskView(BaseModel):
    ref: str
    headline: str
    detail: str
    trend: str


class EarningsQuality(BaseModel):
    summary: str
    points: list[Point]


class ChangeNote(BaseModel):
    ref: str
    note: str


class Synthesis(BaseModel):
    takeaways: list[Point]
    business_overview: str
    risks: list[RiskView]
    earnings_quality: EarningsQuality
    change_notes: list[ChangeNote]


EXTRACT_PROMPT = """
You extract facts from one SEC filing for an equity research tool. Read only the text provided and return JSON that
matches the schema.

Rules:
1. Every item needs "evidence": one sentence copied word for word from the provided text. It is checked
   automatically; do not merge sentences, paraphrase, or change a number.
2. "headline" is a short phrase; "detail" is one or two plain sentences. Use only numbers that appear in the provided
   text and do not calculate new ones.
3. Keep management's hedging: if the filing says "expects", "may" or "believes", say so. Report the opportunities and
   the cautions management describes without adding your own view.
4. Leave a list empty when the text does not support it. Prefer specific, company-specific statements to generic ones.

Fields:
- business_summary: two or three sentences on what the company sells, to whom, and how it is organized, from the
  business description ("" when the filing has none).
- segments: each reportable segment or major product line the text describes (up to 6).
- strategy: management's stated priorities and investments (up to 5).
- drivers: management's explanations of what moved revenue, margins or costs in the period (up to 6); "direction"
  is "up", "down" or "mixed".
- outlook: forward-looking statements about demand, spending, margins or guidance (up to 5).
- upside, downside: the most important opportunities and cautions in management's own words (up to 4 each).
- risks: company-specific risks (up to 10). Include every passage listed under "NEW OR CHANGED RISK FACTORS" or
  "RISK FACTOR UPDATES" with "trend" "new" or "heightened"; risks taken only from the outline are "ongoing".
  "realized" is true only when the text says the event has already happened ("we have been", "resulted in"), false
  when it could happen. "category" is one of: regulation, trade and export controls, supply chain, customers and
  demand, competition, technology, financial, legal, operations, macro, other. "company_specific" is false for risks
  any company could list.
- non_operating: how the filing explains non-operating items such as investment gains or losses, interest, other
  income or one-time charges (up to 5).
"""

SYNTH_PROMPT = """
You write the summary layer of an equity research tool from facts that code has already extracted, calculated and
ranked. You do not see the filing itself.

Rules:
1. Use only the facts provided. Every number you write must appear in the input exactly as written there, with the
   same rounding; do not calculate new totals, ratios or growth rates.
2. Every item cites the ids of the facts it relies on ("m.revenue", "c3", "r2", ...) in "refs" (or "ref"). Items
   without a valid id are discarded.
3. Be neutral and specific: explain what changed and why it matters. Do not recommend buying or selling, predict
   prices, or call a change good or bad unless the filing does. Keep management's hedging, and distinguish what has
   happened from what could happen.

Fields:
- takeaways: the 3 to 5 most important things an investor should know from the latest filing, most material first;
  lean on the highest-scoring filing changes and the financial trends.
- business_overview: two or three sentences on what the company does and where it is investing.
- risks: up to 8 risks ranked by importance now, new or heightened ones first; "ref" is the risk (r...) or filing
  change (c...) id it rests on; "trend" is "new", "heightened" or "ongoing".
- earnings_quality: a neutral "summary" of how much of net income comes from operations versus non-operating items
  (investment gains, interest, one-time items) and whether operating cash flow keeps up with earnings, with up to 4
  "points".
- change_notes: for up to 10 of the highest-scoring filing changes, one sentence on why it matters ("ref" is the
  change id).
"""


# --- inputs for call A ---


def prose(text: str, limit: int) -> str:
    """Paragraphs without flattened tables or page furniture, up to `limit` characters."""
    out, size = [], 0
    for line in narrative.PAGE_FURNITURE.sub("", text or "").split("\n"):
        line = line.strip()
        if not line or narrative.is_tabular(line):
            continue
        if size + len(line) > limit:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def risk_outline(text: str, limit: int) -> str:
    """Risk headings and summary bullets: one-sentence lines, which is how filings set a risk's title."""
    lines, size, seen = [], 0, set()
    low, high = OUTLINE_LINE
    for line in (text or "").split("\n"):
        line = line.strip().lstrip("•●▪- ").strip()
        if not (low <= len(line) <= high) or not line.endswith((".", ":")) or len(narrative.sentences(line)) != 1:
            continue
        if line in seen or size + len(line) > limit:
            continue
        seen.add(line)
        lines.append(f"- {line}")
        size += len(line) + 3
    return "\n".join(lines)


def changed_risks(new_text: str, base_text: str | None, limit: int) -> str:
    if not base_text:
        return ""
    out, size = [], 0
    passages = [p for p in narrative.diff(new_text, base_text, detect_removed=False).passages if p.kind != "numbers"]
    # New risks before rewordings, and flagged language first, so the cap cuts the least informative passages.
    passages.sort(key=lambda p: (p.change_type != "new", -max((t["weight"] for t in p.triggers), default=0), p.position))
    for passage in passages:
        block = f"[{passage.change_type}] {passage.text}"
        if size + len(block) > limit:
            break
        out.append(block)
        size += len(block) + 2
    return "\n\n".join(out)


def _texts(sections: list[dict]) -> dict[tuple[int, str], str]:
    merged: dict[tuple[int, str], list[str]] = {}
    for s in sorted(sections, key=lambda s: (s["filing_id"], s["ordinal"])):
        merged.setdefault((s["filing_id"], s["category"]), []).append(s["text"])
    return {slot: "\n".join(parts) for slot, parts in merged.items()}


def extraction_input(company: dict, filing: dict, texts: dict, base_annual: dict | None) -> str:
    """The text call A reads for one filing; the same text is the source its quotes are checked against."""
    fid = filing["filing_id"]
    label = fiscal_label(filing["fiscal_year"], filing["fiscal_period"]) or filing["period_end"].isoformat()
    parts = [f"COMPANY: {company['name']} ({company['ticker']}). FILING: {filing['form_type']} for {label}, period ended "
             f"{filing['period_end'].isoformat()}. Reporting currency: {company['reporting_currency'] or 'unknown'}."]
    if texts.get((fid, "business")):
        parts.append("=== BUSINESS DESCRIPTION ===\n" + prose(texts[(fid, "business")], LIMITS["business"]))
    mdna_limit = LIMITS["management_discussion_annual" if filing["is_annual"] else "management_discussion_interim"]
    if texts.get((fid, "management_discussion")):
        parts.append("=== MANAGEMENT'S DISCUSSION AND ANALYSIS ===\n" + prose(texts[(fid, "management_discussion")], mdna_limit))
    risks = texts.get((fid, "risk_factors"))
    if risks and filing["is_annual"]:
        parts.append("=== RISK FACTORS: OUTLINE ===\n" + risk_outline(risks, LIMITS["risk_outline"]))
        base = texts.get((base_annual["filing_id"], "risk_factors")) if base_annual else None
        changed = changed_risks(risks, base, LIMITS["risk_changes"])
        if changed:
            parts.append(f"=== NEW OR CHANGED RISK FACTORS (since the {base_annual['form_type']} for "
                         f"{fiscal_label(base_annual['fiscal_year'], base_annual['fiscal_period'])}) ===\n{changed}")
    elif risks:
        parts.append("=== RISK FACTOR UPDATES IN THIS QUARTERLY REPORT ===\n" + prose(risks, LIMITS["risk_updates"]))
    return "\n\n".join(parts)


# --- verification ---


def _fact_index(rows: list[dict]) -> FigureIndex:
    index = FigureIndex()
    for row in rows:
        if row["normalized_unit"] == "ratio":
            index.add_percent(row["value"] * 100)
        elif row["normalized_unit"] in ("currency", "currency_per_share"):
            index.add_amount(row["value"])
    return index


def _annotate(items: list[BaseModel], source: str, index: FigureIndex) -> list[dict]:
    return verify.annotate([i.model_dump() for i in items], source, index)


PASSAGE_MARKER = re.compile(r"^\s*\[(?:new|changed)\]\s*", re.IGNORECASE)


def verify_extraction(result: Extraction, source: str, rows: list[dict]) -> dict:
    # A quote may carry the [new] / [changed] marker the input puts before a risk passage; it is not filing text.
    for field in ("segments", "strategy", "drivers", "outlook", "upside", "downside", "risks", "non_operating"):
        for item in getattr(result, field):
            item.evidence = PASSAGE_MARKER.sub("", item.evidence)
            item.detail = PASSAGE_MARKER.sub("", item.detail)
    normalized = verify.normalize(source)
    index = _fact_index(rows)
    index.add_text(source)
    out = {"business_summary": result.business_summary}
    for field in ("segments", "strategy", "drivers", "outlook", "upside", "downside", "risks", "non_operating"):
        out[field] = _annotate(getattr(result, field), normalized, index)
    for risk in out["risks"]:
        risk["trend"] = risk["trend"] if risk["trend"] in ("new", "heightened") else "ongoing"
    for driver in out["drivers"]:
        driver["direction"] = driver["direction"] if driver["direction"] in ("up", "down") else "mixed"
    return out


# --- inputs for call B ---


def _money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "n/a"
    prefix = {"USD": "$", "TWD": "NT$", "CAD": "C$", "HKD": "HK$", "AUD": "A$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(
        currency or "", f"{currency} " if currency else "")
    sign, amount = ("-" if value < 0 else ""), abs(value)
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if amount >= scale:
            return f"{sign}{prefix}{amount / scale:.1f}{suffix}"
    return f"{sign}{prefix}{amount:,.0f}"


def _value(value: float | None, unit: str, currency: str | None) -> str:
    if value is None:
        return "n/a"
    if unit in ("ratio", "points"):
        return f"{value * 100:.1f}%"
    if unit == "days":
        return f"{value:.0f} days"
    if unit == "currency_per_share":
        return f"{value:.2f} per share"
    return _money(value, currency)


def _change(item: dict) -> str:
    change = item.get("change")
    if change is None:
        return ""
    if item["unit"] in ("ratio", "points"):
        return f" ({change * 100:+.1f} points)"
    if item["unit"] == "days":
        return f" ({change:+.0f} days)"
    return f" ({change * 100:+.1f}%)"


@dataclass
class SynthesisInput:
    text: str
    refs: dict[str, dict]      # id -> stable description of what it points at


DIGEST_ROWS = ("revenue", "revenue_growth", "gross_margin", "operating_margin", "net_income", "net_margin",
               "operating_cash_flow", "free_cash_flow", "cash_conversion", "capex", "buybacks", "net_cash",
               "receivable_days", "inventory_days")


def synthesis_input(payload: dict, extractions: list[tuple[dict, dict]]) -> SynthesisInput:
    company, currency = payload["company"], payload["financials"]["currency"]
    changes_section = payload["changes"]
    refs: dict[str, dict] = {}
    lines = [f"COMPANY: {company['name']} ({company['ticker']}). Latest filing: {changes_section['filing']['form']} for "
             f"{changes_section['filing']['fiscal_label']}. Reporting currency: {currency}. Amounts are in the reporting "
             "currency; nothing is converted."]

    for kind, title in (("annual", "ANNUAL"), ("quarterly", "QUARTERLY")):
        table = payload["financials"][kind]
        columns = table["columns"][-3:] if kind == "annual" else table["columns"][-4:]
        if not columns:
            continue
        offset = len(table["columns"]) - len(columns)
        labels = [fiscal_label(c["fiscal_year"], c["fiscal_period"]) for c in columns]
        lines.append(f"\n{title} FINANCIALS (id m.<row>; columns {', '.join(labels)})")
        for row in table["rows"]:
            if row["key"] not in DIGEST_ROWS:
                continue
            cells = [row["values"][offset + i] for i in range(len(columns))]
            values = [_value(c["v"], row["unit"], currency) if c else "n/a" for c in cells]
            ref = f"m.{row['key']}"
            refs[ref] = {"type": "metric", "key": row["key"], "label": row["label"]}
            lines.append(f"{ref} {row['label']}: " + " | ".join(values))

    lines.append("\nFILING CHANGES, most material first (id c<n>; score 0-1 computed in code)")
    for n, item in enumerate(changes_section["items"][:MAX_CHANGES], start=1):
        ref = f"c{n}"
        refs[ref] = {"type": "change", "key": item["id"], "label": item["label"], "category": item["category_label"]}
        if item["kind"] == "narrative":
            what = f"{item['change_type']} wording in {item['category_label']}: \"{item['text'][:400]}\""
        elif item["change_type"] == "removed":
            what = (f"{item['label']} ({item['category_label']}) no longer disclosed; was "
                    f"{_value(item['base_value'], item['unit'], item['currency'])} ({item.get('base_period_label')})")
        else:
            base = (f" from {_value(item['base_value'], item['unit'], item['currency'])} ({item['base_period_label']})"
                    if item.get("base_value") is not None else "")
            what = (f"{item['change_type']}: {item['label']} ({item['category_label']}) "
                    f"{_value(item['value'], item['unit'], item['currency'])} ({item.get('period_label')}){base}{_change(item)}")
            if item.get("note"):
                what += f"; {item['note']}"
        flags = f" [{', '.join(item['flags'])}]" if item.get("flags") else ""
        lines.append(f"{ref} score {item['score']:.2f}{flags}: {what}")

    bridges = payload["earnings_quality"]["bridges"]
    if bridges:
        lines.append("\nEARNINGS BRIDGE (id e.<period>)")
    for bridge in bridges:
        ref = f"e.{bridge['label'].replace(' ', '_')}"
        refs[ref] = {"type": "bridge", "label": f"Earnings bridge, {bridge['label']}"}
        share = bridge.get("non_operating_share_of_pretax")
        parts = [f"operating income {_money(bridge['operating_income'], currency)}",
                 f"non-operating {_money(bridge['non_operating'], currency)}",
                 f"pretax {_money(bridge['pretax_income'], currency)}", f"tax {_money(bridge['income_tax'], currency)}",
                 f"net income {_money(bridge['net_income'], currency)}"]
        if share is not None:
            parts.append(f"non-operating share of pretax {share * 100:.1f}%")
        items = "; ".join(f"{i['label']} {_money(i['value'], currency)}" for i in bridge["items"][:6])
        lines.append(f"{ref} {bridge['label']}: " + ", ".join(parts) + (f". Items: {items}" if items else ""))

    counters: dict[str, int] = {}
    for filing, output in extractions:
        label = f"{filing['form_type']} {fiscal_label(filing['fiscal_year'], filing['fiscal_period'])}"
        lines.append(f"\nEXTRACTED FROM THE {label} (verified quotes)")
        if output.get("business_summary"):
            lines.append(f"Business: {output['business_summary']}")
        for field, prefix in (("segments", "s"), ("strategy", "g"), ("drivers", "d"), ("outlook", "o"),
                              ("upside", "u"), ("downside", "w"), ("risks", "r"), ("non_operating", "n")):
            for item in output.get(field, []):
                if item["status"] == "unverified":
                    continue
                counters[prefix] = counters.get(prefix, 0) + 1
                ref = f"{prefix}{counters[prefix]}"
                refs[ref] = {"type": "extraction", "field": field, "filing": filing["accession_number"],
                             "label": item["headline"], "form": label}
                extra = ""
                if field == "risks":
                    extra = f" [{item['trend']}{', has happened' if item['realized'] else ''}]"
                elif field == "drivers":
                    extra = f" [{item['direction']}]"
                lines.append(f"{ref} {field}{extra}: {item['headline']}: {item['detail']}")
    return SynthesisInput("\n".join(lines), refs)


def _synthesis_index(payload: dict, text: str) -> FigureIndex:
    index = FigureIndex()
    index.add_text(text)
    for kind in ("annual", "quarterly"):
        for row in payload["financials"][kind]["rows"]:
            for cell in row["values"]:
                if cell is None:
                    continue
                if row["unit"] == "ratio":
                    index.add_percent(cell["v"] * 100)
                elif row["unit"].startswith("currency"):
                    index.add_amount(cell["v"])
    for item in payload["changes"]["items"]:
        for key in ("value", "base_value", "annual_value"):
            if item.get(key) is None:
                continue
            if item["unit"] in ("ratio", "points"):
                index.add_percent(item[key] * 100)
            elif item["unit"] == "currency":
                index.add_amount(item[key])
        if item.get("change") is not None and item["unit"] != "days":
            index.add_percent(item["change"] * 100)
    return index


def verify_synthesis(result: Synthesis, source: SynthesisInput, payload: dict) -> dict:
    index = _synthesis_index(payload, source.text)

    def point(p: Point | RiskView, refs: list[str]) -> dict | None:
        valid = [source.refs[r] | {"id": r} for r in dict.fromkeys(refs) if r in source.refs]
        if not valid:
            return None  # a statement that cites nothing it was given
        figures = {field: check_figures(getattr(p, field), index) for field in ("headline", "detail")}
        traced = all(span["verified"] for spans in figures.values() for span in spans)
        return {"headline": p.headline, "detail": p.detail, "refs": valid, "figures": figures,
                "verified": True, "status": "verified" if traced else "partial"}

    takeaways = [t for t in (point(p, p.refs) for p in result.takeaways) if t]
    risks = []
    for r in result.risks:
        checked = point(r, [r.ref])
        if checked:
            risks.append({**checked, "trend": r.trend if r.trend in ("new", "heightened") else "ongoing"})
    points = [t for t in (point(p, p.refs) for p in result.earnings_quality.points) if t]
    notes = {}
    for note in result.change_notes:
        target = source.refs.get(note.ref)
        if target and target["type"] == "change":
            spans = check_figures(note.note, index)
            notes[target["key"]] = {"note": note.note, "figures": spans}
    summary_spans = check_figures(result.earnings_quality.summary, index)
    return {
        "takeaways": takeaways,
        "business_overview": {"text": result.business_overview, "figures": check_figures(result.business_overview, index)},
        "risks": risks,
        "earnings_quality": {"summary": result.earnings_quality.summary, "figures": summary_spans, "points": points},
        "change_notes": notes,
    }


# --- orchestration ---


def targets(filings: list[dict]) -> list[dict]:
    """The filings the tabs describe: the latest annual report, and the latest interim report if it is newer."""
    originals = sorted((f for f in filings if not f["form_type"].endswith("/A") and f["period_end"]),
                       key=lambda f: (f["period_end"], f["filing_date"]), reverse=True)
    annual = next((f for f in originals if f["is_annual"]), None)
    interim = next((f for f in originals if not f["is_annual"]), None)
    chosen = [f for f in (interim, annual) if f]
    if interim and annual and interim["period_end"] < annual["period_end"]:
        chosen = [annual]
    return chosen


def stored_outputs(conn: psycopg.Connection, company_id: int) -> dict[tuple[int, str], dict]:
    rows = conn.execute(
        "SELECT filing_id, stage, model, output, created_at FROM model_outputs WHERE company_id = %s AND "
        "((stage = 'extract' AND pipeline_version = %s) OR (stage = 'synthesize' AND pipeline_version = %s)"
        " OR (stage = 'audit' AND pipeline_version = %s))",
        (company_id, EXTRACT_VERSION, SYNTH_VERSION, AUDIT_VERSION),
    ).fetchall()
    return {(fid, stage): {"model": model, "output": output, "created_at": created} for fid, stage, model, output, created in rows}


def _save(conn: psycopg.Connection, company_id: int, filing_id: int, stage: str, version: int, model: str,
          input_chars: int, output: dict) -> None:
    conn.execute(
        """
        INSERT INTO model_outputs (company_id, filing_id, stage, pipeline_version, model, input_chars, output)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (filing_id, stage, pipeline_version) DO UPDATE SET model = EXCLUDED.model,
            input_chars = EXCLUDED.input_chars, output = EXCLUDED.output, created_at = now()
        """,
        (company_id, filing_id, stage, version, model, input_chars, Jsonb(output)),
    )


@dataclass
class Job:
    filing: dict
    run_id: int
    text: str


class Busy(Exception):
    """Another worker is running a stage this request needs."""


def run(conn: psycopg.Connection, company_id: int, force: bool = False) -> bool:
    """Runs the stages the company is missing. Returns True when anything new was produced.

    Raises llm.ModelUnavailable when no model can answer, and Busy when another worker holds a needed stage."""
    from research import snapshot  # snapshot reads this module's outputs

    company = store.find_company(conn, company_id=company_id)
    filings = store.company_filings(conn, company_id)
    chosen = targets(filings)
    if not chosen:
        return False
    outputs = {} if force else stored_outputs(conn, company_id)
    sections = store.company_sections(conn, company_id, ("business", "management_discussion", "risk_factors"))
    texts = _texts(sections)
    annuals = sorted((f for f in filings if f["is_annual"] and not f["form_type"].endswith("/A") and f["period_end"]),
                     key=lambda f: f["period_end"], reverse=True)
    busy = False

    jobs: list[Job] = []
    for filing in chosen:
        if (filing["filing_id"], "extract") in outputs:
            continue
        if not any(slot[0] == filing["filing_id"] for slot in texts):
            continue  # no narrative text stored for it (a coverage gap); synthesis works from numbers alone
        run_id = store.claim_stage(conn, filing["accession_number"], "extract", EXTRACT_VERSION, force=force)
        if run_id is None:
            busy = True
            continue
        base = next((a for a in annuals if a["period_end"] < filing["period_end"]), None) if filing["is_annual"] else None
        jobs.append(Job(filing, run_id, extraction_input(company, filing, texts, base)))

    produced = False
    if jobs:
        rows = store.company_facts(conn, company_id)
        # Model calls run in parallel; database writes stay on this connection's thread.
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [(job, pool.submit(llm.generate, "extract", EXTRACT_PROMPT, job.text, Extraction)) for job in jobs]
            failure = None
            for job, future in futures:
                try:
                    result = future.result()
                    output = verify_extraction(result.data, job.text, [r for r in rows if r["filing_id"] == job.filing["filing_id"]])
                    with conn.transaction():
                        _save(conn, company_id, job.filing["filing_id"], "extract", EXTRACT_VERSION, result.model, len(job.text),
                              output)
                        store.finish_stage(conn, job.run_id, "succeeded", filing_id=job.filing["filing_id"], model=result.model,
                                           input_tokens=result.input_tokens, output_tokens=result.output_tokens)
                except Exception as exc:  # noqa: BLE001 - release the lock whatever failed, then report it
                    store.finish_stage(conn, job.run_id, "failed", filing_id=job.filing["filing_id"], error=str(exc)[:500])
                    failure = failure or exc
                    continue
                produced = True
            if failure:
                raise failure
        outputs = stored_outputs(conn, company_id)

    latest = chosen[0]
    if (latest["filing_id"], "synthesize") not in outputs or force:
        if busy:
            raise Busy("An extraction for this company is already running.")
        run_id = store.claim_stage(conn, latest["accession_number"], "synthesize", SYNTH_VERSION, force=force)
        if run_id is None:
            raise Busy("A synthesis for this company is already running.")
        try:
            payload, _, _ = snapshot.build(conn, company_id)
            extractions = [(f, outputs[(f["filing_id"], "extract")]["output"]) for f in chosen
                           if (f["filing_id"], "extract") in outputs]
            source = synthesis_input(payload, extractions)
            result = llm.generate("synthesize", SYNTH_PROMPT, source.text, Synthesis)
            output = verify_synthesis(result.data, source, payload)
            with conn.transaction():
                _save(conn, company_id, latest["filing_id"], "synthesize", SYNTH_VERSION, result.model, len(source.text), output)
                store.finish_stage(conn, run_id, "succeeded", filing_id=latest["filing_id"], model=result.model,
                                   input_tokens=result.input_tokens, output_tokens=result.output_tokens)
                # Earlier syntheses and audits describe filings the tabs no longer show.
                conn.execute("DELETE FROM model_outputs WHERE company_id = %s AND stage IN ('synthesize', 'audit') "
                             "AND filing_id <> %s", (company_id, latest["filing_id"]))
        except Exception as exc:
            store.finish_stage(conn, run_id, "failed", filing_id=latest["filing_id"], error=str(exc)[:500])
            raise
        produced = True
        outputs = stored_outputs(conn, company_id)

    if (latest["filing_id"], "synthesize") in outputs and ((latest["filing_id"], "audit") not in outputs or force):
        try:
            produced |= _run_audit(conn, company_id, filings, chosen, outputs, force)
        except (llm.ModelUnavailable, Busy) as exc:
            # The summary stands without its check; the next request (or the daily job) runs the audit again.
            print(f"omission audit not run: {exc}", flush=True)
    if produced:
        snapshot.rebuild(conn, company_id)
    return produced


def _run_audit(conn: psycopg.Connection, company_id: int, filings: list[dict], chosen: list[dict], outputs: dict,
               force: bool) -> bool:
    from research import audit, snapshot

    latest = chosen[0]
    run_id = store.claim_stage(conn, latest["accession_number"], "audit", AUDIT_VERSION, force=force)
    if run_id is None:
        raise Busy("An omission audit for this company is already running.")
    try:
        synth = outputs[(latest["filing_id"], "synthesize")]["output"]
        payload, _, _ = snapshot.build(conn, company_id)
        extractions = [(f, outputs[(f["filing_id"], "extract")]["output"]) for f in chosen if (f["filing_id"], "extract") in outputs]
        ids = {f["filing_id"] for f in chosen}
        sections = [s for s in store.company_sections(conn, company_id, audit.LANGUAGE_CATEGORIES) if s["filing_id"] in ids]
        items = audit.candidates(payload, synth, sections, filings, extractions)
        open_items = [c for c in items if not c.covered_by]
        model, tokens, text = "none", (None, None), ""
        if open_items:
            text = audit.audit_input(payload, synth, open_items)
            result = llm.generate("audit", audit.AUDIT_PROMPT, text, audit.Audit)
            output = audit.verify(result.data, text, payload, synth, items)
            model, tokens = result.model, (result.input_tokens, result.output_tokens)
        else:
            output = audit.all_covered(items)  # the summary cites everything flagged: no model call
        with conn.transaction():
            _save(conn, company_id, latest["filing_id"], "audit", AUDIT_VERSION, model, len(text), output)
            store.finish_stage(conn, run_id, "succeeded", filing_id=latest["filing_id"], model=model,
                               input_tokens=tokens[0], output_tokens=tokens[1])
    except Exception as exc:
        store.finish_stage(conn, run_id, "failed", filing_id=latest["filing_id"], error=str(exc)[:500])
        raise
    return True


# --- the snapshot's insights section ---


def _with_source(items: list[dict], filing: dict) -> list[dict]:
    source = {"form": filing["form_type"], "fiscal_label": fiscal_label(filing["fiscal_year"], filing["fiscal_period"]),
              "accession_number": filing["accession_number"], "document_url": filing["source_url"]}
    return [{**item, "source": source} for item in items]


def _merged(extractions: list[tuple[dict, dict]], field: str, limit: int) -> list[dict]:
    """Items from the latest filing first, then the annual report's, without repeating a headline."""
    out, seen = [], set()
    for filing, output in extractions:
        for item in _with_source(output.get(field, []), filing):
            key = item["headline"].lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out[:limit]


def insights_section(conn: psycopg.Connection, company_id: int, filings: list[dict]) -> dict:
    chosen = targets(filings)
    outputs = stored_outputs(conn, company_id)
    extractions = [(f, outputs[(f["filing_id"], "extract")]["output"]) for f in chosen if (f["filing_id"], "extract") in outputs]
    synthesis = outputs.get((chosen[0]["filing_id"], "synthesize")) if chosen else None
    audit = outputs.get((chosen[0]["filing_id"], "audit")) if chosen else None
    if not extractions and not synthesis:
        return {"status": "pending"}
    synth = synthesis["output"] if synthesis else {}
    annual = next(((f, o) for f, o in extractions if f["is_annual"]), None)
    latest = extractions[0] if extractions else None

    ranked = []
    by_label = {(f["accession_number"], item["headline"]): (f, item) for f, o in extractions for item in o.get("risks", [])}
    for risk in synth.get("risks", []):
        ref = risk["refs"][0]
        found = by_label.get((ref.get("filing"), ref.get("label"))) if ref["type"] == "extraction" else None
        ranked.append({**risk, "extracted": _with_source([found[1]], found[0])[0] if found else None})

    used = [outputs[(f["filing_id"], "extract")] for f, _ in extractions] + [o for o in (synthesis, audit) if o]
    models = sorted({o["model"] for o in used} - {"none"})
    return {
        "status": "ready" if synthesis else "partial",
        "models": models,
        "generated_at": synthesis["created_at"].isoformat(timespec="seconds") if synthesis else None,
        "sources": [{"form": f["form_type"], "fiscal_label": fiscal_label(f["fiscal_year"], f["fiscal_period"]),
                     "accession_number": f["accession_number"]} for f, _ in extractions],
        "takeaways": synth.get("takeaways", []),
        "business": {
            "overview": synth.get("business_overview"),
            "summary": (annual or latest)[1].get("business_summary") if (annual or latest) else "",
            "segments": _with_source(annual[1].get("segments", []), annual[0]) if annual else _merged(extractions, "segments", 6),
            "strategy": _merged(extractions, "strategy", 6),
            "drivers": _with_source(latest[1].get("drivers", []), latest[0]) if latest else [],
            "outlook": _merged(extractions, "outlook", 6),
            "upside": _with_source(latest[1].get("upside", []), latest[0]) if latest else [],
            "downside": _with_source(latest[1].get("downside", []), latest[0]) if latest else [],
        },
        "risks": {"ranked": ranked, "extracted": _merged(extractions, "risks", 16)},
        "earnings_quality": {**synth.get("earnings_quality", {}), "explanations": _merged(extractions, "non_operating", 6)},
        "change_notes": synth.get("change_notes", {}),
        "audit": {**audit["output"], "model": audit["model"]} if audit else None,
    }
