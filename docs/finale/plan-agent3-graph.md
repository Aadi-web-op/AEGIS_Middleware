# Agent 3 (Graph) — Phase 1 plan

Scope: contract §3 (graph model), §4 (graph read API), non-blocking writes,
rebuildability, seeding. No implementation yet.

## 0. Findings from investigation

* Live Neo4j: 21 Decision (12 `bench-*`, 9 uuid from live API runs),
  23 Evidence, 17 Document, 19 Claim, 61 Reason; rels FROM/HAS_CLAIM/
  SUPPORTED_BY/CONTRADICTED_BY/CONFLICTS_WITH/BECAUSE/ABOUT. **0 SUPERSEDES,
  0 RETRIEVED**, no `created_at`/`topic` on any Decision. Neo4j 5.26 supports
  list comparison (`[1,2] < [1,3]` → true) and `CALL (x) {}` / `COUNT {}`.
* `audit.db` has 266 rows and **0 with `response_json`** (column exists now,
  added by the lead). So today the "rebuildable projection of SQLite" claim
  is false for every existing row; it becomes true only for evaluations
  logged from now on. `rebuild_graph.py` will report skipped rows.
* `evaluate()` calls `safe_write_trace` synchronously; the Neo4j driver is
  built with defaults (`max_transaction_retry_time` 30 s), so a dead server
  can stall a decision for ~30 s.
* The sink caps every `*_preview` key at 120 chars — `query_preview` (≤160)
  needs its own cap.
* Same-source rule caveat: the benchmark leave docs are *different sources*
  (`leave_policy_v2_2024.pdf` vs `leave_circular_v3_2026.pdf`), so the new
  same-source derivation will not link them. The existing within-trace rule
  (SUPERSEDES from a `kind=version` conflict, any source) is kept, so those
  still get an edge when the contradiction signal reports a version conflict.
* `scripts/seed_neo4j.py` runs `evaluate()` and then re-runs every signal a
  second time to get details (double model cost) and hand-writes headlines.

## 1. Graph model changes

`app/graph/topics.py` (new): `topic_key(query) -> str`. Lowercase →
tokens `[a-z0-9]+` → drop stopwords (built-in English list + question words
like how/what/many/does), tokens <3 chars, pure numbers → light plural strip
(`days`→`day` when len>4 and not `ss`) → dedupe → keep the 3 longest (ties
alphabetical) → sort alphabetically → join with `|`. Example: "How many
annual leave days do I get?" → `annual|day|leave`. Empty → `""` (Agent 4
should skip empty topics). Pure and deterministic; unit-tested.

`build_trace(...)` new kwargs (all optional, so existing callers/tests work):
`query: str|None`, `created_at: str|None`, `degraded: bool|None`.
Decision node gains `created_at`, `query_preview`
(`sanitize_secrets` → collapse whitespace → ≤160), `topic`, `degraded`,
and always `trace_version: "2"`. Top-level trace also gets `trace_version`.

* `RETRIEVED` edge Decision→Evidence for every evidence item
  (`evidence_index` prop).
* SUPERSEDES within trace: existing version-conflict rule **plus** every pair
  of Documents in the trace with the same `source` and an order from
  `_supersedes_order` (date first, then same-arity numeric version). Deduped.
* Document nodes gain sort keys used by the cross-trace linker:
  `date_key` (`YYYY-MM-DD` if parseable, else absent) and `version_key`
  (list of ints from the version label, absent if none). Same logic as
  `_supersedes_order`, so Python and Cypher cannot disagree.

`contract.py`: add `RETRIEVED` to `RELATIONSHIP_TYPES`, `TRACE_VERSION="2"`,
`QUERY_PREVIEW_CHARS=160`. Sink caps `query_preview` at 160 (and re-applies
`sanitize_secrets` — defence in depth), every other preview stays 120.

`Decision.created_at` is **first-write-wins**:
`SET n += $props SET n.created_at = coalesce(n.created_at, $created_at)`
(created_at removed from `$props`), so re-seeding/replaying never moves a
decision in time.

Evaluator call sites (my two blocks only, small Edit): pass
`query=request.query`, `created_at=<UTC ISO now>`,
`degraded=bool(score_result.unavailable)` (no-evidence path: `False`).

Schema (`schema.py` + `schema.cypher`, all `IF NOT EXISTS`): add indexes
`decision_created_at (Decision.created_at)`, `decision_topic
(Decision.topic)`, `evidence_source (Evidence.source)`. Constraints unchanged.

## 2. Cross-trace SUPERSEDES linking (post-write, same transaction)

After the node/edge MERGEs, the sink appends one parameterised statement
scoped to the sources in this trace (no interpolation at all):

```cypher
UNWIND $sources AS src
MATCH (a:Document {source: src})
MATCH (b:Document {source: src})
WHERE a.id <> b.id AND (
  (a.date_key IS NOT NULL AND b.date_key IS NOT NULL AND a.date_key > b.date_key)
  OR (
    (a.date_key IS NULL OR b.date_key IS NULL OR a.date_key = b.date_key)
    AND a.version_key IS NOT NULL AND b.version_key IS NOT NULL
    AND size(a.version_key) = size(b.version_key)
    AND a.version_key > b.version_key))
MERGE (a)-[r:SUPERSEDES]->(b)
SET r.derived = coalesce(r.derived, 'same_source_order')
```

Only emitted when the trace has ≥1 Document with a source. Controlled by
`Neo4jGraphSink(..., link_supersedes=True)`.

## 3. Non-blocking writes — `app/graph/async_sink.py` (new)

`AsyncGraphSink(inner, max_queue=256, overflow="drop_oldest")`:
* `write_trace(trace)` deep-copies the trace, `put_nowait` onto a bounded
  `queue.Queue`; when full, drops the oldest (or the new one with
  `overflow="drop_new"`) and increments `dropped`. Returns True (accepted).
  Never raises; never blocks the caller.
* One daemon worker thread (started lazily) calls `safe_write_trace(inner, t)`
  and updates `written` / `failed` / `last_error` (from `inner.last_error`
  when present) / `last_success_at` under a lock.
* `stats()` → `{written, failed, dropped, pending, last_error,
  last_success_at, queue_capacity, running}`; `pending` = queued + in-flight.
* `flush(timeout) -> bool` waits on a Condition until pending==0.
* `close(timeout=5)` stops the worker (sentinel), joins, closes inner;
  registered with `atexit` (daemon thread means no hang regardless).
* Dropped traces are recoverable via `rebuild_graph.py` (projection).
`safe_write_trace` and `Neo4jGraphSink` stay synchronous, so all existing
synchronous tests are untouched.

`app/graph/driver.py` (new): `make_driver(uri, user, password)` with
`connection_timeout=3`, `connection_acquisition_timeout=5`,
`max_transaction_retry_time=5`. Used by `Neo4jGraphSink.from_uri`, seed and
rebuild scripts.

`app/main.py` (allowed edits): sink construction becomes
`AsyncGraphSink(Neo4jGraphSink(driver))` in both places; add
`include_router(graph_router)` + import. **Request:** permission to change the
one line in `_init_neo4j_driver` from `GraphDatabase.driver(...)` to
`make_driver(...)` (short timeouts) — it's driver construction, adjacent to
sink construction. If refused, I'll leave it and only the scripts benefit.

## 4. Graph read API — `app/graph/reader.py` + `app/graph/routes.py`

`GraphReader(driver, database=None)`; every query is a module-level constant
string with `$params`; labels/types only come from contract allow-lists
(also passed as `$rel_types` and filtered again in Python). Records →
`{"id","type","label","props"}` / `{"id":"from|TYPE|to|kind", ...}`.
Node id = `request_id` for Decision, `id` otherwise. Display `label`:
Decision `"ESCALATE · 0.41"`, Claim text[:60]…, Evidence `source#index` or
preview[:60], Document `source@version`, Reason `code`.
Non-JSON values (Neo4j temporal etc.) → `str`.

* `status()`: one query `RETURN COUNT{(:Decision)} AS Decision, …` and one
  for each allow-listed rel type (built from constants). Route always 200:
  `{configured, connected, counts, relationships, writer}`; writer stats from
  `app.state.evaluator.graph_sink.stats()` when available, else zeros/None.
* `list_decisions(limit, decision, source)`: `MATCH (d:Decision) WHERE
  ($decision IS NULL OR d.decision=$decision) AND ($source IS NULL OR EXISTS
  {(d)-[:RETRIEVED]->(:Evidence)-[:FROM]->(:Document {source:$source})} OR
  EXISTS {(d)-[:HAS_CLAIM]->(:Claim)-[:SUPPORTED_BY|CONTRADICTED_BY]->
  (:Evidence)-[:FROM]->(:Document {source:$source})})`, `ORDER BY
  d.created_at IS NULL, d.created_at DESC, d.request_id LIMIT $limit`, counts
  via `COUNT{}` subqueries, `reason_codes` via pattern comprehension.
  `limit` 1..500 (FastAPI `Query`), `decision` validated against DECISIONS.
* `decision_subgraph(rid)`: `MATCH (d:Decision {request_id:$rid})`, `CALL (d)`
  subqueries collecting claims (HAS_CLAIM), evidence (RETRIEVED ∪ claim
  SUPPORTED_BY/CONTRADICTED_BY ∪ reason ABOUT — legacy decisions have no
  RETRIEVED), reasons (BECAUSE), documents (evidence FROM); then all
  relationships among that node set with `type(r) IN $rel_types`
  (so CONFLICTS_WITH and SUPERSEDES between its docs are included).
  Returns `{decision:{summary}, nodes, edges}`; 404 when absent.
* `list_documents(limit)`: per Document `decision_count`,
  `supported_claim_count`, `contradicted_claim_count`, `conflict_count`
  (distinct CONFLICTS_WITH touching its evidence), `superseded_by`,
  `supersedes` (pattern comprehensions). Ordered by source, version.
* `neighbors(node_id, limit)`: node lookup via `CALL { MATCH (n:Decision
  {request_id:$id}) RETURN n UNION MATCH (n:Claim {id:$id}) RETURN n UNION … }`
  (each branch uses that label's unique index), then `MATCH (n)-[r]-(m) WHERE
  type(r) IN $rel_types RETURN … LIMIT $limit`. 404 when node absent.
  Path param uses `{node_id:path}` so ids containing `/` or `:` work.

Errors: no driver → 503 `{"detail": "...", "graph_available": false}`;
any driver exception (ServiceUnavailable, auth, timeout) → same 503 (logged,
no internals leaked). Status endpoint catches and reports `connected:false`.

## 5. Rebuild — `scripts/rebuild_graph.py` (new)

`python -m scripts.rebuild_graph [--db audit.db] [--uri …] [--limit N]
[--dry-run]`: if `audit_logs.response_json` column missing → exit 0 with a
message; for each row with it, parse JSON → `trace`; skip rows with no trace
or `validate_trace` failure (counted); fill missing `created_at` from the row
`timestamp` and `query_preview`/`topic` from the row `query` (already
sanitised) for v1 traces; write with a **synchronous** `Neo4jGraphSink`
(schema applied first). Prints `{rows, replayed, skipped_no_json,
skipped_invalid, failed}`. Idempotent via MERGE + first-write-wins created_at.
Never deletes anything.

## 6. Seeding — `scripts/seed_neo4j.py`

Run each case through the real `Evaluator` once with a capturing sink, take
`response.trace` (now carries query_preview/topic/created_at/RETRIEVED), and
re-key it deterministically to `bench-<name>` (`rekey_trace`: rewrite ids
equal to / prefixed by the uuid request_id). No second signal pass, no
duplicated headlines. Re-running → same ids → MERGE → no duplicates;
created_at stays first-write. **Decision for lead:** also log the seeded
response to the audit DB (`INSERT OR REPLACE`, same `bench-*` id) so seeded
decisions are rebuildable and Agent 4's SQLite counts match the graph —
proposed default ON with `--no-audit` to skip. Existing seed tests keep
passing (signatures preserved).

## 7. Tests (tests/graph/)

Unit (fake driver; extend `fake_driver.py` with a read-capable
`FakeReadDriver(responder)` and `execute_read`):
* `test_topics.py`: determinism, stopwords, order-insensitivity, empty.
* `test_trace_v2.py`: new Decision props, query_preview sanitised + ≤160,
  RETRIEVED for every evidence, same-source SUPERSEDES within trace, date/
  version keys, no-evidence path.
* sink: query_preview 160 cap, created_at coalesce statement, linking
  statement parameterised and only scoped to trace sources, FakeGraph
  idempotency incl. RETRIEVED.
* `test_async_sink.py`: non-blocking with a slow inner sink, written/failed
  counts, exception in inner, drop_oldest + drop_new backpressure counts,
  flush timeout, close joins thread, stats shape.
* `test_reader.py`: every query has no interpolated user input (injection
  strings in params only), label/rel allow-list filtering, node label text.
* `test_graph_routes.py`: 503 + graph_available:false with no driver and with
  a raising driver; status always 200; 404s; shapes per §4.
* Evaluator wiring: one test using `Evaluator(stubs(), graph_sink=Recording)`
  asserting created_at/query_preview/topic/degraded reach the trace.
Integration (`test_neo4j_live.py`, skipped unless `NEO4J_URI`): `itest-<uuid>`
request ids and `itest-<uuid>-*.pdf` sources so cleanup (`DETACH DELETE` of
only those nodes) never touches seed data. Checks: same trace twice → node
and rel counts identical; two separate evaluations of v1/v2 of one source →
SUPERSEDES across traces; decision subgraph via reader round-trips; routes
via TestClient against the live DB.

## 8. Existing-test adjustments I need (tests I own, flagged)

* `test_neo4j_sink.py::test_valid_trace_writes_every_node_and_edge`: call
  count becomes nodes+edges+1 (linking statement) and the relationship set
  gains `RETRIEVED`. Alternative if you prefer zero edits: default
  `link_supersedes=False` and enable it in main/scripts — I prefer default
  on and editing these two assertions.
* `test_trace_builder.py::test_a_minimal_trace_is_just_a_decision`: the
  exact-dict assertion gains `trace_version: "2"`.
No test is removed or renamed.

## 9. Contract adjustments / questions (flagged)

1. Allow the `_init_neo4j_driver` one-line change in main.py (short timeouts).
2. `topic_key` returns `""` for queries with no keywords (Agent 4: skip).
3. Document nodes gain `date_key`, `version_key` (additive, internal).
   SUPERSEDES edges gain optional `derived` prop.
4. Same-source SUPERSEDES won't link the benchmark leave docs (different
   sources) — only the version-conflict rule does.
5. Status response adds `writer.queue_capacity`/`running` (additive).
6. Seed also writes audit rows (default on) — needs lead OK since
   `app/audit/**` is lead-owned (I'd only *call* `AuditLogger`, not edit it).
