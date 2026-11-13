/**
 * App.jsx – AEGIS Trust Console with four views:
 *   #workspace   – RAG ingest + ask
 *   #graph       – Decision graph + explanation panel
 *   #insights    – Cross-decision insights dashboard
 *   #escalations – Escalation queue with graph links
 *
 * Uses window.location.hash for routing — no extra dependency.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";
import DecisionGraph from "./DecisionGraph.jsx";
import EscalationQueue from "./EscalationQueue.jsx";
import ExplanationPanel from "./ExplanationPanel.jsx";
import { buildGraphFromTrace } from "./graphUtils.js";
import InsightsDashboard from "./InsightsDashboard.jsx";
import Landing from "./landing/Landing.jsx";
import { MOCK_TRACE } from "./mockTrace.js";

const API = import.meta.env.VITE_AEGIS_API ?? "http://127.0.0.1:8000";

const DECISION_COLORS = {
  ANSWER: "var(--success)",
  CAVEAT: "var(--warning)",
  ESCALATE: "var(--danger)",
  ABSTAIN: "var(--neutral)",
};

// ── Icons (inline, stroke-based, 16px) ─────────────────────────────────────

function Icon({ name, size = 16 }) {
  const paths = {
    shield: <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z M9 12l2 2 4-4" />,
    workspace: <path d="M4 5h16v11H4z M8 20h8 M12 16v4" />,
    graph: <path d="M6 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M18 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M12 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M8 6h8 M7 8l4 8 M17 8l-4 8" />,
    insights: <path d="M4 20V10 M10 20V4 M16 20v-7 M22 20H2" />,
    escalations: <path d="M12 9v4 M12 17h.01 M10.3 3.9L2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />,
    docs: <path d="M7 3h7l5 5v13H7z M14 3v5h5 M10 13h6 M10 17h6" />,
    arrow: <path d="M5 12h14 M13 6l6 6-6 6" />,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

// ── Routing ────────────────────────────────────────────────────────────────

const ROUTES = {
  "#workspace": {
    label: "Workspace",
    group: "Evaluate",
    icon: "workspace",
    title: "Evaluation workspace",
    description:
      "Ingest source documents, ask a question, and review the AEGIS decision before an answer reaches your users.",
  },
  "#graph": {
    label: "Decision Graph",
    group: "Analyze",
    icon: "graph",
    title: "Decision graph",
    description:
      "Trace every decision back to the claims, evidence and documents behind it.",
  },
  "#insights": {
    label: "Insights",
    group: "Analyze",
    icon: "insights",
    title: "Insights",
    description:
      "Cross-decision analytics from the audit log: recurring conflicts, stale sources and documentation gaps.",
  },
  "#escalations": {
    label: "Escalations",
    group: "Operate",
    icon: "escalations",
    title: "Escalation queue",
    description:
      "Answers AEGIS held back for human review. Triage, resolve or dismiss each one.",
  },
};

const NAV_GROUPS = ["Evaluate", "Analyze", "Operate"];

function useHashRoute() {
  const normalise = (h) => (ROUTES[h] ? h : "#home");
  const [route, setRoute] = useState(normalise(window.location.hash));
  useEffect(() => {
    const handler = () => setRoute(normalise(window.location.hash));
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  const navigate = useCallback((hash) => {
    window.location.hash = hash;
  }, []);
  return [route, navigate];
}

// ── API health ─────────────────────────────────────────────────────────────

function useApiHealth() {
  const [health, setHealth] = useState({ state: "checking", data: null });
  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const r = await fetch(`${API}/v1/health`);
        if (!r.ok) throw new Error(String(r.status));
        const data = await r.json();
        if (!cancelled) setHealth({ state: "ok", data });
      } catch {
        if (!cancelled) setHealth({ state: "down", data: null });
      }
    }
    check();
    const id = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);
  return health;
}

// ── Sidebar ────────────────────────────────────────────────────────────────

function Sidebar({ route, health }) {
  const statusText = {
    checking: "Checking…",
    ok: "Operational",
    down: "Unreachable",
  }[health.state];

  return (
    <aside className="sidebar">
      <a href="#home" className="brand" aria-label="AEGIS home">
        <span className="brand-mark">
          <Icon name="shield" size={19} />
        </span>
        <span>
          <span className="brand-name">AEGIS</span>
          <span className="brand-sub">Trust Console</span>
        </span>
      </a>

      <nav className="nav-groups main-nav" aria-label="Main navigation">
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group}>
            <span className="nav-group-label">{group}</span>
            {Object.entries(ROUTES)
              .filter(([, r]) => r.group === group)
              .map(([hash, r]) => (
                <a
                  key={hash}
                  href={hash}
                  className={`nav-link${route === hash ? " nav-link--active" : ""}`}
                  aria-current={route === hash ? "page" : undefined}
                >
                  <Icon name={r.icon} />
                  {r.label}
                </a>
              ))}
          </div>
        ))}
      </nav>

      <div className="sidebar-foot">
        <div className="status-card" aria-live="polite">
          <div className="status-row">
            <span>API</span>
            <strong>
              <span className={`dot dot--${health.state}`} />
              {statusText}
            </strong>
          </div>
          <div className="status-row">
            <span>Policy</span>
            <strong>{health.data?.policy_version ?? "—"}</strong>
          </div>
          <div className="status-row">
            <span>Signals</span>
            <strong>{health.data?.signals?.length ?? "—"}</strong>
          </div>
        </div>
        <p className="sidebar-meta">
          v{health.data?.api_version ?? "0.1.0"} · MIT licensed
        </p>
      </div>
    </aside>
  );
}

// ── Top bar ────────────────────────────────────────────────────────────────

function Topbar({ route, health }) {
  const r = ROUTES[route];
  return (
    <header className="topbar">
      <div className="breadcrumb">
        {r.group} <span aria-hidden="true">/</span> <strong>{r.label}</strong>
      </div>
      <div className="topbar-actions">
        <span className="pill">
          <span className={`dot dot--${health.state}`} />
          {health.state === "ok" ? "Connected" : health.state === "down" ? "Offline" : "Connecting"}
        </span>
        <span className="pill">Local environment</span>
        <a className="btn-ghost" href={`${API}/docs`} target="_blank" rel="noreferrer">
          <Icon name="docs" size={14} />
          API reference
        </a>
      </div>
    </header>
  );
}

function PageHeader({ route, children }) {
  const r = ROUTES[route];
  return (
    <div className="page-header">
      <div>
        <h1>{r.title}</h1>
        <p>{r.description}</p>
      </div>
      {children}
    </div>
  );
}

// ── Graph view ─────────────────────────────────────────────────────────────

function GraphView({ trace, useMock, onToggleMock }) {
  const effectiveTrace = useMock ? MOCK_TRACE : trace;
  const graphData = useMemo(
    () => (effectiveTrace ? buildGraphFromTrace(effectiveTrace) : null),
    [effectiveTrace]
  );

  return (
    <>
      <PageHeader route="#graph">
        <div className="toggle-box">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={useMock}
              onChange={(e) => onToggleMock(e.target.checked)}
            />
            Use sample trace
          </label>
        </div>
      </PageHeader>

      {!effectiveTrace && (
        <div className="panel">
          <div className="empty">
            <span className="empty-icon">
              <Icon name="graph" size={20} />
            </span>
            <h4>No trace available</h4>
            <p>Ask a question in the Workspace, or turn on the sample trace above.</p>
          </div>
        </div>
      )}

      {effectiveTrace && (
        <div className="graph-layout">
          <div className="graph-pane">
            <DecisionGraph graphData={graphData} />
          </div>
          <div className="explanation-pane">
            <ExplanationPanel trace={effectiveTrace} />
          </div>
        </div>
      )}
    </>
  );
}

// ── Workspace ──────────────────────────────────────────────────────────────

function pct(v) {
  return typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "Unavailable";
}

function WorkspaceView({ onResult }) {
  const [pdfPath, setPdfPath] = useState("data/demo/leave_policy_v2_2024.pdf");
  const [documentDate, setDocumentDate] = useState("2024-03-01");
  const [version, setVersion] = useState("2");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(3);
  const [timeSensitive, setTimeSensitive] = useState(false);

  const [ingestLoading, setIngestLoading] = useState(false);
  const [askLoading, setAskLoading] = useState(false);
  const [ingestMessage, setIngestMessage] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function ingestPdf(event) {
    event.preventDefault();
    setIngestLoading(true);
    setError("");
    setIngestMessage("");
    setResult(null);
    try {
      const response = await fetch(`${API}/v1/rag/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pdf_path: pdfPath,
          date: documentDate || null,
          version: version || null,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || "PDF ingestion failed.")
        );
      }
      setIngestMessage(`Document ingested — ${data.chunks_added} chunks added to the knowledge base.`);
    } catch (err) {
      setError(`${err.message}. Check that the backend is running at ${API}.`);
    } finally {
      setIngestLoading(false);
    }
  }

  async function askQuestion(event) {
    event.preventDefault();
    setAskLoading(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch(`${API}/v1/rag/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: query,
          top_k: Number(topK),
          profile: "standard",
          time_sensitive: timeSensitive,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || "RAG request failed.")
        );
      }
      setResult(data);
      onResult(data); // share trace with graph view
    } catch (err) {
      setError(`${err.message}. Check the backend and provider configuration.`);
    } finally {
      setAskLoading(false);
    }
  }

  const signals = result?.signals ? Object.entries(result.signals) : [];
  const decisionColor = DECISION_COLORS[result?.decision] ?? "var(--neutral)";

  return (
    <>
      <PageHeader route="#workspace" />
      <div className="layout">
        <div className="stack">
          <section className="panel">
            <div className="panel-head">
              <span className="step">1</span>
              <div>
                <h3>Knowledge base</h3>
                <p>Add a source document. The knowledge base is held in memory on the backend.</p>
              </div>
            </div>
            <div className="panel-body">
              <form onSubmit={ingestPdf}>
                <label htmlFor="pdfPath">Document path</label>
                <input
                  id="pdfPath"
                  value={pdfPath}
                  onChange={(e) => setPdfPath(e.target.value)}
                  required
                />
                <p className="hint">Path on the backend machine, absolute or relative to the repository root.</p>
                <div className="two-columns">
                  <div>
                    <label htmlFor="documentDate">Effective date</label>
                    <input
                      id="documentDate"
                      type="date"
                      value={documentDate}
                      onChange={(e) => setDocumentDate(e.target.value)}
                    />
                  </div>
                  <div>
                    <label htmlFor="version">Version</label>
                    <input
                      id="version"
                      value={version}
                      onChange={(e) => setVersion(e.target.value)}
                    />
                  </div>
                </div>
                <button type="submit" disabled={ingestLoading}>
                  {ingestLoading ? "Ingesting…" : "Ingest document"}
                </button>
              </form>
              {ingestMessage && <p className="success">{ingestMessage}</p>}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <span className="step">2</span>
              <div>
                <h3>Ask a question</h3>
                <p>Retrieval, generation and AEGIS evaluation run in one request.</p>
              </div>
            </div>
            <div className="panel-body">
              <form onSubmit={askQuestion}>
                <label htmlFor="query">Question</label>
                <textarea
                  id="query"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="How many casual leaves can an employee take?"
                  required
                />
                <div className="two-columns">
                  <div>
                    <label htmlFor="topK">Evidence chunks</label>
                    <select
                      id="topK"
                      value={topK}
                      onChange={(e) => setTopK(e.target.value)}
                    >
                      <option value={1}>1 chunk</option>
                      <option value={3}>3 chunks</option>
                      <option value={5}>5 chunks</option>
                      <option value={10}>10 chunks</option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="profile">Risk profile</label>
                    <input id="profile" value="Standard" disabled />
                  </div>
                </div>
                <label className="checkbox-label" style={{ marginTop: 14 }}>
                  <input
                    type="checkbox"
                    checked={timeSensitive}
                    onChange={(e) => setTimeSensitive(e.target.checked)}
                  />
                  Treat this question as time-sensitive
                </label>
                <button type="submit" disabled={askLoading}>
                  {askLoading ? "Retrieving and evaluating…" : "Evaluate answer"}
                </button>
              </form>
              {error && <p className="error">{error}</p>}
            </div>
          </section>
        </div>

        <section className="panel results-panel">
          <div className="panel-head">
            <div>
              <h3>Evaluation result</h3>
              <p>The generated answer, the AEGIS decision and the evidence behind it.</p>
            </div>
          </div>
          <div className="panel-body">
            {!result && !askLoading && (
              <div className="empty">
                <span className="empty-icon">
                  <Icon name="shield" size={20} />
                </span>
                <h4>Awaiting question</h4>
                <p>Ingest a document, then ask a question to see its evaluation.</p>
              </div>
            )}

            {askLoading && (
              <div className="loading-row">
                <span className="spinner" />
                Retrieving evidence and evaluating the answer…
              </div>
            )}

            {result && (
              <>
                <div className="result-grid">
                  <div className="decision-card" style={{ borderLeftColor: decisionColor }}>
                    <span className="label-caps">Decision</span>
                    <h2 style={{ color: decisionColor }}>{result.decision}</h2>
                    <p>{result.recommended_action?.replaceAll("_", " ")}</p>
                  </div>
                  <div className="score-card">
                    <span className="label-caps">Answerability score</span>
                    <strong>{pct(result.answerability_score)}</strong>
                    <div className="progress">
                      <div style={{ width: `${(result.answerability_score ?? 0) * 100}%` }} />
                    </div>
                  </div>
                </div>

                <div className="notice">
                  <span className="label-caps">Generated answer</span>
                  <p>{result.answer ?? "No answer field returned by the API."}</p>
                </div>

                {result.caveat_text && (
                  <div className="notice notice--warn">
                    <strong>Caveat</strong>
                    <p>{result.caveat_text}</p>
                  </div>
                )}

                {result.clarifying_question && (
                  <div className="notice">
                    <strong>Clarifying question</strong>
                    <p>{result.clarifying_question}</p>
                  </div>
                )}

                <h4 className="section-title">Reasons</h4>
                {result.reasons?.length ? (
                  <ul className="reason-list">
                    {result.reasons.map((reason, index) => (
                      <li key={`${reason.code}-${index}`}>
                        <strong>{reason.code.replaceAll("_", " ")}</strong>
                        <p>{reason.message}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No reasons returned.</p>
                )}

                <h4 className="section-title">Signal breakdown</h4>
                <div className="signals">
                  {signals.map(([name, value]) => (
                    <div className="signal" key={name}>
                      <span>{name}</span>
                      <strong>{pct(value)}</strong>
                      {typeof value === "number" && (
                        <div className="mini-progress">
                          <div style={{ width: `${value * 100}%` }} />
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {result.claims?.length > 0 && (
                  <>
                    <h4 className="section-title">Claim analysis</h4>
                    {result.claims.map((claim, index) => (
                      <div className="claim" key={index}>
                        <strong>{claim.status}</strong>
                        <p>{claim.claim}</p>
                        <small>Support: {pct(claim.support)}</small>
                      </div>
                    ))}
                  </>
                )}

                <div className="meta-row">
                  <p className="request-id">Request ID: {result.request_id}</p>
                  <a href="#graph" className="view-graph-link">
                    View decision graph <Icon name="arrow" size={14} />
                  </a>
                </div>
              </>
            )}
          </div>
        </section>
      </div>
    </>
  );
}

// ── Root App ───────────────────────────────────────────────────────────────

export default function App() {
  const [route, navigate] = useHashRoute();
  const health = useApiHealth();
  const [lastTrace, setLastTrace] = useState(null);
  const [useMock, setUseMock] = useState(false);

  // When an insight or escalation selects a request_id, switch to graph view.
  // Only the request_id is known there, so a non-matching id shows the
  // "no trace available" state. Future work: fetch the trace from the audit API.
  const handleNavigateToGraph = useCallback(
    (requestId) => {
      if (lastTrace?.request_id !== requestId) {
        setLastTrace({ request_id: requestId, _missing: true });
      }
      navigate("#graph");
    },
    [lastTrace, navigate]
  );

  useEffect(() => {
    window.scrollTo(0, 0);
    if (ROUTES[route]) document.title = `${ROUTES[route].label} · AEGIS Trust Console`;
  }, [route]);

  if (route === "#home") return <Landing />;

  return (
    <div className="shell">
      <Sidebar route={route} health={health} />

      <div className="main">
        <Topbar route={route} health={health} />

        <main className="content page-enter" key={route}>
          {route === "#workspace" && (
            <WorkspaceView
              onResult={(trace) => {
                setLastTrace(trace);
                setUseMock(false);
              }}
            />
          )}

          {route === "#graph" && (
            <GraphView
              trace={lastTrace?._missing ? null : lastTrace}
              useMock={useMock}
              onToggleMock={setUseMock}
            />
          )}

          {route === "#insights" && (
            <>
              <PageHeader route="#insights" />
              <InsightsDashboard onNavigateToGraph={handleNavigateToGraph} />
            </>
          )}

          {route === "#escalations" && (
            <>
              <PageHeader route="#escalations" />
              <EscalationQueue onOpenGraph={handleNavigateToGraph} />
            </>
          )}
        </main>

        <footer className="app-footer">
          <span>© 2026 AEGIS · Uncertainty middleware for AI systems</span>
          <span>Evidence before confidence</span>
        </footer>
      </div>
    </div>
  );
}
