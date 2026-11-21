"""Performance benchmark for the AEGIS Evidence Intelligence Engine.

Measures REAL latency on this machine. Nothing here is invented:
  * cold-load time (first model load)
  * warm evaluate() latency across the 10 spike cases
  * NLI cache hit rate
  * batching benefit (batch=1 vs batch=8)

Run:  python benchmark.py
"""

import time
import statistics
import json
from pathlib import Path

from aegis_core import EvidenceEngine
from aegis_core.models.nli import NLIRunner


# The 10 spike cases from the model spike.
SPIKE_CASES = [
    ("How many casual leaves can an employee take?",
     "Employees receive 18 casual leaves per year.",
     ["Employees are entitled to 18 casual leaves per year."]),
    ("What is the casual leave policy for employees?",
     "Staff members get 18 days of casual leave annually.",
     ["Employees are entitled to 18 casual leaves per year."]),
    ("How many casual leaves can an employee take?",
     "Employees receive 18 casual leaves per year.",
     ["The company cafeteria serves lunch from 12 PM to 2 PM."]),
    ("How many casual leaves can an employee take?",
     "Employees receive 18 casual leaves per year.",
     ["Employees are entitled to 12 casual leaves per year."]),
    ("What is the refund period?",
     "Customers can request refunds within 30 days.",
     ["Refund requests must be made within 45 days of purchase."]),
    ("When does the new policy take effect?",
     "The policy takes effect on January 1, 2024.",
     ["The updated policy is effective from March 15, 2024."]),
    ("What are the leave policies for full-time and part-time employees?",
     "Full-time employees get 18 casual leaves. Part-time employees get 10.",
     ["Full-time employees are entitled to 18 casual leaves per year."]),
    ("How many casual leaves for senior employees?",
     "Senior employees receive 20 casual leaves.",
     ["Employees with more than 5 years tenure receive additional leave benefits."]),
    ("What is the complete leave policy?",
     "Employees get 18 casual leaves, 12 sick leaves, and 10 paid holidays.",
     ["Employees are entitled to 18 casual leaves per year.",
      "Sick leave allowance is 12 days per year.",
      "The company observes 10 paid holidays annually."]),
    ("What is the maternity leave duration?",
     "Maternity leave is 26 weeks.",
     ["Paternity leave is 2 weeks for eligible fathers."]),
]


def main():
    report = {}

    # ---- cold load ----
    t0 = time.perf_counter()
    engine = EvidenceEngine()
    cold_ms = (time.perf_counter() - t0) * 1000
    report["cold_engine_construct_ms"] = round(cold_ms, 1)

    # First evaluate pays the model-load cost.
    t0 = time.perf_counter()
    engine.evaluate(*SPIKE_CASES[0])
    first_ms = (time.perf_counter() - t0) * 1000
    report["first_evaluate_ms_includes_load"] = round(first_ms, 1)

    # ---- warm latency across spike cases ----
    latencies = []
    for case in SPIKE_CASES:
        t0 = time.perf_counter()
        engine.evaluate(*case)
        latencies.append((time.perf_counter() - t0) * 1000)

    report["warm_evaluate_ms"] = {
        "mean": round(statistics.mean(latencies), 1),
        "median": round(statistics.median(latencies), 1),
        "p95": round(sorted(latencies)[int(0.95 * len(latencies))], 1),
        "min": round(min(latencies), 1),
        "max": round(max(latencies), 1),
        "per_case_ms": [round(x, 1) for x in latencies],
    }

    # ---- NLI cache stats ----
    nli = NLIRunner("cross-encoder/nli-MiniLM2-L6-H768")
    report["nli_cache"] = nli.cache_stats()

    # ---- batching benefit ----
    premise = "Employees are entitled to 18 casual leaves per year."
    pairs1 = [(premise, "Employees receive 18 casual leaves per year.")]
    pairs8 = [(premise, "Employees receive %d casual leaves per year." % n)
              for n in range(10, 18)]

    # clear cache to measure pure inference, then run each 5x
    nli.clear_cache()
    b1 = []
    for _ in range(5):
        t0 = time.perf_counter()
        nli.infer_batch(pairs1)
        b1.append((time.perf_counter() - t0) * 1000)
    nli.clear_cache()
    b8 = []
    for _ in range(5):
        t0 = time.perf_counter()
        nli.infer_batch(pairs8)
        b8.append((time.perf_counter() - t0) * 1000)

    report["nli_batching"] = {
        "batch=1_mean_ms": round(statistics.mean(b1), 1),
        "batch=8_mean_ms": round(statistics.mean(b8), 1),
        "batch=8_per_pair_ms": round(statistics.mean(b8) / 8, 2),
    }

    # ---- per-signal timing (from a warm run) ----
    result = engine.evaluate(*SPIKE_CASES[0])
    report["per_signal_ms_warm"] = result.timing_ms

    Path("benchmark_results.json").write_text(json.dumps(report, indent=2))

    print(json.dumps(report, indent=2))
    print("\nSaved to benchmark_results.json")


if __name__ == "__main__":
    main()
