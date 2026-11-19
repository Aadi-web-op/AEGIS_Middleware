# AEGIS Finale Upgrade — Shared Contracts & Ownership

Owner: lead orchestrator. Agents build against this document. If a contract
here is wrong or insufficient, report it in your final summary rather than
silently diverging. All changes are **additive**: no existing response field,
endpoint or test may be removed or renamed.

Branch: `feat/finale-upgrade` (single working tree, strict file ownership).

## 0. Environment (everyone)

* Python: always `export USE_TF=0 TRANSFORMERS_NO_TF=1` before running Python
  (TensorFlow import crashes on this machine with a paging-file error).
* Machine has ~2.5 GB free RAM. Do NOT run the full `pytest tests` suite; run
  only your own test directories. The lead runs the full suite at integration.
* Neo4j 5.26 is running: `bolt://localhost:7687`, `neo4j` / `password`
  (HTTP 7474). It contains older seed data. Integration tests that need it
  must be skipped unless `NEO4J_URI` is set, and must clean up only nodes they
  created (use a unique `request_id` prefix such as `itest-<uuid>`).
* Node is 22.11: `npm run build` works; `vitest` fails at startup with
  ERR_REQUIRE_ESM in jsdom (environmental). Do not upgrade Node or swap test
  environments.
* Only the frontend agent may start long-running servers: backend on :8000,
  Vite on :5173. Everyone else uses FastAPI `TestClient`.
* Do not commit. Do not touch `.kilo/`, `submission-video/`,
  `scripts/make_release_zip.py`, `docs/demo_script.md` (pre-existing
  uncommitted user work).

## 1. File ownership

| Area | Owner | Notes |
|---|---|---|
| `frontend/**` | Agent 1 (Frontend) | sole owner |
| `app/core/policy.py`, `app/core/scoring.py`, `app/core/claims.py`, `app/core/config.py`, `config/policy.yaml`, `aegis_core/**`, `app/evidence/**`, `app/graph/templates.py` | Agent 2 (Reliability) | |
| `app/core/evaluator.py` | Agent 2, **except** the `build_trace(...)` / `safe_write_trace(...)` call blocks, which belong to Agent 3 | |
| `app/schemas.py` | Agent 2 (additive fields only) | |
| `tests/benchmark/evaluator.py`, `scripts/explanation_check.py`, `tests/reliability/**` (new), `tests/test_policy.py`, `tests/test_evaluator.py`, `tests/integration/test_signals.py` | Agent 2 | `tests/benchmark/test_cases.py` is READ-ONLY for everyone |
| `app/graph/**` (except `templates.py`, `insights.py`), `scripts/schema.cypher`, `scripts/seed_neo4j.py`, `tests/graph/**` (except `test_insights.py`) | Agent 3 (Graph) | |
| `app/graph/insights.py`, `tests/graph/test_insights.py`, `app/intelligence/**` (new), `tests/intelligence/**` (new) | Agent 4 (Intelligence) | |
| `app/main.py` | Lead. Agents 3 and 4 may ONLY add an `include_router(...)` line and its import; Agent 3 may also change how the sink is constructed. | |
| `README.md`, `docs/**` | Lead (agents may add `docs/finale/<agent>.md` notes) | |
| `app/insights/routes.py`, `app/audit/**`, `app/escalation/**`, `app/rag/**` | Lead (ask if you need a change; Agent 4 may READ audit DB via existing helpers) | |

## 2. Evaluation response (Agent 2 → Agent 1)

Existing `EvaluateResponse` fields stay. Additive fields (all optional so old
clients keep working):

```jsonc
{
  "headline": "string | null",            // one-line, from app.graph.templates
  "unavailable_signals": ["freshness"],    // signals that returned null
  "explanation": {                          // why this decision
    "summary": "string",                    // 1–3 sentences, plain language
    "decisive_rule": "string | null",       // e.g. "veto:unsupported_claim", "score_threshold"
    "factors": [
      {"signal": "entailment", "value": 0.31, "threshold": 0.40,
       "comparison": "below" , "effect": "ESCALATE", "message": "..."}
    ]
  },
  "claims": [ {                             // ClaimResult, extended
    "claim": "...", "status": "SUPPORTED|UNSUPPORTED|CONTRADICTED",
    "support": 0.0, "evidence_indices": [0],
    "supporting_evidence_indices": [0],
    "contradicting_evidence_indices": [],
    "reason": "string | null",              // why this claim got its status
    "span": [start, end] | null              // char offsets of the claim in `answer`, when it is a verbatim substring
  } ]
}
```

Reason codes stay the existing `ReasonCode` enum; Agent 2 may add codes only
if genuinely needed (document them here in its report).

## 3. Graph model (Agent 3 owns; Agent 4 queries it)

Node labels (closed set): `Decision, Claim, Evidence, Document, Reason`.

New/required properties (in addition to what `trace_builder` writes today):

* `Decision`: `request_id`, `decision`, `headline`, `answerability_score`,
  `profile`, `policy_version`, **`created_at`** (ISO-8601 UTC string),
  **`query_preview`** (≤160 chars, secrets redacted via
  `app.audit.logger.sanitize_secrets`), **`topic`** (deterministic
  normalised keyword key derived from the query, e.g. `"leave|annual|days"`;
  same function exposed as `app.graph.topics.topic_key(query)`),
  **`degraded`** (bool), `trace_version` ("2").
* `Claim`: `text`, `status`, `support`, `claim_index`.
* `Evidence`: `preview` (≤120), `source`, `version`, `date`, `evidence_index`.
* `Document`: `id` (`doc:<source>[@<version>]`), `source`, `version`, `date`.
* `Reason`: `code`, `message`.

Relationships (closed set; existing ones unchanged):

| Type | From → To | Meaning |
|---|---|---|
| `HAS_CLAIM` | Decision → Claim | existing |
| `SUPPORTED_BY` | Claim → Evidence | existing |
| `CONTRADICTED_BY` | Claim → Evidence | existing |
| `FROM` | Evidence → Document | existing |
| `CONFLICTS_WITH` | Evidence → Evidence | existing, `kind` ∈ numeric/date/statement/version |
| `SUPERSEDES` | Document → Document | newer → older. Now ALSO derived whenever two Document nodes share `source` and have comparable version/date — within a trace and across traces (post-write linking query) |
| `BECAUSE` | Decision → Reason | existing |
| `ABOUT` | Reason → Claim/Evidence | existing |
| **`RETRIEVED`** | Decision → Evidence | NEW: every evidence passage the decision considered, cited or not |

Writes must remain MERGE-based/idempotent and must NOT block `evaluate()`:
Agent 3 makes graph writes asynchronous (bounded background queue) with
observable counters (`written`, `failed`, `dropped`, `pending`,
`last_error`, `last_success_at`) and a `flush(timeout)` for tests.

## 4. Graph read API (Agent 3 → Agent 1, Agent 4)

Prefix `/v1/graph`. When no driver/Neo4j is unreachable: HTTP 503
`{"detail": "...", "graph_available": false}`. Subgraph shape everywhere:

```jsonc
{ "nodes": [ {"id": "...", "type": "Decision", "label": "short display text", "props": {...}} ],
  "edges": [ {"id": "from|TYPE|to|kind", "type": "SUPPORTED_BY", "from": "...", "to": "...", "props": {...}} ] }
```

* `GET /v1/graph/status` → `{configured, connected, counts:{Decision:n,…}, relationships:{TYPE:n,…}, writer:{written,failed,dropped,pending,last_error,last_success_at}}` (always 200; `connected:false` when down).
* `GET /v1/graph/decisions?limit=50&decision=&source=` → `{items:[{request_id, decision, created_at, query_preview, topic, answerability_score, claim_count, evidence_count, document_count, reason_codes:[]}]}` newest first.
* `GET /v1/graph/decisions/{request_id}` → subgraph of the decision (claims, evidence, documents, reasons, plus SUPERSEDES between its documents) + `decision` summary object. 404 if absent.
* `GET /v1/graph/documents?limit=100` → `{items:[{doc_id, source, version, date, decision_count, supported_claim_count, contradicted_claim_count, conflict_count, superseded_by:[doc_id], supersedes:[doc_id]}]}`.
* `GET /v1/graph/nodes/{node_id}/neighbors?limit=50` → one-hop subgraph around any node (node_id URL-encoded) — used by the explorer to expand.

## 5. Cross-Decision Intelligence API (Agent 4 → Agent 1)

Prefix `/v1/intelligence`. Every finding must be traceable to stored
records. When Neo4j is down: graph-backed parts return
`{"available": false, "reason": "..."}` inside the payload (HTTP 200 for
`/summary`, 503 for graph-only endpoints). Audit-log-backed parts (decision
distribution, trends) still work from SQLite.

`Finding` shape (used everywhere):

```jsonc
{ "id": "stable-hash", "kind": "unsupported_source|contradiction_hotspot|stale_version_in_use|knowledge_gap|escalation_root_cause|uncertainty_source",
  "severity": "high|medium|low",
  "title": "short", "explanation": "plain-language why, with the numbers",
  "metric": {"name": "unsupported_claim_rate", "value": 0.67, "numerator": 4, "denominator": 6},
  "subjects": [{"type": "Document", "id": "doc:leave_policy.pdf@v2"}],
  "request_ids": ["..."],                  // the decisions it is based on (≤20)
  "query": "name of the Cypher query used" }
```

* `GET /v1/intelligence/summary` → `{generated_at, data:{total_decisions, graph_decisions, min_required, sufficient, message}, decision_distribution:{ANSWER:n,…}, reason_distribution:{CODE:n}, findings:[Finding], graph:{available}}`.
* `GET /v1/intelligence/documents` → per-document reliability table: `{items:[{doc_id, source, version, decisions, supported_claims, unsupported_or_contradicted_claims, unsupported_rate, conflicts, escalations, abstains, superseded_by}]}`.
* `GET /v1/intelligence/contradictions` → document pairs with conflict counts, kinds and request_ids.
* `GET /v1/intelligence/stale-usage` → superseded document versions still retrieved, with the decisions that used them *after* the newer version first appeared.
* `GET /v1/intelligence/knowledge-gaps` → topics ranked by ABSTAIN/ESCALATE share (with sample queries and request_ids); min 2 decisions per topic.
* `GET /v1/intelligence/blast-radius?doc_id=` → decisions that relied on (SUPPORTED_BY) or retrieved (RETRIEVED) that document, split into the two groups.
* `GET /v1/intelligence/trends?bucket=day|hour` → decision counts per bucket from the audit log.

Minimum-data rule: a pattern is a "finding" only if it is observed in ≥2
distinct decisions; `/summary.data.sufficient` is false below 5 graph
decisions and `message` says how many more are needed.

## 6. Frontend information architecture (Agent 1)

Hash routes (single page, no new router dependency):
`#overview`, `#evaluate`, `#decisions` (history + detail), `#intelligence`,
`#graph` (explorer), `#documents` (evidence & document relationships),
`#escalations` (keep), `#system` (health). Landing `#home` may stay.
API base: `import.meta.env.VITE_AEGIS_API ?? "http://127.0.0.1:8000"`.

## 7. Decision history API (lead — DONE)

Backed by SQLite (`audit_logs.response_json` column added, auto-migrated).

* `GET /v1/decisions?limit=50&offset=0&decision=ESCALATE` →
  `{items:[{request_id, timestamp, query, profile, decision, answerability_score, reason_codes, generation_success, error_message, latency_ms}], total, counts:{ANSWER:n,…}, limit, offset}` newest first.
* `GET /v1/decisions/{request_id}` → `{record:{…}, response: <full EvaluateResponse incl. trace> | null}`; 404 if unknown.
* `AuditLogger.list_records(limit, offset, decision, include_response)` and `AuditLogger.count_records()` are available to Python callers (Agent 4: use these for audit-derived distributions/trends; `audit_logs.timestamp` is ISO-8601 UTC).
