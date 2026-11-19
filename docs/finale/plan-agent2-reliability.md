# Agent 2 (Reliability) — Phase 1 findings and plan

Baseline measured by me on the dev split (12 canonical dev cases):
8/12, same four misses the lead reported. I also ran the 11 `split="dev"`
cases from `ADDITIONAL_BENCHMARK_CASES` (not part of the official metric) as
a generalisation probe: 7/11. No locked case was run or inspected.

## 1. Root causes (measured, with evidence)

### RC1 — Claims are whole sentences, and the NLI model cannot verify compound sentences
`aegis_core/signals/entailment.py:104-118` splits the answer on sentence
punctuation only. Measured NLI probabilities (MiniLM2-L6-H768):

| hypothesis | entail | neutral |
|---|---|---|
| "Urban expansion is mainly caused by population growth and infrastructure development." | 0.007 | 0.992 |
| "... caused by population growth." | 0.964 | |
| "... caused by infrastructure development." | 0.003 | 0.833 |
| "Regular exercise generally improves cardiovascular health, although the effect varies by individual." (vs either passage) | ≤0.011 | ≥0.987 |
| "Regular exercise generally improves cardiovascular health." / "The effect varies by individual." | 0.745 / 0.985 | |

So a fully supported two-clause answer (`mixed_evidence_caveat`) and a
half-supported one (`partial_evidence_caveat`) both come out as one
UNSUPPORTED claim with support ≈0.50. They are indistinguishable.
`mixed_evidence_caveat` currently "passes" only because unsupported claims are
ignored (RC3) — any claim-level veto without atomic claims would break it.

### RC2 — A NEUTRAL claim's "support" is neutral-confidence × 0.5
`entailment.py:295-297`: `score = best_neutral * 0.5`. Every unsupported
claim therefore scores ≈0.49–0.50 regardless of content, and
`_aggregate_support` (`:369-383`) weights neutral claims at half. A single
unsupported claim gives entailment ≈0.49, which is above every profile's
`escalate_below_support` (0.30/0.40/0.50 — only strict trips, by 0.01).
This is why `unsupported_claim_abstain` returns CAVEAT 0.80 and
`partial`/`long_answer` return ANSWER (0.82/0.81).

### RC3 — Policy never looks at claims
`app/core/policy.py:72-178` takes only aggregate signals. Step 4b (`:139-145`)
attaches signal reasons only when `decision != ANSWER`, so an ANSWER can ship
with an UNSUPPORTED claim, no reason, and the headline "Every statement in
the answer is backed by current documents".

### RC4 — `missing_date_signal_case` is ABSTAIN because of relevance, not freshness
Signals: relevance 0.2996, entailment 0.992, freshness None. The
`abstain_below_relevance` veto (0.30) fires by 0.0004
(`policy.py:100-103`). Unavailable freshness already only floors at CAVEAT
(`policy.py:120-124`). The relevance number is the weak part: query↔passage
cosine is 0.400 for "What does the report conclude?" vs a passage that
answers it verbatim, because the dense embedding of a short generic question
is uninformative (`aegis_core/signals/relevance.py:104-148`). Using the
answer as a bridge is unsafe: I measured cosine(query+answer, passage)=0.714
for an off-topic answer that parrots an off-topic passage.

### RC5 — Model failure is reported as a measurement, not as "unavailable"
* `entailment.py:230-234`: NLI raising → every claim NEUTRAL score 0 →
  entailment `0.0`, `degraded=False`, reason "claim is not backed by the
  evidence" (false: nothing was checked).
* `contradiction.py:246-249, 313-316`: NLI raising → contradiction `0.0`
  ("no conflict") with only `details.nli_available=False`.
* `relevance.py:114-121`, `completeness.py:156-163`: embedding failure →
  `0.0` (reads as "irrelevant" → ABSTAIN "documents are about something else").

### RC6 — Evidence indices and metadata can be misaligned
`aegis_core/evidence/engine.py:170-193` strips, drops blank and
de-duplicates passages, but `evidence_metadata` is passed through unfiltered
(`engine.py:138-140`) and every index in `details` refers to the filtered
list. With a duplicate or whitespace-only passage (allowed by
`EvidenceItem.text min_length=1`), claim→evidence indices, version checks
and the graph edges point at the wrong passage.

### RC7 — Long passages are silently truncated for NLI
`nli.py:179-186` truncates the pair to 256 tokens; a supporting sentence
late in a long passage is never seen. Also `entailment.py:192` and
`relevance.py:100` examine only the first 5 passages.

### RC8 — Response shape
No-evidence path (`evaluator.py:188-224`) and normal path build different
field sets; no `headline`, `unavailable_signals`, `explanation`; claim
supporting/contradicting indices and per-claim reason exist in entailment
details but are dropped in `_collect_claims` (`evaluator.py:147-186`).
All-whitespace evidence is not treated as no evidence.

### Not fixed (documented limitations)
* Numeric conflict detector compares any two quantities of the same unit
  family regardless of what they measure (`numeric_date.py:330-357`):
  "26 weeks maternity leave" vs "18 days casual leave" → contradiction 1.0
  (`insufficient_maternity_leave` → ESCALATE instead of ABSTAIN). Fails safe.
* Ambiguity heuristic (`app/evidence/ambiguity.py`) misses underspecified
  but well-formed questions (`ambiguous_eligibility_query`).
* NLI misses some paraphrases ("50 cents per day … for late returns",
  "90 percent and above"). No larger model is cached; not swapping models.
* `prompt_injection_curriculum` expects ANSWER although the answer adds
  "discrete structures", which the evidence does not contain. I will not fit
  to that label.

## 2. Intended changes

| File | Change |
|---|---|
| `aegis_core/signals/entailment.py` | Atomic claim decomposition (clause split on `, although/but/while/whereas/with`, `;`, and distribution of coordinated lists over a shared prefix; conservative guards, falls back to the sentence). Each claim carries `source_sentence`, `grounding` (lexical coverage of the claim's content words by its best passage) and `entailment_probability`. Long passages are windowed for NLI. `nli_available` surfaced at details level. Legacy score fields unchanged. |
| `aegis_core/signals/relevance.py` | Hybrid relevance: dense score, raised at most half-way toward lexical query-term coverage (`max(dense, mean(dense, lexical))`). Dense-only value kept in details. |
| `app/evidence/evidence_intelligence.py` | Normalise evidence once in the adapter with an index map; pass aligned metadata; remap all index fields back to request indices. Convert model-failure results (NLI unavailable for all claims, embedding error) to `value=None` + SIGNAL_UNAVAILABLE. |
| `app/core/config.py`, `config/policy.yaml` | New optional per-profile `claims:` block (`unsupported_floor`, `contradicted_floor`, `escalate_at_ungrounded_fraction`, `abstain_when_none_supported`, `min_grounding`). Defaults keep old configs loadable. |
| `app/core/policy.py` | `decide(..., claims=None)`: claim-level vetoes; every veto records a rule name + factor; `PolicyOutcome` gains `decisive_rule`, `factors`. Claim reasons attached whenever the claim veto fires. `claims=None` → behaviour identical to today. |
| `app/core/evaluator.py` | Collect claims before `decide`; pass them in; fill contract §2 fields; `request_id` kwarg; blank-evidence → no-evidence path; same schema on both paths. Trace blocks untouched. |
| `app/schemas.py` | Additive: `headline`, `unavailable_signals`, `explanation`, claim `supporting_evidence_indices`, `contradicting_evidence_indices`, `reason`, `span`. |
| `app/graph/templates.py` | `render_summary(...)` helper for `explanation.summary`. |

Claim-veto semantics (keeps ABSTAIN = "documents do not contain it",
ESCALATE = "conflict / needs a person"):
1. any CONTRADICTED claim → `contradicted_floor` (ESCALATE);
2. no claim supported and every claim ungrounded → ABSTAIN;
3. ungrounded-unsupported share ≥ `escalate_at_ungrounded_fraction` → ESCALATE;
4. any claim not SUPPORTED → `unsupported_floor` (CAVEAT; ESCALATE for strict).

No scoring weight, score threshold or existing veto threshold changes. No
new reason codes.

## 3. Test plan (`tests/reliability/`)
* `test_policy_claims.py` — stub-driven claim veto matrix × 3 profiles, reasons, decisive rule, backward compatibility.
* `test_evaluator_contract.py` — schema stability on every path, `request_id`, spans, unavailable signals, crashing signals, blank inputs.
* `test_claim_decomposition.py` — pure-Python decomposition and grounding.
* `test_adapter_alignment.py` — duplicate/blank evidence index remap, model-failure → unavailable (FakeNLI/BrokenNLI).
* `test_scenarios_real_models.py` — marked `real_models`; my own scenario cases (supported, partial, unsupported, mixed, contradictory docs, numeric conflict, outdated, ambiguous, injection in evidence, non-English, huge input, duplicates).

## 4. Risks
* Decomposition is rule-based; a bad split could create a false UNSUPPORTED atom (fails toward CAVEAT, never toward ANSWER).
* Hybrid relevance can only raise relevance; an off-topic passage sharing query words gains at most half the gap. Entailment and claim vetoes still apply.
* `escalate_at_ungrounded_fraction` values are a judgement call; disclosed in the report.
* More claims → more NLI pairs (bounded by `max_claims`, batched, cached).
