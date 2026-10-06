import datetime

from app.schemas import EvaluateRequest


def make_case(
    name,
    query,
    answer,
    evidence,
    expected_decision,
    expected_reason,
):
    return {
        "name": name,
        "request": EvaluateRequest(
            query=query,
            answer=answer,
            evidence=evidence,
        ),
        "expected_decision": expected_decision,
        "expected_reason": expected_reason,
    }


BENCHMARK_CASES = [
    make_case(
        name="strong_evidence_answer",
        query="What is the capital of France?",
        answer="The capital of France is Paris.",
        evidence=[
            {
                "text": "Paris is the capital and largest city of France.",
                "source": "geography.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Strong evidence directly supports the answer.",
    ),
    make_case(
        name="partial_evidence_caveat",
        query="What are the main causes of urban expansion?",
        answer="Urban expansion is mainly caused by population growth and infrastructure development.",
        evidence=[
            {
                "text": "Population growth is an important driver of urban expansion.",
                "source": "urbanization.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="The evidence supports part of the answer but does not fully support all claims.",
    ),
    make_case(
        name="contradictory_evidence_escalate",
        query="Is the policy currently active?",
        answer="Yes, the policy is currently active.",
        evidence=[
            {
                "text": "The policy was active during 2025.",
                "source": "policy_a.txt",
                "date": datetime.date.today(),
            },
            {
                "text": "The policy was discontinued in January 2026.",
                "source": "policy_b.txt",
                "date": datetime.date.today(),
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Evidence sources directly conflict about the current status.",
    ),
    make_case(
        name="no_evidence_abstain",
        query="Who won the 2035 World Cup?",
        answer="Brazil won the 2035 World Cup.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="There is no evidence supporting the answer.",
    ),
    make_case(
        name="ambiguous_query_escalate",
        query="Why did it happen?",
        answer="It happened because of economic pressure.",
        evidence=[
            {
                "text": "Economic pressure contributed to the event.",
                "source": "economics.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="ESCALATE",
        expected_reason="The query does not identify what 'it' refers to.",
    ),
    make_case(
        name="stale_evidence_caveat",
        query="What is the current population of the city?",
        answer="The city has a population of 2 million.",
        evidence=[
            {
                "text": "The city had a population of 2 million.",
                "source": "census.txt",
                "date": datetime.date(2010, 1, 1),
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="The evidence is substantially outdated for a current-value question.",
    ),
    make_case(
        name="unsupported_claim_abstain",
        query="Does the study prove that the treatment is completely safe?",
        answer="Yes, the study proves the treatment is completely safe.",
        evidence=[
            {
                "text": "The study reports positive results from a controlled trial.",
                "source": "study.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="ABSTAIN",
        expected_reason="The evidence does not support the strong claim that the treatment is completely safe.",
    ),
    make_case(
        name="low_relevance_abstain",
        query="What causes ocean tides?",
        answer="Ocean tides are caused primarily by the gravitational effects of the Moon and Sun.",
        evidence=[
            {
                "text": "Photosynthesis converts light energy into chemical energy in plants.",
                "source": "biology.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="ABSTAIN",
        expected_reason="The available evidence is unrelated to the query.",
    ),
    make_case(
        name="mixed_evidence_caveat",
        query="Does exercise improve cardiovascular health?",
        answer="Regular exercise generally improves cardiovascular health, although the effect varies by individual.",
        evidence=[
            {
                "text": "Regular physical activity is associated with improved cardiovascular health.",
                "source": "health_a.txt",
                "date": datetime.date.today(),
            },
            {
                "text": "The magnitude of benefit varies across individuals.",
                "source": "health_b.txt",
                "date": datetime.date.today(),
            },
        ],
        expected_decision="ANSWER",
        expected_reason="Multiple evidence items support the answer and its qualification.",
    ),
    make_case(
        name="missing_date_signal_case",
        query="What does the report conclude?",
        answer="The report concludes that the proposed method is effective.",
        evidence=[
            {
                "text": "The report concludes that the proposed method is effective.",
                "source": "report.pdf",
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="The evidence supports the answer but lacks a date for freshness assessment.",
    ),
        make_case(
        name="empty_evidence_case",
        query="What is machine learning?",
        answer="Machine learning is a method where computers learn patterns from data.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="No evidence is available to support the answer.",
    ),

    make_case(
        name="long_answer_unsupported_claim",
        query="What are the benefits of regular exercise?",
        answer=(
            "Regular exercise can improve cardiovascular health, support "
            "muscle strength, improve mood, and completely prevent all diseases."
        ),
        evidence=[
            {
                "text": "Regular physical activity is associated with improved cardiovascular health and mood.",
                "source": "health.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="The evidence supports some claims but does not support the extreme claim that exercise prevents all diseases.",
    ),

    make_case(
        name="directly_contradictory_evidence",
        query="Is the company profitable?",
        answer="Yes, the company is profitable.",
        evidence=[
            {
                "text": "The company reported a net profit of $5 million.",
                "source": "financial_2025.txt",
                "date": datetime.date.today(),
            },
            {
                "text": "The company reported a net loss of $3 million.",
                "source": "financial_2026.txt",
                "date": datetime.date.today(),
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Evidence from different sources directly conflicts about profitability.",
    ),

    make_case(
        name="highly_ambiguous_query",
        query="What happened there?",
        answer="The project was cancelled.",
        evidence=[
            {
                "text": "The project was cancelled in March 2026.",
                "source": "project.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="ESCALATE",
        expected_reason="The query does not identify what 'there' or 'what happened' refers to.",
    ),

    make_case(
        name="partial_support_across_chunks",
        query="What factors contributed to the city's growth?",
        answer="The city's growth was driven by population growth, new infrastructure, and increased investment.",
        evidence=[
            {
                "text": "Population growth contributed significantly to the city's expansion.",
                "source": "urban_a.txt",
                "date": datetime.date.today(),
            },
            {
                "text": "New infrastructure projects supported further development.",
                "source": "urban_b.txt",
                "date": datetime.date.today(),
            },
            {
                "text": "The city has several historical monuments.",
                "source": "history.txt",
                "date": datetime.date.today(),
            },
        ],
        expected_decision="CAVEAT",
        expected_reason="The evidence supports population growth and infrastructure but does not support the claim about increased investment.",
    ),
]
