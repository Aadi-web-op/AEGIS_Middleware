# AEGIS: Integration, Neo4j Validation and Product Readiness

Date: 2026-11-18 · Branch `feat/finale-upgrade` · Nothing committed.

How it was run: the three workstreams (Neo4j / backend contracts / full-stack QA)
were done **in sequence by one agent**, not by parallel agents. The machine has about 2.5 GB
of free RAM, every evaluator process loads the NLI and embedding models, and another
agent was still writing `tests/intelligence/**`. Running sequentially avoided both
out-of-memory failures and edits colliding in the same files. All existing
uncommitted work was preserved: no resets, no reverts.

Ports: `:8000` and `:5173` are held by an unrelated local app, so AEGIS was run on
**backend :8010** and **console :5180**.

---

## 1. Neo4j connectivity

| Check | Result |
|---|---|
| Container | `aegis-neo4j` (`neo4j:5.26-community`, docker-compose), status *healthy* |
| Bolt | `bolt://localhost:7687`, `neo4j/password`: connected |
| `GET /v1/graph/status` | `configured: true, connected: true` |
| Constraints | `claim_id`, `decision_request_id`, `document_id`, `evidence_id`, `reason_id` (unique), present |
| Schema | `apply_schema`: 14 statements applied (idempotent, run by the rebuild and seed scripts) |

## 2. Graph seeding and recovery

| Step | Command | Result |
|---|---|---|
| Replay audit log → graph | `python -m scripts.rebuild_graph` | 364 rows, **98 replayed**, 266 skipped (no stored trace: legacy rows / generation failures), **0 failed** |
| Seed benchmark dev set | `python -m scripts.seed_neo4j` | **12/12 succeeded, 0 failed**. Real `Evaluator` runs; stable `bench-*` ids; MERGE, no duplicates |
| Legacy key backfill | one-off Cypher (below) | 4 legacy Document nodes got the missing `date_key`; writer's own `LINK_SUPERSEDES_CYPHER` re-run |

Legacy backfill, explained: 21 of the original 42 decisions predate trace v2.
Their Document nodes had `date` but no `date_key`, so the writer's supersession
linker (which compares `date_key`) could never connect them. The intelligence layer,
which compares `date` in Python, did report supersession. Result: a finding
with no matching graph edge. I set `date_key = substring(date, 0, 10)` (exactly what
`trace_builder` stores today) on nodes missing it and re-ran the writer's linking
query. No records were invented; one derived edge appeared:
`doc:policy_2026.pdf → SUPERSEDES → doc:policy_2026.pdf@v3`.

## 3. Graph nodes and relationships verified

Final counts (`/v1/graph/status`, matching direct Cypher):

| Nodes | | Relationships | |
|---|---|---|---|
| Decision | 135+ | HAS_CLAIM 48 · SUPPORTED_BY 32 · CONTRADICTED_BY 10 | Decision→Claim, Claim→Evidence |
| Claim | 48 | FROM 177 | Evidence→Document |
| Evidence | 177 | CONFLICTS_WITH 14 | Evidence↔Evidence (kind numeric/date/statement/version) |
| Document | 31 | SUPERSEDES 2 | Document version chain |
| Reason | 153 | BECAUSE 153 · ABOUT 103 · RETRIEVED 166 | |

Per-scenario relationships were checked directly in Cypher against what the UI showed (section 6).

## 4. Graph API verification (live, HTTP 200 with real data)

`/v1/graph/status`, `/decisions`, `/decisions/{id}`, `/documents`,
`/nodes/{id}/neighbors`; `/v1/intelligence/summary`, `/documents`,
`/contradictions`, `/stale-usage`, `/knowledge-gaps`, `/blast-radius`, `/trends`.
With Neo4j stopped: graph-only endpoints return **503 in about 3 ms** (fail-fast window);
`/summary`, `/trends`, `/v1/decisions` stay **200** (audit-backed).

## 5. Page validation (browser, Playwright, live backend + live Neo4j)

| Page | Result |
|---|---|
| Overview | Real counts; findings panel populated; system strip shows writer counters |
| Live evaluation | 4 examples ran end to end; claim spans highlighted; E-labels correct; trace graph and inspector |
| Decisions | Paged history; drawer rebuilds the full result from the stored response |
| Intelligence | Real findings (each cites request ids and the Cypher query used); all tables populated |
| Graph explorer | Decision subgraph loads; node select → inspector; **Expand neighbours** merges; edges match Cypher |
| Documents | Version groups; supersedes / superseded-by tags; blast-radius drawer (relied-on vs retrieved-only) |
| Escalations | Auto-created escalation visible with links to decision and graph (no PATCH sent; real queue left as is) |
| System | Health, writer counters (written / failed / dropped / pending / last_error), policy matrix |

Console: **0 errors, 0 warnings** with Neo4j up. At 390 px: no horizontal scroll on any
page. Dark mode was checked. Screenshots are in the session scratchpad (`screens/`), not in the repo.

UI fixes made during live validation (frontend only, no redesign):
* Graph explorer: three columns only at ≥1680 px; below that the inspector moves under the
  canvas. At 1440 px the canvas had been ~520 px wide and clipped most of the graph.
* Tabs strip: `overflow-y: hidden` (stray scroll arrows).
* "No further neighbours" shown as a neutral note, not an error.
* Overview reads the new `generation_failures` field.

## 6. End-to-end acceptance scenarios

All were run through the real API (`POST /v1/evaluate`) and checked in Neo4j.

| # | Scenario | Result |
|---|---|---|
| 1 | Supported answer | **ANSWER**; claim SUPPORTED "Stated by evidence E1."; graph `HAS_CLAIM`, `SUPPORTED_BY`, `FROM`, `RETRIEVED` |
| 2 | Unsupported answer | **ABSTAIN**; claim UNSUPPORTED "No evidence passage states this…"; reasons include `UNSUPPORTED_CLAIM` |
| 3 | Contradictory evidence (10 vs 14 days) | **ESCALATE**; "Stated by evidence E2. Evidence E1 says otherwise…"; `CONFLICTS_WITH {kind: numeric}` between the two passages; `CONTRADICTED_BY` → E1 |
| 4 | Cross-decision intelligence | `hr_circular_2024@v1 conflicts with hr_circular_2026@v2`, **3 of 3** decisions; knowledge gap "personnel sanctioned university" 3/3; finding request ids verified (20/20 found as Decision nodes) |
| 5 | Document impact | Two real evaluations citing `staff_handbook.pdf` v1 (2024) and v2 (2026) → writer derived `v2 SUPERSEDES v1`; blast radius of v1 = 2 relied-on decisions; stale-usage lists the 2 decisions that used v1 after v2 existed |
| 6 | Human escalation | Scenario 3 auto-enqueued `esc-…` (pending, ESCALATE); visible in Escalations with links to decision detail and graph |
| 7 | Neo4j outage | `docker stop aegis-neo4j` → `/v1/evaluate` **200 in 56 ms**; writer `failed: 1`, `last_error: ServiceUnavailable…`; graph pages show the offline state. `docker start` → reconnects; the outage decision was 404 in the graph; `rebuild_graph` replayed it → **200**, 0 failures |

## 7. Backend API contract fixes

| Issue | Finding | Change | Tests |
|---|---|---|---|
| C1 Evidence numbering | Already fixed in the working tree (`Evaluator._claim_reason` emits `E{i+1}`). Verified live: index 1 → "E2", index 0 → "E1", matching the passage order | none needed | `test_supported_reason_labels_are_one_based`, `test_contradicted_reason_labels_are_one_based` |
| C2 Generation failures | `count_records()` folds NULL decisions into a `GENERATION_FAILED` bucket, which `/v1/decisions` returned as if it were a fifth decision | `app/audit/routes.py`: `counts` now holds only ANSWER/CAVEAT/ESCALATE/ABSTAIN; new `generation_failures: int`; `total` still counts every logged row so paging is unchanged. Intelligence distributions already excluded NULLs | `test_decision_counts_exclude_generation_failures`, `test_no_generation_failures_reports_zero` |
| C3 RAG answer | `/v1/rag/ask` returned no answer text, so spans had nothing to index | `app/schemas.py`: optional `EvaluateResponse.answer` (additive). `app/rag/aegis_workflow.py`: attaches the generated answer before audit logging (history keeps it too). `/v1/evaluate` leaves it `null`. The frontend already falls back to `response.answer` | `test_rag_response_carries_generated_answer_and_spans_index_into_it`, `test_rag_empty_knowledge_base_still_returns_answer_text`, `test_evaluate_endpoint_leaves_answer_unset` |

New file: `tests/test_contract_fixes.py` (7 tests). No fake responses; the frontend
was not changed to hide backend inconsistencies.

## 8. Evidence highlighting verification

Claim `span` offsets index into the evaluated answer (`/v1/evaluate`: request answer;
RAG: `response.answer`). Verified in the browser (highlight covers the exact claim
text) and in a test (`answer[start:end] == claim` for every claim with a span).
E-labels in the reasons match the E-numbers on the evidence cards.

## 9. Backend tests (executed)

| Run | Result |
|---|---|
| Full suite, standard config (`NEO4J_URI` unset) | **810 passed, 8 skipped, 0 failed** (skips = live-Neo4j tests) |
| Live Neo4j tests (`NEO4J_URI` set): `tests/graph/test_neo4j_live.py`, `tests/intelligence/test_live_neo4j.py` | **9 passed**; 0 leftover `itest-` nodes |
| Note | Running the *whole* suite with `NEO4J_URI` exported gives 8 failures in tests that assert "no driver → 503"; with the variable set, `create_app()` connects to the real DB. This comes from the environment, not a regression; run those two ways as above |

## 10. Frontend lint / test / build (executed)

Root cause of "lint and tests broken": system Node is **22.11**. The oxlint native
binding (`@oxlint/binding-win32-x64-msvc`) declares `engines: ^20.19.0 || >=22.12.0`,
and npm **silently skips optional packages whose engines don't match**, so the binding
was never installed. vitest has the same Node gate. `npm ci` on 22.11 does not help.

With a portable, checksum-verified **Node 22.12.0** (scratchpad only, system untouched) and `npm ci`:

| Command | Result |
|---|---|
| `npm run lint` | exit 0, **0 errors**, 6 advisory warnings (`set-state-in-effect` ×4, `only-export-components` ×2) |
| `npm test` | **13/13 passed** |
| `npm run build` | passes (CSS 38 kB, JS 335 kB / 99 kB gzip) |

`package.json` and `package-lock.json` were unchanged. **Fix: install Node ≥ 22.12 (or 20.19+) and run `npm ci`.**

## 11. Remaining issues (honest list)

1. **Graph recovery after an outage is manual.** The writer counts the failure but does
   not retry once Neo4j returns; run `python -m scripts.rebuild_graph` (idempotent).
2. **`CONFLICTS_WITH` is stored in both directions** for one pair (a→b and b→a).
   Intelligence normalises pairs, so counts are right, but the explorer draws two edges.
   Smallest fix (Agent 3): MERGE undirected or order the pair before writing.
3. **Supersession rule split.** Intelligence derives supersession from `date` in Python;
   the writer links on `date_key`. They now agree on the current data (after the backfill), but
   any future legacy node could diverge. Smallest fix (Agent 4): use `SUPERSEDES` edges
   (or `date_key`) only.
4. **Top stale-version finding is driven by dev data.** "policy_2026.pdf@v3 still retrieved
   (73/73)" is correct by the rule (an unversioned `policy_2026.pdf` dated 2026-11-01 exists),
   but that newer document came from earlier test/demo runs. For the finale, use a clean
   database seeded with the demo flow below, or explain it as such.
5. **Evaluator quirks (Agent 2's domain):** an unsupported-only answer also lists `CONTRADICTION`
   reasons; reason codes can repeat. (Lead correction: `mixed_evidence_caveat` → ANSWER is *correct* —
   its locked label is ANSWER despite the case name; see FINAL_REPORT.md §benchmark.)
6. Lint warnings (6, advisory) left as-is.
7. Graph canvas: on narrow screens the document column starts off-screen at the
   minimum readable zoom (pan or Fit).

## 12. Startup

```bash
# 1. Neo4j
docker compose up -d neo4j            # waits for "healthy"

# 2. Backend (repo root). Use :8000 if it is free.
export USE_TF=0 TRANSFORMERS_NO_TF=1
export NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=password
export AEGIS_CORS_ORIGINS=http://localhost:5180,http://127.0.0.1:5180
python -m uvicorn app.main:app --port 8010

# 3. (once) graph projection + benchmark seed
python -m scripts.rebuild_graph
python -m scripts.seed_neo4j

# 4. Console (Node >= 22.12)
cd frontend && npm ci
VITE_AEGIS_API=http://127.0.0.1:8010 npx vite --port 5180
# open http://localhost:5180
```

## 13. Demo sequence (about 6 minutes)

1. **System**: API ok, graph *connected*, writer counters, policy profile matrix.
2. **Live evaluation → "Supported"**: Evaluate → ANSWER; claim highlighted green; "Stated by evidence E1".
3. **"Unsupported claim"** → ABSTAIN; amber claim; reason explains that no passage states it.
4. **"Contradictory sources"** → ESCALATE; "Stated by E2. E1 says otherwise"; factors table;
   graph shows the dashed red *conflicts with* edge. Click it to read the relationship's meaning.
5. **Escalations**: the new item is at the top; expand; "Decision graph".
6. **Graph explorer**: click the claim → inspector shows SUPPORTED_BY E2 and CONTRADICTED_BY E1; Expand neighbours.
7. **"Outdated version"** (and/or the staff_handbook v1/v2 pair) → **Documents**: v2 *supersedes* v1;
   open v1 → **blast radius** lists the decisions that relied on it.
8. **Intelligence**: contradiction hotspot (hr_circular 2024 vs 2026, 3 of 3), knowledge gap,
   stale version; click a request id → that decision's detail. Every number links back to stored records.
9. **Resilience (optional)**: `docker stop aegis-neo4j` → evaluate still answers in milliseconds; System
   shows `failed: 1`; graph pages show the offline state. `docker start aegis-neo4j` → `python -m scripts.rebuild_graph` → the decision appears.

## Files changed in this pass

* Backend: `app/schemas.py` (+`answer`), `app/rag/aegis_workflow.py` (`_with_answer`), `app/audit/routes.py` (counts split)
* Tests: `tests/test_contract_fixes.py` (new, 7 tests)
* Frontend: `src/pages/Overview.jsx`, `src/pages/GraphExplorer.jsx`, `src/components/GraphInspector.jsx`, `src/styles/components.css`
* Data (dev Neo4j only): `date_key` backfilled on 4 legacy Document nodes, plus 1 derived SUPERSEDES edge
* Docs: this report
