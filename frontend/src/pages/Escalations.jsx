/** Escalation queue – /v1/escalations (GET, PATCH). */
import { Fragment, useState } from "react";
import { apiPatch, enc, useApi } from "../api.js";
import { DASH, dateTime, humanCode, timeAgo, truncate } from "../format.js";
import { href } from "../router.js";
import { Async, DecisionBadge, EmptyState, Icon, PageHeader, Panel, RefreshButton, Segmented } from "../ui/index.jsx";

const STATUSES = ["pending", "in_review", "resolved", "dismissed"];

// Mirrors VALID_TRANSITIONS in app/escalation/queue.py.
const ACTIONS = {
  pending: [
    ["in_review", "Start review", "btn--secondary"],
    ["resolved", "Resolve", ""],
    ["dismissed", "Dismiss", "btn--danger"],
  ],
  in_review: [
    ["resolved", "Resolve", ""],
    ["dismissed", "Dismiss", "btn--danger"],
    ["pending", "Return to queue", "btn--ghost"],
  ],
  resolved: [],
  dismissed: [],
};

function StatusLabel({ status }) {
  return <span className={`esc-status esc-status--${status}`}>{humanCode(status)}</span>;
}

function Detail({ item, onUpdated }) {
  const [notes, setNotes] = useState(item.notes ?? "");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const actions = ACTIONS[item.status] ?? [];

  const update = async (status) => {
    setBusy(status);
    setError(null);
    try {
      await apiPatch(`/v1/escalations/${enc(item.escalation_id)}`, { status, notes: notes.trim() || null });
      onUpdated();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="esc-detail__grid">
        <div className="esc-detail__block">
          <h4>Question</h4>
          <p>{item.query ?? DASH}</p>
        </div>
        <div className="esc-detail__block">
          <h4>AI answer</h4>
          <p>{item.answer ?? DASH}</p>
        </div>
        <div className="esc-detail__block">
          <h4>Why it was escalated</h4>
          <p>{item.reason}</p>
        </div>
        <div className="esc-detail__block">
          <h4>Record</h4>
          <p className="small">
            <span className="mono">{item.escalation_id}</span> · created {dateTime(item.created_at)} · updated {dateTime(item.updated_at)}
          </p>
          <p className="small" style={{ marginTop: 4 }}>
            <a className="link" href={href("decisions", item.request_id)}>
              Open decision
            </a>{" "}
            ·{" "}
            <a className="link" href={href("graph", "decision", item.request_id)}>
              Decision graph
            </a>
          </p>
        </div>
      </div>
      {actions.length > 0 ? (
        <div className="esc-actions">
          <div className="field">
            <label className="field__label" htmlFor={`notes-${item.escalation_id}`}>
              Reviewer notes
            </label>
            <textarea id={`notes-${item.escalation_id}`} className="textarea" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          {actions.map(([status, label, cls]) => (
            <button key={status} type="button" className={`btn btn--sm ${cls}`} disabled={Boolean(busy)} onClick={() => update(status)}>
              {busy === status ? "Saving…" : label}
            </button>
          ))}
        </div>
      ) : (
        item.notes && (
          <div className="esc-detail__block" style={{ marginTop: 8 }}>
            <h4>Reviewer notes</h4>
            <p>{item.notes}</p>
          </div>
        )
      )}
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}

export default function Escalations({ onEscalationsChanged }) {
  const [status, setStatus] = useState("pending");
  const [open, setOpen] = useState(null);
  const q = useApi(`/v1/escalations?limit=200${status ? `&status=${status}` : ""}`);

  const onUpdated = () => {
    q.reload();
    onEscalationsChanged?.();
  };

  return (
    <>
      <PageHeader title="Escalations" description="Answers AEGIS routed to a human. Review each one, add notes, and resolve or dismiss it.">
        <RefreshButton onClick={q.reload} loading={q.loading} />
      </PageHeader>
      <div className="toolbar">
        <Segmented
          label="Filter by status"
          value={status}
          onChange={(v) => {
            setStatus(v);
            setOpen(null);
          }}
          options={[{ value: "", label: "All" }, ...STATUSES.map((s) => ({ value: s, label: humanCode(s) }))]}
        />
      </div>
      <Panel flush>
        <Async q={q} rows={6}>
          {(items) =>
            !items.length ? (
              <div className="pad">
                <EmptyState title={status ? `No ${humanCode(status).toLowerCase()} escalations` : "No escalations"}>
                  {status === "pending" ? "Nothing is waiting for human review." : "Escalations are created automatically when AEGIS decides ESCALATE."}
                </EmptyState>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="table table--stack">
                  <thead>
                    <tr>
                      <th aria-label="Expand" />
                      <th>Status</th>
                      <th>Question</th>
                      <th>Decision</th>
                      <th>Reason</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it) => {
                      const isOpen = open === it.escalation_id;
                      return (
                        <Fragment key={it.escalation_id}>
                          <tr className={isOpen ? "is-clickable is-selected" : "is-clickable"} onClick={() => setOpen(isOpen ? null : it.escalation_id)}>
                            <td>
                              <button
                                type="button"
                                className="icon-btn"
                                aria-expanded={isOpen}
                                aria-label={isOpen ? "Collapse" : "Expand"}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpen(isOpen ? null : it.escalation_id);
                                }}
                              >
                                <Icon name="chevron" size={14} className={isOpen ? "rot-90" : undefined} />
                              </button>
                            </td>
                            <td data-label="Status">
                              <StatusLabel status={it.status} />
                            </td>
                            <td data-label="Question" className="cell-query">
                              {truncate(it.query, 110) || <span className="mono">{it.request_id}</span>}
                            </td>
                            <td data-label="Decision">
                              <DecisionBadge decision={it.decision} />
                            </td>
                            <td data-label="Reason" className="wrap">
                              {truncate(it.reason, 110)}
                            </td>
                            <td data-label="Created" title={dateTime(it.created_at)}>
                              {timeAgo(it.created_at)}
                            </td>
                          </tr>
                          {isOpen && (
                            <tr className="esc-detail">
                              <td colSpan={6}>
                                <Detail item={it} onUpdated={onUpdated} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          }
        </Async>
      </Panel>
    </>
  );
}
