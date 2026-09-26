"""Deterministic diffs of filing language: which sentences are new, reworded, renumbered or gone.

Sections are compared sentence by sentence using fingerprints, so a repeated risk factor costs nothing and only new
or changed language is scored (and, in later phases, read by a model). Two fingerprints per sentence: the exact
wording, and the wording with every number masked, so "grew 12%" -> "grew 15%" is a number change rather than new
language, and a year rolling forward ("fiscal 2025" -> "fiscal 2026") is treated as a repeat.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field

MIN_SENTENCE_CHARS = 40
PASSAGE_CHARS = 1_500
REWORD_SIMILARITY = 0.75
# Sentence ends, but not after abbreviations such as "U.S." or "Inc." that are followed by a capitalized word.
SENTENCE_BREAK = re.compile(
    r"(?<![A-Z]\.[A-Z]\.)(?<!\bInc\.)(?<!\bCorp\.)(?<!\bCo\.)(?<!\bLtd\.)(?<!\bNo\.)(?<!\bvs\.)(?<!\bSt\.)"
    r"(?<=[.!?;])\s+(?=[A-Z“\"(•])|\s*•\s*"
)
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
# Dates roll forward every period ("As of April 26, 2026" -> "As of July 26, 2026").
MONTH = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
         r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?")
DATE = re.compile(rf"\b{MONTH}\s+\d{{1,2}},?\s+(?:19|20)\d\d\b|\b{MONTH}\s+(?:19|20)\d\d\b")
WORD = re.compile(r"[a-z][a-z'-]{2,}")
STOPWORDS = {
    "the", "and", "for", "that", "with", "our", "are", "was", "were", "which", "this", "from", "have", "has", "had",
    "not", "any", "such", "its", "may", "could", "would", "will", "can", "these", "those", "their", "other", "also",
    "been", "into", "than", "more", "including", "may", "all", "but", "result", "results", "business",
}

# Phrases worth a look when they appear in new or changed language; weights feed the language component of
# materiality. They create candidates, never conclusions.
TRIGGERS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(p, re.IGNORECASE), label, weight) for p, label, weight in [
        (r"effectively foreclosed", "effectively foreclosed", 1.0),
        (r"material weakness", "material weakness", 1.0),
        (r"substantial doubt", "substantial doubt", 1.0),
        (r"going concern", "going concern", 0.9),
        (r"\brestat(?:e|ed|ement)\b", "restatement", 0.8),
        (r"extended payment terms", "extended payment terms", 0.8),
        (r"significant non-?refundable payment", "significant nonrefundable payment", 0.8),
        (r"credit support", "credit support", 0.7),
        (r"subsequent event|subsequent to (?:the end of )?(?:the )?(?:quarter|period|fiscal year)", "subsequent event", 0.7),
        (r"new business model", "new business model", 0.7),
        (r"\bsubpoena", "subpoena", 0.7),
        (r"critical audit matter", "critical audit matter", 0.6),
        (r"counterparty (?:risk|credit)", "counterparty risk", 0.6),
        (r"significant concentration", "significant concentration", 0.6),
        (r"export control|license requirement", "export controls", 0.6),
        (r"cybersecurity incident|cyber-?attack", "cybersecurity incident", 0.6),
        (r"\bin default\b|\bdefault(?:ed|s)? (?:on|under)\b|event of default", "default", 0.6),
        (r"material(?:ly)? adverse(?:ly)? (?:effect|impact|affect)", "material adverse impact", 0.5),
        (r"\bguarant(?:ee|ees|eed|or)\b", "guarantee", 0.5),
        (r"\bimpairment", "impairment", 0.5),
        (r"unrealized loss", "unrealized loss", 0.5),
        (r"investigation", "investigation", 0.5),
        (r"unrealized gain", "unrealized gain", 0.4),
        (r"\bunable to\b", "unable to", 0.4),
        (r"\bindemnif", "indemnification", 0.4),
    ]
]
HYPOTHETICAL = re.compile(r"\b(?:could|may|might|would|if|potential(?:ly)?|possible)\b", re.IGNORECASE)
REALIZED = re.compile(
    r"\b(?:has|have|had|did|resulted|incurred|recorded|recognized|were|was|became|announced|entered|identified"
    r"|determined|concluded|received|experienced|occurred|completed|agreed|issued|terminated)\b",
    re.IGNORECASE,
)
HYPOTHETICAL_FACTOR = 0.5


# Page furniture that lands mid-sentence in flattened HTML ("For example, 24 Table of Contents we may face ...").
PAGE_ARTIFACT = re.compile(r"\s*\b\d{0,3}\s*Table of Contents\b\s*", re.IGNORECASE)
# Boilerplate that says nothing changed.
BOILERPLATE = re.compile(
    r"there have been no material changes|risk factors (?:previously )?(?:described|disclosed) (?:in|under)|forward-looking statements",
    re.IGNORECASE,
)


def sentences(text: str) -> list[str]:
    """Prose sentences; boilerplate and flattened table fragments are left out.

    Lines are paragraphs or table rows, so a line break also ends a sentence ("... $ 7,469" then "As of April 26 ...")
    unless the next line continues in lowercase (text wrapped mid-sentence)."""
    text = re.sub(r"[ \t]*\n\s*(?=[a-z])", " ", PAGE_ARTIFACT.sub(" ", text or ""))
    parts = (re.sub(r"\s+", " ", s).strip() for line in text.split("\n") for s in SENTENCE_BREAK.split(line))
    return [s for s in parts if len(s) >= MIN_SENTENCE_CHARS and not BOILERPLATE.search(s) and not is_tabular(s)]


FIGURE = re.compile(r"[$(]*[\d,.%)—–-]*\d[\d,.%)—–-]*")
SENTENCE_END = re.compile(r"[.!?:;][”\"')]*$")


def is_tabular(text: str) -> bool:
    """A flattened table row or block (labels and figures) rather than prose; its amounts are tagged values."""
    tokens = text.split()
    figures = sum(bool(FIGURE.fullmatch(t)) for t in tokens)
    if len(tokens) >= 8 and figures / len(tokens) > 0.3:
        return True
    return figures > 0 and not SENTENCE_END.search(text.strip())


def _normalize(sentence: str, mask_numbers: bool) -> str:
    text = sentence
    if mask_numbers:
        text = NUMBER.sub("#", DATE.sub("#date", text))
    text = text.lower()
    return " ".join(re.findall(r"[a-z0-9#]+", text))


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def fingerprints(sentence: str) -> tuple[str, str]:
    """(exact, number-masked) fingerprints."""
    return _hash(_normalize(sentence, False)), _hash(_normalize(sentence, True))


def _tokens(sentence: str) -> set[str]:
    return {w for w in WORD.findall(sentence.lower()) if w not in STOPWORDS}


def _only_years_changed(new: str, old: str) -> bool:
    """Dates and years rolling forward ('fiscal 2025' -> 'fiscal 2026') are not new information."""
    a, b = NUMBER.findall(DATE.sub(" ", new)), NUMBER.findall(DATE.sub(" ", old))
    if len(a) != len(b):
        return False
    changed = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
    return all(re.fullmatch(r"(19|20)\d\d", x) and re.fullmatch(r"(19|20)\d\d", y) and abs(int(x) - int(y)) <= 2
               for x, y in changed)


def triggers(text: str) -> list[dict]:
    """Trigger phrases in a passage, each weighted down when every sentence using it is hypothetical."""
    found: dict[str, dict] = {}
    for sentence in sentences(text) or [text]:
        realized = bool(REALIZED.search(sentence)) and not HYPOTHETICAL.search(sentence)
        for pattern, label, weight in TRIGGERS:
            if pattern.search(sentence):
                effective = weight if realized else weight * HYPOTHETICAL_FACTOR
                if effective > found.get(label, {}).get("weight", -1):
                    found[label] = {"phrase": label, "weight": round(effective, 3), "realized": realized}
    return sorted(found.values(), key=lambda t: -t["weight"])


def modality_shift(new: str, old: str) -> bool:
    """Language that moved from what could happen to what has happened."""
    return bool(HYPOTHETICAL.search(old)) and not HYPOTHETICAL.search(new) and bool(REALIZED.search(new))


@dataclass
class Passage:
    change_type: str            # new | changed | removed
    text: str                   # the new wording (the old wording for removed)
    base_text: str | None = None
    kind: str = "wording"       # wording | numbers
    modality_shift: bool = False
    triggers: list[dict] = field(default_factory=list)
    position: int = 0


@dataclass
class Diff:
    passages: list[Passage]
    repeated: int
    total: int

    @property
    def repeated_share(self) -> float:
        return self.repeated / self.total if self.total else 1.0


def diff(new_text: str, base_text: str, detect_removed: bool = True) -> Diff:
    """Compares a section with its counterpart in an earlier filing.

    detect_removed is off when the newer section only lists updates (a 10-Q's risk factors against the 10-K's)."""
    new_sentences, base_sentences = sentences(new_text), sentences(base_text)
    base_exact: set[str] = set()
    base_shape: dict[str, str] = {}
    for sentence in base_sentences:
        exact, shape = fingerprints(sentence)
        base_exact.add(exact)
        base_shape.setdefault(shape, sentence)

    used_base: set[str] = set()
    status: list[tuple[str, str | None]] = []   # (new | changed-numbers | changed | repeated, base sentence)
    repeated = 0
    for sentence in new_sentences:
        exact, shape = fingerprints(sentence)
        if exact in base_exact:
            status.append(("repeated", None))
            used_base.add(exact)
            repeated += 1
        elif shape in base_shape:
            old = base_shape[shape]
            used_base.add(fingerprints(old)[0])
            if _only_years_changed(sentence, old):
                status.append(("repeated", None))
                repeated += 1
            else:
                status.append(("numbers", old))
        else:
            status.append(("new", None))

    # Reworded sentences: an unmatched new sentence that shares most of its words with an unmatched old one.
    unmatched_base = [s for s in base_sentences if fingerprints(s)[0] not in used_base]
    index: dict[str, list[int]] = defaultdict(list)
    base_tokens = [_tokens(s) for s in unmatched_base]
    for i, tokens in enumerate(base_tokens):
        for token in tokens:
            index[token].append(i)
    for i, (state, _) in enumerate(status):
        if state != "new":
            continue
        tokens = _tokens(new_sentences[i])
        if len(tokens) < 4:
            continue
        counts: dict[int, int] = defaultdict(int)
        for token in tokens:
            for j in index.get(token, ()):
                counts[j] += 1
        best = max(counts, key=lambda j: counts[j] / len(tokens | base_tokens[j]), default=None)
        if best is not None and counts[best] / len(tokens | base_tokens[best]) >= REWORD_SIMILARITY:
            status[i] = ("reworded", unmatched_base[best])
            used_base.add(fingerprints(unmatched_base[best])[0])

    passages: list[Passage] = []
    run: list[str] = []
    run_start = 0

    def flush_run():
        if run:
            text = " ".join(run)[:PASSAGE_CHARS]
            passages.append(Passage("new", text, triggers=triggers(text), position=run_start))
            run.clear()

    for i, (state, old) in enumerate(status):
        if state == "new":
            if not run:
                run_start = i
            run.append(new_sentences[i])
            if sum(len(s) for s in run) >= PASSAGE_CHARS:
                flush_run()
            continue
        flush_run()
        if state in ("numbers", "reworded"):
            sentence = new_sentences[i]
            passages.append(Passage(
                "changed", sentence, old, kind="numbers" if state == "numbers" else "wording",
                modality_shift=modality_shift(sentence, old), triggers=triggers(sentence), position=i,
            ))
    flush_run()

    if not detect_removed:
        return Diff(passages, repeated, len(new_sentences))
    removed_run: list[str] = []
    for sentence in base_sentences:
        if fingerprints(sentence)[0] in used_base:
            if removed_run:
                text = " ".join(removed_run)[:PASSAGE_CHARS]
                passages.append(Passage("removed", text, triggers=triggers(text), position=len(new_sentences)))
                removed_run = []
            continue
        removed_run.append(sentence)
    if removed_run:
        text = " ".join(removed_run)[:PASSAGE_CHARS]
        passages.append(Passage("removed", text, triggers=triggers(text), position=len(new_sentences)))
    return Diff(passages, repeated, len(new_sentences))
