"""Unit tests for numeric/date extraction and conflict detection.

These tests are pure-Python and run without downloading any model.
Assertions use tolerance ranges, never exact floating-point equality.
"""

from aegis_core.utils.numeric_date import (
    extract_quantities,
    extract_dates,
    find_numeric_conflicts,
    find_date_conflicts,
)


# ------------------------------------------------------------------
# extraction
# ------------------------------------------------------------------
def test_extract_quantity_with_unit():
    qs = extract_quantities("Refund within 30 days.")
    assert len(qs) >= 1
    assert any(q.value == 30 and q.unit == "days" for q in qs)
    assert any(q.family == "duration" for q in qs)


def test_extract_bare_quantity_has_context():
    qs = extract_quantities("Employees get 18 casual leaves.")
    assert any(q.value == 18 and q.unit is None for q in qs)
    assert any(q.context_key == "casual leaves" for q in qs)


def test_extract_number_word():
    qs = extract_quantities("Employees get eighteen days.")
    assert any(q.value == 18 and q.unit == "days" for q in qs)


def test_extract_upper_and_lower_qualifiers():
    up = extract_quantities("Up to 18 leaves.")
    low = extract_quantities("At least 18 leaves.")
    assert any(q.qualifier == "upper" for q in up)
    assert any(q.qualifier == "lower" for q in low)


def test_extract_iso_date():
    ds = extract_dates("Effective 2024-01-15.")
    assert any(d.iso == "2024-01-15" for d in ds)


def test_extract_long_date():
    ds = extract_dates("Effective January 15, 2024.")
    assert any(d.year == 2024 and d.month == 1 and d.day == 15 for d in ds)


# ------------------------------------------------------------------
# numeric conflicts
# ------------------------------------------------------------------
def test_numeric_conflict_detected():
    c = find_numeric_conflicts(
        "Employees get 18 casual leaves.",
        "Employees get 12 casual leaves.",
    )
    assert len(c) == 1
    assert c[0]["value_a"] == 18
    assert c[0]["value_b"] == 12
    assert "leaves" in c[0]["context_key"]


def test_numeric_agreement_no_conflict():
    c = find_numeric_conflicts(
        "Employees get 18 casual leaves.",
        "Staff get 18 casual leaves.",
    )
    assert c == []


def test_different_head_noun_no_conflict():
    # 18 casual vs 12 sick are different leave types -> not comparable
    c = find_numeric_conflicts(
        "18 casual leaves.",
        "12 sick leaves.",
    )
    assert c == []


def test_duration_units_normalised():
    # 2 weeks == 14 days -> compatible, no conflict
    c = find_numeric_conflicts("Warranty lasts 2 weeks.", "Warranty lasts 14 days.")
    assert c == []


def test_duration_conflict_detected():
    c = find_numeric_conflicts("Refund within 30 days.", "Refund within 45 days.")
    assert len(c) == 1
    assert c[0]["family"] == "duration"


def test_cross_unit_approximation_not_conflict():
    # 60 km ~ 40 miles (within tolerance) -> compatible
    c = find_numeric_conflicts("Speed limit 60 km.", "Speed limit 40 miles.")
    assert c == []


def test_bound_conflict():
    # "up to 18" and "at least 20" cannot both hold
    c = find_numeric_conflicts("Up to 18 leaves.", "At least 20 leaves.")
    assert len(c) == 1


def test_bound_compatible():
    # "up to 20" and "at least 18" overlap
    c = find_numeric_conflicts("Up to 20 leaves.", "At least 18 leaves.")
    assert c == []


def test_different_currency_not_compared():
    c = find_numeric_conflicts("Costs 100 dollars.", "Costs 100 rupees.")
    assert c == []


def test_percent_conflict():
    c = find_numeric_conflicts("Discount is 10 percent.", "Discount is 25 percent.")
    assert len(c) == 1
    assert c[0]["family"] == "ratio-percent"


# ------------------------------------------------------------------
# date conflicts
# ------------------------------------------------------------------
def test_date_conflict_detected():
    c = find_date_conflicts(
        "Policy effective January 1, 2024.",
        "Policy effective March 15, 2024.",
    )
    assert len(c) == 1


def test_date_agreement_no_conflict():
    c = find_date_conflicts(
        "Policy effective January 1, 2024.",
        "Policy effective 2024-01-01.",
    )
    assert c == []


def test_year_only_compatible_with_full_date():
    # A bare year must not be treated as conflicting with a full date
    # inside that year.
    c = find_date_conflicts("Effective 2024.", "Effective March 2024.")
    assert c == []


def test_year_conflict_detected():
    c = find_date_conflicts("Effective 2023.", "Effective 2024.")
    assert len(c) == 1
