"""Fact Lock: check an answer against approved, versioned facts.

Unlike the evidence signals, this does not look at what retrieval returned.
The answer is compared with the value the company locked, so a stale chunk,
a missed chunk or a different model cannot change the verdict.

Matching is rule-based:
  1. A fact is in scope when every content word of its label or an alias is
     in a sentence of the answer, or else in the question.
  2. The sentence is cut into clauses; the clause that best names the fact
     (words unique to this fact weigh more) supplies the stated value.
  3. Stated and locked values are normalised and compared exactly.

Levels decide what a wrong value does:
  L1 Info        -> CAVEAT with the correct value
  L2 Operational -> CAVEAT and a corrected answer (ESCALATE if it cannot be fixed)
  L3 Commitment  -> ESCALATE: blocked until a person checks it
  L4 Regulated   -> ESCALATE and needs approval; must also cite the current version
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.facts.store import Fact, FactStore
from app.facts.values import Value, extract_values
from app.schemas import Decision, EvidenceItem, FactCheck, Reason, ReasonCode

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "of", "for", "to", "in", "on", "at", "by", "is", "are", "be",
    "and", "or", "per", "with", "within", "from", "our", "your", "my", "we", "you",
    "how", "what", "many", "much", "do", "does", "i", "it", "this", "that", "there",
    "can", "get", "have", "has", "will", "up",
}
_BOUNDARY = re.compile(r"[.!?]+(?=\s|$)|\n")
_ABBREVIATIONS = {"rs", "no", "approx", "e.g", "i.e", "etc", "mr", "mrs", "ms", "dr", "st", "vs"}
_CLAUSE_BREAK = re.compile(r";|,(?!\d)|\s+(?:and|but|while|whereas)\s+", re.I)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


_NEGATED = re.compile(r"\b(non|not|un)[-\s]+(?=[a-z])")


def _tokens(text: str) -> list[str]:
    # "non-metro" is one word: it must not count as "metro".
    text = _NEGATED.sub(lambda m: m.group(1), text.lower())
    return [_stem(w) for w in _WORD.findall(text) if w not in _STOP]


@dataclass
class _Span:
    start: int
    end: int
    text: str


def _sentences(text: str) -> list[_Span]:
    """Sentence spans; "Rs. 500" and "1.5%" do not end a sentence."""
    out, cursor = [], 0
    for m in _BOUNDARY.finditer(text):
        before = re.search(r"([A-Za-z.]+)$", text[cursor:m.start()])
        if m.group(0) == "." and before and before.group(1).lower().rstrip(".") in _ABBREVIATIONS:
            continue
        if text[cursor:m.end()].strip():
            out.append(_Span(cursor, m.end(), text[cursor:m.end()]))
        cursor = m.end()
    if text[cursor:].strip():
        out.append(_Span(cursor, len(text), text[cursor:]))
    return out


def _clauses(sentence: _Span) -> list[_Span]:
    out, cursor = [], 0
    for m in _CLAUSE_BREAK.finditer(sentence.text):
        out.append(_Span(sentence.start + cursor, sentence.start + m.start(),
                         sentence.text[cursor:m.start()]))
        cursor = m.end()
    out.append(_Span(sentence.start + cursor, sentence.end, sentence.text[cursor:]))
    return [c for c in out if c.text.strip()]


def _phrase_in(phrase_tokens: set[str], tokens: Iterable[str]) -> bool:
    return bool(phrase_tokens) and phrase_tokens <= set(tokens)


@dataclass
class FactLockResult:
    checks: list[FactCheck] = field(default_factory=list)
    floor: Decision | None = None
    reasons: list[Reason] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    corrected_answer: str | None = None
    requires_approval: bool = False


_SEVERITY = {Decision.ANSWER: 0, Decision.CAVEAT: 1, Decision.ESCALATE: 2, Decision.ABSTAIN: 3}


def _stricter(a: Decision | None, b: Decision | None) -> Decision | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


def _cites_current(fact: Fact, evidence: Sequence[EvidenceItem]) -> bool:
    want_source = (fact.source or "").strip().lower()
    want_version = (fact.version or "").strip().lower()
    for item in evidence:
        source = (item.source or "").strip().lower()
        version = (item.version or "").strip().lower()
        if want_source and source != want_source:
            continue
        if want_version and version != want_version:
            continue
        if want_source or want_version:
            return True
    return False


class FactLock:
    def __init__(self, store: FactStore):
        self.store = store

    # -------------------------------------------------------------- matching
    def _weights(self, facts: Sequence[Fact]) -> dict[str, float]:
        """Words used by fewer facts identify a fact better."""
        counts: Counter = Counter()
        for fact in facts:
            words = set()
            for phrase in fact.phrases():
                words |= set(_tokens(phrase))
            counts.update(words)
        return {word: 1.0 / n for word, n in counts.items()}

    def _stated(
        self, fact: Fact, answer: str, query: str, weights: dict[str, float]
    ) -> tuple[list[Value], str] | None:
        """Values the answer states for this fact, or None when out of scope."""
        phrases = [set(_tokens(p)) for p in fact.phrases()]
        fact_words = set().union(*phrases) if phrases else set()
        sentences = _sentences(answer)
        values = extract_values(answer, fact.kind, fact.unit)

        def in_span(value: Value, span: _Span) -> bool:
            return span.start <= value.start and value.end <= span.end

        def pick(spans: list[_Span]) -> list[Value]:
            # Words naming this fact count for a clause; words that only name
            # other facts ("metro" for the other-cities limit) count against it.
            best, best_score = [], float("-inf")
            for clause in (c for s in spans for c in _clauses(s)):
                inside = [v for v in values if in_span(v, clause)]
                if not inside:
                    continue
                words = set(_tokens(clause.text))
                own = sum(weights.get(w, 0.0) for w in words & fact_words)
                if own <= 0:
                    continue
                foreign = sum(weights.get(w, 0.0) for w in words - fact_words)
                if own - foreign > best_score:
                    best, best_score = inside, own - foreign
            return best

        named = [s for s in sentences if any(_phrase_in(p, _tokens(s.text)) for p in phrases)]
        if named:
            chosen = pick(named)
            if not chosen:  # the fact is named but the value sits in a clause of its own
                chosen = [v for v in values if any(in_span(v, s) for s in named)]
            return chosen, "answer"
        if any(_phrase_in(p, _tokens(query)) for p in phrases):
            chosen = pick(sentences) or values
            return chosen, "question"
        return None

    # --------------------------------------------------------------- verdict
    def check(
        self, query: str, answer: str, evidence: Sequence[EvidenceItem] | None = None
    ) -> FactLockResult:
        facts = self.store.active()
        result = FactLockResult()
        if not facts or not answer.strip():
            return result
        previous = self.store.previous_values()
        weights = self._weights(facts)
        corrected = answer
        replacements: list[tuple[int, int, str]] = []

        for fact in facts:
            try:
                found = self._stated(fact, answer, query, weights)
                if found is None:
                    continue
                stated, scope = found
                locked = fact.parsed()
                check = self._judge(fact, locked, stated, previous.get(fact.key, []), evidence, scope)
            except Exception:
                logger.exception("Fact Lock could not check %s", fact.key)
                continue
            result.checks.append(check)
            floor = None
            if check.action == "note":
                floor = Decision.CAVEAT
            elif check.action == "correct":
                floor = Decision.CAVEAT
                replacements.append((check.span[0], check.span[1], fact.value))
            elif check.action in ("block", "approval"):
                floor = Decision.ESCALATE
                result.requires_approval |= check.action == "approval"
            if floor is not None:
                result.floor = _stricter(result.floor, floor)
                result.reasons.append(Reason(code=ReasonCode.LOCKED_FACT_MISMATCH, message=check.message))
                if check.verdict in ("mismatch", "outdated"):
                    result.notes.append(f"The current {fact.label} is {fact.value}"
                                        + (f" ({fact.source} {fact.version})." if fact.source else "."))

        if replacements and result.floor == Decision.CAVEAT:
            for start, end, text in sorted(replacements, reverse=True):
                corrected = corrected[:start] + text + corrected[end:]
            result.corrected_answer = corrected
        return result

    @staticmethod
    def _judge(
        fact: Fact,
        locked: Value,
        stated: list[Value],
        previous: list[Fact],
        evidence: Sequence[EvidenceItem] | None,
        scope: str,
    ) -> FactCheck:
        base = dict(fact_key=fact.key, label=fact.label, level=fact.level, locked=fact.value,
                    source=fact.source, version=fact.version, scope=scope)
        if not stated:
            return FactCheck(**base, verdict="not_stated", action="none",
                             message=f"The answer mentions {fact.label} but states no value.")
        same = [v for v in stated if v.same_as(locked)]
        if same:
            value = same[0]
            span = [value.start, value.end]
            if fact.level == 4 and evidence and not _cites_current(fact, evidence):
                return FactCheck(**base, verdict="uncited", stated=value.text, span=span,
                                 action="approval",
                                 message=f"{fact.label} is correct ({value.text}) but no evidence "
                                         f"from {fact.source or 'the source'} {fact.version or ''} "
                                         "was supplied. Regulated facts must cite the current version."
                                         .replace("  ", " "))
            return FactCheck(**base, verdict="confirmed", stated=value.text, span=span,
                             action="none", message=f"{fact.label} matches the locked value.")

        comparable = [v for v in stated if v.comparable(locked)]
        if not comparable:
            value = stated[0]
            action = {4: "approval", 3: "note"}.get(fact.level, "none")
            return FactCheck(**base, verdict="unclear", stated=value.text,
                             span=[value.start, value.end], action=action,
                             message=f"The answer gives {fact.label} as {value.text}, which cannot be "
                                     f"compared exactly with the locked {fact.value}.")

        value = comparable[0]
        span = [value.start, value.end]
        old = next((p for p in previous if _safe_same(p, value)), None)
        verdict = "outdated" if old else "mismatch"
        what = (f"the old value from {old.source or 'an earlier version'} {old.version or ''}".strip()
                if old else "not the locked value")
        action = {1: "note", 2: "correct", 3: "block", 4: "approval"}[fact.level]
        effect = {
            "note": "Shown with a correction note.",
            "correct": "Corrected automatically.",
            "block": "Blocked until a person checks it.",
            "approval": "Blocked: a regulated fact needs approval.",
        }[action]
        return FactCheck(**base, verdict=verdict, stated=value.text, span=span, action=action,
                         outdated_version=old.version if old else None,
                         message=f"The answer says {fact.label} is {value.text}, {what}; "
                                 f"the locked value is {fact.value}. {effect}")


def _safe_same(fact: Fact, value: Value) -> bool:
    try:
        return fact.parsed().same_as(value)
    except ValueError:
        return False
