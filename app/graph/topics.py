"""Deterministic topic keys for queries.

`topic_key(query)` reduces a question to a short, normalised keyword key
such as ``"annual|day|leave"``. It is stored on the Decision node as
`topic`, so that cross-decision queries can group "questions about the
same thing" without an embedding model or any stored free text.

It is deliberately simple and fully deterministic: the same query always
yields the same key, word order does not matter, and there is no model,
no randomness and no state. It is a grouping key, not a classifier.
"""

from __future__ import annotations

import re
from typing import List

MAX_TOPIC_KEYWORDS = 3
_MIN_TOKEN_CHARS = 3
_TOKEN = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are aren as at
    be because been before being below between both but by can cannot could
    couldn did didn do does doesn doing don down during each either else ever
    every few for from further get gets getting give given got had hadn has
    hasn have haven having he her here hers herself him himself his how however
    i if in into is isn it its itself just know let like many may me might
    more most much must my myself need needs no nor not now of off on once
    only or other ought our ours ourselves out over own per please same shall
    shan she should shouldn so some such tell than that the their theirs them
    themselves then there these they this those through to too under until
    up upon us use used very was wasn we were weren what when where whether
    which while who whom whose why will with within without won would
    wouldn yes yet you your yours yourself yourselves
    """.split()
)


def _singular(token: str) -> str:
    """Light plural folding so "days" and "day" share a key. Not a stemmer."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def topic_keywords(query: object) -> List[str]:
    """The keywords a topic key is made of, alphabetically sorted."""
    if not isinstance(query, str) or not query:
        return []
    seen: set[str] = set()
    for raw in _TOKEN.findall(query.lower()):
        if len(raw) < _MIN_TOKEN_CHARS or raw.isdigit() or raw in _STOPWORDS:
            continue
        token = _singular(raw)
        if len(token) < _MIN_TOKEN_CHARS or token in _STOPWORDS:
            continue
        seen.add(token)
    # Longest words first as a cheap proxy for "most specific"; ties broken
    # alphabetically so the choice never depends on word order.
    chosen = sorted(seen, key=lambda t: (-len(t), t))[:MAX_TOPIC_KEYWORDS]
    return sorted(chosen)


def topic_key(query: object) -> str:
    """Normalised keyword key for `query`, or "" when it has no keywords.

    >>> topic_key("How many annual leave days do I get?")
    'annual|day|leave'
    """
    return "|".join(topic_keywords(query))
