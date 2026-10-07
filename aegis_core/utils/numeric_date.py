"""Numeric and date extraction/comparison utilities for contradiction detection.

Pure-Python, no external dependencies. Kept deliberately simple and auditable so
that numeric/date mismatches reported to users can be traced back to a rule.

Design notes
------------
Two numeric mentions are comparable when:
  * both carry a formal unit of the same family (durations are normalised
    to days, distances to km, weights to kg, data to MB), or
  * both are bare numbers followed by the *same* head noun
    (e.g. "18 casual leaves" vs "12 casual leaves" -> head noun "leaves").

Qualifiers matter for policy text: "up to 18" is an upper bound, "at least
18" is a lower bound, "18" is exact. Two mentions conflict when their
allowed ranges cannot both hold.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

# Number words -> value, for cases like "eighteen casual leaves"
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
}

# Formal units grouped by family, with a multiplier to a base unit.
# Base units: duration->days, distance->km, weight->kg, data->MB.
UNIT_SPEC: Dict[str, Tuple[str, float]] = {
    # duration -> days
    "day": ("duration", 1.0), "days": ("duration", 1.0),
    "week": ("duration", 7.0), "weeks": ("duration", 7.0),
    "month": ("duration", 30.4375), "months": ("duration", 30.4375),
    "year": ("duration", 365.25), "years": ("duration", 365.25),
    "hour": ("duration", 1.0 / 24), "hours": ("duration", 1.0 / 24),
    "minute": ("duration", 1.0 / 1440), "minutes": ("duration", 1.0 / 1440),
    # ratio (compared only within identical units)
    "percent": ("ratio-percent", 1.0), "%": ("ratio-percent", 1.0),
    "percentage": ("ratio-percent", 1.0),
    "times": ("ratio-times", 1.0), "x": ("ratio-times", 1.0),
    # currency (compared only within identical currency)
    "usd": ("currency-usd", 1.0), "dollar": ("currency-usd", 1.0), "dollars": ("currency-usd", 1.0),
    "inr": ("currency-inr", 1.0), "rupee": ("currency-inr", 1.0), "rupees": ("currency-inr", 1.0),
    "eur": ("currency-eur", 1.0), "euro": ("currency-eur", 1.0), "euros": ("currency-eur", 1.0),
    "gbp": ("currency-gbp", 1.0), "pound": ("currency-gbp", 1.0), "pounds": ("currency-gbp", 1.0),
    # distance -> km
    "km": ("distance", 1.0), "kilometer": ("distance", 1.0), "kilometers": ("distance", 1.0),
    "kilometre": ("distance", 1.0), "kilometres": ("distance", 1.0),
    "mile": ("distance", 1.60934), "miles": ("distance", 1.60934),
    "meter": ("distance", 0.001), "meters": ("distance", 0.001),
    "metre": ("distance", 0.001), "metres": ("distance", 0.001),
    # weight -> kg
    "kg": ("weight", 1.0), "kilogram": ("weight", 1.0), "kilograms": ("weight", 1.0),
    "lb": ("weight", 0.453592), "lbs": ("weight", 0.453592),
    "pound_w": ("weight", 0.453592),
    # data -> MB
    "mb": ("data", 1.0), "gb": ("data", 1024.0), "tb": ("data", 1024.0 * 1024),
}

# Qualifiers that turn a number into a bound.
UPPER_QUALIFIERS = ("up to", "at most", "maximum of", "maximum", "no more than", "less than", "under")
LOWER_QUALIFIERS = ("at least", "minimum of", "minimum", "no fewer than", "no less than", "more than", "over", "greater than")

# Months for date parsing
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# number + optional formal unit
NUMERIC_PATTERN = re.compile(
    r"(?P<value>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<unit>%|percent|percentage|days|day|weeks|week|months|month|years|year|hours|hour|minutes|minute|rupees|rupee|dollars|dollar|usd|inr|eur|euros?|gbp|pounds?|lbs|kg|kilograms?|kilometres?|kilometers?|km|miles?|meters?|metres?|mb|gb|tb|times|x)?",
    re.IGNORECASE,
)

# number word + optional unit (e.g. "eighteen days")
WORD_NUMBER_PATTERN = re.compile(
    r"\b(?P<word>" + "|".join(NUMBER_WORDS.keys()) + r")\s+(?P<unit>days|day|weeks|week|months|month|years|year|hours|hour|minutes|minute|times)\b",
    re.IGNORECASE,
)

MONTH_NAMES = "|".join(MONTHS.keys())

# ISO: 2024-01-15  |  15/01/2024  |  15 January 2024  |  January 15, 2024
DATE_PATTERNS = [
    re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b"),
    re.compile(r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})\b"),
    re.compile(
        r"\b(?P<day>\d{1,2})\s+(?P<month_name>" + MONTH_NAMES + r")\s+(?P<year>\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<month_name>" + MONTH_NAMES + r")\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b",
        re.IGNORECASE,
    ),
]

YEAR_PATTERN = re.compile(r"\b(?P<year>(?:19|20)\d{2})\b")

# Trailing noun phrase after a bare number, used as a comparability key.
# e.g. "18 casual leaves" -> head noun "leaves"
TRAILING_WORDS = re.compile(r"(?:\s+(?:[A-Za-z]+)){0,3}")


@dataclass
class Quantity:
    """A numeric quantity extracted from text."""
    value: float
    unit: Optional[str] = None
    family: Optional[str] = None      # normalised family, e.g. "duration"
    base_value: Optional[float] = None  # value normalised to family base unit
    context_key: Optional[str] = None  # head noun for bare numbers
    qualifier: str = "exact"          # exact | upper | lower
    text: str = ""
    start: int = 0
    end: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "family": self.family,
            "context_key": self.context_key,
            "qualifier": self.qualifier,
            "text": self.text,
        }


@dataclass
class DateMention:
    """A date extracted from text."""
    year: int
    month: Optional[int] = None
    day: Optional[int] = None
    text: str = ""
    iso: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "iso": self.iso,
            "text": self.text,
        }


def _detect_qualifier(text: str, match_start: int) -> str:
    """Look backwards for an upper/lower qualifier near the number."""
    window = text[max(0, match_start - 30):match_start].lower()
    for q in UPPER_QUALIFIERS:
        if window.endswith(q) or window.endswith(q + " "):
            return "upper"
    for q in LOWER_QUALIFIERS:
        if window.endswith(q) or window.endswith(q + " "):
            return "lower"
    return "exact"


_HEAD_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and", "or",
    "per", "each", "every", "is", "are", "was", "were", "be", "been",
}


def _head_noun_after(text: str, match_end: int) -> Optional[str]:
    """
    Return the trailing noun phrase after a bare number, used as a
    comparability key.

    Captures up to three trailing words and drops stopwords, so that
    "18 casual leaves" -> "casual leaves" and "12 sick leaves" ->
    "sick leaves" are treated as *different* contexts, while
    "18 casual leaves" and "12 casual leaves" match.
    """
    rest = text[match_end:].lstrip()
    m = re.match(r"((?:[A-Za-z]+[\s,-]?){0,3})", rest)
    if not m:
        return None
    words = [w for w in re.split(r"[\s,-]+", m.group(1)) if w]
    words = [w.lower() for w in words if w.lower() not in _HEAD_STOPWORDS]
    return " ".join(words) if words else None


def extract_quantities(text: str) -> List[Quantity]:
    """Extract numeric quantities with units/context from text."""
    if not text:
        return []
    quantities: List[Quantity] = []

    for match in NUMERIC_PATTERN.finditer(text):
        raw_value = match.group("value")
        unit = (match.group("unit") or "").strip().lower() or None
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            continue

        family, base_value = None, None
        if unit and unit in UNIT_SPEC:
            family, multiplier = UNIT_SPEC[unit]
            base_value = value * multiplier

        qualifier = _detect_qualifier(text, match.start())
        context_key = None
        if unit is None:
            context_key = _head_noun_after(text, match.end())

        quantities.append(
            Quantity(
                value=value,
                unit=unit,
                family=family,
                base_value=base_value,
                context_key=context_key,
                qualifier=qualifier,
                text=match.group(0).strip(),
                start=match.start(),
                end=match.end(),
            )
        )

    for match in WORD_NUMBER_PATTERN.finditer(text):
        word = match.group("word").lower()
        unit = match.group("unit").lower()
        value = float(NUMBER_WORDS[word])
        family, multiplier = UNIT_SPEC[unit]
        qualifier = _detect_qualifier(text, match.start())
        quantities.append(
            Quantity(
                value=value,
                unit=unit,
                family=family,
                base_value=value * multiplier,
                context_key=None,
                qualifier=qualifier,
                text=match.group(0).strip(),
                start=match.start(),
                end=match.end(),
            )
        )

    return quantities


def extract_dates(text: str) -> List[DateMention]:
    """Extract dates from text."""
    if not text:
        return []
    dates: List[DateMention] = []
    consumed: List[Tuple[int, int]] = []

    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < e and match.end() > s for s, e in consumed):
                continue
            groups = match.groupdict()
            year = int(groups["year"])
            month = groups.get("month")
            day = groups.get("day")
            month_name = groups.get("month_name")

            month_int = MONTHS[month_name.lower()] if month_name else (int(month) if month else None)
            day_int = int(day) if day else None

            iso = None
            if month_int and day_int:
                try:
                    iso = datetime(year, month_int, day_int).date().isoformat()
                except ValueError:
                    iso = None

            dates.append(DateMention(year, month_int, day_int, match.group(0).strip(), iso))
            consumed.append((match.start(), match.end()))

    for match in YEAR_PATTERN.finditer(text):
        if any(match.start() < e and match.end() > s for s, e in consumed):
            continue
        dates.append(DateMention(year=int(match.group("year")), text=match.group(0).strip()))
        consumed.append((match.start(), match.end()))

    return dates


def _ranges(q: Quantity) -> Tuple[float, float]:
    """Return the (low, high) inclusive range implied by the qualifier."""
    val = q.base_value if q.base_value is not None else q.value
    if q.qualifier == "upper":
        return (float("-inf"), val)
    if q.qualifier == "lower":
        return (val, float("inf"))
    return (val, val)


def _compatible(
    a: Quantity, b: Quantity, lo_a: float, hi_a: float, lo_b: float, hi_b: float
) -> bool:
    """
    Test whether two quantity ranges can both hold.

    Same-unit (or bare) comparisons use a tight tolerance; cross-unit
    comparisons use a looser tolerance because unit conversion plus
    human rounding is approximate (e.g. 60 km ~ 40 miles).
    """
    same_unit = (a.unit == b.unit)
    tol_rel = 0.01 if same_unit else 0.10
    tol_abs = 0.5

    def expand(lo: float, hi: float, ref: float) -> Tuple[float, float]:
        tol = max(tol_abs, tol_rel * abs(ref)) if ref not in (float("inf"), float("-inf")) else tol_abs
        return lo - tol, hi + tol

    ref_a = a.base_value if a.base_value is not None else a.value
    ref_b = b.base_value if b.base_value is not None else b.value
    lo_a, hi_a = expand(lo_a, hi_a, ref_a)
    lo_b, hi_b = expand(lo_b, hi_b, ref_b)

    return lo_a <= hi_b and lo_b <= hi_a


def compare_quantities(a: Quantity, b: Quantity) -> Optional[Dict[str, Any]]:
    """
    Compare two quantities for conflict.

    Comparable when both share a formal unit family (with base-unit
    normalisation) or both are bare numbers with the same head noun.
    Returns a conflict dict when their implied ranges cannot both hold.
    """
    if a.family is not None and b.family is not None:
        if a.family != b.family:
            return None
        # ratio/currency families only compare within identical units.
        if a.family.startswith(("ratio", "currency")) and a.unit != b.unit:
            return None
        lo_a, hi_a = _ranges(a)
        lo_b, hi_b = _ranges(b)
        if _compatible(a, b, lo_a, hi_a, lo_b, hi_b):
            return None  # ranges overlap -> compatible
        return {
            "kind": "numeric",
            "family": a.family,
            "value_a": a.value,
            "value_b": b.value,
            "unit_a": a.unit,
            "unit_b": b.unit,
            "text_a": a.text,
            "text_b": b.text,
            "qualifier_a": a.qualifier,
            "qualifier_b": b.qualifier,
        }

    if a.family is None and b.family is None:
        if not a.context_key or a.context_key != b.context_key:
            return None
        lo_a, hi_a = _ranges(a)
        lo_b, hi_b = _ranges(b)
        if _compatible(a, b, lo_a, hi_a, lo_b, hi_b):
            return None
        return {
            "kind": "numeric",
            "family": "bare",
            "context_key": a.context_key,
            "value_a": a.value,
            "value_b": b.value,
            "unit_a": None,
            "unit_b": None,
            "text_a": a.text,
            "text_b": b.text,
            "qualifier_a": a.qualifier,
            "qualifier_b": b.qualifier,
        }

    return None


def compare_dates(a: DateMention, b: DateMention) -> Optional[Dict[str, Any]]:
    """
    Compare two dates for conflict.

    Only fully-specified dates (or same-granularity partial dates) that
    differ are flagged. A bare year is compatible with any date in that
    year.
    """
    if a.year != b.year:
        return {"kind": "date", "date_a": a.to_dict(), "date_b": b.to_dict()}
    if a.month is None or b.month is None:
        return None
    if a.month != b.month:
        return {"kind": "date", "date_a": a.to_dict(), "date_b": b.to_dict()}
    if a.day is None or b.day is None:
        return None
    if a.day != b.day:
        return {"kind": "date", "date_a": a.to_dict(), "date_b": b.to_dict()}
    return None


def find_numeric_conflicts(text_a: str, text_b: str) -> List[Dict[str, Any]]:
    """Find all numeric conflicts between two texts."""
    conflicts = []
    for qa in extract_quantities(text_a):
        for qb in extract_quantities(text_b):
            conflict = compare_quantities(qa, qb)
            if conflict:
                conflicts.append(conflict)
    return conflicts


def find_date_conflicts(text_a: str, text_b: str) -> List[Dict[str, Any]]:
    """Find all date conflicts between two texts."""
    conflicts = []
    for da in extract_dates(text_a):
        for db in extract_dates(text_b):
            conflict = compare_dates(da, db)
            if conflict:
                conflicts.append(conflict)
    return conflicts
