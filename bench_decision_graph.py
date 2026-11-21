"""Measures the latency the Decision Graph add-on adds.

Run it on this branch and on `origin/main` (via a git worktree) with the
same arguments; the sections `origin/main` cannot provide are skipped
there, so the two JSON outputs are directly comparable.

    python bench_decision_graph.py --runs 200 --out bench.json

Honesty notes, which the printed report repeats:

* The signal and trace sections use a **fake NLI runner**, deliberately.
  A real NLI forward pass costs tens of milliseconds and would bury the
  added Python work in noise; faking it isolates exactly the work the
  add-on introduced. These numbers are therefore *not* end-to-end
  latency.
* The graph-write section uses a **fake driver**. It measures Cypher
  construction and the Python call path only. It says nothing about
  production Neo4j latency, which needs a real server and is Shatakshi's
  to measure.
* The end-to-end section uses the **real models** through the central
  evaluator, and is the only section that reflects a real request.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from typing import Any, Callable, Dict, List, Optional

LEAVE_18 = "Full-time employees are entitled to 18 casual leaves per year."
LEAVE_12 = "Employees are entitled to 12 casual leaves per year."
HANDBOOK = (
    "Casual leave entitlement is reviewed annually by the human resources "
    "committee, which publishes the revised allowance in the staff handbook "
    "together with the carry-over rules and the approval workflow."
)
ANSWER = "Employees receive 18 casual leaves. Approval is granted by a manager."
QUERY = "How many casual leaves do employees get?"

EVIDENCE_TEXTS = [LEAVE_18, LEAVE_12, HANDBOOK]
EVIDENCE_META = [
    {"source": "hr-policy.pdf", "version": "2023.1", "date": "2023-04-01"},
    {"source": "hr-policy.pdf", "version": "2024.2", "date": "2024-04-01"},
    {"source": "staff-handbook.pdf", "version": "7", "date": "2024-01-15"},
]
EVIDENCE_ITEMS = [
    {"text": text, **meta} for text, meta in zip(EVIDENCE_TEXTS, EVIDENCE_META)
]


class _FakeNLI:
    """Deterministic NLI stand-in, so a timing run measures only Python."""

    model_id = "fake/nli"

    def __init__(self) -> None:
        from aegis_core.models.nli import NLIPrediction

        self._prediction = NLIPrediction
        self._table = {
            (LEAVE_18, "Employees receive 18 casual leaves."): (0.91, 0.02, 0.07),
            (LEAVE_12, "Employees receive 18 casual leaves."): (0.02, 0.88, 0.10),
        }

    def infer_batch(self, pairs):
        out = []
        for premise, hypothesis in pairs:
            ent, con, neu = self._table.get((premise, hypothesis), (0.1, 0.1, 0.8))
            label = max(
                (("entailment", ent), ("contradiction", con), ("neutral", neu)),
                key=lambda item: item[1],
            )[0]
            out.append(
                self._prediction(
                    entailment=ent, contradiction=con, neutral=neu, label=label
                )
            )
        return out


def _time(fn: Callable[[], Any], runs: int, warmup: int) -> Dict[str, Any]:
    """Time `fn`, reporting the cold run separately from the warm ones."""
    cold_start = time.perf_counter()
    fn()
    cold_ms = (time.perf_counter() - cold_start) * 1000

    for _ in range(max(0, warmup - 1)):
        fn()

    samples: List[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)

    samples.sort()
    return {
        "cold_ms": round(cold_ms, 4),
        "median_ms": round(statistics.median(samples), 4),
        "mean_ms": round(statistics.fmean(samples), 4),
        "p95_ms": round(samples[min(len(samples) - 1, int(0.95 * len(samples)))], 4),
        "min_ms": round(samples[0], 4),
        "max_ms": round(samples[-1], 4),
        "samples": len(samples),
    }


def _signal_sections(runs: int, warmup: int) -> Dict[str, Any]:
    """Entailment and contradiction, with the NLI model faked out."""
    from aegis_core.signals.contradiction import ContradictionSignal
    from aegis_core.signals.entailment import EntailmentSignal

    entailment = EntailmentSignal()
    entailment.nli = _FakeNLI()
    contradiction = ContradictionSignal()
    contradiction.nli = _FakeNLI()

    return {
        "entailment_signal_fake_nli": _time(
            lambda: entailment.evaluate(QUERY, ANSWER, list(EVIDENCE_TEXTS)),
            runs,
            warmup,
        ),
        "contradiction_signal_fake_nli": _time(
            lambda: contradiction.evaluate(
                QUERY,
                ANSWER,
                list(EVIDENCE_TEXTS),
                evidence_metadata=list(EVIDENCE_META),
            ),
            runs,
            warmup,
        ),
    }


def _graph_sections(runs: int, warmup: int) -> Optional[Dict[str, Any]]:
    """Trace construction and the graph write. Absent on `origin/main`."""
    try:
        from app.graph.neo4j_sink import Neo4jGraphSink
        from app.graph.trace_builder import build_trace
    except ImportError:
        return None

    from aegis_core.signals.contradiction import ContradictionSignal
    from aegis_core.signals.entailment import EntailmentSignal

    entailment = EntailmentSignal()
    entailment.nli = _FakeNLI()
    contradiction = ContradictionSignal()
    contradiction.nli = _FakeNLI()

    entailment_details = entailment.evaluate(
        QUERY, ANSWER, list(EVIDENCE_TEXTS)
    ).details
    contradiction_details = contradiction.evaluate(
        QUERY, ANSWER, list(EVIDENCE_TEXTS), evidence_metadata=list(EVIDENCE_META)
    ).details
    reasons = [
        {"code": "CONTRADICTION", "message": "Two policy passages disagree."},
        {"code": "UNSUPPORTED_CLAIM", "message": "One claim is unsupported."},
    ]

    def make_trace() -> Dict[str, Any]:
        return build_trace(
            request_id="bench-0001",
            decision="ESCALATE",
            headline="Two versions of the leave policy disagree.",
            evidence=EVIDENCE_ITEMS,
            entailment_details=entailment_details,
            contradiction_details=contradiction_details,
            reasons=reasons,
            answerability_score=0.41,
            policy_version="0.1.0",
            profile="standard",
        )

    trace = make_trace()

    class _NoopTx:
        def run(self, cypher: str, **params: Any) -> None:
            pass

    class _NoopSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute_write(self, fn, *args, **kwargs):
            return fn(_NoopTx(), *args, **kwargs)

    class _NoopDriver:
        def session(self, **kwargs):
            return _NoopSession()

    sink = Neo4jGraphSink(_NoopDriver())

    return {
        "trace_construction": _time(make_trace, runs, warmup),
        "cypher_construction_only": _time(
            lambda: sink.build_statements(trace), runs, warmup
        ),
        "graph_write_fake_driver": _time(
            lambda: sink.write_trace(trace), runs, warmup
        ),
        "statements_per_trace": len(sink.build_statements(trace)),
        "nodes": len(trace["nodes"]),
        "edges": len(trace["edges"]),
    }


def _end_to_end(runs: int, warmup: int) -> Dict[str, Any]:
    """The central evaluator with the real models. The only honest e2e number.

    `EvidenceIntelligence` memoises the most recent (query, answer,
    evidence) triple, so timing the *same* request repeatedly measures a
    cache hit rather than an evaluation. Each run therefore uses a
    distinct query, and the cached-repeat cost is reported separately
    because it is a real property of the system, just not the cost of
    evaluating something new.
    """
    from app.core.evaluator import Evaluator
    from app.evidence.registry import default_signals
    from app.schemas import EvaluateRequest

    evaluator = Evaluator(default_signals())
    evidence = [
        {
            "text": text,
            "source": meta["source"],
            "version": meta["version"],
            "date": meta["date"],
        }
        for text, meta in zip(EVIDENCE_TEXTS, EVIDENCE_META)
    ]

    def request_for(index: int) -> "EvaluateRequest":
        # A distinct query per run defeats the per-request memo without
        # changing the amount of work: same answer, same three passages.
        return EvaluateRequest(
            query=f"{QUERY} (variant {index})",
            answer=ANSWER,
            evidence=evidence,
        )

    counter = {"n": 0}

    def once() -> None:
        counter["n"] += 1
        evaluator.evaluate(request_for(counter["n"]))

    distinct = _time(once, runs, warmup)

    repeated_request = request_for(0)
    evaluator.evaluate(repeated_request)  # prime the memo
    cached = _time(lambda: evaluator.evaluate(repeated_request), runs, 2)

    return {
        "distinct_requests": distinct,
        "repeated_identical_request_cached": cached,
        "note": (
            "distinct_requests is the figure to compare across revisions; "
            "repeated_identical_request_cached is served from the "
            "EvidenceIntelligence memo and is not an evaluation"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument(
        "--e2e-runs",
        type=int,
        default=20,
        help="end-to-end runs; each loads/uses the real models, so keep it small",
    )
    parser.add_argument("--skip-e2e", action="store_true")
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument("--label", type=str, default="")
    args = parser.parse_args()

    report: Dict[str, Any] = {
        "label": args.label,
        "conditions": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor(),
            "runs": args.runs,
            "warmup": args.warmup,
            "evidence_count": len(EVIDENCE_TEXTS),
            "answer_claims": 2,
        },
        "limitations": [
            "signal and trace sections use a FAKE NLI runner; they isolate the "
            "added Python work and are not end-to-end latency",
            "graph_write_fake_driver uses a FAKE driver; it is NOT production "
            "Neo4j latency",
            "single machine, single process, no concurrency",
        ],
        "signals_fake_nli": _signal_sections(args.runs, args.warmup),
    }

    graph = _graph_sections(args.runs, args.warmup)
    report["graph"] = graph if graph is not None else "not present on this revision"

    if not args.skip_e2e:
        report["conditions"]["e2e_runs"] = args.e2e_runs
        report["end_to_end_real_models"] = _end_to_end(args.e2e_runs, 2)

    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
