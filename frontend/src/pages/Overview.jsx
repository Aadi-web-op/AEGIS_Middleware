/** Overview – what has AEGIS decided, and what needs attention. */
import { useApi } from "../api.js";
import DistributionBar from "../components/DistributionBar.jsx";
import { FindingRow } from "../components/Findings.jsx";
import { DASH, DECISIONS, int, ratio, score, timeAgo, truncate } from "../format.js";
import { go, href } from "../router.js";
import { Async, DecisionBadge, EmptyState, ErrorState, Loading, Metric, Notice, PageHeader, Panel, RefreshButton, StatusDot } from "../ui/index.jsx";

function share(counts, key) {
  const total = DECISIONS.reduce((s, d) => s + (counts?.[d] ?? 0), 0);
  return { text: ratio(counts?.[key] ?? 0, total, 1), sub: total ? `${int(counts?.[key] ?? 0)} of ${int(total)} decisions` : "no decisions yet" };
}

function RecentDecisions({ q }) {
  return (
    <Async q={q} rows={6}>
      {(data) =>
        data.items?.length ? (
          <div className="table-wrap">
            <table className="table table--stack">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Question</th>
                  <th>Decision</th>
                  <th className="num">Score</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.request_id} className="is-clickable" onClick={() => go("decisions", r.request_id)}>
                    <td data-label="When" className="muted" title={r.timestamp}>
                      {timeAgo(r.timestamp)}
                    </td>
                    <td data-label="Question" className="cell-query">
                      <a href={href("decisions", r.request_id)} onClick={(e) => e.stopPropagation()}>
                        {truncate(r.query, 90) || DASH}
                      </a>
                    </td>
                    <td data-label="Decision">
                      <DecisionBadge decision={r.decision} />
                    </td>
                    <td data-label="Score" className="num mono">
                      {score(r.answerability_score)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No decisions recorded" action={<a className="btn btn--sm" href={href("evaluate")}>Run an evaluation</a>}>
            Every call to <span className="mono">POST /v1/evaluate</span> is logged here.
          </EmptyState>
        )
      }
    </Async>
  );
}

export default function Overview({ graphStatus, health }) {
  const summary = useApi("/v1/intelligence/summary");
  const recent = useApi("/v1/decisions?limit=8");

  // Decision counts: the audit log is the system of record.
  const counts = recent.data?.counts ?? summary.data?.decision_distribution ?? null;
  const total = recent.data?.total ?? summary.data?.data?.total_decisions ?? null;
  const sdata = summary.data?.data;
  const findings = summary.data?.findings ?? [];
  const esc = share(counts, "ESCALATE");
  const abs = share(counts, "ABSTAIN");
  const loadingTop = !counts && (recent.loading || summary.loading);
  const writer = graphStatus?.data?.writer;

  const reload = () => {
    summary.reload();
    recent.reload();
    graphStatus?.reload?.();
    health?.reload?.();
  };

  return (
    <>
      <PageHeader title="Overview" description="Decisions AEGIS has made on AI answers, and the patterns across them that need attention.">
        <RefreshButton onClick={reload} loading={summary.loading || recent.loading} />
      </PageHeader>

      <div className="stack">
        {recent.error && summary.error ? (
          <ErrorState error={recent.error} onRetry={reload} />
        ) : (
          <div className="metrics" aria-busy={loadingTop}>
            <Metric
              label="Requests logged"
              value={loadingTop ? DASH : int(total)}
              sub={recent.data?.generation_failures ? `incl. ${int(recent.data.generation_failures)} where answer generation failed` : "audit log (SQLite)"}
            />
            <Metric
              label="Decisions in graph"
              value={sdata ? int(sdata.graph_decisions) : DASH}
              sub={summary.data?.graph?.available === false ? "graph offline" : sdata ? `analysis needs ≥ ${sdata.min_required}` : "—"}
            />
            <Metric label="Escalated" value={loadingTop ? DASH : esc.text} sub={esc.sub} />
            <Metric label="Abstained" value={loadingTop ? DASH : abs.text} sub={abs.sub} />
          </div>
        )}

        {sdata && !sdata.sufficient && sdata.message && summary.data?.graph?.available !== false && (
          <Notice tone="accent" title="Not enough data for cross-decision findings yet">
            {sdata.message}
          </Notice>
        )}

        <div className="grid-2">
          <Panel title="Decision distribution" description="All logged evaluations, by outcome.">
            {counts ? <DistributionBar counts={counts} /> : recent.loading ? <Loading rows={4} /> : <ErrorState error={recent.error} compact onRetry={recent.reload} />}
          </Panel>

          <Panel
            title="Top findings"
            description="Patterns observed in at least two decisions."
            actions={
              <a className="link small" href={href("intelligence")}>
                All intelligence
              </a>
            }
            flush
          >
            <Async q={summary} rows={4}>
              {(s) =>
                s.graph?.available === false ? (
                  <div className="state state--offline" style={{ padding: "16px" }}>
                    <p className="state__title">Graph database offline</p>
                    <p className="state__body">{s.graph.reason ?? "Findings need the decision graph."}</p>
                  </div>
                ) : findings.length ? (
                  <ul className="findings">
                    {findings.slice(0, 5).map((f) => (
                      <FindingRow key={f.id} finding={f} compact />
                    ))}
                  </ul>
                ) : (
                  <div style={{ padding: "0 16px" }}>
                    <EmptyState title="No findings">
                      {s.data?.sufficient
                        ? "No pattern met the two-decision minimum in the stored decisions."
                        : "Findings appear once enough decisions are stored in the graph."}
                    </EmptyState>
                  </div>
                )
              }
            </Async>
          </Panel>
        </div>

        <Panel
          title="Recent decisions"
          actions={
            <a className="link small" href={href("decisions")}>
              Decision history
            </a>
          }
          flush
        >
          <RecentDecisions q={recent} />
        </Panel>

        <Panel title="System" actions={<a className="link small" href={href("system")}>Details</a>}>
          <dl className="finding__meta" style={{ marginTop: 0 }}>
            <div>
              <dt>API</dt>
              <dd>
                <StatusDot state={health?.error ? "down" : health?.data ? "ok" : "unknown"} label={health?.error ? "unreachable" : health?.data?.status ?? "checking"} />
              </dd>
            </div>
            <div>
              <dt>Policy version</dt>
              <dd className="mono">{health?.data?.policy_version ?? DASH}</dd>
            </div>
            <div>
              <dt>Signals</dt>
              <dd className="mono">{health?.data?.signals?.length ?? DASH}</dd>
            </div>
            <div>
              <dt>Graph</dt>
              <dd>
                <StatusDot
                  state={graphStatus?.data?.connected ? "ok" : graphStatus?.data?.configured ? "down" : "unknown"}
                  label={graphStatus?.data ? (graphStatus.data.connected ? "connected" : graphStatus.data.configured ? "unreachable" : "not configured") : "checking"}
                />
              </dd>
            </div>
            <div>
              <dt>Graph writes</dt>
              <dd className="mono">{writer ? int(writer.written) : DASH}</dd>
            </div>
            <div>
              <dt>Pending / failed / dropped</dt>
              <dd className="mono">{writer ? `${int(writer.pending)} / ${int(writer.failed)} / ${int(writer.dropped)}` : DASH}</dd>
            </div>
          </dl>
        </Panel>
      </div>
    </>
  );
}
