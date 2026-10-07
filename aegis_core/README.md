# AEGIS — Evidence Intelligence Engine

**Owner:** Sumit
**Subsystem of:** [AEGIS — Open-Source Uncertainty Middleware for AI Systems](../README.md)

AEGIS Evidence Intelligence is a **model-agnostic, CPU-friendly** component that
answers one question before any answer is shown to a user:

> *Does this AI answer have enough evidence to be safely shown?*

It sits **between** an existing AI/RAG/agent system and the central AEGIS policy
engine. It does **not** replace the LLM, the RAG retriever, or the knowledge base.
It does **not** decide the final action — it produces the *evidence signals* that
the central policy engine turns into `ANSWER / CAVEAT / ESCALATE / ABSTAIN`.

```
USER QUERY
    |
EXISTING AI / RAG / AGENT
    |
ANSWER + EVIDENCE
    |
    v
+--------------------------------------------------+
|  EVIDENCE INTELLIGENCE  (this subsystem)         |
|                                                  |
|   Relevance   -> is the evidence related?        |
|   Entailment  -> does evidence support claims?   |
|   Contradiction-> do sources conflict?           |
|   Completeness-> is the query fully covered?     |
|                                                  |
+--------------------------------------------------+
    |
    v
signals + reasons + diagnostics
    |
    v
CENTRAL AEGIS POLICY ENGINE  (owned by a teammate)
    |
    v
ANSWER / CAVEAT / ESCALATE / ABSTAIN
```

## Features

- **Four modular signals**, each returning the same `SignalResult` shape:
  `value` in `[0,1]`, human-readable `reasons`, and diagnostic `details`.
- **Batched NLI** with an **LRU cache** — repeated claim/evidence pairs are
  served from cache (measured 43% hit rate on the spike cases).
- **Rule-based numeric + date contradiction detection** that catches the
  classic policy-document failure ("18 casual leaves" vs "12 casual leaves")
  which pure NLI can miss.
- **Evidence-vs-evidence conflict detection** and version-metadata checks.
- **Conservative on bad input**: empty/duplicate/malformed evidence never
  produces a good score.
- **Local CPU inference** — no vendor lock-in, no mandatory external LLM.

## Quick start

```python
from aegis_core import EvidenceEngine

engine = EvidenceEngine()
result = engine.evaluate(
    query="How many casual leaves can an employee take?",
    answer="Employees receive 18 casual leaves per year.",
    evidence=["Employees are entitled to 18 casual leaves per year."],
)

print(result.signals["relevance"]["value"])     # ~0.88
print(result.signals["entailment"]["value"])    # ~0.99
print(result.signals["contradiction"]["value"]) # 0.0
print(result.signals["completeness"]["value"])  # 1.0
```

### HTTP API

```bash
uvicorn aegis_core.api:app --reload
```

```bash
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How many casual leaves?",
    "answer": "Employees receive 18 casual leaves per year.",
    "evidence": ["Employees are entitled to 18 casual leaves per year."]
  }'
```

Evidence items may carry metadata used by the contradiction signal's
version check:

```json
"evidence": [
  {"text": "Refunds within 30 days.", "source": "handbook", "version": "v1"},
  {"text": "Refunds within 45 days.", "source": "handbook", "version": "v2"}
]
```

### For the central policy engine

```python
from aegis_core.central_adapter import evaluate_for_policy

payload = evaluate_for_policy(query, answer, evidence)
# payload["signals"] -> feed to your policy engine
# your engine adds payload["decision"] and payload["answerability_score"]
```

The decision labels are exactly `ANSWER`, `CAVEAT`, `ESCALATE`, `ABSTAIN`.
There is no `CLARIFY`; a clarifying question is an *action* inside `ESCALATE`.

## Signal reference

| Signal | Question | High value means |
|---|---|---|
| `relevance` | Is the evidence related to the query? | evidence is on-topic |
| `entailment` | Does the evidence support the answer's claims? | claims are grounded |
| `contradiction` | Do answer/evidence or sources conflict? | **conflict present** (inverted) |
| `completeness` | Does the evidence cover every part of the query? | all aspects covered |

> Note: `contradiction` is the only *inverted* signal — a high value is a
> warning, not a good outcome. The policy engine must treat it accordingly.

## Models (measured, not guessed)

Selected in the model spike (`model_spike.py`, results in
`model_spike_results.json`). All are public and CPU-runnable.

| Role | Model | Params | Size | Warm latency |
|---|---|---|---|---|
| Embedding | `sentence-transformers/all-MiniLM-L6-v2` | 22.7M | 91 MB | ~15 ms/encode |
| NLI | `cross-encoder/nli-MiniLM2-L6-H768` | 82.1M | 328 MB | ~1.7 ms/pair (batch=8) |
| Cross-encoder (optional) | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 22M | ~90 MB | off by default |

Rejected: `moritzlaurer/mDeBERTa-v3-base-mnli-xnli` (~1.5 GB, slow to fetch);
`microsoft/deberta-v3-*-mnli` (gated, needs auth).

## Measured performance

From `benchmark.py` (`benchmark_results.json`), laptop CPU:

- **First `evaluate()`:** ~112 s (one-time model load from disk)
- **Warm `evaluate()`:** ~120 ms median, ~337 ms p95 across the 10 spike cases
- **Per signal (warm):** relevance 18 ms, entailment 24 ms, contradiction 0.1 ms
  (served from NLI cache), completeness 17 ms
- **NLI batching:** batch=1 → 4.6 ms; batch=8 → 13.6 ms (1.7 ms/pair, ~2.7× throughput)
- **NLI cache hit rate:** 43% on the spike cases

## Project layout

```
aegis_core/
  signals/
    base.py          SignalResult, SignalName, BaseSignal (shared interface)
    relevance.py     RelevanceSignal (embeddings + optional cross-encoder)
    entailment.py    EntailmentSignal (claim extraction + batched NLI)
    contradiction.py ContradictionSignal (NLI + numeric + date + version)
    completeness.py  CompletenessSignal (query decomposition + coverage)
  evidence/
    engine.py        EvidenceEngine.evaluate() — the single entry point
  models/
    registry.py      ModelRegistry (lazy loading, thread-safe singleton)
    nli.py           NLIRunner (batched inference + LRU cache)
  utils/
    numeric_date.py  rule-based numeric/date extraction & comparison
  api.py             FastAPI POST /v1/evaluate
  central_adapter.py contract for the central AEGIS policy engine
model_spike.py       reproducible model-selection experiment
benchmark.py         latency benchmark (real measurements)
tests/
  unit/              pure-Python tests (no model download)
  integration/       model-backed tests
```

## Development

```bash
pip install -r requirements.txt
python model_spike.py     # model selection (reproducible)
python benchmark.py       # latency measurements
python -m pytest -q       # 68 tests
```

## Assumptions & limitations

- Claim extraction is sentence-splitting, not semantic parsing — adequate for
  policy/document answers, may over-split conversational answers.
- Completeness decomposes queries on conjunctions; very complex multi-part
  questions may be under-decomposed.
- Numeric comparison compares quantities sharing a unit family or head noun;
  unrelated quantities are never compared (avoids false positives).
- NLI label mapping is derived from the model config, so any HuggingFace NLI
  model exposing entailment/contradiction/neutral works without code changes.
