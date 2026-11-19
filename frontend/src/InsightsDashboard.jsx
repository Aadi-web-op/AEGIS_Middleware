/**
 * InsightsDashboard – Fetches and displays cross-decision analytics from /v1/insights/*.
 *
 * Endpoints used (actual, verified against the backend):
 *   GET /v1/insights/conflicting-document-pairs
 *   GET /v1/insights/stale-document-retrievals
 *   GET /v1/insights/abstain-topics
 *   GET /v1/insights/decisions-by-decision?decision=ESCALATE
 *   GET /v1/insights/escalation-clusters
 *   GET /v1/insights/impacted-decisions?source=...&version=...
 *
 * All requests are real API calls. No mock statistics are shown as real data.
 * Each section has loading, empty, error and retry states.
 */
import { useCallback, useEffect, useState } from "react";

const API = import.meta.env.VITE_AEGIS_API ?? "http://127.0.0.1:8000";

function useInsight(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetch_ = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(url);
      if (r.status === 503) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? "Database unavailable");
      }
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${r.status}`);
      }
      setData(await r.json());
    } catch (e) {
      setError(e.message ?? "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => { fetch_(); }, [fetch_]);
  return { data, loading, error, retry: fetch_ };
}

// ── Reusable section wrapper ────────────────────────────────────────────────

function InsightSection({ title, icon, desc, loading, error, retry, children, empty }) {
  return (
    <div className="insight-section">
      <h3>
        <span className="insight-icon" aria-hidden="true">{icon}</span>
        {title}
      </h3>
      {desc && <p className="insight-desc">{desc}</p>}
      {loading && <p className="muted">Loading…</p>}
      {!loading && error && (
        <div className="insight-error">
          <p>
            {error.includes("unavailable")
              ? "Persisted insights cannot be loaded — the database is unavailable."
              : error}
          </p>
          <button onClick={retry} className="retry-btn">
            Retry
          </button>
        </div>
      )}
      {!loading && !error && empty && (
        <p className="muted">No data yet.</p>
      )}
      {!loading && !error && !empty && children}
    </div>
  );
}

// ── 1. Conflicting requests ─────────────────────────────────────────────────

function ConflictingPairs({ onSelectRequestId }) {
  const { data, loading, error, retry } = useInsight(
    `${API}/v1/insights/conflicting-document-pairs?limit=10`
  );
  const rows = data ?? [];
  return (
    <InsightSection
      title="High-contradiction requests"
      icon="!=" desc="Requests where the retrieved sources disagreed with each other or with the answer."
      loading={loading}
      error={error}
      retry={retry}
      empty={rows.length === 0}
    >
      <table className="insight-table">
        <thead>
          <tr>
            <th>Query</th>
            <th>Contradiction</th>
            <th>Decision</th>
            <th>Time</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.request_id}>
              <td className="truncate" title={r.query}>{r.query || "—"}</td>
              <td>
                <span className="score-pill score-red">
                  {(r.contradiction_score * 100).toFixed(0)}%
                </span>
              </td>
              <td>{r.decision}</td>
              <td className="ts">{r.timestamp ? r.timestamp.slice(0, 19).replace("T", " ") : "—"}</td>
              <td>
                <button
                  className="link-btn"
                  onClick={() => onSelectRequestId(r.request_id)}
                  aria-label={`View graph for request ${r.request_id}`}
                >
                  Graph →
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </InsightSection>
  );
}

// ── 2. Stale evidence retrievals ────────────────────────────────────────────

function StaleRetrievals({ onSelectRequestId }) {
  const { data, loading, error, retry } = useInsight(
    `${API}/v1/insights/stale-document-retrievals?limit=15`
  );
  const rows = data ?? [];
  return (
    <InsightSection
      title="Stale evidence retrievals"
      icon="⏲" desc="Requests answered from evidence that scored low on freshness."
      loading={loading}
      error={error}
      retry={retry}
      empty={rows.length === 0}
    >
      <table className="insight-table">
        <thead>
          <tr>
            <th>Query</th>
            <th>Freshness</th>
            <th>Decision</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.request_id}>
              <td className="truncate" title={r.query}>{r.query || "—"}</td>
              <td>
                <span className="score-pill score-amber">
                  {(r.freshness_score * 100).toFixed(0)}%
                </span>
              </td>
              <td>{r.decision}</td>
              <td>
                <button
                  className="link-btn"
                  onClick={() => onSelectRequestId(r.request_id)}
                >
                  Graph →
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </InsightSection>
  );
}

// ── 3. Abstain topics ───────────────────────────────────────────────────────

function AbstainTopics() {
  const { data, loading, error, retry } = useInsight(
    `${API}/v1/insights/abstain-topics?limit=15`
  );
  const rows = data ?? [];
  return (
    <InsightSection
      title="Topics leading to ABSTAIN"
      icon="∅" desc="Questions the documents could not answer — your documentation gaps."
      loading={loading}
      error={error}
      retry={retry}
      empty={rows.length === 0}
    >
      <table className="insight-table">
        <thead>
          <tr>
            <th>Query</th>
            <th>Reason codes</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.request_id}>
              <td className="truncate" title={r.query}>{r.query || "—"}</td>
              <td>
                {(r.reason_codes ?? []).map((c, i) => (
                  <span key={`${c}-${i}`} className="reason-chip">{c}</span>
                ))}
              </td>
              <td className="ts">{r.timestamp ? r.timestamp.slice(0, 19).replace("T", " ") : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </InsightSection>
  );
}

// ── 4. Past escalations ─────────────────────────────────────────────────────

function PastEscalations({ onSelectRequestId }) {
  const { data, loading, error, retry } = useInsight(
    `${API}/v1/insights/decisions-by-decision?decision=ESCALATE&limit=15`
  );
  const rows = data ?? [];
  return (
    <InsightSection
      title="Past escalation decisions"
      icon="↑" desc="Recent decisions routed to a human reviewer."
      loading={loading}
      error={error}
      retry={retry}
      empty={rows.length === 0}
    >
      <table className="insight-table">
        <thead>
          <tr>
            <th>Query</th>
            <th>Score</th>
            <th>Reason codes</th>
            <th>Time</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.request_id}>
              <td className="truncate" title={r.query}>{r.query || "—"}</td>
              <td>
                {r.answerability_score !== null && r.answerability_score !== undefined
                  ? `${(r.answerability_score * 100).toFixed(0)}%`
                  : "—"}
              </td>
              <td>
                {(r.reason_codes ?? []).map((c, i) => (
                  <span key={`${c}-${i}`} className="reason-chip">{c}</span>
                ))}
              </td>
              <td className="ts">{r.timestamp ? r.timestamp.slice(0, 19).replace("T", " ") : "—"}</td>
              <td>
                <button
                  className="link-btn"
                  onClick={() => onSelectRequestId(r.request_id)}
                >
                  Graph →
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </InsightSection>
  );
}

// ── 5. Escalation clusters ──────────────────────────────────────────────────

function EscalationClusters({ onSelectRequestId }) {
  const { data, loading, error, retry } = useInsight(
    `${API}/v1/insights/escalation-clusters?limit=20`
  );
  const rows = data ?? [];
  return (
    <InsightSection
      title="Escalations by root cause"
      icon="≡" desc="Escalations grouped by shared root cause, so one fix clears many."
      loading={loading}
      error={error}
      retry={retry}
      empty={rows.length === 0}
    >
      {rows.map((cluster) => (
        <div key={cluster.reason_code} className="cluster-block">
          <div className="cluster-header">
            <span className="reason-chip">{cluster.reason_code}</span>
            <strong>{cluster.count} escalation{cluster.count !== 1 ? "s" : ""}</strong>
          </div>
          <div className="cluster-ids">
            {(cluster.request_ids ?? []).slice(0, 5).map((rid) => (
              <button
                key={rid}
                className="link-btn small"
                onClick={() => onSelectRequestId(rid)}
                title={`View graph for request ${rid}`}
              >
                {rid.slice(0, 12)}…
              </button>
            ))}
            {(cluster.request_ids ?? []).length > 5 && (
              <span className="muted">+{cluster.request_ids.length - 5} more</span>
            )}
          </div>
        </div>
      ))}
    </InsightSection>
  );
}

// ── 6. Blast-radius impact (Feature #6) ─────────────────────────────────────

function BlastRadius({ onSelectRequestId }) {
  const [source, setSource] = useState("");
  const [version, setVersion] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function search(e) {
    e.preventDefault();
    if (!source.trim()) return;
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const params = new URLSearchParams({ source: source.trim() });
      if (version.trim()) params.set("version", version.trim());
      const r = await fetch(`${API}/v1/insights/impacted-decisions?${params}`);
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${r.status}`);
      }
      setResults(await r.json());
    } catch (err) {
      setError(err.message ?? "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  const rows = results ?? [];

  return (
    <InsightSection
      title="Blast-radius impact"
      icon="💥"
      desc="When a source document is updated, see which past decisions relied on it and may now be stale."
      loading={false}
      error={null}
      retry={() => {}}
      empty={false}
    >
      <form className="blast-radius-form" onSubmit={search}>
        <label>
          Document source
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="e.g. hr-policy.pdf"
            required
          />
        </label>
        <label>
          Version (optional)
          <input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="e.g. 2024.2"
          />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Searching…" : "Find impacted decisions"}
        </button>
      </form>

      {error && (
        <div className="insight-error">
          <p>{error}</p>
          <button onClick={(e) => search(e)} className="retry-btn">Retry</button>
        </div>
      )}

      {results !== null && rows.length === 0 && !loading && !error && (
        <p className="muted">No decisions found for this source document.</p>
      )}

      {rows.length > 0 && (
        <div>
          <p className="muted" style={{ marginBottom: 10 }}>
            {rows.length} decision{rows.length !== 1 ? "s" : ""} relied on this document and may need re-evaluation.
          </p>
          {rows.map((r) => (
            <div key={r.request_id} className="impact-card">
              <div className="impact-card-info">
                <div className="truncate" title={r.query}>{r.query || "—"}</div>
                <div className="ts">{r.timestamp ? r.timestamp.slice(0, 19).replace("T", " ") : ""}</div>
              </div>
              <span className="impact-card-decision">{r.decision}</span>
              <button
                className="link-btn"
                onClick={() => onSelectRequestId(r.request_id)}
                aria-label={`View graph for request ${r.request_id}`}
              >
                Graph →
              </button>
            </div>
          ))}
        </div>
      )}
    </InsightSection>
  );
}

// ── Main dashboard ──────────────────────────────────────────────────────────

export default function InsightsDashboard({ onNavigateToGraph }) {
  return (
    <div className="insights-dashboard">
      <div className="insights-header">
        <h2>Insights dashboard</h2>
      </div>
      <div className="insights-grid">
        <ConflictingPairs onSelectRequestId={onNavigateToGraph} />
        <StaleRetrievals onSelectRequestId={onNavigateToGraph} />
        <AbstainTopics />
        <PastEscalations onSelectRequestId={onNavigateToGraph} />
        <EscalationClusters onSelectRequestId={onNavigateToGraph} />
        <BlastRadius onSelectRequestId={onNavigateToGraph} />
      </div>
    </div>
  );
}
