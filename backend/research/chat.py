"""Questions about a company's filings, answered from what is stored (no filing is fetched per question).

Each question gets a small context so it fits Groq's free tier (about 8k tokens a minute): the key figures and the
largest filing changes from the snapshot, plus the filing passages that best match the question (ranked in code
over the stored paragraphs of the latest annual and interim reports). Groq answers, with Mistral as the
fallback; Gemini is kept for the filing analysis. The model must cite the passages it uses;
the passages come back with the answer so the reader can check them, and every figure in the answer is checked
against the context. The server keeps no conversation state: the page sends the recent turns with each question.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import psycopg

from figures import FigureIndex, check_figures
from research import interpret, llm, narrative, store
from research.rows import fiscal_label

MAX_QUESTION_CHARS = 500
MAX_TURNS = 8
MAX_TURN_CHARS = 1_500
CHUNK_CHARS = 900
PASSAGE_BUDGET = 7_000        # characters of filing passages per question
MAX_PASSAGES = 8
DIGEST_ROWS = ("revenue", "revenue_growth", "gross_margin", "operating_margin", "net_income", "free_cash_flow",
               "capex", "net_cash", "buybacks")
STOPWORDS = set("""a an and are as at be been but by can could did do does for from had has have how i if in into is
it its of on or our so than that the their them then there these they this to up was we were what when where which
while who why will with would you your about any company companies filing filings tell me please much many""".split())
SECTION_LABELS = {
    "management_discussion": "Management's discussion", "risk_factors": "Risk factors", "business": "Business",
    "subsequent_events": "Subsequent events", "commitments": "Commitments and contingencies",
}

SYSTEM = """
You answer questions about one company's SEC filings for an equity research tool.

Rules:
1. Use only the KEY FIGURES and FILING PASSAGES provided. Do not use outside knowledge about the company, its stock
   or the news. If they do not answer the question, say so plainly and say what the filings do cover.
2. Cite the passage behind each statement right after it, like [S2]; cite the key figures as [F].
3. Copy numbers exactly as they are written in the input; do not calculate new totals or growth rates.
4. Be concise (under 180 words unless asked for detail) and neutral. Keep management's hedging ("expects", "may"),
   and distinguish what has happened from what could happen. Do not give investment advice or predict prices.
5. Write plain sentences; a short list may use "- " bullets. No bold, headings or tables.
"""


class InvalidQuestion(ValueError):
    pass


# Models add markdown emphasis despite the prompt, and write "$25.0 B", which the figure check reads as $25.0.
EMPHASIS = re.compile(r"\*\*|__")
SPACED_UNIT = re.compile(r"(\$\d[\d,]*(?:\.\d+)?) ([KMBT])\b")


def tidy(text: str) -> str:
    return SPACED_UNIT.sub(r"\1\2", EMPHASIS.sub("", text)).strip()


@dataclass
class Chunk:
    id: str
    text: str
    label: str
    document_url: str | None
    tokens: Counter


def _tokens(text: str) -> list[str]:
    return [w[:6] for w in re.findall(r"[a-z][a-z0-9'-]{2,}", text.lower()) if w not in STOPWORDS]


def chunks(sections: list[dict], filings: dict[int, dict]) -> list[Chunk]:
    """Paragraphs of prose, merged up to about CHUNK_CHARS, labelled with their filing and section."""
    out = []
    for section in sorted(sections, key=lambda s: (s["filing_id"], s["ordinal"])):
        filing = filings[section["filing_id"]]
        label = (f"{filing['form_type']} {fiscal_label(filing['fiscal_year'], filing['fiscal_period'])} · "
                 f"{SECTION_LABELS.get(section['category'], (section['heading'] or section['category'].replace('_', ' ')).capitalize())}")
        buffer = ""
        for line in narrative.PAGE_FURNITURE.sub("", section["text"]).split("\n"):
            line = line.strip()
            if not line or narrative.is_tabular(line):
                continue
            if buffer and len(buffer) + len(line) > CHUNK_CHARS:
                out.append(Chunk("", buffer, label, section["document_url"], Counter(_tokens(buffer))))
                buffer = ""
            buffer = f"{buffer} {line}".strip()
        if len(buffer) >= 80:
            out.append(Chunk("", buffer, label, section["document_url"], Counter(_tokens(buffer))))
    return out


def rank(pool: list[Chunk], query: str, follow_up: str = "") -> list[Chunk]:
    """BM25 over the chunks; the previous question adds context at half weight (for follow-ups like "why?")."""
    weights = Counter({t: 1.0 for t in _tokens(query)})
    for t in _tokens(follow_up):
        weights[t] = max(weights[t], 0.5)
    if not weights or not pool:
        return []
    n = len(pool)
    average = sum(sum(c.tokens.values()) for c in pool) / n
    frequency = Counter(t for c in pool for t in c.tokens if t in weights)
    scored = []
    for chunk in pool:
        length = sum(chunk.tokens.values())
        score = 0.0
        for term, weight in weights.items():
            tf = chunk.tokens.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += weight * idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / average))
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda s: -s[0])
    chosen, size = [], 0
    for _, chunk in scored:
        if len(chosen) == MAX_PASSAGES or size + len(chunk.text) > PASSAGE_BUDGET:
            break
        chosen.append(chunk)
        size += len(chunk.text)
    for n_, chunk in enumerate(chosen, 1):
        chunk.id = f"S{n_}"
    return chosen


def digest(payload: dict) -> str:
    currency = payload["financials"]["currency"]
    lines = []
    for kind, count in (("annual", 2), ("quarterly", 2)):
        table = payload["financials"][kind]
        columns = table["columns"][-count:]
        if not columns:
            continue
        offset = len(table["columns"]) - len(columns)
        labels = [fiscal_label(c["fiscal_year"], c["fiscal_period"]) for c in columns]
        for row in table["rows"]:
            if row["key"] in DIGEST_ROWS:
                cells = [row["values"][offset + i] for i in range(len(columns))]
                values = " | ".join(f"{label} {interpret._value(c['v'], row['unit'], currency) if c else 'n/a'}"
                                    for label, c in zip(labels, cells))
                lines.append(f"{row['label']}: {values}")
    for item in payload["changes"]["items"][:6]:
        if item["kind"] == "narrative":
            continue
        value = interpret._value(item["value"], item["unit"], item["currency"]) if item.get("value") is not None else "no longer disclosed"
        base = (f" (was {interpret._value(item['base_value'], item['unit'], item['currency'])}, {item.get('base_period_label')})"
                if item.get("base_value") is not None else "")
        lines.append(f"Filing change ({item['change_type']}): {item['label']} {value}, {item.get('period_label')}{base}")
    return "\n".join(lines)


def _clean(question: str, history: list[dict]) -> tuple[str, list[dict]]:
    question = (question or "").strip()
    if not question:
        raise InvalidQuestion("Ask a question about the filing.")
    if len(question) > MAX_QUESTION_CHARS:
        raise InvalidQuestion(f"Keep questions under {MAX_QUESTION_CHARS} characters.")
    turns = [{"role": t.get("role"), "content": str(t.get("content", ""))[:MAX_TURN_CHARS]}
             for t in (history or [])[-MAX_TURNS:] if t.get("role") in ("user", "assistant")]
    return question, turns


def answer(conn: psycopg.Connection, company_id: int, question: str, history: list[dict], payload: dict) -> dict:
    question, turns = _clean(question, history)
    company = store.find_company(conn, company_id=company_id)
    filings = store.company_filings(conn, company_id)
    chosen = interpret.targets(filings)
    ids = {f["filing_id"] for f in chosen}
    sections = [s for s in store.company_sections(conn, company_id, (
        "business", "management_discussion", "risk_factors", "subsequent_events", "commitments", "contingencies",
        "guarantees", "debt", "acquisitions", "customer_concentration", "revenue", "segment_information",
        "income_taxes", "capital_return", "investments", "leases", "restructuring", "goodwill_impairment",
    )) if s["filing_id"] in ids]
    previous = next((t["content"] for t in reversed(turns) if t["role"] == "user"), "")
    passages = rank(chunks(sections, {f["filing_id"]: f for f in filings}), question, previous)

    latest = payload["changes"].get("filing") or {}
    parts = [f"COMPANY: {company['name']} ({company['ticker']}). Latest filing: {latest.get('form', '')} for "
             f"{latest.get('fiscal_label', '')}. Reporting currency: {payload['financials']['currency']}.",
             "KEY FIGURES [F] (from the filings' tagged data)\n" + digest(payload)]
    if passages:
        parts.append("FILING PASSAGES\n" + "\n".join(f"[{p.id}] {p.label}: {p.text}" for p in passages))
    else:
        parts.append("FILING PASSAGES\n(none of the stored filing text matches this question)")
    if turns:
        parts.append("CONVERSATION SO FAR\n" + "\n".join(
            f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content']}" for t in turns))
    parts.append(f"QUESTION: {question}")
    context = "\n\n".join(parts)

    result = llm.reply(SYSTEM, context)
    text = tidy(result.text)
    index = FigureIndex()
    index.add_text(context)
    cited = set(re.findall(r"\[(S\d+)\]", text))
    return {
        "answer": text,
        "figures": check_figures(text, index),
        "sources": [{"id": p.id, "label": p.label, "text": p.text, "document_url": p.document_url}
                    for p in passages if p.id in cited],
        "model": result.model,
    }
