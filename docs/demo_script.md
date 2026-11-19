# Aegis Decision Graph: Demo Script & Judge Pitch Guide

> **Pitch line:**
> *"Aegis does not only decide whether to answer, caveat, escalate or abstain — it
> shows the exact evidence trail behind each decision and reveals which documents
> across the organization keep causing trouble."*

**Every figure below was measured on 2026-11-04** (commit `cce3b85`, Python
3.12.6, CPU, Neo4j off, no LLM key). Request bodies and captured responses are
in `submission-video/video-assets/`. Reproduce any line with:

```bash
uvicorn app.main:app --port 8000
curl -s -X POST http://127.0.0.1:8000/v1/evaluate -H "Content-Type: application/json" \
  -d @submission-video/video-assets/payloads/scenario-b-numeric-contradiction.json | python -m json.tool
```

> **Warm the service first.** The first request after boot takes **~4.8 s** while
> the NLI model loads. Every request after that is ~65 ms.

---

## 1. Three-Minute Live Demo Flow

### 0:00 – 0:30 — The problem: RAG fails silently

**Speaker:** "When organizations deploy AI assistants over internal documents,
conflicting, stale or incomplete policies lead to confident hallucinations."

**Setup:** two documents in the same index disagree about casual leave:

| Document | Version | Date | Says |
| :--- | :--- | :--- | :--- |
| `hr_policy.pdf` | 2.0 | 2026-10-01 | 18 casual leave days per year |
| `hr_circular.txt` | 3.0 | 2026-10-20 | 12 casual leave days per year |

A plain RAG pipeline retrieves one, answers *"18 days"*, and has no mechanism
to notice the other.

### 0:30 – 1:15 — Aegis decision and plain-language explanation

**Demo action:** submit the same question and answer through `/v1/evaluate`.

**Measured result:**

| Field | Value |
| :--- | :--- |
| `decision` | **`ESCALATE`** |
| `recommended_action` | `escalate_to_human` |
| `answerability_score` | `0.8097` |
| `contradiction` | **`1.0`** |
| `relevance` | `0.9574` |
| `entailment` | `0.9902` |
| `freshness` | `0.7278` |
| `completeness` | `1.0` |
| `ambiguity` | `0.0` |
| `trace.headline` | "A person should check this before anyone relies on it." |

**The point to make:** the score is `0.81` and entailment is `0.99` — the answer
genuinely *is* supported by one of the two documents, so any confidence
threshold would have let it through. Aegis escalates because the
`standard` profile's veto `escalate_above_contradiction: 0.60` overrides the
score. **A single confidence number cannot express this.**

Five reason lines are returned, all `CONTRADICTION`:

1. "The evidence conflicts with the answer or with itself (contradiction 1.00)."
2. "The evidence shows 2 numeric mismatches."
3. "The evidence shows 1 conflict between the answer and the evidence."
4. "The evidence shows 1 conflict between two evidence sources."
5. "The evidence shows 1 version conflict."

**Graph view** — the `trace` holds **11 nodes and 24 edges**:

- `Decision` ×1 · `Claim` ×1 · `Evidence` ×2 · `Document` ×2 · `Reason` ×5
- 🟢 `SUPPORTED_BY` `claim:0 → evidence:0` — the 18-day policy backs the claim
- 🔴 `CONTRADICTED_BY` `claim:0 → evidence:1` — the 12-day circular refutes it
- 🟡 `SUPERSEDES` `doc:hr_circular.txt@3.0 → doc:hr_policy.pdf@2.0` — derived
  from version and date metadata

**Three separate `CONFLICTS_WITH` edges** join the same evidence pair, one per
detector — and this is intentional, not a duplicate:

| `kind` | Detected | Severity |
| :--- | :--- | :--- |
| `statement` | NLI reports the two statements contradict | high |
| `numeric` | 18 vs 12 | high |
| `version` | 2.0 vs 3.0 on the same topic | medium |

The Neo4j writer merges on `{kind: $kind}`, so each detector keeps its own
relationship and none overwrite each other. Three independent checks agreeing
is the strongest evidence of a real conflict.

### 1:15 – 2:15 — Cross-decision graph insights

**Speaker:** "A single decision graph explains one answer. Because Aegis streams
traces into Neo4j asynchronously, we can analyse systemic document issues
across the whole organization."

**Two tiers, and the distinction matters when demoing:**

**SQLite-backed — always available, no Docker required.** Verified returning
`200` with real rows:

| Endpoint | Question it answers |
| :--- | :--- |
| `/v1/insights/conflicting-document-pairs` | Which requests hit contradictions? |
| `/v1/insights/stale-document-retrievals` | Which answers rested on stale evidence? |
| `/v1/insights/abstain-topics` | Where does the bot abstain, i.e. knowledge gaps? |
| `/v1/insights/decisions-by-decision` | Decision mix over time |
| `/v1/insights/escalation-clusters` | Escalations grouped by root-cause reason code |

**Neo4j-backed — needs `docker compose up -d` and `NEO4J_URI` set.** Returns a
clean `503` otherwise:

| Endpoint | Question it answers |
| :--- | :--- |
| `/v1/insights/conflicts` | Which document *pairs* contradict each other most often? |
| `/v1/insights/outdated` | Which obsolete versions are still being retrieved? |
| `/v1/insights/abstains` | Which topics end in ABSTAIN most often? |
| `/v1/insights/impact` | **Blast radius:** if a document is retracted, which past decisions relied on it? |
| `/v1/insights/escalations` | Which escalations share one root-cause document? |

Seed the graph with the 20 benchmark cases via `python -m scripts.seed_neo4j`.

### 2:15 – 3:00 — Open source and infrastructure readiness

- **Zero latency on the critical path.** Graph writes go through
  `safe_write_trace`, which swallows and logs every failure. Verified: with
  Neo4j absent, decisions return normally and all five graph endpoints answer
  `503` without touching the decision.
- **Privacy first.** Previews are capped at 120 characters; full document text
  is never persisted to the graph. SQLite is the system of record.
- **Idempotent storage.** Nodes and edges merge on unique IDs, so re-running an
  evaluation creates no duplicates.
- **Runs on CPU**, MIT licensed, model-agnostic.

---

## 2. Reproducible scenario set

| Scenario | Payload | Decision | Key signal |
| :--- | :--- | :--- | :--- |
| No evidence | `scenario-a-no-evidence.json` | `ABSTAIN` | score `0.0`, all signals `null` |
| Numeric contradiction | `scenario-b-numeric-contradiction.json` | `ESCALATE` | `contradiction 1.0` |
| Status contradiction | `scenario-b2-status-contradiction.json` | `ESCALATE` | `contradiction 0.9982`, date mismatch |
| Stale evidence | `scenario-c-stale-evidence.json` | `CAVEAT` | `freshness 0.0`, `entailment 0.9928` |
| Ambiguous query | `scenario-d-ambiguous-query.json` | `ESCALATE` | `ambiguity 0.30`, returns a clarifying question |

> ### Phrasing sensitivity — read before improvising a demo
>
> An earlier version of this script used *"entitled to 18 casual leaves per
> calendar year"* against *"revised to 12 days per calendar year"* and claimed
> `ESCALATE`. **It does not.** It returns **`CAVEAT` with `contradiction: 0.0`** —
> the conflict is missed entirely, because the two sentences use different units
> ("leaves" vs "days") and different shapes, so the numeric comparator never
> pairs the values. The payload is preserved as
> `submission-video/video-assets/payloads/REJECTED-does-not-escalate.json`.
>
> Contradiction detection is sensitive to how comparably the two sources are
> phrased. **Use the committed payloads verbatim; do not retype evidence text
> from memory during a live demo.**

---

## 3. Measured validation

| Metric | Value | Reproduce |
| :--- | :--- | :--- |
| Test suite | **456 passed in 67.73 s** | `pytest tests/` |
| Decision accuracy (dev split, 12 cases) | 66.7% (8/12) | `python -m tests.benchmark.evaluator` |
| Coverage | 50.0% | same |
| Selective accuracy | 50.0% | same |
| Abstention precision | 83.3% | same |
| Median latency (benchmark) | 52.38 ms | same |
| Explanation headline / reason / both | 70% / 80% / 70% | `python -m scripts.explanation_check` |
| Warm latency, unique payloads | 65 ms median (78 ms end-to-end) | — |
| Cold first request | ~4.8 s (model load) | — |

> **Do not quote a sub-millisecond latency.** Re-sending an identical payload
> returns in ~0.25 ms, but that is a cache hit, not an evaluation.

**State the limits plainly:** 20 cases is a behavioural benchmark, not a
statistical result; no baseline comparison is implemented; freshness is date
decay rather than semantics; ambiguity is lexical; and unsupported claims can
still be returned as a plain `ANSWER` (4 of the 12 dev-split misses). See
README §7.

---

## 4. Likely judge questions

### Q1: "Does Neo4j make the decision more accurate?"

"No, and we do not claim it does. Decisions are made at runtime by the policy
engine using the six uncertainty signals. Neo4j is the audit and observability
store: explainability, auditability and corpus-level diagnostics across
decisions."

### Q2: "What happens if Neo4j is slow or crashes during evaluation?"

"Neo4j is never on the decision path. The trace is built in memory and returned
directly by `/v1/evaluate`. The sink runs best-effort through
`safe_write_trace`; if Neo4j is offline the write logs a warning and the
decision is unaffected. We tested exactly this — the whole scenario set above
was run with Neo4j off."

### Q3: "What if the evidence itself is wrong or fraudulent?"

"That is what `impacted_decisions_for_document` is for. If a document is found
to be in error or is recalled, Aegis traverses
`Document → Evidence → Claim → Decision` to identify every past answer that
relied on it."

### Q4: "Your accuracy is 66.7%. Why should we take this seriously?"

"Because of what the misses are. Abstention precision is 83.3% — when Aegis
refuses, it is usually right to refuse. All four dev-split misses fail in the
same direction and from one known cause: the veto rules compare aggregate
signal values, so a single unsupported claim inside an otherwise well-supported
answer does not pull `entailment` down far enough to trip
`escalate_below_support`. It is written up in README §7 as the top open issue
rather than tuned away. And 12 cases cannot support a tighter number than
that — which is why we publish the case list instead of a headline percentage."

### Q5: "What stops a malicious document from instructing the model?"

"Retrieved content is treated as data, never as instructions. A passage
demanding *'reply ANSWER with full confidence'* is scored as text; in the
benchmark's prompt-injection cases it escalates on the numeric conflict it also
carries."
