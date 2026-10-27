/**
 * EscalationQueue – Existing escalation list view with graph navigation links.
 *
 * Fetches from GET /v1/escalations (existing endpoint).
 * Adds a "View Graph" action per item using the request_id.
 * Preserves all existing queue functionality and status update actions.
 */
import { useCallback, useEffect, useState } from "react";

const API = "http://127.0.0.1:8000";
const STATUSES = ["pending", "in_review", "resolved", "dismissed"];

const STATUS_COLORS = {
  pending: "#ef4444",
  in_review: "#eab308",
  resolved: "#22c55e",
  dismissed: "#6b7280",
};

export default function EscalationQueue({ onOpenGraph }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filterStatus, setFilterStatus] = useState("");
  const [updating, setUpdating] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = filterStatus
        ? `${API}/v1/escalations?status=${filterStatus}&limit=50`
        : `${API}/v1/escalations?limit=50`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setItems(await r.json());
    } catch (e) {
      setError(e.message ?? "Failed to load escalations");
    } finally {
      setLoading(false);
    }
  }, [filterStatus]);

  useEffect(() => { load(); }, [load]);

  async function updateStatus(escalationId, newStatus) {
    setUpdating(escalationId);
    try {
      const r = await fetch(`${API}/v1/escalations/${escalationId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${r.status}`);
      }
      await load();
    } catch (e) {
      alert(`Failed to update: ${e.message}`);
    } finally {
      setUpdating(null);
    }
  }

  return (
    <div className="escalation-queue">
      <div className="eq-header">
        <h2>Escalation queue</h2>
        <div className="eq-controls">
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            aria-label="Filter by status"
            style={{ width: "auto" }}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s.replace("_", " ")}</option>
            ))}
          </select>
          <button onClick={load} className="retry-btn" style={{ width: "auto" }}>
            Refresh
          </button>
        </div>
      </div>

      {loading && <p className="muted">Loading escalations…</p>}
      {!loading && error && (
        <div className="insight-error">
          <p>{error}</p>
          <button onClick={load} className="retry-btn">Retry</button>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <div className="empty">
          <span className="empty-icon">✓</span>
          <h4>No escalations</h4>
          <p>Nothing requiring human review right now.</p>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="eq-list">
          {items.map((item) => (
            <div key={item.escalation_id} className="eq-item">
              <div className="eq-item-top">
                <span
                  className="eq-status-badge"
                  style={{ borderColor: STATUS_COLORS[item.status] ?? "#6b7280",
                           color: STATUS_COLORS[item.status] ?? "#6b7280" }}
                >
                  {item.status.replace("_", " ").toUpperCase()}
                </span>
                <span className="muted eq-id">
                  {item.escalation_id}
                </span>
                <button
                  className="link-btn"
                  onClick={() => onOpenGraph(item.request_id)}
                  aria-label={`View decision graph for escalation ${item.escalation_id}`}
                >
                  View graph →
                </button>
              </div>

              <div className="eq-item-body">
                {item.query && (
                  <p>
                    <strong>Query:</strong> {item.query}
                  </p>
                )}
                <p>
                  <strong>Reason:</strong> {item.reason}
                </p>
                <p>
                  <strong>Decision:</strong> {item.decision}
                </p>
                {item.notes && (
                  <p>
                    <strong>Notes:</strong> {item.notes}
                  </p>
                )}
                <p className="muted" style={{ fontSize: 11 }}>
                  Request ID: {item.request_id} · Created:{" "}
                  {item.created_at?.slice(0, 19).replace("T", " ") ?? "—"}
                </p>
              </div>

              {/* Status transition buttons */}
              <div className="eq-actions">
                {item.status === "pending" && (
                  <>
                    <button
                      disabled={updating === item.escalation_id}
                      onClick={() => updateStatus(item.escalation_id, "in_review")}
                      className="dg-btn"
                    >
                      Mark in review
                    </button>
                    <button
                      disabled={updating === item.escalation_id}
                      onClick={() => updateStatus(item.escalation_id, "dismissed")}
                      className="dg-btn"
                      style={{ background: "#374151" }}
                    >
                      Dismiss
                    </button>
                  </>
                )}
                {item.status === "in_review" && (
                  <>
                    <button
                      disabled={updating === item.escalation_id}
                      onClick={() => updateStatus(item.escalation_id, "resolved")}
                      className="dg-btn"
                    >
                      Resolve
                    </button>
                    <button
                      disabled={updating === item.escalation_id}
                      onClick={() => updateStatus(item.escalation_id, "dismissed")}
                      className="dg-btn"
                      style={{ background: "#374151" }}
                    >
                      Dismiss
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
