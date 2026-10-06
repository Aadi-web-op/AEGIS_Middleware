from tests.benchmark.test_cases import BENCHMARK_CASES


def test_benchmark_has_expected_coverage():
    assert len(BENCHMARK_CASES) == 15

    decisions = {
        case["expected_decision"]
        for case in BENCHMARK_CASES
    }

    assert decisions == {
        "ANSWER",
        "CAVEAT",
        "ESCALATE",
        "ABSTAIN",
    }


def test_benchmark_cases_have_required_fields():
    for case in BENCHMARK_CASES:
        assert case["name"]
        assert case["request"].query
        assert case["request"].answer
        assert case["expected_decision"]
        assert case["expected_reason"]

        assert case["expected_decision"] in {
            "ANSWER",
            "CAVEAT",
            "ESCALATE",
            "ABSTAIN",
        }


def test_benchmark_case_names_are_unique():
    names = [case["name"] for case in BENCHMARK_CASES]

    assert len(names) == len(set(names))
