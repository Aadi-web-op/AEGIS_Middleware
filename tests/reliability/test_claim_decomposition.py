"""Atomic claim decomposition and lexical grounding. Pure Python, no model."""

import pytest

from aegis_core.utils.claim_split import (
    content_tokens,
    decompose_sentence,
    grounding,
)


def texts(sentence):
    return [a.text for a in decompose_sentence(sentence)]


def test_coordinated_objects_share_the_prefix():
    atoms = decompose_sentence(
        "Urban expansion is mainly caused by population growth and infrastructure development."
    )
    assert [a.text for a in atoms] == [
        "Urban expansion is mainly caused by population growth.",
        "Urban expansion is mainly caused by infrastructure development.",
    ]
    assert all(a.decomposed for a in atoms)
    assert all(a.source_sentence.startswith("Urban expansion") for a in atoms)


def test_verb_phrase_list_is_distributed_over_the_modal():
    assert texts(
        "Regular exercise can improve cardiovascular health, support muscle strength, "
        "improve mood, and completely prevent all diseases."
    ) == [
        "Regular exercise can improve cardiovascular health.",
        "Regular exercise can support muscle strength.",
        "Regular exercise can improve mood.",
        "Regular exercise can completely prevent all diseases.",
    ]


def test_concession_clause_becomes_its_own_claim():
    assert texts(
        "Regular exercise generally improves cardiovascular health, although the effect varies by individual."
    ) == [
        "Regular exercise generally improves cardiovascular health.",
        "The effect varies by individual.",
    ]


def test_independent_clauses_keep_their_own_subject():
    assert texts("Employees get 20 days of leave and contractors get 10 days.") == [
        "Employees get 20 days of leave.",
        "Contractors get 10 days.",
    ]


def test_uncertain_prefix_offers_alternatives():
    atoms = decompose_sentence("Paris is the capital of France and the largest city.")
    assert atoms[0].text == "Paris is the capital of France."
    # "of the largest city" would be wrong; the verifier may pick the other.
    assert "Paris is the largest city." in atoms[1].candidates


@pytest.mark.parametrize(
    "sentence",
    [
        "Full-time employees get 18 casual leaves.",
        "The fee is between 10 and 20 dollars.",
        "An examination score of 90 percent and above receives an A grade.",
        "Students must maintain a minimum CGPA of 7.5 with zero active backlogs.",
        "The refund is $1,200.",
        "Either the dean or the registrar signs the form.",
    ],
)
def test_sentences_without_a_safe_split_are_left_alone(sentence):
    atoms = decompose_sentence(sentence)
    assert [a.text for a in atoms] == [sentence]
    assert atoms[0].decomposed is False


def test_leading_interjection_is_not_split_off():
    # "Yes, ..." has no clause before the comma, so nothing is cut.
    sentence = "Yes, the policy is currently active."
    assert texts(sentence) == [sentence]


def test_empty_input():
    assert decompose_sentence("") == []
    assert decompose_sentence("   ") == []


def test_every_atom_uses_only_words_from_the_sentence():
    """Decomposition may drop words but must never invent one."""
    sentence = (
        "The average salary package is $18,000, top recruiters include Google and "
        "Microsoft, with a 6-month internship."
    )
    allowed = set(sentence.lower().replace(",", " ").replace(".", " ").split())
    allowed |= {"$18,000"}
    for atom in decompose_sentence(sentence):
        for cand in atom.candidates:
            words = cand.lower().rstrip(".").replace(", ", " ").split()
            assert set(words) <= allowed, cand


def test_stemming_joins_inflections():
    assert content_tokens("The report concludes") == content_tokens("report conclude")
    assert content_tokens("caused") == content_tokens("cause")


def test_grounding_separates_discussed_from_absent():
    passage = ["Books returned past the due date incur a fine of 50 cents per day per volume."]
    discussed = grounding("The library charges an overdue fine of 50 cents per day for late returns.", passage)
    absent = grounding("The study proves the treatment is completely safe.", passage)
    assert discussed >= 0.5
    assert absent < 0.2


def test_grounding_edge_cases():
    assert grounding("", ["anything"]) == 0.0
    assert grounding("A real claim here.", []) == 0.0
    assert grounding("Leave is 18 days.", ["Leave is 18 days."]) == 1.0
