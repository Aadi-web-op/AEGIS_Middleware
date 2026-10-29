import datetime

from app.schemas import EvaluateRequest


def make_case(
    name,
    query,
    answer,
    evidence,
    expected_decision,
    expected_reason,
    split="dev",
    failure_type="NONE",
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
        "split": split,
        "failure_type": failure_type,
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
        split="dev",
        failure_type="NONE",
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
        split="dev",
        failure_type="UNSUPPORTED_CLAIM",
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
        split="dev",
        failure_type="CONTRADICTION",
    ),
    make_case(
        name="no_evidence_abstain",
        query="Who won the 2035 World Cup?",
        answer="Brazil won the 2035 World Cup.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="There is no evidence supporting the answer.",
        split="dev",
        failure_type="NO_EVIDENCE",
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
        split="dev",
        failure_type="AMBIGUOUS_QUERY",
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
        split="dev",
        failure_type="STALE_EVIDENCE",
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
        split="dev",
        failure_type="UNSUPPORTED_CLAIM",
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
        split="dev",
        failure_type="LOW_RELEVANCE",
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
        split="dev",
        failure_type="NONE",
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
        split="dev",
        failure_type="STALE_EVIDENCE",
    ),
    make_case(
        name="empty_evidence_case",
        query="What is machine learning?",
        answer="Machine learning is a method where computers learn patterns from data.",
        evidence=[],
        expected_decision="ABSTAIN",
        expected_reason="No evidence is available to support the answer.",
        split="dev",
        failure_type="NO_EVIDENCE",
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
        split="dev",
        failure_type="UNSUPPORTED_CLAIM",
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
        split="test",
        failure_type="CONTRADICTION",
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
        split="test",
        failure_type="AMBIGUOUS_QUERY",
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
        split="test",
        failure_type="UNSUPPORTED_CLAIM",
    ),
    make_case(
        name="incomplete_evidence_multi_aspect",
        query="What is the hostel accommodation fee and what are the library operating hours?",
        answer="Hostel fee is $500 per semester and the library is open 24 hours daily.",
        evidence=[
            {
                "text": "Hostel accommodation fee is fixed at $500 per semester.",
                "source": "fee_structure_2026.pdf",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="Evidence only covers hostel fee; library operating hours are missing.",
        split="test",
        failure_type="INCOMPLETE_EVIDENCE",
    ),
    make_case(
        name="conflicting_circular_dates",
        query="When is the deadline for semester course registration?",
        answer="Course registration closes on August 15.",
        evidence=[
            {
                "text": "Course registration closes on August 15.",
                "source": "academic_calendar_v1.pdf",
                "version": "v1",
                "date": datetime.date.today(),
            },
            {
                "text": "Course registration has been extended to August 25.",
                "source": "academic_calendar_v2.pdf",
                "version": "v2",
                "date": datetime.date.today(),
            },
        ],
        expected_decision="ESCALATE",
        expected_reason="Two academic circulars state conflicting registration deadlines.",
        split="test",
        failure_type="CONTRADICTION",
    ),
    make_case(
        name="stale_curfew_policy",
        query="What is the current campus curfew time for residents?",
        answer="The campus curfew time for residents is 9 PM.",
        evidence=[
            {
                "text": "Hostel residents must be inside the hostel premises by 9 PM.",
                "source": "hostel_rules_2012.pdf",
                "version": "v1",
                "date": datetime.date(2012, 8, 1),
            }
        ],
        expected_decision="CAVEAT",
        expected_reason="The curfew evidence is from 2012 and substantially outdated for current rules.",
        split="test",
        failure_type="STALE_EVIDENCE",
    ),
    make_case(
        name="completely_unrelated_passage",
        query="What is the minimum GPA required for the merit scholarship?",
        answer="The minimum GPA required for the merit scholarship is 3.8.",
        evidence=[
            {
                "text": "The campus dining facility serves breakfast between 7:30 AM and 9:30 AM on weekdays.",
                "source": "campus_dining.txt",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="ABSTAIN",
        expected_reason="The retrieved dining passage is completely unrelated to the scholarship query.",
        split="test",
        failure_type="LOW_RELEVANCE",
    ),
    make_case(
        name="fully_supported_multi_claim",
        query="What are the book borrowing limits and loan duration for students?",
        answer="Students can borrow up to 5 books for a loan duration of 14 days.",
        evidence=[
            {
                "text": "Enrolled students may borrow up to 5 library books for a loan duration of 14 days.",
                "source": "library_policy_2026.pdf",
                "version": "v3",
                "date": datetime.date.today(),
            }
        ],
        expected_decision="ANSWER",
        expected_reason="Every claim is directly supported by the current official library policy.",
        split="test",
        failure_type="NONE",
    ),
]

DEV_CASES = [c for c in BENCHMARK_CASES if c["split"] == "dev"]
TEST_CASES = [c for c in BENCHMARK_CASES if c["split"] == "test"]
