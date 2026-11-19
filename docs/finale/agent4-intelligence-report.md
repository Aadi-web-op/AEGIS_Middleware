# Agent 4: Cross-Decision Intelligence Report

Scope: `app/intelligence/**`, `tests/intelligence/**`. I left `app/graph/insights.py` and
`tests/graph/test_insights.py` unchanged; their 8 tests still pass.

## Capabilities (`/v1/intelligence`, CONTRACTS.md §5)

| Endpoint | Source | Neo4j down |
|---|---|---|
| `GET /summary` | audit log (distributions) + graph (findings) | 200, `graph:{available:false, reason}`, `findings:[]`, audit parts intact |
| `GET /documents` | graph | 503 `{detail, graph_available:false}` |
| `GET /contradictions` | graph | 503 |
| `GET /stale-usage` | graph | 503 |
| `GET /knowledge-gaps` | graph (+ audit queries for the topic fallback) | 503 |
| `GET /blast-radius?doc_id=` | graph | 503; 422 if `doc_id` is missing; 404 if the document is unknown |
| `GET /trends?bucket=day\|hour` | audit log | still works; 503 only if the audit DB itself can't be read |

Every endpoint accepts `request_prefix` to scope the analysis. Audit-backed parts honour it too
(SQLite `LIKE` is escaped, so `_` and `%` match literally). Additive fields beyond the contract:

- On findings: `attribution` (`direct` or `considered`) and `details`.
- On `/summary`: `data.needed`, `audit`, `excluded` and `scope`.
- `excluded` is also on `/stale-usage` and `/knowledge-gaps`.

## Finding kinds and thresholds (all in `app/intelligence/rules.py`)

These rules hold for every kind:

- **Minimum data:** a finding needs at least 2 distinct decisions.
- **Traceability:** every finding lists the decisions it rests on (`request_ids`, sorted, at most 20) and the query that produced it (`query`, the `QUERIES` key, `+`-joined when two are combined).
- **Real counts:** the metric's numerator and denominator are counts of stored rows.
- **Sufficiency:** `/summary.data.sufficient` is false below 5 graph decisions, and `message` says "N more are needed".

| kind | metric | finding if | severity |
|---|---|---|---|
| `unsupported_source` (direct) | contradicted_claim_rate | ≥2 decisions with a claim CONTRADICTED_BY the document's evidence | high if ≥3 decisions or rate ≥0.5, else medium |
| `unsupported_source` (considered) | unsupported_claim_rate | ≥2 decisions with non-supported claims that retrieved the document, and rate ≥0.5 | medium if rate ≥0.75 and ≥3 decisions, else low. Never above medium; the text says it is co-occurrence only |
| `contradiction_hotspot` | conflict_rate (conflicting decisions / decisions retrieving both) | ≥2 decisions | high if ≥3 decisions, or a numeric/date conflict in an ANSWER/CAVEAT decision; else medium |
| `stale_version_in_use` | stale_usage_rate | ≥2 dated decisions retrieved the older version after the cutoff | high if ≥3, or any shown answer relied on the old version; else medium |
| `knowledge_gap` | gap_rate (ABSTAIN+ESCALATE / topic decisions) | topic has ≥2 decisions, ≥2 gap decisions and rate ≥0.5 | high if rate ≥0.8 over ≥3 decisions; else medium |
| `escalation_root_cause` | escalation_share | ≥2 escalations whose Reason is ABOUT the document's evidence (directly, or via a claim it contradicts) | high if ≥3 or share ≥0.5; else medium |
| `uncertainty_source` | reason_code_share among ABSTAIN/ESCALATE | ≥2 decisions and share ≥0.3 | high if share ≥0.6; else medium |

Missing data is never guessed. A rule that needs a field a decision lacks skips that decision
and reports it under `excluded`:

- `created_at` for stale usage. The cutoff for stale usage is the newer document's `date`, or failing that the first dated retrieval of the newer document.
- `topic` for knowledge gaps. If it is missing, `topic_key` is applied to the query in the audit log; if that is missing too, the decision is excluded.

Older stored traces have no SUPERSEDES edges. For those, supersession is worked out from
same-source documents with comparable date or version (`supersedes_basis` says which applied).

## Bugs fixed in my files

1. **All graph reads failed against real Neo4j (critical).** `queries.run` passed a
   `neo4j.Query(..., timeout=)` object to `tx.run` inside `execute_read`. Driver 6.4.1 raises
   `TypeError: Query object is only supported for session.run` for this, so every real query
   became `GraphUnavailable`. The query is now passed as a plain string, and the timeout is set
   with `neo4j.unit_of_work(timeout=5)`. The fake driver now rejects non-string queries the same
   way the real driver does, so a regression would fail the tests.
2. **Conflicts blamed on the wrong decisions.** With global chunk ids, `conflict_edges` gave a
   conflict to every decision that RETRIEVED one of the two passages. It now requires the
   decision to have retrieved both.
3. **Slow, leaky failures.** The 503 `detail` and `/summary` `graph.reason` included the raw
   driver exception text (host and port), and every poll paid the driver's retry window while
   Neo4j was down. Connection failures now give a fixed message and set the same
   `app.state.graph_down_until` 10-second marker that `/v1/graph` uses, so later requests fail
   fast. Query errors that are not connection failures still return 503 but don't set the marker.
4. **`graph_decisions` was capped.** It came from `len(decision_overview)`, which has a 5000-row
   limit. It now uses the exact `graph_decision_count` query.
5. **Blast radius could return a false 404.** The document lookup scanned the first 5000
   documents. It now uses a direct `document_by_id` query.
6. **`/summary` could return 500 on unexpected stored data.** That could happen with rows that
   have a null id, or with non-JSON Neo4j temporal values. Rows missing the keys a rule groups on
   are now skipped. Temporal values are converted to ISO strings. Any other derivation error now
   gives 200 with `graph.analysis_error` and is logged.
7. **`supported_by_doc` miscounted.** It counted distinct claim texts rather than distinct claims.

All Cypher is static text in `queries.QUERIES` and takes only the parameters `$prefix`,
`$limit` and `$doc_id`. A test enforces this, and also that no Cypher is built inside
`service.py`.

## Tests

```
export USE_TF=0 TRANSFORMERS_NO_TF=1
python -m pytest tests/intelligence tests/graph/test_insights.py -q
111 passed, 1 skipped
```

The intelligence suite has 104 tests: 103 passed and 1 skipped. `test_insights.py` has 8, all passed.

- `test_rules.py`: every threshold and severity boundary, plus stable finding ids.
- `test_service.py`: canned rows go through each builder and finding function. Covers the boundary at 1 versus 2 decisions, cap and sort of `request_ids`, sufficiency at 0, 4, 5 and 9 decisions, the stale fallbacks (no edges, no date, no `created_at`), the topic fallback from audit queries, rows with null ids, and the service with a fake driver (prefix passed as a parameter, failure midway, malformed rows, unreadable audit DB).
- `test_queries.py`: parameterisation, prefix scoping, row limits, the plain-string-in-`execute_read` regression, the timeout attached to the unit of work, and temporal values converted to strings.
- `test_routes.py`: the real `create_app` with `TestClient`. Covers no driver, unreachable driver (no internals leaked), the fail-fast window and its expiry, contract field names, insufficient data, `request_prefix`, trends by day and by hour, and blast-radius 422 and 404.
- `test_live_neo4j.py`: an offline check that the scenario traces are accepted by the real `Neo4jGraphSink.build_statements`. It also has the opt-in live test, which needs `NEO4J_URI`.
  - The live test writes 8 traces through the real sink under `itest-<uuid>-`.
  - It asserts the contradiction, knowledge-gap, stale-version, unsupported-source and root-cause findings refer only to those ids, and checks blast radius and documents.
  - It then deletes only the nodes that contain the marker and asserts none are left.

## Limitations

- **The live test has not been run.** Neo4j was not reachable during this session (nothing was listening on 7687 or 7474, and Docker Desktop was stopped). The Cypher has only been checked by review and through fakes. To run it: `NEO4J_URI=bolt://localhost:7687 python -m pytest tests/intelligence/test_live_neo4j.py`.
- **Considered attribution is co-occurrence, not cause.** Unsupported claims have no edge to a document, so these findings are capped at medium and worded that way.
- **Stale usage includes decisions that retrieved both versions.** A decision that retrieved both the old and the new version after the cutoff still counts as stale.
- **Topics are keyword keys, not semantic clusters.**
- **Row caps.** Each query returns at most 5000 rows, which bounds the worst case at demo scale. Above that, findings cover a truncated set, but the summary decision count stays exact.
- **One slow request when Neo4j goes down.** The first request after Neo4j becomes unreachable still waits for the driver's timeout (about 3 to 5 seconds) before the 10-second fail-fast window starts.
