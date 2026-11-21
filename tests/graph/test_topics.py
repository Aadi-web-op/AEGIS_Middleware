"""topic_key: a deterministic grouping key, nothing cleverer."""

from __future__ import annotations

import pytest

from app.graph.topics import MAX_TOPIC_KEYWORDS, topic_key, topic_keywords


def test_the_contract_example_shape():
    assert topic_key("How many annual leave days do I get?") == "annual|day|leave"


def test_word_order_case_and_punctuation_do_not_matter():
    a = topic_key("How many annual leave days do I get?")
    b = topic_key("LEAVE days, annual -- how many?")
    assert a == b


def test_plurals_fold_together():
    assert topic_key("refund policies") == topic_key("refund policy")


def test_it_is_deterministic():
    query = "What is the reimbursement limit for travel expenses?"
    assert topic_key(query) == topic_key(query)
    assert len(topic_keywords(query)) <= MAX_TOPIC_KEYWORDS
    assert topic_keywords(query) == sorted(topic_keywords(query))


def test_numbers_and_short_tokens_are_dropped():
    assert topic_key("Is 2024 ok to go?") == ""


@pytest.mark.parametrize("empty", ["", "   ", "What is it?", None, 42, "??!"])
def test_keywordless_input_gives_an_empty_key(empty):
    assert topic_key(empty) == ""


def test_the_key_is_bounded_and_lowercase():
    key = topic_key("Explain the Quarterly Performance Bonus Eligibility Criteria Thoroughly")
    parts = key.split("|")
    assert len(parts) == MAX_TOPIC_KEYWORDS
    assert key == key.lower()
