/**
 * Graph explorer – /v1/graph/*.
 *   #graph                     pick a decision or document
 *   #graph/decision/<id>       a decision's subgraph
 *   #graph/node/<node id>      one-hop neighbourhood of any node
 * Expanding a node merges its neighbours into the current view.
 */
import { useEffect, useMemo, useState } from "react";
import { apiGet, enc, useApi } from "../api.js";
import GraphCanvas, { GraphLegend } from "../components/GraphCanvas.jsx";
import GraphInspector from "../components/GraphInspector.jsx";
import { DASH, DECISIONS, DECISION_META, dateTime, int, score, timeAgo, truncate } from "../format.js";
import { mergeGraphs, normaliseGraph } from "../graphUtils.js";
import { go, href } from "../router.js";
import { Async, DecisionBadge, EmptyState, ErrorState, Loading, PageHeader, Panel, RefreshButton, Tabs } from "../ui/index.jsx";

function DecisionPicker({ activeId }) {
  const [decision, setDecision] = useState("");
  const q = useApi(`/v1/graph/decisions?limit=100${decision ? `&decision=${decision}` : ""}`);
  return (
    <>
      <div className="toolbar" style={{ padding: "8px 12px 0" }}>
        <label className="sr-only" htmlFor="gx-dec-filter">
          Filter by decision
        </label>
        <select id="gx-dec-filter" className="select select--sm" value={decision} onChange={(e) => setDecision(e.target.value)}>
          <option value="">All outcomes</option>
          {DECISIONS.map((d) => (
            <option key={d} value={d}>
              {DECISION_META[d].label}
            </option>
          ))}
        </select>
      </div>
      <Async q={q} rows={6}>
        {(d) =>
          d.items?.length ? (
            <div className="picker-list">
              {d.items.map((it) => (
                <button
                  key={it.request_id}
                  type="button"
                  className={activeId === it.request_id ? "picker-item is-active" : "picker-item"}
                  onClick={() => go("graph", "decision", it.request_id)}
                >
                  <span className="picker-item__row">
                    <DecisionBadge decision={it.decision} />
                    <span title={it.created_at}>{timeAgo(it.created_at)}</span>
                  </span>
                  <span className="picker-item__text">{truncate(it.query_preview, 90) || <span className="mono">{it.request_id}</span>}</span>
                  <span className="picker-item__row">
                    <span>
                      {int(it.claim_count)} claims · {int(it.evidence_count)} evidence · {int(it.document_count)} docs
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="pad">
              <EmptyState title="No decisions in the graph">
                Run an evaluation with the graph connected. Writes happen in the background after each decision.
              </EmptyState>
            </div>
          )
        }
      </Async>
    </>
  );
}

function DocumentPicker({ activeId }) {
  const q = useApi("/v1/graph/documents?limit=200");
  return (
    <Async q={q} rows={6}>
      {(d) =>
        d.items?.length ? (
          <div className="picker-list">
            {d.items.map((it) => (
              <button
                key={it.doc_id}
                type="button"
                className={activeId === it.doc_id ? "picker-item is-active" : "picker-item"}
                onClick={() => go("graph", "node", it.doc_id)}
              >
                <span className="picker-item__text mono">{it.doc_id.replace(/^doc:/, "")}</span>
                <span className="picker-item__row">
                  <span>
                    {int(it.decision_count)} decisions · {int(it.conflict_count)} conflicts
                  </span>
                  {it.superseded_by?.length > 0 && <span>superseded</span>}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="pad">
            <EmptyState title="No documents in the graph" />
          </div>
        )
      }
    </Async>
  );
}

function useSubgraph(mode, id) {
  const [state, setState] = useState({ graph: null, summary: null, error: null, loading: false });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!mode || !id) {
      setState({ graph: null, summary: null, error: null, loading: false });
      return undefined;
    }
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    const path = mode === "decision" ? `/v1/graph/decisions/${enc(id)}` : `/v1/graph/nodes/${enc(id)}/neighbors?limit=100`;
    apiGet(path)
      .then((d) => live && setState({ graph: normaliseGraph(d), summary: d.decision ?? null, error: null, loading: false }))
      .catch((error) => live && setState({ graph: null, summary: null, error, loading: false }));
    return () => {
      live = false;
    };
  }, [mode, id, nonce]);
  return { ...state, setGraph: (g) => setState((s) => ({ ...s, graph: g })), reload: () => setNonce((n) => n + 1) };
}

function DecisionSummary({ summary, id }) {
  if (!summary) return null;
  return (
    <div className="explorer__summary">
      <DecisionBadge decision={summary.decision} />
      <span className="grow">{summary.query_preview ?? summary.headline ?? <span className="mono">{id}</span>}</span>
      <span>
        score <span className="mono">{score(summary.answerability_score)}</span>
      </span>
      <span title={summary.created_at}>{summary.created_at ? dateTime(summary.created_at) : DASH}</span>
      <a className="link" href={href("decisions", summary.request_id ?? id)}>
        Decision detail
      </a>
    </div>
  );
}

export default function GraphExplorer({ args, graphStatus }) {
  const [mode, rawId] = args[0] === "decision" || args[0] === "node" ? [args[0], args[1]] : [null, null];
  const [tab, setTab] = useState(mode === "node" ? "documents" : "decisions");
  const sub = useSubgraph(mode, rawId);
  const [selected, setSelected] = useState(null);
  const [expanding, setExpanding] = useState(null);
  const [expandError, setExpandError] = useState(null);

  useEffect(() => {
    setSelected(mode === "node" && rawId ? { kind: "node", id: rawId } : null);
    setExpandError(null);
  }, [mode, rawId]);

  const graph = sub.graph;
  const counts = useMemo(() => {
    if (!graph) return null;
    const c = {};
    for (const n of graph.nodes) c[n.type] = (c[n.type] ?? 0) + 1;
    return c;
  }, [graph]);

  const expand = async (nodeId) => {
    setExpanding(nodeId);
    setExpandError(null);
    try {
      const d = await apiGet(`/v1/graph/nodes/${enc(nodeId)}/neighbors?limit=50`);
      const before = graph.nodes.length;
      const merged = mergeGraphs(graph, d);
      sub.setGraph(merged);
      if (merged.nodes.length === before) setExpandError({ info: true, message: "No further neighbours: every connected node is already shown." });
    } catch (e) {
      setExpandError({ info: false, message: e.message });
    } finally {
      setExpanding(null);
    }
  };

  const offline = graphStatus?.data && !graphStatus.data.connected;

  return (
    <>
      <PageHeader
        title="Graph explorer"
        description="Follow a decision through its claims, the evidence that supported or contradicted them, the source documents and the reasons."
      >
        {mode && <RefreshButton onClick={sub.reload} loading={sub.loading} />}
      </PageHeader>

      {offline && (
        <div className="panel offline-banner">
          <ErrorState compact
            error={{ kind: "offline", message: graphStatus.data.configured ? "Neo4j is configured but not reachable." : "Neo4j is not configured (NEO4J_URI is not set)." }}
            onRetry={graphStatus.reload}
          />
        </div>
      )}

      <div className="explorer">
        <Panel className="explorer__picker" flush>
          <div style={{ padding: "0 12px" }}>
            <Tabs
              label="Browse"
              value={tab}
              onChange={setTab}
              tabs={[
                { value: "decisions", label: "Decisions" },
                { value: "documents", label: "Documents" },
              ]}
            />
          </div>
          <div className="panel__body panel__body--flush" style={{ maxHeight: 620, overflowY: "auto" }}>
            {tab === "decisions" ? <DecisionPicker activeId={mode === "decision" ? rawId : null} /> : <DocumentPicker activeId={mode === "node" ? rawId : null} />}
          </div>
        </Panel>

        <div style={{ minWidth: 0 }}>
          {!mode ? (
            <div className="graph-canvas graph-canvas--empty" style={{ height: 480 }}>
              <div style={{ textAlign: "center", maxWidth: 360, padding: 16 }}>
                <p style={{ color: "var(--text)", fontWeight: 500 }}>Select a decision or a document</p>
                <p>The graph shows what the decision was based on. Click any node to inspect it and expand its neighbours.</p>
              </div>
            </div>
          ) : sub.error ? (
            <Panel>
              {sub.error.kind === "notfound" ? (
                <EmptyState title={mode === "decision" ? "Decision not in the graph" : "Node not in the graph"}>
                  <span className="mono">{rawId}</span> was not found. Graph writes are asynchronous; a decision made seconds ago may still be queued, or the
                  graph was unavailable when it was made.
                </EmptyState>
              ) : (
                <ErrorState error={sub.error} onRetry={sub.reload} />
              )}
            </Panel>
          ) : !graph ? (
            <Panel>
              <Loading rows={6} />
            </Panel>
          ) : (
            <>
              {mode === "decision" ? (
                <DecisionSummary summary={sub.summary} id={rawId} />
              ) : (
                <div className="explorer__summary">
                  <span className="grow">
                    Neighbourhood of <span className="mono">{rawId}</span>
                  </span>
                  {rawId?.startsWith("doc:") && (
                    <a className="link" href={href("documents", rawId)}>
                      Document detail
                    </a>
                  )}
                </div>
              )}
              <GraphCanvas graph={graph} selected={selected} onSelect={setSelected} height={560} ariaLabel={`Graph for ${rawId}`} />
              <div className="explorer__summary" style={{ marginTop: 8, marginBottom: 0 }}>
                <span>
                  {int(graph.nodes.length)} nodes · {int(graph.edges.length)} relationships
                </span>
                {counts &&
                  Object.entries(counts).map(([t, n]) => (
                    <span key={t} className="muted">
                      {t} {n}
                    </span>
                  ))}
              </div>
              <GraphLegend />
            </>
          )}
        </div>

        <Panel className="explorer__inspector" title="Inspector" flush>
          {graph ? (
            <GraphInspector graph={graph} selected={selected} onSelect={setSelected} onExpand={expand} expanding={Boolean(expanding)} expandError={expandError} />
          ) : (
            <div className="inspector inspector--empty">
              <p className="muted small">Load a graph to inspect its nodes and relationships.</p>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
