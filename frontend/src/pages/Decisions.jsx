/** Decision history – /v1/decisions (SQLite audit log) with a detail drawer. */
import { useCallback, useMemo, useState } from "react";
import { enc, useApi } from "../api.js";
import DecisionResult from "../components/DecisionResult.jsx";
import { DASH, DECISIONS, DECISION_META, dateTime, int, ms, score, timeAgo, truncate } from "../format.js";
import { go, href } from "../router.js";
import { Async, CopyButton, DecisionBadge, Drawer, EmptyState, ErrorState, KeyValue, Loading, Notice, PageHeader, Panel, RefreshButton, Segmented, Tag } from "../ui/index.jsx";

const PAGE = 50;

function DecisionDetail({ id, config }) {
  const q = useApi(`/v1/decisions/${enc(id)}`);
  if (q.error) {
    return q.error.kind === "notfound" ? (
      <EmptyState title="Decision not found">
        No decision with id <span className="mono">{id}</span> is in the audit log.
      </EmptyState>
    ) : (
      <ErrorState error={q.error} onRetry={q.reload} />
    );
  }
  if (!q.data) return <Loading rows={8} />;
  const { record, response } = q.data;
  const request = { query: record.query, answer: record.answer, profile: record.profile };
  if (!response) {
    return (
      <div className="stack">
        <Notice title="Full response not stored">
          This decision was logged before full responses were kept, so only the audit summary is available.
        </Notice>
        <Panel title="Audit record">
          <KeyValue
            items={[
              ["Decision", <DecisionBadge key="d" decision={record.decision} />],
              ["Question", record.query ?? DASH],
              ["Answer", record.answer ?? DASH],
              ["Score", <span key="s" className="mono">{score(record.answerability_score)}</span>],
              ["Reason codes", (record.reason_codes ?? []).length ? <span key="r" className="tags">{record.reason_codes.map((c, i) => <Tag key={`${c}-${i}`}>{c}</Tag>)}</span> : DASH],
              ["Profile", <span key="p" className="mono">{record.profile ?? DASH}</span>],
              ["Logged", dateTime(record.timestamp)],
              ["Latency", ms(record.latency_ms)],
              record.error_message ? ["Error", record.error_message] : null,
            ]}
          />
        </Panel>
        <a className="btn btn--secondary btn--sm" href={href("graph", "decision", id)}>
          Look for it in the graph explorer
        </a>
      </div>
    );
  }
  return (
    <div className="stack">
      {record.generation_success === false && record.error_message && (
        <Notice tone="escalate" title="Answer generation failed">
          {record.error_message}
        </Notice>
      )}
      <DecisionResult response={response} request={request} config={config} />
    </div>
  );
}

export default function Decisions({ args }) {
  const [decision, setDecision] = useState("");
  const [offset, setOffset] = useState(0);
  const [text, setText] = useState("");
  const config = useApi("/v1/config");
  const path = `/v1/decisions?limit=${PAGE}&offset=${offset}${decision ? `&decision=${decision}` : ""}`;
  const q = useApi(path);
  const openId = args[0] ?? null;
  const close = useCallback(() => go("decisions"), []);

  const items = useMemo(() => {
    const list = q.data?.items ?? [];
    const t = text.trim().toLowerCase();
    if (!t) return list;
    return list.filter(
      (r) =>
        r.query?.toLowerCase().includes(t) ||
        r.request_id?.toLowerCase().includes(t) ||
        (r.reason_codes ?? []).some((c) => c.toLowerCase().includes(t))
    );
  }, [q.data, text]);

  const counts = q.data?.counts ?? {};
  const total = q.data?.total;
  const filteredTotal = decision ? counts[decision] ?? 0 : total;
  const options = [
    { value: "", label: "All", count: total !== undefined ? int(total) : undefined },
    ...DECISIONS.map((d) => ({ value: d, label: DECISION_META[d].label, count: q.data ? int(counts[d] ?? 0) : undefined })),
  ];

  return (
    <>
      <PageHeader title="Decisions" description="Every evaluation AEGIS has logged, newest first. Open one to see its claims, evidence, reasons and graph.">
        <RefreshButton onClick={q.reload} loading={q.loading} />
      </PageHeader>

      <div className="toolbar">
        <Segmented
          label="Filter by decision"
          options={options}
          value={decision}
          onChange={(v) => {
            setDecision(v);
            setOffset(0);
          }}
        />
        <span className="toolbar__spacer" />
        <label className="sr-only" htmlFor="dec-search">
          Filter this page
        </label>
        <input
          id="dec-search"
          className="input input--sm input--search"
          type="search"
          placeholder="Filter this page by text, id or reason"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>

      <Panel flush>
        <Async q={q} rows={8}>
          {(data) =>
            data.items.length === 0 ? (
              <div className="pad">
                <EmptyState
                  title={decision ? `No ${DECISION_META[decision].label.toLowerCase()} decisions` : "No decisions recorded"}
                  action={<a className="btn btn--sm" href={href("evaluate")}>Run an evaluation</a>}
                >
                  Decisions appear here as soon as <span className="mono">POST /v1/evaluate</span> or the RAG pipeline is called.
                </EmptyState>
              </div>
            ) : (
              <>
                <div className="table-wrap">
                  <table className="table table--stack">
                    <thead>
                      <tr>
                        <th>Logged</th>
                        <th>Question</th>
                        <th>Decision</th>
                        <th className="num">Score</th>
                        <th>Reasons</th>
                        <th>Profile</th>
                        <th className="num">Latency</th>
                        <th>Request id</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((r) => (
                        <tr
                          key={r.request_id}
                          className={openId === r.request_id ? "is-clickable is-selected" : "is-clickable"}
                          onClick={() => go("decisions", r.request_id)}
                        >
                          <td data-label="Logged" title={dateTime(r.timestamp)}>
                            {timeAgo(r.timestamp)}
                          </td>
                          <td data-label="Question" className="cell-query">
                            <a href={href("decisions", r.request_id)} onClick={(e) => e.stopPropagation()}>
                              {truncate(r.query, 120) || DASH}
                            </a>
                            {r.generation_success === false && <span className="cell-sub">generation failed</span>}
                          </td>
                          <td data-label="Decision">
                            <DecisionBadge decision={r.decision} />
                          </td>
                          <td data-label="Score" className="num mono">
                            {score(r.answerability_score)}
                          </td>
                          <td data-label="Reasons">
                            {(r.reason_codes ?? []).length ? (
                              <span className="tags">
                                {[...new Set(r.reason_codes)].slice(0, 3).map((c, i) => (
                                  <Tag key={`${c}-${i}`}>{c}</Tag>
                                ))}
                                {new Set(r.reason_codes).size > 3 && <span className="muted small">+{new Set(r.reason_codes).size - 3}</span>}
                              </span>
                            ) : (
                              <span className="muted">{DASH}</span>
                            )}
                          </td>
                          <td data-label="Profile" className="mono">
                            {r.profile ?? DASH}
                          </td>
                          <td data-label="Latency" className="num mono">
                            {ms(r.latency_ms)}
                          </td>
                          <td data-label="Request id" className="mono muted" title={r.request_id}>
                            {r.request_id?.slice(0, 10)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {items.length === 0 && (
                    <div className="pad">
                      <EmptyState title="No matches on this page">Clear the text filter to see all {data.items.length} rows.</EmptyState>
                    </div>
                  )}
                </div>
                <div className="pager">
                  <span>
                    {int(offset + 1)}–{int(offset + data.items.length)} of {int(filteredTotal)}
                  </span>
                  <span className="row">
                    <button type="button" className="btn btn--secondary btn--sm" disabled={offset === 0 || q.loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                      Newer
                    </button>
                    <button
                      type="button"
                      className="btn btn--secondary btn--sm"
                      disabled={q.loading || offset + data.items.length >= (filteredTotal ?? 0)}
                      onClick={() => setOffset(offset + PAGE)}
                    >
                      Older
                    </button>
                  </span>
                </div>
              </>
            )
          }
        </Async>
      </Panel>

      <Drawer
        open={Boolean(openId)}
        onClose={close}
        wide
        title="Decision detail"
        subtitle={
          openId && (
            <span className="row">
              <span className="mono">{openId}</span>
              <CopyButton value={openId} label="Copy request id" />
              <a className="link" href={href("graph", "decision", openId)}>
                Graph explorer
              </a>
            </span>
          )
        }
      >
        {openId && <DecisionDetail key={openId} id={openId} config={config.data} />}
      </Drawer>
    </>
  );
}
