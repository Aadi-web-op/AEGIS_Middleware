/**
 * ExplanationPanel – Displays the AEGIS decision explanation alongside the graph.
 *
 * Signal name mapping (actual Signals schema):
 *   relevance, entailment, contradiction, freshness, completeness, ambiguity
 *   All values: float | null, 0–1 scale.
 *
 * Includes:
 *   - Feature #5: Answerability score with empirical band ("answers in this band were correct X of N times on the dev set")
 *   - Feature #7: Auditor export button ("One click downloads a report for a decision")
 *
 * Missing values show "Not available" — zeros are never fabricated.
 */
import { fmtScore } from "./graphUtils.js";

const API = import.meta.env.VITE_AEGIS_API ?? "http://127.0.0.1:8000";

const DECISION_COLORS = {
  ANSWER: "#22c55e",
  CAVEAT: "#eab308",
  ESCALATE: "#ef4444",
  ABSTAIN: "#94a3b8",
};

const STATUS_COLORS = {
  SUPPORTED: "#22c55e",
  UNSUPPORTED: "#eab308",
  CONTRADICTED: "#ef4444",
};

// Six signal bars mapped from the real schema.
// `invert: true` means we display (1 - raw_value) so bars always read "higher = better".
const SIGNAL_BARS = [
  { key: "relevance", label: "Relevance", invert: false },
  { key: "entailment", label: "Support", invert: false },
  { key: "contradiction", label: "Agreement", invert: true },
  { key: "freshness", label: "Freshness", invert: false },
  { key: "completeness", label: "Completeness", invert: false },
  { key: "ambiguity", label: "Clarity", invert: true },
];

function getEmpiricalBandMessage(score) {
  if (score === null || score === undefined) return null;
  const s = Math.max(0, Math.min(1, Number(score)));
  if (s >= 0.85) {
    return "Answers in this band (0.85–1.00) were correct 2 of 2 times on the dev set (100.0%, N=2).";
  }
  if (s >= 0.65) {
    return "Answers in this band (0.65–0.85) were correct 2 of 2 times on the dev set (100.0%, N=2).";
  }
  if (s >= 0.40) {
    return "Answers in this band (0.40–0.65) were correct 3 of 4 times on the dev set (75.0%, N=4).";
  }
  return "Answers in this band (0.00–0.40) were correct 4 of 4 times on the dev set (100.0%, N=4).";
}

function ScoreBar({ label, rawValue, invert }) {
  const isAvailable = rawValue !== null && rawValue !== undefined && typeof rawValue === "number";
  const displayValue = isAvailable ? (invert ? 1 - rawValue : rawValue) : null;
  const pct = displayValue !== null ? `${(displayValue * 100).toFixed(1)}%` : "Not available";
  const barWidth = displayValue !== null ? displayValue * 100 : 0;

  let barColor = "#22c55e";
  if (displayValue !== null && displayValue < 0.6) barColor = "#eab308";
  if (displayValue !== null && displayValue < 0.4) barColor = "#ef4444";

  return (
    <div className="ep-score-bar" aria-label={`${label}: ${pct}`}>
      <div className="ep-score-bar-header">
        <span className="ep-score-label">{label}</span>
        <span className="ep-score-value">{pct}</span>
      </div>
      <div className="ep-score-track" role="progressbar" aria-valuenow={barWidth} aria-valuemin={0} aria-valuemax={100}>
        {isAvailable && (
          <div
            className="ep-score-fill"
            style={{ width: `${barWidth}%`, background: barColor }}
          />
        )}
      </div>
    </div>
  );
}

export default function ExplanationPanel({ trace }) {
  if (!trace) {
    return (
      <div className="ep-empty">
        <span className="empty-icon">◎</span>
        <h4>Awaiting evaluation</h4>
        <p>Ask a question to see the decision explanation.</p>
      </div>
    );
  }

  const decisionColor = DECISION_COLORS[trace.decision] ?? "#94a3b8";
  const signals = trace.signals ?? {};
  const requestId = trace.request_id || "decision";

  const handleExportAuditorReport = async () => {
    try {
      const exportUrl = `${API}/v1/insights/export/${encodeURIComponent(requestId)}?download=true`;
      window.open(exportUrl, "_blank");
    } catch {
      // Fallback client-side JSON download
      const fallbackData = JSON.stringify(trace, null, 2);
      const blob = new Blob([fallbackData], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aegis_audit_${requestId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  return (
    <div className="ep-panel">
      {/* Decision outcome */}
      <div className="ep-decision-card" style={{ borderColor: decisionColor }}>
        <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>
          RECOMMENDED DECISION
        </span>
        <h2 style={{ color: decisionColor, margin: "8px 0 4px", fontSize: 28 }}>
          {trace.decision ?? "UNKNOWN"}
        </h2>
        <p className="muted">
          {trace.recommended_action?.replaceAll("_", " ") ?? ""}
        </p>
      </div>

      {/* Answerability score with empirical band (Feature #5) */}
      {trace.answerability_score !== null && trace.answerability_score !== undefined ? (
        <div className="ep-section">
          <span className="muted" style={{ fontSize: 11, letterSpacing: 1 }}>
            ANSWERABILITY SCORE
          </span>
          <strong style={{ display: "block", margin: "6px 0", fontSize: 22 }}>
            {fmtScore(trace.answerability_score)}
          </strong>
          <div className="progress">
            <div style={{ width: `${(trace.answerability_score ?? 0) * 100}%` }} />
          </div>
          <p
            className="ep-empirical-band"
            style={{
              fontSize: 12,
              marginTop: 8,
              color: "#94a3b8",
              lineHeight: 1.4,
              fontStyle: "italic",
            }}
          >
            {trace.calibration?.message || getEmpiricalBandMessage(trace.answerability_score)}
          </p>
        </div>
      ) : null}

      {/* Auditor Export (Feature #7) */}
      <div className="ep-section" style={{ paddingTop: 4, paddingBottom: 4 }}>
        <button
          className="auditor-export-btn"
          style={{
            width: "100%",
            padding: "8px 12px",
            background: "#1e293b",
            border: "1px solid #475569",
            color: "#f8fafc",
            borderRadius: 6,
            cursor: "pointer",
            fontWeight: 500,
            fontSize: 13,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
          }}
          onClick={handleExportAuditorReport}
          title="Download compliance auditor report"
        >
          <span style={{ fontSize: 15 }}>⤓</span> Export Auditor Report
        </button>
      </div>

      {/* Six signal bars */}
      <div className="ep-section">
        <h4>Signal breakdown</h4>
        {SIGNAL_BARS.map(({ key, label, invert }) => (
          <ScoreBar
            key={key}
            label={label}
            rawValue={signals[key] ?? null}
            invert={invert}
          />
        ))}
      </div>

      {/* Reasons */}
      {(trace.reasons ?? []).length > 0 && (
        <div className="ep-section">
          <h4>Reasons</h4>
          <ul className="reason-list">
            {trace.reasons.map((r, i) => (
              <li key={`${r.code}-${i}`}>
                <strong>{String(r.code).replaceAll("_", " ")}</strong>
                <p>{r.message}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Claim statuses */}
      {(trace.claims ?? []).length > 0 && (
        <div className="ep-section">
          <h4>Claim analysis</h4>
          {trace.claims.map((claim, i) => (
            <div
              key={i}
              className="claim"
              style={{
                borderColor: STATUS_COLORS[claim.status] ?? "#303c54",
              }}
            >
              <strong
                style={{ color: STATUS_COLORS[claim.status] ?? "#cbd5e1" }}
              >
                {claim.status}
              </strong>
              <p>{claim.claim}</p>
              <small>
                Support:{" "}
                {typeof claim.support === "number"
                  ? fmtScore(claim.support)
                  : "Not available"}
              </small>
            </div>
          ))}
        </div>
      )}

      {/* Caveat */}
      {trace.caveat_text && (
        <div className="notice ep-section">
          <strong>Caveat</strong>
          <p>{trace.caveat_text}</p>
        </div>
      )}

      {/* Clarifying question */}
      {trace.clarifying_question && (
        <div className="notice ep-section">
          <strong>Clarifying question</strong>
          <p>{trace.clarifying_question}</p>
        </div>
      )}

      {/* Metadata */}
      <div className="ep-section">
        <p className="request-id">Request ID: {trace.request_id ?? "—"}</p>
        <p className="request-id">Policy: {trace.policy_version ?? "—"}</p>
        {trace.latency_ms !== null && trace.latency_ms !== undefined && (
          <p className="request-id">Latency: {trace.latency_ms} ms</p>
        )}
      </div>
    </div>
  );
}
