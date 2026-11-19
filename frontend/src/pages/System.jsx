/** System – /v1/health, /v1/config, /v1/graph/status. */
import { API, useApi } from "../api.js";
import { DASH, dateTime, int, isNum, timeAgo } from "../format.js";
import { Async, ErrorState, KeyValue, PageHeader, Panel, RefreshButton, StatusDot } from "../ui/index.jsx";

function fmt(v) {
  if (v === null || v === undefined) return DASH;
  if (isNum(v)) return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

function ProfileMatrix({ profiles }) {
  const names = Object.keys(profiles);
  const rows = [];
  const add = (group, key, get) => rows.push({ group, key, get });
  const first = profiles[names[0]] ?? {};
  for (const k of Object.keys(first.thresholds ?? {})) add("Score thresholds (decide at or above)", k, (p) => p.thresholds?.[k]);
  for (const k of Object.keys(first.vetoes ?? {})) add("Signal vetoes", k, (p) => p.vetoes?.[k]);
  for (const k of Object.keys(first.claims ?? {})) add("Claim rules", k, (p) => p.claims?.[k]);
  if (names.some((n) => profiles[n].answer_min_signal !== undefined)) add("Other", "answer_min_signal", (p) => p.answer_min_signal);

  let lastGroup = null;
  return (
    <div className="table-wrap">
      <table className="table table--compact matrix">
        <thead>
          <tr>
            <th>Rule</th>
            {names.map((n) => (
              <th key={n} className="num">
                {n}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="muted">description</td>
            {names.map((n) => (
              <td key={n} className="num muted" style={{ whiteSpace: "normal" }}>
                {profiles[n].description || DASH}
              </td>
            ))}
          </tr>
          {rows.flatMap((r) => {
            const out = [];
            if (r.group !== lastGroup) {
              lastGroup = r.group;
              out.push(
                <tr key={`g-${r.group}`} className="group-row">
                  <td colSpan={names.length + 1}>{r.group}</td>
                </tr>
              );
            }
            out.push(
              <tr key={`${r.group}-${r.key}`}>
                <td className="mono">{r.key}</td>
                {names.map((n) => (
                  <td key={n} className="num mono">
                    {fmt(r.get(profiles[n]))}
                  </td>
                ))}
              </tr>
            );
            return out;
          })}
        </tbody>
      </table>
    </div>
  );
}

function CountsGrid({ counts }) {
  const entries = Object.entries(counts ?? {});
  if (!entries.length) return <p className="muted small">{DASH}</p>;
  return (
    <dl className="counts-grid">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{int(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function System({ health, graphStatus }) {
  const config = useApi("/v1/config");
  const g = graphStatus.data;
  const w = g?.writer;

  return (
    <>
      <PageHeader title="System" description="Service health, the active decision policy and the state of the decision graph.">
        <RefreshButton
          onClick={() => {
            health.reload();
            graphStatus.reload();
            config.reload();
          }}
          loading={health.loading || graphStatus.loading || config.loading}
        />
      </PageHeader>

      <div className="stack">
        <div className="grid-2">
          <Panel title="API">
            {health.error ? (
              <ErrorState error={health.error} onRetry={health.reload} />
            ) : (
              <KeyValue
                items={[
                  ["Status", <StatusDot key="s" state={health.data ? "ok" : "unknown"} label={health.data?.status ?? "checking"} />],
                  ["Base URL", <span key="u" className="mono">{API}</span>],
                  ["API version", <span key="a" className="mono">{health.data?.api_version ?? DASH}</span>],
                  ["Policy version", <span key="p" className="mono">{health.data?.policy_version ?? DASH}</span>],
                  ["Signals", health.data?.signals?.length ? <span key="g" className="tags">{health.data.signals.map((s) => <span key={s} className="tag">{s}</span>)}</span> : DASH],
                ]}
              />
            )}
          </Panel>

          <Panel title="Graph writer" description="Decision traces are written to Neo4j by a background queue, never on the decision path.">
            {graphStatus.error ? (
              <ErrorState error={graphStatus.error} onRetry={graphStatus.reload} />
            ) : (
              <KeyValue
                items={[
                  [
                    "Neo4j",
                    <StatusDot
                      key="n"
                      state={!g ? "unknown" : g.connected ? "ok" : g.configured ? "down" : "warn"}
                      label={!g ? "checking" : g.connected ? "connected" : g.configured ? "configured, unreachable" : "not configured"}
                    />,
                  ],
                  ["Written", <span key="w" className="mono">{w ? int(w.written) : DASH}</span>],
                  ["Pending", <span key="p" className="mono">{w ? int(w.pending) : DASH}</span>],
                  ["Failed", <span key="f" className="mono">{w ? int(w.failed) : DASH}</span>],
                  ["Dropped (queue full)", <span key="d" className="mono">{w ? int(w.dropped) : DASH}</span>],
                  ["Last success", w?.last_success_at ? <span key="l" title={dateTime(w.last_success_at)}>{timeAgo(w.last_success_at)}</span> : DASH],
                  ["Last error", w?.last_error ? <span key="e" className="mono" style={{ color: "var(--escalate)" }}>{w.last_error}</span> : DASH],
                ]}
              />
            )}
          </Panel>
        </div>

        <div className="grid-2">
          <Panel title="Graph nodes" description="Stored nodes by label.">
            {g?.connected ? <CountsGrid counts={g.counts} /> : <p className="muted small">{g ? "Graph not connected." : "Checking…"}</p>}
          </Panel>
          <Panel title="Graph relationships" description="Stored relationships by type.">
            {g?.connected ? <CountsGrid counts={g.relationships} /> : <p className="muted small">{g ? "Graph not connected." : "Checking…"}</p>}
          </Panel>
        </div>

        <Async q={config} rows={6} errorTitle="Policy config unavailable">
          {(c) => (
            <div className="stack">
              <Panel title="Scoring weights" description={`Policy version ${c.version}. Weights combine the signals into the answerability score.`}>
                <table className="table table--compact table--plain" style={{ maxWidth: 520 }}>
                  <tbody>
                    {Object.entries(c.weights ?? {}).map(([k, v]) => (
                      <tr key={k}>
                        <td className="mono">{k}</td>
                        <td className="num mono">{fmt(v)}</td>
                        <td className="bar-cell">
                          <span className="minibar">
                            <span style={{ width: `${Math.min(1, v) * 100}%` }} />
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
              <Panel title="Policy profiles" description="Each request names a profile. Vetoes override the score; claim rules set a minimum decision for unsupported or contradicted claims." flush>
                <ProfileMatrix profiles={c.profiles ?? {}} />
              </Panel>
              <p className="muted small">Values as served by <span className="mono">GET /v1/config</span>.</p>
            </div>
          )}
        </Async>
      </div>
    </>
  );
}
