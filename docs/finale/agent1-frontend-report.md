# Agent 1 — Frontend report (AEGIS Trust Console)

Scope: `frontend/**` only. Nothing committed. No backend files edited.

## What was built

A hash-routed operations console (`#overview`, `#evaluate`, `#decisions[/<id>]`,
`#intelligence`, `#graph[/decision/<id> | /node/<id>]`, `#documents[/<doc_id>]`,
`#escalations`, `#system`; unknown or `#home` hashes redirect to `#overview`).
Light theme by default, dark via `prefers-color-scheme` or the sidebar toggle
(`localStorage["aegis-theme"]`). Every value on screen comes from an API response;
missing values render as "—", never 0. There is no mock data in the running app.

| Page | Endpoints | Notes |
|---|---|---|
| Overview | `/v1/intelligence/summary`, `/v1/decisions?limit=8`, `/v1/graph/status`, `/v1/health` | Four metric cells with denominators, distribution bar + count table, top 5 findings, recent decisions, system strip. The insufficient-data notice shows only when the graph is up. |
| Live evaluation | `POST /v1/evaluate`, `/v1/config`, `/v1/rag/ingest`, `/v1/rag/ask` | Form with evidence editor and profile select. Four example buttons (Supported / Unsupported claim / Contradictory sources / Outdated version) only prefill wording from `tests/benchmark/test_cases.py`. The result is the shared `DecisionResult`: verdict + headline + score vs profile thresholds; the answer with claim spans highlighted by status (uses `claim.span`, falls back to text matching); claims with `reason` and supporting/contradicting E-refs (hover links claims and evidence); evidence list; `explanation.summary` / `decisive_rule` / factors table; reasons; per-request graph with inspector; technical details (signals incl. "unavailable", request id copy, raw JSON). The RAG tab keeps the old ingest + ask flow. |
| Decisions | `/v1/decisions`, `/v1/decisions/{id}` | Paged table (filter by outcome with real counts, text filter on the page), stacked rows on phones. Clicking a row opens a URL-addressable drawer that rebuilds the full result from `record` + `response`, or shows a record-only view when `response` is null. |
| Intelligence | `/v1/intelligence/summary`, `/documents`, `/contradictions`, `/stale-usage`, `/knowledge-gaps`, `/trends` | Findings (severity, kind, explanation, metric n/d, subject links, request-id links to Decisions, query name, "considered only" attribution), document reliability table (with the API's own definitions), contradiction pairs with sample values, stale versions (relied vs. all), knowledge gaps, reason codes, trends (day/hour SVG stacked bars, text instead of a chart when there are fewer than 2 buckets). Honest states: "N more evaluations needed" when `sufficient=false`. When the graph is offline, one consolidated offline panel replaces the graph sections; audit-backed sections still render. |
| Graph explorer | `/v1/graph/decisions`, `/v1/graph/documents`, `/v1/graph/decisions/{id}`, `/v1/graph/nodes/{id}/neighbors` | Picker (decisions with outcome filter / documents), deterministic layered canvas (Reason, Decision, Claim, Evidence, Document), pan / zoom / fit, keyboard-selectable nodes and edges. The inspector shows props, clickable relationships, a plain-language meaning for each edge, and "Expand neighbours", which merges into the view. The selected node is auto-panned into view. 404 explains async graph writes; 503 shows "Graph database offline". |
| Documents | `/v1/graph/documents` joined with `/v1/intelligence/documents`, `/v1/intelligence/blast-radius` | Versions grouped by source with supersedes / superseded-by tags and usage counts. The drawer shows document facts and blast radius split into "relied on" and "retrieved only", with decision links and "open in explorer". |
| Escalations | `GET/PATCH /v1/escalations` | Status filter, expandable rows (question, answer, reason, record, links to the decision and graph), reviewer notes, actions limited to the valid transitions in `app/escalation/queue.py`. The sidebar badge shows the pending count. |
| System | `/v1/health`, `/v1/config`, `/v1/graph/status` | API facts; graph writer counters (written / pending / failed / dropped / last success / last error); node and relationship counts; scoring weights; profile × rule matrix (thresholds, signal vetoes, claim rules, answer_min_signal). |

## Files

New: `src/styles/base.css`, `src/styles/components.css`, `src/pages/{Overview,Evaluate,Decisions,Intelligence,GraphExplorer,Documents,Escalations,System}.jsx`, `src/pages/examples.js`, `src/components/TrendBars.jsx`.
Rewritten: `src/App.jsx` (shell + route switch), `src/test/graph.test.jsx` (now tests graphUtils, format, router, segmentAnswer, GraphCanvas, GraphInspector and DecisionResult).
Touched (from the earlier session, finished here): `components/GraphCanvas.jsx` (readable minimum fit zoom 0.62 and pan; auto-pan to selection), `ui/`, `api.js`, `format.js`, `router.js`, `tokens.css`.
Removed: `src/DecisionGraph.jsx` (legacy). `src/mockTrace.js` moved to `src/test/mockTrace.js` (test-only).
No new npm dependencies.

## Verification

* `npm run build`: passes (vite 8.3.4; 38 modules; CSS 38.3 kB, JS 334.7 kB / 98.8 kB gzip). It prints a Node 22.11 version warning, which is environmental.
* `npm run lint`: cannot run here because oxlint's native binding (`@oxlint/binding-win32-x64-msvc`) is missing from node_modules (environmental). `vitest` also cannot start on Node 22.11 (known; see CONTRACTS §0).
* Live check with Playwright against the real backend. Ports 8000 and 5173 were taken by an unrelated local app, so I used backend :8010 (`AEGIS_CORS_ORIGINS=http://localhost:5180`) and Vite :5180 (`VITE_AEGIS_API=http://127.0.0.1:8010`). Both are stopped now.
  * All 8 pages loaded. Three examples were evaluated end to end (Contradictory → ESCALATE, Outdated → ESCALATE, Unsupported → ABSTAIN), showing claim highlighting, evidence refs, explanation and factors, and the trace graph with the inspector. The decision drawer was opened from history. The escalation row was expanded, but no PATCH was sent, to avoid altering real queue records.
  * Console: the only errors are the expected 503 network entries from graph endpoints while Neo4j was down. One React duplicate-key warning (repeated reason codes) was found and fixed.
  * At 390 px, `scrollWidth ≤ viewport` on every page; tables become stacked rows; the slide-out nav and full-width drawer work. Dark theme was checked.
  * Screenshots (outside the repo): `C:\Users\chauh\AppData\Local\Temp\claude\e88ae5d3e5185915\f3e07480-8fda-43ab-a1d0-38d65515805b\scratchpad\screens\`.
* **Neo4j was not reachable during verification** (`bolt://localhost:7687` refused; Docker daemon not running). The graph-online views (explorer with real subgraphs, documents table, blast radius, intelligence tables, findings) were therefore checked only for build correctness, offline/error states, and through the per-request trace graph, which uses the same canvas and inspector. They should be clicked through once Neo4j is up.

## API contract notes / mismatches (not edited)

1. `ClaimResult.reason` cites passages with 0-based indices ("Stated by evidence passage(s) [1]. Passage(s) [0] say otherwise"), while the UI and the rest of the product label passages E1..En. Suggest Agent 2 phrase reasons with `E{i+1}`.
2. `/v1/decisions` `counts` includes a non-decision key `GENERATION_FAILED`, and `total` includes it (305 total vs 301 decisions). The UI handles this (the overview labels the metric "Requests logged" with the failure count), but it is not in the contract.
3. `/v1/rag/ask` returns `EvaluateResponse` without the generated answer text, so the RAG result cannot highlight claims in the answer. It lists claims instead, and the UI says so.
4. Reason nodes in traces can repeat the same code (e.g. three `unsupported claim` Reason nodes for one decision). This is correct per reasons[], but noisy in the graph.
5. `/v1/graph/status.writer` carries extra keys (`queue_capacity`, `running`) beyond the contract. Harmless; not displayed.

## Known issues

* On narrow canvases the right-hand graph columns (documents) start off-screen at the minimum readable zoom; the user pans or uses "Fit".
* Decision drawer and explorer depend on `/v1/graph/*` being up for the "Open in graph explorer" path; when the graph is down they show the offline state.
