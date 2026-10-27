/**
 * App.jsx – AEGIS frontend with four views:
 *   #workspace  – RAG ingest + ask (existing flow)
 *   #graph      – Decision graph + explanation panel
 *   #insights   – Cross-decision insights dashboard
 *   #escalations – Escalation queue with graph links
 *
 * Uses window.location.hash for routing — no extra dependency.
 * All existing workspace functionality is preserved unchanged.
 */
import { useCallback, useEffect, useState } from "react";
import "./App.css";
import DecisionGraph from "./DecisionGraph.jsx";
import EscalationQueue from "./EscalationQueue.jsx";
import ExplanationPanel from "./ExplanationPanel.jsx";
import { buildGraphFromTrace } from "./graphUtils.js";
import InsightsDashboard from "./InsightsDashboard.jsx";
import { MOCK_TRACE } from "./mockTrace.js";

const API = "http://127.0.0.1:8000";

// ── Hash-based router ──────────────────────────────────────────────────────

function useHashRoute() {
  const [route, setRoute] = useState(window.location.hash || "#workspace");
  useEffect(() => {
    const handler = () => setRoute(window.location.hash || "#workspace");
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  function navigate(hash) {
    window.location.hash = hash;
  }
  return [route, navigate];
}

// ── Nav ────────────────────────────────────────────────────────────────────

function Nav({ route }) {
  const links = [
    { hash: "#workspace", label: "Workspace" },
    { hash: "#graph", label: "Decision Graph" },
    { hash: "#insights", label: "Insights" },
    { hash: "#escalations", label: "Escalations" },
  ];
  return (
    <nav className="main-nav" aria-label="Main navigation">
      {links.map((l) => (
        <a
          key={l.hash}
          href={l.hash}
          className={`nav-link${route === l.hash ? " nav-link--active" : ""}`}
          aria-current={route === l.hash ? "page" : undefined}
        >
          {l.label}
        </a>
      ))}
    </nav>
  );
}

// ── Graph view (graph + explanation panel side by side) ────────────────────

function GraphView({ trace, useMock, onToggleMock }) {
  const effectiveTrace = useMock ? MOCK_TRACE : trace;
  const graphData = effectiveTrace ? buildGraphFromTrace(effectiveTrace) : null;

  return (
    <div>
      <div className="graph-view-header">
        <div>
          <h2>Decision Graph</h2>
          <p className="muted">
            Interactive visualisation of the AEGIS decision trace.
          </p>
        </div>
        <label className="checkbox-label" style={{ gap: 8 }}>
          <input
            type="checkbox"
            checked={useMock}
            onChange={(e) => onToggleMock(e.target.checked)}
          />
          Use mock trace
        </label>
      </div>

      {!effectiveTrace && (
        <div className="empty">
          <span className="empty-icon">◎</span>
          <h4>No trace available</h4>
          <p>
            Ask a question in the Workspace tab, or enable the mock trace above.
          </p>
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
    </div>
  );
}

// ── Workspace (original RAG flow, unchanged) ───────────────────────────────

function WorkspaceView({ onResult }) {
  const [pdfPath, setPdfPath] = useState(
    "C:\\Users\\saran\\Downloads\\AEGIS_Middleware\\badge.pdf"
  );
  const [documentDate, setDocumentDate] = useState("2026-10-19");
  const [version, setVersion] = useState("1.0");
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
      setIngestMessage(`PDF ingested successfully. Chunks added: ${data.chunks_added}`);
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

  return (
    <div className="layout">
      <div className="panel form-panel">
        <h3>1. Knowledge base</h3>
        <p className="muted">
          Ingest a PDF before asking questions. The backend currently stores the
          knowledge base in memory.
        </p>

        <form onSubmit={ingestPdf}>
          <label htmlFor="pdfPath">PDF path on the backend machine</label>
          <input
            id="pdfPath"
            value={pdfPath}
            onChange={(e) => setPdfPath(e.target.value)}
            required
          />
          <div className="two-columns">
            <div>
              <label htmlFor="documentDate">Document date</label>
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
            {ingestLoading ? "Ingesting PDF..." : "Ingest PDF →"}
          </button>
        </form>

        {ingestMessage && (
          <div className="notice">
            <strong>Ingestion status</strong>
            <p>{ingestMessage}</p>
          </div>
        )}

        <hr />

        <h3>2. Ask a question</h3>
        <p className="muted">
          Your question will be sent to the RAG backend for retrieval, answer
          generation, and AEGIS evaluation. The result also populates the
          Decision Graph tab.
        </p>

        <form onSubmit={askQuestion}>
          <label htmlFor="query">Your question</label>
          <textarea
            id="query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What information does this document contain?"
            required
          />
          <label htmlFor="topK">Evidence chunks to retrieve</label>
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
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={timeSensitive}
              onChange={(e) => setTimeSensitive(e.target.checked)}
            />
            Treat this question as time-sensitive
          </label>
          <button type="submit" disabled={askLoading}>
            {askLoading ? "Retrieving and evaluating..." : "Ask AEGIS →"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}
      </div>

      <section className="panel results-panel">
        <h3>AEGIS evaluation</h3>
        <p className="muted">
          The generated answer and its reliability assessment appear here.
        </p>

        {!result && !askLoading && (
          <div className="empty">
            <span className="empty-icon">◎</span>
            <h4>Awaiting question</h4>
            <p>Ingest a PDF, then ask a question.</p>
          </div>
        )}

        {askLoading && (
          <p>Retrieving evidence and evaluating the answer...</p>
        )}

        {result && (
          <>
            <div className="decision-card">
              <span className="muted">RECOMMENDED DECISION</span>
              <h2>{result.decision}</h2>
              <p>{result.recommended_action?.replaceAll("_", " ")}</p>
            </div>

            <div className="notice">
              <strong>Generated answer</strong>
              <p>{result.answer ?? "No answer field returned by the API."}</p>
            </div>

            <div className="score-card">
              <span className="muted">ANSWERABILITY SCORE</span>
              <strong>
                {typeof result.answerability_score === "number"
                  ? `${(result.answerability_score * 100).toFixed(1)}%`
                  : "Unavailable"}
              </strong>
              <div className="progress">
                <div
                  style={{
                    width: `${(result.answerability_score ?? 0) * 100}%`,
                  }}
                />
              </div>
            </div>

            <h4>Signal breakdown</h4>
            <div className="signals">
              {signals.map(([name, value]) => (
                <div className="signal" key={name}>
                  <span>{name}</span>
                  <strong>
                    {typeof value === "number"
                      ? `${(value * 100).toFixed(1)}%`
                      : "Unavailable"}
                  </strong>
                  {typeof value === "number" && (
                    <div className="mini-progress">
                      <div style={{ width: `${value * 100}%` }} />
                    </div>
                  )}
                </div>
              ))}
            </div>

            <h4>Reasons</h4>
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

            {result.caveat_text && (
              <div className="notice">
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

            {result.claims?.length > 0 && (
              <>
                <h4>Claim analysis</h4>
                {result.claims.map((claim, index) => (
                  <div className="claim" key={index}>
                    <strong>{claim.status}</strong>
                    <p>{claim.claim}</p>
                    <small>
                      Support:{" "}
                      {typeof claim.support === "number"
                        ? `${(claim.support * 100).toFixed(1)}%`
                        : "Unavailable"}
                    </small>
                  </div>
                ))}
              </>
            )}

            <p className="request-id">Request ID: {result.request_id}</p>

            <a href="#graph" className="view-graph-link">
              View decision graph →
            </a>
          </>
        )}
      </section>
    </div>
  );
}

// ── Root App ───────────────────────────────────────────────────────────────

export default function App() {
  const [route, navigate] = useHashRoute();
  const [lastTrace, setLastTrace] = useState(null);
  const [useMock, setUseMock] = useState(false);

  // When an insight or escalation selects a request_id, switch to graph view.
  // Since we only have the request_id (not the full trace), we show a
  // "trace not available" state with the request_id displayed.
  const handleNavigateToGraph = useCallback(
    (requestId) => {
      // If the current trace matches, just navigate.
      if (lastTrace?.request_id === requestId) {
        navigate("#graph");
        return;
      }
      // Otherwise navigate to graph with a placeholder — the user can see
      // the request_id. Future work: fetch trace from audit API.
      setLastTrace((prev) =>
        prev?.request_id === requestId
          ? prev
          : { request_id: requestId, _missing: true }
      );
      navigate("#graph");
    },
    [lastTrace, navigate]
  );

  return (
    <main className="app">
      <header className="header">
        <div className="brand">
          <span className="brand-icon" aria-hidden="true">A</span>
          <div>
            <h1>AEGIS</h1>
            <p>Evidence-aware AI middleware</p>
          </div>
        </div>
        <Nav route={route} />
      </header>

      <section className="intro">
        <p className="eyebrow">RELIABILITY WORKSPACE</p>
        <h2>Ask questions. Evaluate the evidence.</h2>
        <p>
          Ingest a PDF, ask a question, and inspect the AEGIS reliability
          decision — including the decision graph and cross-decision insights.
        </p>
      </section>

      {/* Views */}
      {route === "#workspace" && (
        <WorkspaceView onResult={(trace) => { setLastTrace(trace); setUseMock(false); }} />
      )}

      {route === "#graph" && (
        <GraphView
          trace={lastTrace?._missing ? null : lastTrace}
          useMock={useMock}
          onToggleMock={setUseMock}
        />
      )}

      {route === "#insights" && (
        <InsightsDashboard onNavigateToGraph={handleNavigateToGraph} />
      )}

      {route === "#escalations" && (
        <EscalationQueue onOpenGraph={handleNavigateToGraph} />
      )}

      <footer>AEGIS · Evidence before confidence</footer>
    </main>
  );
}
