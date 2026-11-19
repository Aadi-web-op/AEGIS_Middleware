"""Deterministic decomposition of a sentence into atomic claims.

Why this exists: a small NLI model judges a compound sentence as a whole.
"Growth is caused by A and B" comes back NEUTRAL when the evidence states
only A, and so does "X improves Y, although the effect varies" when two
different passages each state one half. Both look identical to the policy
engine. Splitting the sentence lets each part be verified on its own.

The splitter is intentionally conservative and purely rule-based (no model,
no parser):

  * clause boundaries: ";" and ", although / though / but / while / whereas /
    however / yet"
  * coordinated lists: "P a, b, and c" -> "P a", "P b", "P c", where the
    shared prefix P ends at a pivot word (auxiliary, modal, common list verb,
    or preposition) found in the first item
  * a segment that carries its own verb is kept as an independent clause

When the prefix is uncertain, an atom carries more than one candidate
wording (`alternatives`); the verifier keeps the best-supported one. When no
safe split exists the sentence is returned unchanged, so the worst outcome
of this module is "no decomposition", never an invented statement about
something the answer did not mention.

It also provides `grounding`: the share of a claim's content words that
appear in a passage. That is not a support judgement -- it only separates
"the documents discuss this but the model could not confirm it" from "the
documents do not mention this at all".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

_CLAUSE_RE = re.compile(
    r"\s*;\s*|,\s+(?:although|though|but|while|whereas|however|yet)\s+",
    re.IGNORECASE,
)

# Words after which a list of objects / predicates can start.
_VERB_PIVOTS = frozenset({
    "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "does", "do", "did",
    "can", "could", "may", "might", "must", "shall", "should", "will", "would",
    "include", "includes", "included", "including",
    "cover", "covers", "covered", "covering",
    "require", "requires", "required",
    "offer", "offers", "offered",
    "provide", "provides", "provided",
    "contain", "contains", "contained",
    "comprise", "comprises", "comprised",
    "receive", "receives", "received",
    "get", "gets", "need", "needs",
})
_PREP_PIVOTS = frozenset({"by", "to", "for", "of", "in", "on", "from", "with", "as"})

# Splitting around these would change the meaning ("between 5 and 10").
_NO_SPLIT_RE = re.compile(r"\b(between|either|neither|both)\b", re.IGNORECASE)
_AND_RE = re.compile(r"\s+(?:and|or)\s+", re.IGNORECASE)
_LEADING_CONJ_RE = re.compile(r"^(?:and|or)\s+", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z0-9$%'.\-]+")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "and", "are", "for", "was", "were", "that", "this", "with", "has",
    "have", "can", "will", "not", "but", "you", "your", "its", "their", "they",
    "them", "from", "into", "than", "then", "also", "all", "any", "may", "must",
    "per", "yes", "who", "what", "which", "when", "where", "why", "how", "does",
    "did", "there", "been", "being", "would", "could", "should", "about",
})

MAX_ITEM_WORDS = 8


@dataclass
class AtomicClaim:
    """One verifiable unit of an answer sentence."""

    text: str
    source_sentence: str
    # Other candidate wordings of the same atom (uncertain prefix).
    alternatives: List[str] = field(default_factory=list)
    decomposed: bool = False

    @property
    def candidates(self) -> List[str]:
        seen: Set[str] = set()
        out: List[str] = []
        for cand in [self.text, *self.alternatives]:
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
        return out


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text)


def _has_verb_pivot(text: str) -> bool:
    return any(w.lower() in _VERB_PIVOTS for w in _words(text))


def _prefixes(first_segment: str) -> List[str]:
    """Candidate shared prefixes of a list, most specific first.

    "Urban expansion is mainly caused by population growth" ->
        ["Urban expansion is mainly caused by", "Urban expansion is"]
    """
    tokens = list(re.finditer(r"\S+", first_segment))
    last_any: Optional[int] = None
    last_verb: Optional[int] = None
    # The final token is (part of) the first item, never the pivot.
    for i, tok in enumerate(tokens[:-1]):
        word = tok.group(0).lower().strip(",.:")
        if word in _VERB_PIVOTS:
            last_verb = i
            last_any = i
        elif word in _PREP_PIVOTS:
            last_any = i

    out: List[str] = []
    for idx in (last_any, last_verb):
        if idx is None:
            continue
        prefix = first_segment[: tokens[idx].end()].strip()
        if prefix and prefix not in out:
            out.append(prefix)
    return out


def _clean(fragment: str) -> str:
    return fragment.strip().strip(",").strip()


def _finish(text: str) -> str:
    text = _clean(text).rstrip(".!?").strip()
    if not text:
        return text
    return text[0].upper() + text[1:] + "."


def _split_list(clause: str) -> List[List[str]]:
    """Split one clause into atoms; each atom is a list of candidate wordings.

    Returns [] when the clause should be left alone.
    """
    body = clause.strip().rstrip(".!?").strip()
    if not body or _NO_SPLIT_RE.search(body):
        return []

    segments = [_clean(s) for s in re.split(r",\s+", body)]
    segments = [s for s in segments if s]

    # Split the trailing "x and y" (Oxford comma or not).
    expanded: List[str] = []
    for i, seg in enumerate(segments):
        seg = _LEADING_CONJ_RE.sub("", seg).strip()
        if not seg:
            continue
        is_last = i == len(segments) - 1
        parts = _AND_RE.split(seg) if is_last or len(segments) == 1 else [seg]
        if len(parts) == 2 and all(p.strip() for p in parts):
            expanded.extend(p.strip() for p in parts)
        else:
            expanded.append(seg)

    if len(expanded) < 2:
        return []

    first = expanded[0]
    # The first segment must be a full clause (subject + verb + first item).
    # "A score of 90 percent and above receives an A" must not be cut at
    # "and": its first half states nothing on its own.
    if not _has_verb_pivot(first):
        return []
    prefixes = _prefixes(first)
    atoms: List[List[str]] = [[_finish(first)]]

    for seg in expanded[1:]:
        if _has_verb_pivot(seg):
            # Independent clause: it already has its own subject and verb.
            nested = _split_list(seg)
            atoms.extend(nested if nested else [[_finish(seg)]])
            continue
        if not prefixes or len(_words(seg)) > MAX_ITEM_WORDS:
            return []  # cannot attach this item safely -> do not decompose
        atoms.append([_finish(f"{p} {seg}") for p in prefixes])

    return atoms if len(atoms) >= 2 else []


def decompose_sentence(sentence: str) -> List[AtomicClaim]:
    """Break one sentence into atomic claims (or return it unchanged)."""
    sentence = sentence.strip()
    if not sentence:
        return []

    clauses = [c.strip() for c in _CLAUSE_RE.split(sentence) if c and c.strip()]
    atoms: List[List[str]] = []
    for clause in clauses:
        if len(_words(clause)) < 2:
            continue
        split = _split_list(clause)
        atoms.extend(split if split else [[_finish(clause)]])

    # Drop fragments that state nothing checkable ("Yes.", "OK.").
    atoms = [
        cands for cands in atoms
        if cands and len(_words(cands[0])) >= 2 and content_tokens(cands[0])
    ]
    unchanged = (
        len(atoms) == 1 and len(clauses) == 1 and len(atoms[0]) == 1
        and atoms[0][0].rstrip(".").lower() == sentence.rstrip(".!?").lower()
    )
    if not atoms or unchanged:
        return [AtomicClaim(text=sentence, source_sentence=sentence)]

    return [
        AtomicClaim(
            text=cands[0],
            source_sentence=sentence,
            alternatives=cands[1:],
            decomposed=True,
        )
        for cands in atoms
        if cands and cands[0]
    ]


# ----------------------------------------------------------------------
# lexical grounding
# ----------------------------------------------------------------------
def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    # "conclude" / "concludes" / "concluded" must meet at one stem.
    if len(token) > 3 and token.endswith("e"):
        token = token[:-1]
    return token


def content_tokens(text: str) -> Set[str]:
    """Lower-cased, lightly stemmed content words and numbers."""
    return {
        _stem(t)
        for t in _TOKEN_RE.findall((text or "").lower())
        if (len(t) >= 3 or t.isdigit()) and t not in _STOPWORDS
    }


def grounding(claim: str, passages: List[str]) -> float:
    """Best share of the claim's content words found in a single passage."""
    tokens = content_tokens(claim)
    if not tokens or not passages:
        return 0.0
    best = 0.0
    for passage in passages:
        overlap = len(tokens & content_tokens(passage)) / len(tokens)
        best = max(best, overlap)
    return round(best, 4)
