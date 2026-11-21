# Agent 4 — Cross-Decision Intelligence: Plan (Phase 1)

Status: plan only, nothing implemented yet. Builds against `CONTRACTS.md` §3 and §5.

## 0. What I found

* Live Neo4j (old seed): 21 Decision, 19 Claim, 23 Evidence, 17 Document, 61 Reason;
  edges FROM/HAS_CLAIM/SUPPORTED_BY/CONTRADICTED_BY/CONFLICTS_WITH/BECAUSE/ABOUT.
  No `created_at`, `topic`, `query_preview`, `RETRIEVED`, and **zero SUPERSEDES**.
  Documents are mostly unversioned (`doc:policy_a.txt`).
* Evidence ids are request-scoped (`<request_id>:evidence:<i>`) unless a `chunk_id`
  is supplied; Document ids are global. CONFLICTS_WITH is only drawn within one trace.
  SUPERSEDES is currently only drawn on a *version* conflict inside one trace.
* `Evaluator.evaluate()` generates `request_id = uuid4().hex` internally; there is
  no override. `/v1/evaluate` does log to the audit DB.
* `app/graph/topics.py` does not exist yet (Agent 3).
* Existing `/v1/insights/*` (main.py, Neo4j) and `/v1/insights/*` (SQLite router)
  stay untouched; `tests/graph/test_insights.py` (8 tests) pins the five query
  functions and their return shapes, so `app/graph/insights.py` keeps its API.

## 1. Module layout (`app/intelligence/`)

| File | Content |
|---|---|
| `rules.py` | ALL thresholds + severity rules as documented constants/functions (single source of truth). |
| `models.py` | pydantic `Metric`, `Subject`, `Finding`, `DataSufficiency`, `SummaryResponse`, row models for tables. |
| `queries.py` | Named, parameterised Cypher strings (`QUERIES: dict[name, str]`) + thin runners reusing `app.graph.insights._run_query`. Every query takes `$prefix` (request_id STARTS WITH, default `""`) and `$limit`. |
| `audit.py` | Read-only SQLite helpers on `audit_logs` (distribution, reasons, trends, query text by request_id). Uses `default_audit_db_path()` / `app.state.audit_db_path`. |
| `service.py` | Pure functions: rows → `Finding`s (thresholds, severity, explanation text from numbers, stable id = sha1(kind+subject ids)[:16]). No I/O, so unit-testable from canned rows. Plus `IntelligenceService(driver, audit_db)` orchestration with per-section graceful degradation. |
| `routes.py` | `APIRouter(prefix="/v1/intelligence")`. Only change to `main.py`: `from app.intelligence import intelligence_router` + `app.include_router(intelligence_router)`. Driver from `request.app.state.neo4j_driver`. |

Common query param on all endpoints: `request_prefix` (optional, e.g. `demo-`) to scope
analysis; `limit`.

### "Decision → evidence it considered" (degradation core)
Agent 3's `RETRIEVED` edge is preferred; old data lacks it. A reusable sub-pattern
unions three sources so queries work on both models:
```cypher
CALL { WITH d MATCH (d)-[:RETRIEVED]->(e:Evidence) RETURN e
       UNION WITH d MATCH (d)-[:HAS_CLAIM]->(:Claim)-[:SUPPORTED_BY|CONTRADICTED_BY]->(e:Evidence) RETURN e
       UNION WITH d MATCH (e:Evidence) WHERE e.id STARTS WITH d.request_id + ':evidence:' RETURN e }
```
(`Evidence.id` has a uniqueness constraint → STARTS WITH is index-backed.)
Timestamps: `coalesce(d.created_at, null)`; anything time-dependent says so in the
explanation when ordering is unknown. Topic: `d.topic`, falling back in Python to
`topic_key(audit.query)` (via `app.graph.topics` if present, else a local identical-
contract fallback) joined on request_id; decisions with neither are excluded and
counted in a `skipped_without_topic` note.

## 2. Finding kinds

All findings require ≥2 distinct decisions (`MIN_DECISIONS_FOR_FINDING = 2`) and carry
`metric{name,value,numerator,denominator}`, `subjects`, `request_ids` (≤20, sorted),
`query` (the QUERIES key). Severity is computed only in `rules.py`:

| kind | Cypher sketch | metric | finding if | severity |
|---|---|---|---|---|
| `unsupported_source` | per Document: claims "touching" it = claims with SUPPORTED_BY/CONTRADICTED_BY→Evidence-FROM→doc **plus** claims of decisions that considered doc's evidence (pattern above). `numerator` = those with `status <> 'SUPPORTED'`; split `contradicted_direct` (CONTRADICTED_BY into this doc) in the row. | `unsupported_claim_rate` | ≥2 decisions with a non-supported claim AND rate ≥ 0.34 | high: rate ≥0.6 and ≥3 decisions, or ≥2 decisions with *direct* CONTRADICTED_BY; medium: rate ≥0.4; else low |
| `contradiction_hotspot` | `(e1)-[c:CONFLICTS_WITH]->(e2)`, both FROM docs, canonical pair `d1.id<d2.id`, decision via `e.id` prefix/RETRIEVED; group by pair: `count(DISTINCT dec)`, `collect(DISTINCT c.kind)`, sample `value_a/value_b`. | `conflicting_decisions` (num) / decisions that considered both docs (den) | ≥2 decisions | high: ≥3 decisions or (numeric/date kind and ≥1 of them ANSWER/CAVEAT — conflict reached a user); medium: 2 decisions; low: none (below threshold not emitted) |
| `stale_version_in_use` | SUPERSEDES pairs; **fallback when edges are absent**: Python groups Documents by `source` and orders with the same rule as trace_builder (`_supersedes_order`: date, else comparable version). Cutoff = `newer.date` if set, else min `created_at` of decisions considering newer. Count decisions considering *older* with `created_at > cutoff` (unknown created_at → counted, flagged `ordering:"assumed"`). | `stale_usage_rate` = stale decisions / decisions considering either version | ≥2 stale decisions | high: ≥3, or any stale decision ended ANSWER/CAVEAT while relying (SUPPORTED_BY) on older; medium: 2 |
| `knowledge_gap` | per topic: `count(d)`, `sum(decision IN ['ABSTAIN','ESCALATE'])`, sample `query_preview`s. | `gap_rate` = abstain+escalate / topic decisions | topic ≥2 decisions AND ≥2 gap decisions AND rate ≥0.5 | high: rate ≥0.8 and ≥3 decisions; medium: rate ≥0.5; |
| `escalation_root_cause` | `(d:Decision {decision:'ESCALATE'})-[:BECAUSE]->(r)-[:ABOUT]->(e:Evidence)-[:FROM]->(doc)` UNION `…-[:ABOUT]->(:Claim)-[:CONTRADICTED_BY]->(e)-[:FROM]->(doc)`; group doc+code. | `escalation_share` = escalations rooted in doc / all escalations | ≥2 escalations | high: ≥3 or share ≥0.5; medium: 2 |
| `uncertainty_source` | per reason code among ESCALATE/ABSTAIN decisions: `count(DISTINCT d)`. | `code_share` = decisions with code / all ESCALATE+ABSTAIN | ≥2 decisions and share ≥0.3 | high: share ≥0.6; medium: ≥0.3 |

Explanations are f-strings over the numbers only, e.g. *"4 of 6 claims (67%) in 3
decisions that used leave_policy.pdf@v1 were not supported by the evidence."*
Ordering of findings: severity, then numerator desc, then id (deterministic).

## 3. Endpoints → queries

| Endpoint | Source | Notes |
|---|---|---|
| `GET /summary` | audit: `total_decisions`, `decision_distribution`, `reason_distribution`; graph: `graph_decisions` (`MATCH (d:Decision) WHERE d.request_id STARTS WITH $prefix RETURN count(d)`), all six finding derivations. | Always 200. `data.min_required=5`; `sufficient = graph_decisions ≥ 5`; `message` "N more graph decisions needed…". Graph failure → `graph:{available:false, reason}`, `findings:[]`, audit parts intact. Findings still computed when insufficient but message says so (contract: findings need ≥2 decisions regardless). |
| `GET /documents` | `document_reliability` query (per doc: decisions, supported/unsupported claims, conflicts, escalations, abstains, superseded_by) | contract item fields exactly; 503 if graph down |
| `GET /contradictions` | `contradiction_pairs` | items `{doc_a, doc_b, source_a, source_b, conflict_count, decision_count, kinds, sample_values, request_ids}` |
| `GET /stale-usage` | `supersedes_pairs` + `document_usage` (+ Python fallback ordering) | items `{older_doc_id, newer_doc_id, cutoff, ordering, stale_decisions, request_ids, relied_request_ids}` |
| `GET /knowledge-gaps` | `topic_outcomes` | items `{topic, decisions, abstains, escalations, gap_rate, sample_queries, request_ids}`; topics with <2 decisions dropped |
| `GET /blast-radius?doc_id=` | `blast_radius` | `{doc_id, exists, relied_on:{count, decisions:[{request_id, decision, created_at, claims}]}, retrieved_only:{count, decisions}}`; 404 if doc unknown, 422 if missing param |
| `GET /trends?bucket=day\|hour` | audit SQLite `substr(timestamp,1,10|13)` | `{bucket, items:[{bucket, total, ANSWER, CAVEAT, ESCALATE, ABSTAIN}]}`; 503 only if the audit DB itself is unreadable |

Graph-only endpoints return 503 `{"detail": …, "graph_available": false}` (same shape as
§4) when driver is None or a query raises `ServiceUnavailable`/`SessionExpired`/OSError.

## 4. Dependency on Agent 3 and fallbacks

| Field | Used for | Fallback when absent |
|---|---|---|
| `Decision.created_at` | stale cutoff, ordering, blast-radius dates | Document.date as cutoff; otherwise counted with `ordering:"assumed"` and explanation states it |
| `Decision.topic` | knowledge gaps | `topic_key(audit.query)` by request_id; else excluded + counted |
| `Decision.query_preview` | sample queries | audit query (sanitised already) truncated 160 |
| `RETRIEVED` | "considered" set, blast-radius retrieved_only | claim edges ∪ request-scoped evidence id prefix |
| cross-trace `SUPERSEDES` | stale usage | Python ordering of same-`source` Documents (date, else comparable version) |

I will not edit `app/graph/**` (except `insights.py`, which I keep API-stable).

## 5. Demo dataset — `scripts/seed_intelligence_demo.py`

* Builds `Evaluator(default_signals(), graph_sink=…)` with the **real** `Neo4jGraphSink`
  and logs each response with `AuditLogger().log_evaluation(req, resp)`.
* `demo-` ids: the evaluator assigns uuid ids, so the script wraps the real sink in a
  `_DemoIdSink` that rewrites the trace's request_id (`<uuid>` → `demo-<slug>`) in the
  Decision and every `<uuid>:…` node id/edge endpoint before delegating, and the audit
  row uses `resp.model_copy(update={"request_id": demo_id})`. Trace content is otherwise
  untouched evaluator output. (Cleaner alternative, needs Agent 2/lead: optional
  `request_id` kwarg on `Evaluator.evaluate`; I will use it if it appears.) Calls
  `sink.flush(timeout)` if Agent 3's async writer exposes it.
* Fictional corpus "Northwind Ltd": `leave_policy.pdf@v1` (2025-01-10, 20 days),
  `leave_policy.pdf@v2` (2026-03-01, 25 days), `travel_policy.pdf@v3` ($75/day meals),
  `finance_circular_2026-04.pdf@v1` (cap $50/day), `it_security_policy.pdf@v4`,
  `expense_handbook.pdf@v2`, `remote_work_policy.pdf@v1`.
* 13 cases: 3 leave questions retrieving v1+v2 (version conflict), 2 retrieving only v1
  (stale; one answers "20 days"), 1 v2-only clean; 3 meal-allowance questions retrieving
  travel+circular (numeric conflict → escalate/caveat expected); 3 "contractor equity
  vesting" questions (no coverage: empty / unrelated evidence → ABSTAIN), sharing one
  topic key; 3 clean supported cases (password rotation, hotel approval, remote days).
* Prints the actual decision per case next to the intended one and warns on mismatch;
  never forces an outcome. `--reset` deletes `Decision` with `request_id STARTS WITH
  'demo-'`, their `demo-…` Claim/Evidence/Reason nodes, then Documents left with no
  FROM edge **and** whose id is in the demo corpus list; deletes `demo-%` audit rows.
  `--reset-only` for cleanup without reseeding. Expected run ≈1 min (model load).

## 6. Tests (`tests/intelligence/`)

* `test_rules.py` / `test_service.py`: canned rows → findings: below-threshold (1
  decision) emits nothing; boundary at 2; severity boundaries per kind; stable ids;
  request_ids capped/sorted; explanation contains numerator/denominator; empty rows;
  sufficiency message (0, 4, 5 decisions); stale fallback ordering without SUPERSEDES
  and without created_at; topic fallback from audit queries.
* `test_routes.py` (TestClient, `create_app(evaluator=stub, neo4j_driver=…)` with
  temp audit DB): driver None → `/summary` 200 with `graph.available false` and audit
  distribution; graph-only endpoints 503 with `graph_available:false`; driver whose
  session raises → same; canned driver → contract field names exactly; trends day/hour;
  blast-radius 422/404.
* `test_live_neo4j.py` (skip unless `NEO4J_URI`): write `itest-<uuid>-n` traces via
  `Neo4jGraphSink` + `build_trace` (2 docs conflicting numerically in 2 decisions, 2
  abstains), run service with `request_prefix=itest-<uuid>`, assert findings reference
  those ids; teardown deletes only `itest-<uuid>` nodes and itest-only Documents.
* Keep `tests/graph/test_insights.py` green (no API change to insights.py; possibly add
  `coalesce`/robustness only).

## 7. Open points for the lead

1. Optional `request_id` override on `Evaluator.evaluate` would remove the id-rewriting
   wrapper in the seeder (Agent 2's file).
2. Unsupported claims carry no edge to a document; attribution to "documents the
   decision considered" is a documented heuristic (flagged in the finding row as
   `attribution:"considered"` vs `"direct"`).
3. Neo4j driver default connection timeout may make `/summary` slow when the server is
   down; main.py constructs the driver (lead/Agent 3) — suggest a short
   `connection_timeout`.
