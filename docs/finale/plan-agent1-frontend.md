# Agent 1 — Frontend plan (AEGIS Trust Console, finale)

Status: PHASE 1 (plan only). Owner: Agent 1. Scope: `frontend/**`.

## 0. Findings from the current frontend

* `App.jsx` (677 lines) holds routing, sidebar, workspace (RAG only) and the graph view. There is **no** direct `/v1/evaluate` form — the key demo is missing.
* The graph view only shows the *last* trace in memory, or `MOCK_TRACE` behind a "Use sample trace" checkbox (fake data in a production path). Clicking a request id elsewhere lands on an empty state.
* `InsightsDashboard.jsx` calls `/v1/insights/conflicting-document-pairs`, `stale-document-retrievals`, `abstain-topics`, `decisions-by-decision`, `escalation-clusters` (lead-owned `app/insights/routes.py`). These will be superseded by `/v1/intelligence/*`.
* `DecisionGraph.jsx`: hand-written SVG, BFS layering (not type-layered), random-ish rainbow palette (purple documents, pink reasons). `graphUtils.js` already normalises the real trace shape (`nodes/edges` with `from/to`, flat props) — worth keeping.
* `landing/` (animated hero, GraphField canvas, 56 gradient/blur/glow/shadow rules) is exactly the decorative style we are told to avoid.
* `index.css` already has a token block (dark teal), but `App.css` mixes ad-hoc values, gradients and shadows.

## 1. Design system

Theme: **light by default, dark via `prefers-color-scheme`** plus a manual toggle stored in `localStorage` (`data-theme` on `<html>`). Every colour is a token; components never use hex.

### Palette (light / dark)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F7F8FA` | `#0E1014` | page background |
| `--surface` | `#FFFFFF` | `#15181E` | panels, tables |
| `--surface-2` | `#F1F3F6` | `#1B1F26` | table header, hover, code |
| `--border` | `#E3E6EB` | `#262B33` | hairlines |
| `--border-strong` | `#CDD2DA` | `#363C46` | inputs, focus-adjacent |
| `--text` | `#14171C` | `#E8EAED` | primary text |
| `--text-2` | `#4A515C` | `#A9AFB8` | secondary |
| `--muted` | `#6E7681` | `#7D848E` | labels, meta |
| `--accent` | `#2D5BD8` | `#6B8EF0` | links, primary button, selection, focus ring |
| `--accent-soft` | `#EAF0FD` | `#1C2540` | selected row/nav |

Semantic decision colours (fg / soft bg), used identically in badges, graph nodes, table chips and distribution bars:

| Decision | fg light | soft light | fg dark | soft dark |
|---|---|---|---|---|
| ANSWER | `#1A7F4B` | `#E7F5EE` | `#4CC38A` | `#12271D` |
| CAVEAT | `#A15C00` | `#FDF3E1` | `#E0A443` | `#2A2112` |
| ESCALATE | `#C0362C` | `#FCEBEA` | `#F0776D` | `#2E1716` |
| ABSTAIN | `#5B6472` | `#EEF0F3` | `#9AA3AF` | `#20242B` |

Claim status reuses them: SUPPORTED = ANSWER green, UNSUPPORTED = CAVEAT amber, CONTRADICTED = ESCALATE red. Severity: high = red, medium = amber, low = neutral.
Graph node types are neutral-toned with a coloured 3px left rule only: Decision = decision colour, Claim = status colour, Evidence = `--text-2`, Document = `--accent`, Reason = `--muted`.

No gradients, no translucent blur, no glow; one shadow token only for overlays (drawer, popover): `0 8px 24px rgba(16,20,28,.12)`.

### Typography
* UI: **Inter** (already loaded) 400/500/600. Mono: **JetBrains Mono** 400/500 for request ids, doc ids, numbers in tables, JSON.
* `font-variant-numeric: tabular-nums` on all tables, metrics and scores.
* Scale (px / line-height): 12/16 meta+labels, 13/20 body-small & tables, 14/22 body, 16/24 section title, 20/28 page title (h1). No larger text anywhere in the console.
* Labels: 12px, 500, `--muted`, sentence case (no letter-spaced all-caps walls).

### Space, radius, layout
* Spacing scale 4/8/12/16/24/32/48 (`--s-1`…`--s-7`).
* Radius: 4 (inputs, chips), 6 (panels, buttons), 8 (drawer). Pill only for status dots.
* Shell: 232px left sidebar (collapses to a top bar + slide-out nav under 900px), content max-width 1280px, 24px gutter (16px under 600px). Tables become stacked rows / horizontal scroll inside their container under 600px; page never scrolls horizontally down to 380px.
* Focus: `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }` on every interactive element. `prefers-reduced-motion` honoured; the only motion is 120ms colour/opacity transitions and drawer slide.

## 2. Information architecture (hash routes per contract §6)

Sidebar groups:
* **Evaluate**: Overview `#overview`, Live evaluation `#evaluate`
* **Investigate**: Decisions `#decisions` (`#decisions/<request_id>` opens detail), Intelligence `#intelligence`, Graph explorer `#graph` (`#graph/decision/<id>`, `#graph/node/<urlenc id>`), Documents `#documents` (`#documents/<urlenc doc_id>`)
* **Operate**: Escalations `#escalations`, System `#system`

Sidebar footer: API status dot, policy version, graph connected/offline (from `/v1/graph/status`). Default route: `#overview`. `#home` → redirect to `#overview` (see §5, landing).

Compact page header everywhere: 20px title, one-line description, actions right-aligned (refresh, filters). Every number shown is from an API response; absent data shows "—" with a tooltip, never 0.

## 3. Pages

**Overview** — `/v1/intelligence/summary` (fallback `/v1/decisions?limit=200` counts when 404), `/v1/graph/status`, `/v1/health`.
Row 1: four compact metric cells (total decisions, graph decisions, escalation share, abstain share) — plain numbers with their denominators. Row 2: decision distribution as one horizontal stacked bar + legend table with counts and %. Row 3 (2 cols): top 5 findings (severity chip, title, metric n/d, link) | recent decisions (8 rows from `/v1/decisions`). Row 4: system strip (API, policy, signals, graph writer pending/failed). Insufficient-data banner from `data.message`.

**Live evaluation** — tabs: *Evaluate an answer* (`POST /v1/evaluate`) | *RAG pipeline* (existing `/v1/rag/ingest` + `/v1/rag/ask`).
Left column form: question, answer, evidence list (add/remove passages; text, source, date, version), profile select (from `/v1/config` profiles), time-sensitive toggle. Above the form: example chips — *Supported*, *Unsupported claim*, *Contradictory sources*, *Outdated version* — that only prefill (leave-policy wording reused from `data/demo` / benchmark cases) and the user presses Evaluate.
Right column result = shared `<DecisionResult>` component:
1. Decision header: badge + `headline` + answerability score vs the profile thresholds (small inline scale with the 3 threshold ticks, real values).
2. Question, then the answer with each claim span highlighted by status (match claim text in answer; fallback to listing claims as sentences). Hover/click claim → highlights the evidence passages it used (`supporting_evidence_indices` / `contradicting_evidence_indices`, fallback `evidence_indices`) and shows `claim.reason`.
3. Evidence list with E1..En labels, source/version/date, which claims cite it and how.
4. Why: `explanation.summary`, `decisive_rule`, factor table (signal, value, threshold, comparison, effect, message); fallback to `reasons[]` when `explanation` absent.
5. Decision graph for this request (from `response.trace`) via the shared `<GraphCanvas>`; "Open in explorer" link.
6. Collapsed `<details>` Technical: all six signals (null = "unavailable", listed in `unavailable_signals`), latency, request_id (copy), policy version, degraded flag, raw JSON.

**Decision history** — `/v1/decisions?limit=&decision=`; table: time, query (truncated), decision chip, score, reason codes, profile, latency. Filters: decision segmented control, text filter (client-side). Row click → right drawer (full width on mobile) that loads `/v1/decisions/{id}` and renders `<DecisionResult>` from `response` (or a record-only view with "Full response not stored" when null). Fallback to `/v1/graph/decisions` if `/v1/decisions` 404s.

**Intelligence** — `/v1/intelligence/summary`, `/documents`, `/contradictions`, `/stale-usage`, `/knowledge-gaps`, `/trends`.
Sufficiency banner when `data.sufficient` false: "Not enough data yet — N more evaluations needed" (N = `min_required - graph_decisions`, plus `message`). Sections stacked, each a titled panel with its own loading/empty/error: Findings (list rows: severity, kind, title, explanation, metric `name: value (num/den)`, subject links to Documents/Graph, request-id links to Decisions), Document reliability table, Contradiction pairs table, Stale versions in use, Knowledge gaps, Trends (small bar series per bucket split by decision, real counts, axis labels; hidden when < 2 buckets).

**Graph explorer** — load by request id (picker from `/v1/graph/decisions`) or doc id (from `/v1/graph/documents`). `GET /v1/graph/decisions/{id}`; expand via `/v1/graph/nodes/{id}/neighbors` (merge into the current subgraph). Layout deterministic by columns Decision → Claim → Evidence → Document, Reason column placed left of Decision (stacked, ordered by index). Within a column order by `claim_index`/`evidence_index`/id so the same graph always renders the same. Pan/zoom/fit, keyboard selectable nodes (tab + enter). Side panel: node → type, label, all props, in/out relationships list (clickable); edge → type, plain meaning sentence, props (support, kind, values). Legend for node types and edge styles (support solid green, contradiction solid red, conflict dashed red, supersedes dashed accent, structural neutral). 503 → "Graph database offline" state with the detail text.

**Documents** — `/v1/graph/documents` joined with `/v1/intelligence/documents` by `doc_id`. Table grouped by `source` showing versions in order with "supersedes / superseded by" tags, decisions, supported/contradicted claims, unsupported rate, conflicts. Row → drawer with blast radius (`/v1/intelligence/blast-radius?doc_id=`): two lists *relied on (SUPPORTED_BY)* and *retrieved only*, each linking to decisions; button to open document node in the explorer.

**Escalations** — existing `/v1/escalations` GET/PATCH logic kept, restyled as a table with status filter, row expansion for query/answer/notes, resolve/dismiss actions, link to decision detail.

**System** — `/v1/health`, `/v1/config` (weights table; per-profile thresholds + vetoes as a profile × rule matrix), `/v1/graph/status` (connected, node counts by label, relationship counts, writer written/failed/dropped/pending/last_error/last_success_at). API base URL shown.

## 4. Components / files

New `frontend/src/` layout:
* `api.js` — `apiGet/apiPost/apiPatch` with typed error classes (`unavailable` for 404/405, `offline` for 503 incl. `graph_available:false`, `network`), `useApi(path)` hook (loading/error/data/reload).
* `router.js` — `useHashRoute()` parsing `#page/arg`.
* `styles/tokens.css`, `styles/base.css`, `styles/components.css` (replaces `index.css` + `App.css`).
* `ui/` — `Shell` (Sidebar, MobileNav), `PageHeader`, `Panel`, `DecisionBadge`, `StatusChip`, `SeverityChip`, `Table`, `Drawer`, `Tabs`, `Segmented`, `EmptyState`, `ErrorState` (handles unavailable/offline wording), `Loading` (skeleton rows), `Mono`, `CopyButton`, `Icon`, `KeyValue`.
* `components/` — `DecisionResult.jsx`, `ClaimHighlighter.jsx`, `FactorTable.jsx`, `ScoreScale.jsx`, `DistributionBar.jsx`, `TrendBars.jsx`, `GraphCanvas.jsx` (rewrite of `DecisionGraph.jsx`: layered layout + selection callbacks; no internal mock), `GraphInspector.jsx`.
* `pages/` — `Overview`, `Evaluate` (+ `examples.js`, `RagPanel`), `Decisions`, `Intelligence`, `GraphExplorer`, `Documents`, `Escalations`, `System`.
* `graphUtils.js` — keep `buildGraphFromTrace` (trace → normalised subgraph) and add `normaliseSubgraph` (API shape `{nodes:[{id,type,label,props}],edges:[{from,to,type,props}]}`), `layeredLayout`, `mergeSubgraphs`, `edgeMeaning`.

Rewritten/removed:
* Rewrite `App.jsx` (shell + route switch only), `DecisionGraph.jsx` → `components/GraphCanvas.jsx`, `ExplanationPanel.jsx` → folded into `DecisionResult`, `InsightsDashboard.jsx` → `pages/Intelligence.jsx`, `EscalationQueue.jsx` → `pages/Escalations.jsx`.
* Delete `landing/` (animated hero/canvas), `assets/hero.png`, `react.svg`, `vite.svg`; `#home` redirects to `#overview`. (If the lead wants a landing kept for the video, I can instead keep a single static, token-styled product page — say so.)
* `mockTrace.js` stays only for `test/graph.test.jsx`; no production import. The test file will be updated to import the new modules (vitest can't run here, but build/lint will cover imports).

## 5. Dependencies

None added. Plain SVG for graph and the two small charts; no router, no UI kit, no chart lib.

## 6. Error/empty-state rules

* 404/405 → "Endpoint unavailable — `GET /v1/…` is not served by this backend version."
* 503 / `graph_available:false` / `available:false` → "Graph database offline" with detail; audit-backed sections still render.
* Network error → "API unreachable at <base>" with Retry.
* Empty lists → one-line reason + the action that produces data (e.g. link to Live evaluation).

## 7. Verification (phase 2)

`npm run build`, `npm run lint`; backend on :8000 + Vite :5173; Playwright: every page, all four examples, RAG tab, drawer, explorer expand/select, console errors, 390px width, light + dark screenshots into the scratchpad `screens/` directory.

## 8. Open questions for the lead

1. OK to delete the animated landing and make `#overview` the default?
2. `/v1/decisions/{id}` — will `response.trace` include the v2 trace (RETRIEVED edges) or just the stored evaluate response? I render whatever trace is present.
3. Claim-to-answer highlighting needs claim text to be a substring (or near) of the answer; if Agent 2 can add character offsets (`span:[start,end]`) to `ClaimResult`, highlighting becomes exact. Otherwise I use normalised substring matching with a sentence-list fallback.
