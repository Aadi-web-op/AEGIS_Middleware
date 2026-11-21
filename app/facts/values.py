"""Find and normalise the values a locked fact can hold.

Deterministic on purpose: no model, no threshold. The same text always gives
the same values, so a Fact Lock verdict never moves when retrieval, prompts
or models change.

Kinds
-----
duration  "15 days", "3 working days", "2 weeks", "48 hours", "6 months"
money     "Rs 7,500", "₹5 lakh", "INR 50,000", "$1,200"
percent   "2%", "1.5 percent"
count     "12 characters", "2 children" (number + the fact's unit word)
date      "2 November 2026", "November 2, 2026", "2026-11-02", "02/11/2026"
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

KINDS = ("duration", "money", "percent", "count", "date")

_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60,
    "ninety": 90, "hundred": 100,
}
_WORDS = "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))
# 1,000 / 1,00,000 (Indian grouping) / 7500 / 1.5 / or a number word.
_NUM = rf"(?:\d{{1,3}}(?:,\d{{2,3}})+|\d+)(?:\.\d+)?|\b(?:{_WORDS})\b"

_MULTIPLIERS = {
    "k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "crore": 1e7, "crores": 1e7, "cr": 1e7, "million": 1e6, "mn": 1e6,
}
_MULT = r"(?:\s*(?P<mult>k|thousand|lakhs?|lacs?|crores?|cr|million|mn)\b)?"

_CURRENCY_PREFIX = r"(?P<cur>₹|rs\.?|inr|usd|\$|eur|€)\s*"
_CURRENCY_SUFFIX = r"\s*(?P<cur2>rupees|inr|rs\b|usd|dollars|eur|euros)"
_CURRENCY_NAMES = {
    "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupees": "INR",
    "$": "USD", "usd": "USD", "dollars": "USD", "€": "EUR", "eur": "EUR", "euros": "EUR",
}

# unit word -> (unit family, factor into that family's base unit)
_DURATION_UNITS = {
    "minute": ("hours", 1 / 60), "minutes": ("hours", 1 / 60), "min": ("hours", 1 / 60),
    "mins": ("hours", 1 / 60), "hour": ("hours", 1), "hours": ("hours", 1),
    "hr": ("hours", 1), "hrs": ("hours", 1),
    "day": ("days", 1), "days": ("days", 1), "week": ("days", 7), "weeks": ("days", 7),
    "month": ("months", 1), "months": ("months", 1), "year": ("months", 12),
    "years": ("months", 12),
}
_DURATION = (
    rf"(?P<num>{_NUM})\s*(?:-\s*)?"
    r"(?P<qual>(?:working|business|calendar|clear)\s+)?"
    r"(?P<unit>minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)\b"
)
_PERCENT = rf"(?P<num>{_NUM})\s*(?:%|percent\b|per\s+cent\b)"

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MON = r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_PATTERNS = [
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}\.?,?\s+(?P<y>\d{{4}})\b", re.I),
    re.compile(rf"\b{_MON}\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b", re.I),
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})\b"),  # Indian DD/MM/YYYY
]


@dataclass(frozen=True)
class Value:
    kind: str
    amount: float  # normalised: base unit of the family, currency units, %, ordinal day
    unit: str      # family ("days", "business_days", "hours", "months"), currency, "%", count word, "date"
    text: str      # exactly as written
    start: int = 0
    end: int = 0

    def same_as(self, other: "Value") -> bool:
        if self.kind != other.kind or self.unit != other.unit:
            return False
        return abs(self.amount - other.amount) <= 1e-9 * max(1.0, abs(self.amount))

    def comparable(self, other: "Value") -> bool:
        return self.kind == other.kind and self.unit == other.unit


def _number(raw: str) -> float:
    raw = raw.strip().lower()
    if raw in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[raw])
    return float(raw.replace(",", ""))


def _durations(text: str) -> list[Value]:
    out = []
    for m in re.finditer(_DURATION, text, re.I):
        unit = m.group("unit").lower()
        family, factor = _DURATION_UNITS[unit]
        qual = (m.group("qual") or "").strip().lower()
        if family == "days" and qual in ("working", "business"):
            family = "business_days"
        out.append(Value("duration", _number(m.group("num")) * factor, family,
                         m.group(0), m.start(), m.end()))
    return out


def _money(text: str) -> list[Value]:
    out, taken = [], []
    for pattern, cur_group in (
        (rf"{_CURRENCY_PREFIX}(?P<num>{_NUM}){_MULT}", "cur"),
        (rf"(?P<num>{_NUM}){_MULT}{_CURRENCY_SUFFIX}", "cur2"),
    ):
        for m in re.finditer(pattern, text, re.I):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            amount = _number(m.group("num"))
            mult = (m.group("mult") or "").lower()
            amount *= _MULTIPLIERS.get(mult, 1)
            currency = _CURRENCY_NAMES.get(m.group(cur_group).lower().rstrip(), "INR")
            out.append(Value("money", amount, currency, m.group(0).strip(), m.start(), m.end()))
            taken.append((m.start(), m.end()))
    return sorted(out, key=lambda v: v.start)


def _percents(text: str) -> list[Value]:
    return [Value("percent", _number(m.group("num")), "%", m.group(0), m.start(), m.end())
            for m in re.finditer(_PERCENT, text, re.I)]


def _counts(text: str, unit: str | None) -> list[Value]:
    word = (unit or "").strip().lower()
    if word:
        stem = re.escape(word.rstrip("s"))
        pattern = rf"(?P<num>{_NUM})\s+(?:[a-z-]+\s+)?(?P<u>{stem}s?)\b"
    else:
        pattern = rf"(?P<num>{_NUM})"
    out = []
    for m in re.finditer(pattern, text, re.I):
        out.append(Value("count", _number(m.group("num")), word, m.group(0), m.start(), m.end()))
    return out


def _dates(text: str) -> list[Value]:
    out, taken = [], []
    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            g = m.groupdict()
            try:
                month = _MONTHS[g["mon"].lower()[:3]] if g.get("mon") else int(g["m"])
                day = dt.date(int(g["y"]), month, int(g["d"]))
            except (ValueError, KeyError):
                continue
            out.append(Value("date", float(day.toordinal()), "date", m.group(0), m.start(), m.end()))
            taken.append((m.start(), m.end()))
    return sorted(out, key=lambda v: v.start)


def extract_values(text: str, kind: str, unit: str | None = None) -> list[Value]:
    """Every value of `kind` in `text`, with character offsets."""
    if kind == "duration":
        return _durations(text)
    if kind == "money":
        return _money(text)
    if kind == "percent":
        return _percents(text)
    if kind == "count":
        return _counts(text, unit)
    if kind == "date":
        return _dates(text)
    raise ValueError(f"kind must be one of {', '.join(KINDS)}")


def parse_value(text: str, kind: str, unit: str | None = None) -> Value:
    """Parse the single value a fact is locked to; refuse anything ambiguous."""
    values = extract_values(text, kind, unit)
    if len(values) != 1:
        found = "no" if not values else f"{len(values)}"
        raise ValueError(f"expected exactly one {kind} value in {text!r}, found {found}")
    return values[0]
