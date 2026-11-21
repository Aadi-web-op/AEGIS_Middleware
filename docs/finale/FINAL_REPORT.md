# AEGIS Finale Upgrade — Final Report (lead orchestrator)

Branch `feat/finale-upgrade`, uncommitted. Detailed agent reports:
`agent1-frontend-report.md`, `agent4-intelligence-report.md`, `INTEGRATION_REPORT.md`;
plans and contracts: `CONTRACTS.md`, `plan-agent*.md`.

## 1. What each workstream delivered

| Workstream | Delivered |
|---|---|
| **Agent 1, frontend** | Operations console, written from scratch, with no new dependencies. Hash-routed pages: Overview, Evaluate, Decisions, Intelligence, Graph explorer, Documents, Escalations, System. Real API data only; loading, empty, error and offline states; light and dark themes; works at 390px. |
| **Agent 2, reliability** | Answers are split into atomic claims (`aegis_core/utils/claim_split.py`). Claim-level vetoes in `app/core/policy.py`: a contradicted claim escalates; an answer with no supported claim abstains; mostly ungrounded claims escalate; any unsupported claim caveats. Hybrid relevance. Evidence indices kept aligned. Model failures are reported as `SIGNAL_UNAVAILABLE` instead of a score. Additive response fields: `headline`, `explanation{summary, decisive_rule, factors}`, `unavailable_signals`, per-claim `reason` and `span`, supporting and contradicting evidence indices. |
| **Agent 3, Neo4j** | Trace v2: `created_at`, `topic`, `query_preview` (secrets redacted), `degraded`. New `RETRIEVED` edge. `SUPERSEDES` linking across traces. Non-blocking `AsyncGraphSink` with written/failed/dropped/pending counters. Read API at `/v1/graph/*`. `scripts/rebuild_graph.py` replays the audit log into the graph. |
| **Agent 4, intelligence** | `app/intelligence/` with `/v1/intelligence/*`. Six finding kinds; each needs at least 2 decisions and cites `request_ids` and the query it came from. Reports "insufficient data" below 5 graph decisions. Also: blast radius, stale-version usage, knowledge gaps, trends. Reviewing it fixed 7 bugs, including every graph read failing on driver 6.x. |
| **Lead, integration** | Contracts, decision-history API (`/v1/decisions`), contract fixes (E1-style evidence labels in claim reasons, `generation_failures` counted separately, `answer` added to RAG responses), live verification, this report. |

## 2. Test results (measured 2026-11-18)

* **Backend, full suite** (`pytest tests`, without `NEO4J_URI`): **803 passed, 8 skipped, 0 failed**. The 8 skips are the live Neo4j tests. The integration pass then added 7 contract tests; its own run reports 810 passed.
* **Live Neo4j** (`NEO4J_URI` set): `tests/graph/test_neo4j_live.py` and `tests/intelligence/test_live_neo4j.py`, **9/9 passed**. Tests use their own `itest-<uuid>` ids and delete only those nodes.
* **Frontend**: `npm run build` passes (JS 334.8 kB, 98.8 kB gzipped). With Node 22.12 from a temporary folder: lint exits 0 with 6 advisory warnings, and vitest passes 13/13. System Node 22.11 is too old for oxlint and vitest; **install Node 22.12 or later**.
* **Browser**: all 8 pages loaded with Neo4j live, 0 console errors, no horizontal scroll at 390px.

## 3. Benchmark: measured, not tuned

The baseline is HEAD (`9c329c4`), run from a clean worktree. The labels in `tests/benchmark/test_cases.py` are unchanged (`git diff` is empty).

| Split | Baseline | Now |
|---|---|---|
| Dev (12) | 8/12 | **12/12** |
| Locked test (8) | **6/8** | 5/8 |
| All 20 | 14/20 (70%) | 17/20 (85%) |
| Selective accuracy | 55.6% | **100%** |
| Coverage | 45% | 35% |

* Fixed on dev:
  * `partial_evidence_caveat` and `long_answer_unsupported_claim`: ANSWER became CAVEAT, which is the README's documented weakness.
  * `unsupported_claim_abstain`: CAVEAT became ABSTAIN.
  * `missing_date_signal_case`: ABSTAIN became CAVEAT.
* **Regression on the locked split.**
  * `partial_support_across_chunks` and `incomplete_evidence_multi_aspect` now go to ESCALATE where CAVEAT is expected.
  * `stale_curfew_policy` now goes to ABSTAIN where CAVEAT is expected. It was already wrong at baseline, as ESCALATE.
  * The evaluator now fails toward caution: it no longer returns ANSWER where ANSWER is wrong, but it over-escalates partial or incomplete evidence. It was **not** tuned against the locked set. The next step is to tune `escalate_at_ungrounded_fraction` and `min_grounding` on new dev cases only.

## 4. Remaining limitations

1. **Over-escalation** of partially supported answers (see §3).
2. **Graph outage recovery is manual.** The writer counts failed writes and doesn't retry; run `python -m scripts.rebuild_graph` once Neo4j is back.
3. **`CONFLICTS_WITH` is stored in both directions,** so the explorer draws two edges for one conflict. Intelligence counts are correct.
4. **Two supersession rules.** Intelligence compares raw `date`; the writer compares `date_key`. They agree on the current data.
5. **Intelligence findings show association, not cause.** Topics are keyword keys, not semantic clusters. Each query returns at most 5,000 rows.
6. **Repeated reason codes.** An unsupported-only answer can also list `CONTRADICTION`, and reason codes can repeat.
7. **The dev Neo4j holds old test data.** Its top stale-version finding comes from earlier runs, so **use a clean database for the finale** (below).
8. **Cypher deprecation warnings.** Neo4j 5.26 warns about the `CALL { WITH x … }` subquery syntax; the queries still work.

## 5. Startup

```bash
docker compose up -d neo4j
export USE_TF=0 TRANSFORMERS_NO_TF=1
export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=password
export AEGIS_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
python -m uvicorn app.main:app --port 8000          # repo root
python -m scripts.seed_neo4j                         # once: benchmark seed through the real evaluator
cd frontend && npm ci && npm run dev                 # Node >= 22.12; open http://localhost:5173
```
If ports 8000 and 5173 are taken (they were on this machine), use 8010 and 5180, and set `VITE_AEGIS_API=http://127.0.0.1:8010` and `AEGIS_CORS_ORIGINS` to match.

**Clean database for the finale**, run in the Neo4j browser on a dedicated demo DB:
```cypher
MATCH (n) DETACH DELETE n
```
Then run `python -m scripts.seed_neo4j`.

## 6. Demo script for the judges (about 6 minutes)

1. **Reliability (Demo 1 and 4)**: Evaluate the examples.
   * **Supported** gives ANSWER; the claim is green with "Stated by evidence E1".
   * **Unsupported** gives ABSTAIN; the explanation says no passage states the claim.
   * **Contradictory** gives ESCALATE, with the factors table, the decisive rule, and a numeric conflict.
   * Point out that the old aggregate score would have passed some of these. Per-claim vetoes are what change the outcome.
2. **Neo4j (Demo 3)**: open the Graph explorer and select that decision.
   * Click through Decision, Claim, Evidence and Document, then click the `CONTRADICTED_BY` and `CONFLICTS_WITH` edges; the inspector explains what each relationship means.
   * Expand neighbours to see the other decisions that used the same document.
3. **Versions**: evaluate the **Outdated version** example, then open Documents.
   * v2 *supersedes* v1.
   * v1's blast radius lists the decisions that relied on the outdated version.
4. **Cross-Decision Intelligence (Demo 2)**: open Intelligence.
   * Contradiction hotspot, stale version still in use, knowledge gap.
   * Each finding shows its numerator and denominator and links to the decisions it was derived from. Click one.
   * On a fresh DB, show the "insufficient data" state first, which shows the system doesn't invent findings.
5. **Resilience and the whole product (Demo 5)**:
   * Run `docker stop aegis-neo4j`. Evaluation still answers quickly, System shows the writer's failed count, and the graph pages show an offline state.
   * Run `docker start aegis-neo4j` then `python -m scripts.rebuild_graph`, and the decision reappears.
   * Close on Escalations: the contradictory case is waiting for review.
