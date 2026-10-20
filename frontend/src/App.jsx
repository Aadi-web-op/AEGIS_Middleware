
import { useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

function App() {
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

      setIngestMessage(
        `PDF ingested successfully. Chunks added: ${data.chunks_added}`
      );
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
    } catch (err) {
      setError(`${err.message}. Check the backend and provider configuration.`);
    } finally {
      setAskLoading(false);
    }
  }

  const signals = result?.signals
    ? Object.entries(result.signals)
    : [];

  return (
    <main className="app">
      <header className="header">
        <div className="brand">
          <span className="brand-icon">A</span>
          <div>
            <h1>AEGIS</h1>
            <p>Evidence-aware AI middleware</p>
          </div>
        </div>
        <span className="status">RAG workspace</span>
      </header>

      <section className="intro">
        <p className="eyebrow">RELIABILITY WORKSPACE</p>
        <h2>Ask questions. Evaluate the evidence.</h2>
        <p>
          Ingest a PDF, ask a question about its contents, and inspect
          the AEGIS reliability decision.
        </p>
      </section>

      <div className="layout">
        <div className="panel form-panel">
          <h3>1. Knowledge base</h3>
          <p className="muted">
            Ingest a PDF before asking questions. The backend currently
            stores the knowledge base in memory.
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
            Your question will be sent to the RAG backend for retrieval,
            answer generation, and AEGIS evaluation.
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

          {askLoading && <p>Retrieving evidence and evaluating the answer...</p>}

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
                      width: `${
                        (result.answerability_score ?? 0) * 100
                      }%`,
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

              <p className="request-id">
                Request ID: {result.request_id}
              </p>
            </>
          )}
        </section>
      </div>

      <footer>AEGIS · Evidence before confidence</footer>
    </main>
  );
}

export default App;
