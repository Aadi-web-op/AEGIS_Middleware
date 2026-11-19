/**
 * Documents – evidence sources and their versions (/v1/graph/documents),
 * joined with reliability (/v1/intelligence/documents). Opening a document
 * shows its blast radius (/v1/intelligence/blast-radius).
 */
import { useCallback, useMemo } from "react";
import { enc, useApi } from "../api.js";
import { DASH, int, pct, timeAgo } from "../format.js";
import { go, href } from "../router.js";
import { Async, DecisionBadge, Drawer, EmptyState, ErrorState, KeyValue, Loading, PageHeader, Panel, RefreshButton, Tag } from "../ui/index.jsx";

function DocLink({ id }) {
  return (
    <a className="link mono" href={href("documents", id)}>
      {id.replace(/^doc:/, "")}
    </a>
  );
}

function versionKey(d) {
  return `${d.date ?? ""}|${String(d.version ?? "").padStart(8, "0")}`;
}

function BlastList({ group, empty }) {
  if (!group?.decisions?.length) return <p className="muted small">{empty}</p>;
  return (
    <ul className="blast-list">
      {group.decisions.map((d) => (
        <li className="blast-item" key={d.request_id}>
          <DecisionBadge decision={d.decision} />
          <a className="link mono" href={href("decisions", d.request_id)} title={d.request_id}>
            {d.request_id}
          </a>
          <span className="muted small" title={d.created_at}>
            {timeAgo(d.created_at)}
          </span>
          {(d.supported_claims > 0 || d.contradicted_claims > 0 || d.claims?.length > 0) && (
            <span className="blast-item__claims">
              {d.supported_claims > 0 && `${d.supported_claims} claim${d.supported_claims === 1 ? "" : "s"} supported`}
              {d.supported_claims > 0 && d.contradicted_claims > 0 && " · "}
              {d.contradicted_claims > 0 && `${d.contradicted_claims} contradicted`}
              {d.claims?.length > 0 && (
                <>
                  {" "}
                  — “{d.claims[0]}”{d.claims.length > 1 ? ` +${d.claims.length - 1}` : ""}
                </>
              )}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function DocumentDetail({ id, graphRow, intelRow }) {
  const q = useApi(`/v1/intelligence/blast-radius?doc_id=${enc(id)}`);
  const doc = q.data?.document ?? graphRow ?? {};
  return (
    <div className="stack">
      <Panel title="Document">
        <KeyValue
          items={[
            ["Id", <span key="i" className="mono">{id}</span>],
            ["Source", <span key="s" className="mono">{doc.source ?? graphRow?.source ?? DASH}</span>],
            ["Version", <span key="v" className="mono">{doc.version ?? DASH}</span>],
            ["Date", <span key="d" className="mono">{doc.date ?? DASH}</span>],
            ["Supersedes", graphRow?.supersedes?.length ? <span key="sp" className="tags">{graphRow.supersedes.map((x) => <DocLink key={x} id={x} />)}</span> : DASH],
            ["Superseded by", graphRow?.superseded_by?.length ? <span key="sb" className="tags">{graphRow.superseded_by.map((x) => <DocLink key={x} id={x} />)}</span> : DASH],
            intelRow ? ["Not-supported rate", `${pct(intelRow.unsupported_rate)} (${int(intelRow.unsupported_or_contradicted_claims)} of ${int(intelRow.claims_in_decisions)} claims)`] : null,
            intelRow ? ["Escalated / abstained", `${int(intelRow.escalations)} / ${int(intelRow.abstains)}`] : null,
          ]}
        />
        <div className="form-actions">
          <a className="btn btn--secondary btn--sm" href={href("graph", "node", id)}>
            Open in graph explorer
          </a>
        </div>
      </Panel>

      <Panel title="Blast radius" description="Decisions that would be affected if this document is wrong or withdrawn.">
        {q.error ? (
          q.error.kind === "notfound" ? (
            <EmptyState title="Not in the decision graph">{q.error.message}</EmptyState>
          ) : (
            <ErrorState error={q.error} onRetry={q.reload} />
          )
        ) : !q.data ? (
          <Loading rows={4} />
        ) : (
          <div className="stack">
            {q.data.explanation && <p className="small">{q.data.explanation}</p>}
            <div>
              <h4>
                Relied on it <span className="count">{int(q.data.relied_on?.count)}</span>
              </h4>
              <p className="muted small" style={{ marginBottom: 6 }}>
                A claim in the decision was supported by (or contradicted by) evidence from this document.
              </p>
              <BlastList group={q.data.relied_on} empty="No decision cited this document as support." />
            </div>
            <div>
              <h4>
                Retrieved only <span className="count">{int(q.data.retrieved_only?.count)}</span>
              </h4>
              <p className="muted small" style={{ marginBottom: 6 }}>
                The document was among the passages considered, but no claim depended on it.
              </p>
              <BlastList group={q.data.retrieved_only} empty="No decision only retrieved this document." />
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

export default function Documents({ args }) {
  const graphDocs = useApi("/v1/graph/documents?limit=500");
  const intelDocs = useApi("/v1/intelligence/documents");
  const openId = args[0] ?? null;
  const close = useCallback(() => go("documents"), []);

  const intelById = useMemo(() => new Map((intelDocs.data?.items ?? []).map((r) => [r.doc_id, r])), [intelDocs.data]);
  const groups = useMemo(() => {
    const m = new Map();
    for (const d of graphDocs.data?.items ?? []) {
      const k = d.source ?? d.doc_id;
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(d);
    }
    return [...m.entries()]
      .map(([source, docs]) => [source, docs.sort((a, b) => versionKey(b).localeCompare(versionKey(a)))])
      .sort((a, b) => a[0].localeCompare(b[0]));
  }, [graphDocs.data]);

  const graphRow = graphDocs.data?.items?.find((d) => d.doc_id === openId);

  return (
    <>
      <PageHeader
        title="Documents"
        description="Source documents behind the evidence, grouped by source with their versions, what supersedes what, and how each version was used."
      >
        <RefreshButton
          onClick={() => {
            graphDocs.reload();
            intelDocs.reload();
          }}
          loading={graphDocs.loading}
        />
      </PageHeader>

      <Panel flush>
        <Async q={graphDocs} rows={8}>
          {(d) =>
            !d.items?.length ? (
              <div className="pad">
                <EmptyState title="No documents in the graph" action={<a className="btn btn--sm" href={href("evaluate")}>Run an evaluation</a>}>
                  Documents are created from the <span className="mono">source</span> and <span className="mono">version</span> of evidence passages.
                </EmptyState>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Version</th>
                      <th>Date</th>
                      <th>Relationship</th>
                      <th className="num">Decisions</th>
                      <th className="num">Supported claims</th>
                      <th className="num">Contradicted claims</th>
                      <th className="num">Conflicts</th>
                      <th className="num" title={intelDocs.data?.definitions?.unsupported_rate}>
                        Not supported
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map(([source, docs]) => [
                      <tr key={`g-${source}`} className="group-row">
                        <td colSpan={8}>
                          <span className="mono">{source}</span> · {docs.length} version{docs.length === 1 ? "" : "s"}
                        </td>
                      </tr>,
                      ...docs.map((doc) => {
                        const ir = intelById.get(doc.doc_id);
                        return (
                          <tr
                            key={doc.doc_id}
                            className={openId === doc.doc_id ? "is-clickable is-selected" : "is-clickable"}
                            onClick={() => go("documents", doc.doc_id)}
                          >
                            <td>
                              <a className="link mono" href={href("documents", doc.doc_id)} onClick={(e) => e.stopPropagation()}>
                                {doc.version ?? "unversioned"}
                              </a>
                            </td>
                            <td className="mono">{doc.date ?? DASH}</td>
                            <td>
                              <span className="tags">
                                {doc.superseded_by?.length > 0 && (
                                  <Tag tone="caveat" title={doc.superseded_by.join(", ")}>
                                    superseded by {doc.superseded_by.map((x) => x.split("@")[1] ?? x).join(", ")}
                                  </Tag>
                                )}
                                {doc.supersedes?.length > 0 && (
                                  <Tag tone="accent" title={doc.supersedes.join(", ")}>
                                    supersedes {doc.supersedes.map((x) => x.split("@")[1] ?? x).join(", ")}
                                  </Tag>
                                )}
                                {!doc.superseded_by?.length && !doc.supersedes?.length && <span className="muted">{DASH}</span>}
                              </span>
                            </td>
                            <td className="num">{int(doc.decision_count)}</td>
                            <td className="num">{int(doc.supported_claim_count)}</td>
                            <td className="num">{int(doc.contradicted_claim_count)}</td>
                            <td className="num">{int(doc.conflict_count)}</td>
                            <td className="num">{ir ? pct(ir.unsupported_rate) : <span className="muted" title={intelDocs.error ? intelDocs.error.message : "not computed"}>{DASH}</span>}</td>
                          </tr>
                        );
                      }),
                    ])}
                  </tbody>
                </table>
              </div>
            )
          }
        </Async>
      </Panel>
      {graphDocs.data?.items?.length > 0 && <p className="muted small hint-below">Select a version to see which decisions depend on it.</p>}

      <Drawer open={Boolean(openId)} onClose={close} title={openId?.replace(/^doc:/, "") ?? ""} subtitle="Document detail">
        {openId && <DocumentDetail key={openId} id={openId} graphRow={graphRow} intelRow={intelById.get(openId)} />}
      </Drawer>
    </>
  );
}
