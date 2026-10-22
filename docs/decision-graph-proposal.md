# Decision Graph add-on — what Sumit built, and what needs Aaradhya's approval

Branch: `feature/sumit-graph-evidence-details`, based on `origin/main` @ `18cd3d3`.
Author: Sumit (Evidence Intelligence + graph writer). Date: 2026-10-23.

## 1. Why this document exists

The team brief of 22 Oct 2026 describes a trace contract — `request_id`,
`decision`, `headline`, `nodes`, `edges`, `reasons` — and says Aaradhya owns
it. **That contract does not exist anywhere in the repository.** I checked
every branch and every commit reachable from any ref:

```
git log --all --oneline --name-only | grep -iE 'neo4j|graph|trace'   # no matches
```

There is also no `GraphSink` call site, no Neo4j code, no `neo4j`
dependency and no Docker configuration. The SQLite audit log the brief
calls the system of record exists only on the unmerged
`origin/feature/nandini-rag` branch (`app/audit/logger.py`).

So I could not confirm the contract, and per section 11 of the brief I have
**not** changed any shared interface. `app/schemas.py`, `app/core/evaluator.py`
and `app/core/policy.py` are untouched on this branch. What I did instead:
built my three pieces so they fit the documented contract, and wrote the
contract down in one file (`app/graph/contract.py`) so that when Aaradhya's
version lands, one file changes rather than five.

## 2. What I implemented

| Area | Files |
| --- | --- |
| Claim-level entailment detail | `aegis_core/signals/entailment.py` |
| Conflict-level contradiction detail | `aegis_core/signals/contradiction.py` |
| Graph contract, in one place | `app/graph/contract.py` |
| Sink interface + failure isolation | `app/graph/sink.py` |
| Neo4j writer | `app/graph/neo4j_sink.py` |
| Trace builder (**proposal only**) | `app/graph/trace_builder.py` |
| Fake-driver tests | `tests/graph/` |
| Signal detail regression tests | `tests/test_entailment_details.py`, `tests/test_contradiction_details.py` |
| Latency harness | `bench_decision_graph.py` |

I deliberately did **not**: wire a sink call into the evaluator, add fields to
`EvaluateResponse`, implement the frontend, or write insight queries.

## 3. Detail shapes (additive — no existing key changed)

`entailment` details `claims[]` gains, per claim:

```json
{
  "claim_index": 0,
  "claim": "Employees receive 18 casual leaves.",
  "status": "SUPPORTED",
  "support": 0.91,
  "supporting_evidence_indices": [0],
  "contradicting_evidence_indices": [1],
  "evidence_indices": [0, 1],
  "reasons": ["Entailed by evidence [0].", "Also contradicted by evidence [1]; sources disagree about this claim."],
  "nli_available": true
}
```

`status` uses `app.schemas.ClaimStatus` (`SUPPORTED` / `UNSUPPORTED` /
`CONTRADICTED`) and `support` matches `app.schemas.ClaimResult.support`, so
these drop straight into the response model that already exists. I followed
that over the brief's illustrative `text` key.

`contradiction` details gains a `conflicts[]` list:

```json
{
  "kind": "numeric",
  "scope": "evidence_vs_evidence",
  "index_a": 0, "index_b": 1,
  "evidence_indices": [0, 1],
  "value_a": "18", "value_b": "12",
  "source_a": "hr-policy.pdf", "source_b": "hr-policy.pdf",
  "version_a": "2023.1", "version_b": "2024.2",
  "reason": "Numeric mismatch: 18 vs 12.",
  "graph_edge_eligible": true
}
```

Three properties worth noting:

* **`graph_edge_eligible` is the honesty flag.** It is true only for a
  conflict between two evidence passages whose indices are both known. An
  answer-vs-evidence conflict has one evidence index, so it is reported as a
  diagnostic and marked ineligible — the graph omits the edge rather than
  inventing a pair, as the brief requires.
* **`kind` is a new vocabulary** (`numeric` / `date` / `statement` /
  `version`); the existing `conflict_type` (`nli` / `numeric` / `date` /
  `version`) is untouched. `nli` maps to `statement`.
* **The contradiction score cannot move.** The projection is built *after*
  `_score_contradiction` from the same findings and is never fed back into
  it. `test_projection_does_not_change_the_contradiction_score` recomputes
  the score from the untouched scoring inputs and asserts equality. High
  still means more contradiction; nothing is inverted.

## 4. Three decisions that need approval

### (1) Node identity — the one that decides whether insight queries work

A `Decision` is keyed on `request_id` (brief rule 3). For the rest I propose:

| Node | Id | Scope |
| --- | --- | --- |
| Claim | `{request_id}:claim:{index}` | per request |
| Evidence | `{request_id}:evidence:{index}` | per request |
| Document | `doc:{source}@{version}` | **global** |
| Reason | `{request_id}:reason:{index}` | per request |

The asymmetry is the point. "Which document keeps causing conflicts?" needs
one `Document` node shared across decisions; a `Claim` only ever belongs to
the decision it was extracted for. **Shatakshi should confirm this is what her
insight queries need before I finalise it.**

An `Evidence` chunk would also be worth sharing across decisions, but nothing
in the retrieval layer emits a stable chunk id today, so it stays
request-scoped. The builder already honours a `chunk_id` on an evidence item
if one appears, so this is a one-line change later.

### (2) `ABOUT` attribution

`ABOUT` needs to know which claim or evidence a reason concerns, and a
`{code, message}` reason does not carry that. I attribute structurally from
the signal details, never by parsing message text:

* `UNSUPPORTED_CLAIM` → `ABOUT` each non-`SUPPORTED` Claim
* `CONTRADICTION`, `STALE_EVIDENCE` → `ABOUT` each Evidence in an eligible conflict
* anything else → `BECAUSE` only, no `ABOUT`

**Aaradhya: is this the attribution you want, or should `Reason` carry the
target explicitly in the contract?** An explicit field would be more robust
than my code-based mapping.

### (3) Where the sink gets called

The brief says to inspect where the `GraphSink` call was placed; there is no
such call. The minimal interface change I propose — **for Aaradhya to make,
not me** — is one line after the response is built and after the SQLite audit
write, never before:

```python
# app/core/evaluator.py, at the very end of evaluate(), after the response exists
safe_write_trace(self.graph_sink, trace)   # returns bool, never raises
```

with `graph_sink: GraphSink | None = None` on `Evaluator.__init__`, defaulting
to `None`. `safe_write_trace` swallows and logs everything, so the call cannot
affect the decision even if Neo4j is down, the trace is malformed, or the
driver raises. I have left this unwired.

## 5. Safety properties, and how each is tested

| Rule | Test |
| --- | --- |
| Neo4j never in the decision path | not wired in; `safe_write_trace` returns bool and never raises |
| Trace usable with no Neo4j | `test_decision_and_trace_survive_an_unavailable_neo4j` |
| Failed write changes nothing | `test_a_failed_transaction_writes_nothing`, `test_a_driver_exception_is_logged_and_swallowed` |
| Repeated writes do not duplicate | `test_repeating_a_trace_creates_no_duplicates`, `test_a_repeated_benchmark_run_keeps_one_decision` |
| Previews ≤ 120 chars | `test_every_stored_preview_is_within_the_cap`, `test_a_long_passage_is_truncated_not_stored_whole` |
| Full document text never stored | `test_full_document_text_is_refused_even_if_a_trace_offers_it` |
| Malformed traces handled safely | 11 parametrised cases + 4 non-mapping cases |

On Cypher safety: property names and values are always parameters. The only
things interpolated into a query string are node labels and relationship
types, because Cypher cannot parameterise those — and they come from the
closed allow-lists in `contract.py`, never from trace content. A label or
relationship type not on the list fails the write before it reaches the
database.

## 6. Measured latency

Conditions: Windows 11, Python 3.12.6, torch 2.8.0+cpu, single process, no
concurrency. 3 evidence passages, 2 answer claims. Harness:
`bench_decision_graph.py`, run on this branch and on `origin/main` @ `18cd3d3`
in a separate git worktree with the identical script.

**Added work, isolated (fake NLI runner — 300 runs, 30 warm-up, medians):**

| Step | `origin/main` | this branch | added |
| --- | --- | --- | --- |
| entailment signal | 0.0273 ms | 0.0354 ms | **+0.008 ms** |
| contradiction signal | 0.3390 ms | 0.3567 ms | **+0.018 ms** |
| trace construction | — | 0.0212 ms | **+0.021 ms** |
| Cypher construction | — | 0.0884 ms | +0.088 ms |
| graph write, **fake driver** | — | 0.1000 ms | +0.100 ms |

The NLI runner is faked here on purpose: a real forward pass costs tens of
milliseconds and would bury the added Python work. These are therefore *not*
end-to-end figures.

**End-to-end, real models, distinct requests (25 runs per repetition, 3 repetitions):**

| | medians across repetitions | spread |
| --- | --- | --- |
| `origin/main` | 46.81, 46.93, 46.34 ms | 0.59 ms |
| this branch | 47.65, 45.10, 46.12 ms | 2.55 ms |

**The end-to-end difference is below this harness's noise floor.** The ranges
overlap and the within-branch spread (up to 2.55 ms) is larger than any
apparent difference, which is consistent with the directly measured added
work of ~0.026 ms. I am claiming no end-to-end regression and no improvement.

Cold start is ~24 s on both branches, dominated by model load, and unchanged.

### Limitations, stated plainly

* **The fake-driver figure is not production Neo4j latency.** It measures
  Cypher construction and the Python call path only. A real number needs a
  real server and belongs to Shatakshi's setup work.
* A repeated *identical* request measures 0.06 ms because
  `EvidenceIntelligence` memoises the latest `(query, answer, evidence)`
  triple. That is a real property of the system but is not an evaluation, so
  the end-to-end figures above use a distinct query per run.
* Single machine, no concurrency, one evidence size.

## 7. Defect found, deliberately not fixed

`_check_answer_vs_evidence` and `_check_evidence_vs_evidence` call
`find_numeric_conflicts` / `find_date_conflicts` from *inside* their
`zip(..., preds)` loop. When the NLI model is unavailable, `preds` is `[]`,
the zip is empty, and the pure-Python numeric and date rules — which need no
model at all — never run. The signal reports `0.0`, i.e. "no contradiction",
on a degraded model.

This is on `origin/main` and predates the add-on. I have **not** fixed it
here, because moving it changes the contradiction score on the degraded path
and therefore changes decisions, which sections 4 and 5 of the brief rule out
for this piece of work. It is asserted as-is in
`test_broken_nli_currently_disables_rule_based_conflicts_too`, alongside a
check that the rule itself detects 18 vs 12 fine on its own.

The fix is to hoist the two rule calls out of the prediction loop. It wants
its own branch and a policy conversation, since it would make some degraded
evaluations escalate that currently answer.

Also noted: `app/schemas.py` defines `Decision`, `RecommendedAction`,
`ReasonCode` and `ClaimStatus` twice (lines 8–37 and 39–68). Harmless, since
the second definition simply replaces the first, but worth a tidy-up in
whichever PR next touches that file. Not this one.

## 8. Open items

* **Aaradhya** — approve or amend node identity (§4.1), `ABOUT` attribution
  (§4.2); make the one-line sink call (§4.3); confirm `headline` wording stays
  in the explanation templates rather than in my builder.
* **Shatakshi** — confirm the global `Document` identity supports the insight
  queries; add `neo4j` to `requirements.txt` with the schema/constraints; and
  measure real-server write latency, which I cannot.
* **Both** — once the contract is agreed, `app/graph/trace_builder.py` should
  either move under Aaradhya's ownership or be deleted in favour of his
  implementation. It exists to make the mapping concrete and testable, not to
  pre-empt him.
