/**
 * Cross-decision intelligence – /v1/intelligence/*.
 * Every row links back to the decisions it was computed from.
 */
import { useState } from "react";
import { useApi } from "../api.js";
import { FindingRow, RequestLinks } from "../components/Findings.jsx";
import TrendBars from "../components/TrendBars.jsx";
import { DASH, dateTime, humanCode, int, pct, truncate } from "../format.js";
import { href } from "../router.js";
import { Async, EmptyState, Notice, PageHeader, Panel, RefreshButton, Segmented, Tag } from "../ui/index.jsx";

const SECTIONS = [
  ["findings", "Findings"],
  ["documents", "Document reliability"],
  ["contradictions", "Contradictions"],
  ["stale", "Stale versions"],
  ["gaps", "Knowledge gaps"],
  ["reasons", "Reasons"],
  ["trends", "Trends"],
];

function DocLink({ id }) {
  if (!id) return <span className="muted">{DASH}</span>;
  return (
    <a className="link mono" href={href("documents", id)} title={id}>
      {id.replace(/^doc:/, "")}
    </a>
  );
}

function Excluded({ items }) {
  if (!items?.length) return null;
  return (
    <div className="panel__foot">
      {items.map((e) => (
        <p key={e.rule}>
          {int(e.count)} decision{e.count === 1 ? "" : "s"} skipped by <span className="mono">{e.rule}</span>: {e.reason}
        </p>
      ))}
    </div>
  );
}

function FindingsPanel({ summary }) {
  return (
    <Panel id="findings" title="Findings" description="Patterns seen in at least two distinct decisions, ranked by severity. Each cites the decisions and the query it came from." flush>
      <Async q={summary} rows={5}>
        {(s) =>
          s.graph?.available === false ? (
            <div className="pad">
              <div className="state state--offline">
                <p className="state__title">Graph database offline</p>
                <p className="state__body">{s.graph.reason} Findings need the decision graph; decision counts and trends below still come from the audit log.</p>
              </div>
            </div>
          ) : s.findings?.length ? (
            <>
              <ul className="findings">
                {s.findings.map((f) => (
                  <FindingRow key={f.id} finding={f} />
                ))}
              </ul>
              <Excluded items={s.excluded} />
            </>
          ) : (
            <div className="pad">
              <EmptyState title="No findings">
                {s.data?.sufficient
                  ? `None of the ${int(s.data.graph_decisions)} stored decisions share a failure pattern that meets the two-decision minimum.`
                  : "There is not enough data yet. Findings appear once enough evaluations are stored in the graph."}
              </EmptyState>
            </div>
          )
        }
      </Async>
    </Panel>
  );
}

function DocumentsPanel() {
  const q = useApi("/v1/intelligence/documents");
  return (
    <Panel id="documents" title="Document reliability" description="How each document version performed in the decisions that retrieved it." flush>
      <Async q={q} rows={5}>
        {(d) =>
          d.items?.length ? (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th className="num" title={d.definitions?.decisions}>Decisions</th>
                      <th className="num" title={d.definitions?.supported_claims}>Supported</th>
                      <th className="num" title={d.definitions?.contradicted_claims}>Contradicted</th>
                      <th className="num" title={d.definitions?.unsupported_rate}>Not supported</th>
                      <th className="num">Conflicts</th>
                      <th className="num">Escalated</th>
                      <th className="num">Abstained</th>
                      <th>Superseded by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((r) => (
                      <tr key={r.doc_id}>
                        <td>
                          <DocLink id={r.doc_id} />
                          {r.date && <span className="cell-sub mono">{r.date}</span>}
                        </td>
                        <td className="num">{int(r.decisions)}</td>
                        <td className="num">{int(r.supported_claims)}</td>
                        <td className="num">{int(r.contradicted_claims)}</td>
                        <td className="num" title={`${r.unsupported_or_contradicted_claims} of ${r.claims_in_decisions} claims`}>
                          {pct(r.unsupported_rate)} <span className="muted">({int(r.unsupported_or_contradicted_claims)}/{int(r.claims_in_decisions)})</span>
                        </td>
                        <td className="num">{int(r.conflicts)}</td>
                        <td className="num">{int(r.escalations)}</td>
                        <td className="num">{int(r.abstains)}</td>
                        <td>{r.superseded_by?.length ? r.superseded_by.map((id) => <DocLink key={id} id={id} />) : <span className="muted">{DASH}</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {d.definitions && (
                <div className="panel__foot">
                  “Not supported” counts claims that were not supported in decisions that retrieved the document (co-occurrence, not
                  causation): {d.definitions.unsupported_rate}.
                </div>
              )}
            </>
          ) : (
            <div className="pad">
              <EmptyState title="No documents in the graph">Documents appear after evaluations with sourced evidence are written to the graph.</EmptyState>
            </div>
          )
        }
      </Async>
    </Panel>
  );
}

function ContradictionsPanel() {
  const q = useApi("/v1/intelligence/contradictions");
  return (
    <Panel id="contradictions" title="Contradictions between documents" description="Document pairs whose evidence passages conflict (stored CONFLICTS_WITH edges)." flush>
      <Async q={q} rows={4}>
        {(d) =>
          d.items?.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Documents</th>
                    <th>Kinds</th>
                    <th className="num">Conflict edges</th>
                    <th className="num">Decisions affected</th>
                    <th>Example values</th>
                    <th>Decisions</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((p) => (
                    <tr key={`${p.doc_a}|${p.doc_b}`}>
                      <td className="wrap">
                        <DocLink id={p.doc_a} />
                        <span className="cell-sub">conflicts with</span>
                        <DocLink id={p.doc_b} />
                      </td>
                      <td>
                        <span className="tags">{p.kinds?.length ? p.kinds.map((k) => <Tag key={k}>{k}</Tag>) : DASH}</span>
                      </td>
                      <td className="num">{int(p.conflict_count)}</td>
                      <td className="num" title={`${p.decision_count} of ${p.decisions_retrieving_both} decisions that retrieved both`}>
                        {int(p.decision_count)} <span className="muted">of {int(p.decisions_retrieving_both)}</span>
                      </td>
                      <td className="wrap">
                        {p.sample_values?.length ? (
                          p.sample_values.slice(0, 2).map((s, i) => (
                            <span key={i} className="cell-sub mono">
                              {s.kind}: {String(s.value_a ?? DASH)} vs {String(s.value_b ?? DASH)}
                            </span>
                          ))
                        ) : (
                          <span className="muted">{DASH}</span>
                        )}
                      </td>
                      <td className="wrap">
                        <RequestLinks ids={p.request_ids} max={4} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="pad">
              <EmptyState title="No conflicting documents">No stored decision found two evidence passages that disagree.</EmptyState>
            </div>
          )
        }
      </Async>
    </Panel>
  );
}

function StalePanel() {
  const q = useApi("/v1/intelligence/stale-usage");
  return (
    <Panel
      id="stale"
      title="Superseded versions still in use"
      description="Older document versions retrieved by decisions made after a newer version of the same source was available."
      flush
    >
      <Async q={q} rows={4}>
        {(d) => (
          <>
            {d.items?.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Older version</th>
                      <th>Superseded by</th>
                      <th>Since</th>
                      <th className="num">Stale decisions</th>
                      <th>Relied on it</th>
                      <th>All stale decisions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((s) => (
                      <tr key={`${s.older_doc_id}|${s.newer_doc_id}`}>
                        <td>
                          <DocLink id={s.older_doc_id} />
                        </td>
                        <td>
                          <DocLink id={s.newer_doc_id} />
                          {s.supersedes_basis && <span className="cell-sub">by {s.supersedes_basis}</span>}
                        </td>
                        <td>
                          <span className="mono">{s.cutoff ? String(s.cutoff).slice(0, 19).replace("T", " ") : DASH}</span>
                          {s.cutoff_basis && <span className="cell-sub">{humanCode(s.cutoff_basis)}</span>}
                        </td>
                        <td className="num" title={`${s.stale_decisions} of ${s.eligible_decisions} eligible decisions`}>
                          {int(s.stale_decisions)} <span className="muted">of {int(s.eligible_decisions)}</span>
                        </td>
                        <td className="wrap">
                          <RequestLinks ids={s.relied_request_ids} max={4} />
                        </td>
                        <td className="wrap">
                          <RequestLinks ids={s.request_ids} max={4} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="pad">
                <EmptyState title="No stale usage">No decision retrieved a document version after it was superseded.</EmptyState>
              </div>
            )}
            <Excluded items={d.excluded} />
          </>
        )}
      </Async>
    </Panel>
  );
}

function GapsPanel() {
  const q = useApi("/v1/intelligence/knowledge-gaps");
  return (
    <Panel id="gaps" title="Knowledge gaps" description="Question topics where AEGIS most often abstains or escalates, i.e. the knowledge base does not answer them well." flush>
      <Async q={q} rows={4}>
        {(d) => (
          <>
            {d.items?.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Topic</th>
                      <th className="num">Decisions</th>
                      <th className="num">Abstained</th>
                      <th className="num">Escalated</th>
                      <th className="num">Gap rate</th>
                      <th>Sample questions</th>
                      <th>Decisions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((g) => (
                      <tr key={g.topic}>
                        <td className="mono">{g.topic}</td>
                        <td className="num">{int(g.decisions)}</td>
                        <td className="num">{int(g.abstains)}</td>
                        <td className="num">{int(g.escalations)}</td>
                        <td className="num">{pct(g.gap_rate)}</td>
                        <td className="wrap">
                          {(g.sample_queries ?? []).slice(0, 2).map((s, i) => (
                            <span key={i} className="cell-sub">
                              {truncate(s, 90)}
                            </span>
                          ))}
                        </td>
                        <td className="wrap">
                          <RequestLinks ids={g.request_ids} max={4} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="pad">
                <EmptyState title="No knowledge gaps">
                  No topic has {d.min_decisions_per_topic ?? 2} or more decisions with abstentions or escalations.
                </EmptyState>
              </div>
            )}
            <Excluded items={d.excluded} />
          </>
        )}
      </Async>
    </Panel>
  );
}

function ReasonsPanel({ summary }) {
  return (
    <Panel id="reasons" title="Reason codes" description="How often each reason was cited across all logged decisions (audit log).">
      <Async q={summary} rows={3}>
        {(s) => {
          const entries = Object.entries(s.reason_distribution ?? {}).sort((a, b) => b[1] - a[1]);
          if (!entries.length) return <EmptyState title="No reasons recorded" />;
          const max = entries[0][1] || 1;
          return (
            <table className="table table--compact table--plain">
              <tbody>
                {entries.map(([code, n]) => (
                  <tr key={code}>
                    <td className="mono">{code}</td>
                    <td className="num">{int(n)}</td>
                    <td className="bar-cell">
                      <span className="minibar">
                        <span style={{ width: `${(n / max) * 100}%` }} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          );
        }}
      </Async>
    </Panel>
  );
}

function TrendsPanel() {
  const [bucket, setBucket] = useState("day");
  const q = useApi(`/v1/intelligence/trends?bucket=${bucket}`);
  return (
    <Panel
      id="trends"
      title="Decisions over time"
      description="Counts per bucket from the audit log."
      actions={
        <Segmented
          label="Bucket size"
          value={bucket}
          onChange={setBucket}
          options={[
            { value: "day", label: "Day" },
            { value: "hour", label: "Hour" },
          ]}
        />
      }
    >
      <Async q={q} rows={3}>
        {(d) =>
          !d.items?.length ? (
            <EmptyState title="No decisions logged" />
          ) : d.items.length < 2 ? (
            <p className="muted">
              All {int(d.items[0].total)} decisions fall in one {bucket} (<span className="mono">{d.items[0].bucket}</span>). A trend needs at
              least two buckets{bucket === "day" ? "; try hourly buckets" : ""}.
            </p>
          ) : (
            <TrendBars items={d.items} bucket={bucket} />
          )
        }
      </Async>
    </Panel>
  );
}

export default function Intelligence() {
  const summary = useApi("/v1/intelligence/summary");
  const [nonce, setNonce] = useState(0);
  const s = summary.data;
  const needed = s?.data ? Math.max(0, (s.data.min_required ?? 0) - (s.data.graph_decisions ?? 0)) : 0;
  const graphOffline = s?.graph?.available === false;

  const reload = () => {
    summary.reload();
    setNonce((n) => n + 1);
  };

  return (
    <>
      <PageHeader
        title="Intelligence"
        description="Patterns across many decisions: unreliable sources, conflicting documents, outdated versions in use and unanswered topics."
      >
        {s?.generated_at && <span className="muted small">Generated {dateTime(s.generated_at)}</span>}
        <RefreshButton onClick={reload} loading={summary.loading} />
      </PageHeader>

      <div className="stack">
        {graphOffline && (
          <Notice tone="caveat" title="Graph database offline">
            {s.graph.reason} Findings, document reliability, contradictions, stale versions and knowledge gaps are computed from the decision
            graph and are unavailable until it is back. Reason codes and trends below come from the audit log.
          </Notice>
        )}
        {!graphOffline && s?.data && !s.data.sufficient && (
          <Notice tone="accent" title={needed > 0 ? `Not enough data yet: ${needed} more evaluation${needed === 1 ? "" : "s"} needed` : "Not enough data yet"}>
            {s.data.message} Results below are computed from the {int(s.data.graph_decisions)} decision
            {s.data.graph_decisions === 1 ? "" : "s"} currently in the graph and should not be read as patterns.
          </Notice>
        )}

        <nav className="row" aria-label="Sections">
          {SECTIONS.filter(([id]) => !graphOffline || ["findings", "reasons", "trends"].includes(id)).map(([id, label]) => (
            <button key={id} type="button" className="btn btn--ghost btn--sm" onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
              {label}
            </button>
          ))}
        </nav>

        <div key={nonce} className="stack">
          {graphOffline ? (
            <Panel id="findings" title="Graph-based analysis" description="Findings, document reliability, contradictions, stale versions, knowledge gaps.">
              <div className="state state--offline state--compact">
                <p className="state__title">Unavailable while the graph database is offline</p>
                <p className="state__body">Start Neo4j and refresh. Nothing is estimated or cached in its place.</p>
                <div className="state__action">
                  <button type="button" className="btn btn--secondary btn--sm" onClick={reload}>
                    Retry
                  </button>
                </div>
              </div>
            </Panel>
          ) : (
            <>
              <FindingsPanel summary={summary} />
              <DocumentsPanel />
              <ContradictionsPanel />
              <StalePanel />
              <GapsPanel />
            </>
          )}
          <div className="grid-2">
            <ReasonsPanel summary={summary} />
            <TrendsPanel />
          </div>
        </div>
      </div>
    </>
  );
}
