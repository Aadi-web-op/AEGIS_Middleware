/**
 * GraphInspector – side panel for the selected node or edge.
 * Node: properties + relationships (click to follow). Edge: why it exists.
 */
import { DASH } from "../format.js";
import { EDGE_INFO, relationsOf } from "../graphUtils.js";
import { href } from "../router.js";
import { ClaimChip, DecisionBadge, Icon, Tag } from "../ui/index.jsx";

const HIDDEN_PROPS = new Set(["id", "type", "label"]);

function fmtValue(v) {
  if (v === null || v === undefined || v === "") return DASH;
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function PropTable({ props }) {
  const entries = Object.entries(props ?? {}).filter(([k, v]) => !HIDDEN_PROPS.has(k) && v !== undefined);
  if (!entries.length) return <p className="muted small">No properties recorded.</p>;
  return (
    <dl className="kv kv--tight">
      {entries.map(([k, v]) => (
        <div className="kv__row" key={k}>
          <dt>{k}</dt>
          <dd className={typeof v === "number" || /id$|_at$|version|date/.test(k) ? "mono" : undefined}>{fmtValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function NodeRef({ node, onSelect }) {
  if (!node) return <span className="muted">unknown node</span>;
  return (
    <button type="button" className="link-btn" onClick={() => onSelect({ kind: "node", id: node.id })}>
      <span className="muted">{node.type}</span> {node.label}
    </button>
  );
}

export default function GraphInspector({ graph, selected, onSelect, onExpand, expanding, expandError }) {
  if (!selected) {
    return (
      <div className="inspector inspector--empty">
        <p className="inspector__hint">Select a node or an edge to inspect it.</p>
        <p className="muted small">
          Nodes show their stored properties and relationships. Edges explain why the relationship exists.
        </p>
      </div>
    );
  }

  if (selected.kind === "edge") {
    const edge = graph.edges.find((e) => e.id === selected.id);
    if (!edge) return null;
    const info = EDGE_INFO[edge.type] ?? { label: edge.type, meaning: "Relationship stored in the decision graph." };
    const from = graph.nodes.find((n) => n.id === edge.from);
    const to = graph.nodes.find((n) => n.id === edge.to);
    return (
      <div className="inspector">
        <p className="inspector__kicker">Relationship</p>
        <h3 className="inspector__title mono">{edge.type}</h3>
        <p className="inspector__meaning">{info.meaning}</p>
        <div className="inspector__section">
          <h4>Connects</h4>
          <div className="rel-pair">
            <NodeRef node={from} onSelect={onSelect} />
            <span className="rel-pair__arrow">
              <Icon name="arrow" size={13} /> {info.label}
            </span>
            <NodeRef node={to} onSelect={onSelect} />
          </div>
        </div>
        <div className="inspector__section">
          <h4>Properties</h4>
          <PropTable props={edge.props} />
        </div>
      </div>
    );
  }

  const node = graph.nodes.find((n) => n.id === selected.id);
  if (!node) return null;
  const rels = relationsOf(graph, node.id);
  const p = node.props;
  const requestId = node.type === "Decision" ? p.request_id ?? node.id : null;

  return (
    <div className="inspector">
      <p className="inspector__kicker">{node.type}</p>
      <h3 className="inspector__title">
        {node.type === "Decision" ? <DecisionBadge decision={p.decision} /> : null}
        {node.type === "Claim" && p.status ? <ClaimChip status={p.status} /> : null}
        {node.type === "Document" ? <span className="mono">{node.id}</span> : null}
        {node.type === "Reason" ? <Tag>{p.code ?? "reason"}</Tag> : null}
      </h3>
      <p className="inspector__text">
        {node.type === "Decision"
          ? p.headline ?? p.query_preview ?? node.label
          : p.text ?? p.preview ?? p.message ?? node.label}
      </p>

      <div className="inspector__actions">
        {onExpand && (
          <button type="button" className="btn btn--secondary btn--sm" onClick={() => onExpand(node.id)} disabled={expanding}>
            <Icon name="expand" size={14} />
            {expanding ? "Expanding…" : "Expand neighbours"}
          </button>
        )}
        {requestId && (
          <a className="btn btn--ghost btn--sm" href={href("decisions", requestId)}>
            Open decision
          </a>
        )}
        {node.type === "Document" && (
          <a className="btn btn--ghost btn--sm" href={href("documents", node.id)}>
            Open document
          </a>
        )}
      </div>
      {expandError && (
        <p className={expandError.info ? "muted small inspector__note" : "field-error"}>{expandError.message ?? String(expandError)}</p>
      )}

      <div className="inspector__section">
        <h4>Properties</h4>
        <PropTable props={p} />
      </div>

      <div className="inspector__section">
        <h4>
          Relationships <span className="count">{rels.length}</span>
        </h4>
        {rels.length === 0 ? (
          <p className="muted small">None loaded. Expand neighbours to fetch more.</p>
        ) : (
          <ul className="rel-list">
            {rels.map(({ edge, direction, other }) => (
              <li key={edge.id}>
                <button
                  type="button"
                  className="rel-list__edge mono"
                  onClick={() => onSelect({ kind: "edge", id: edge.id })}
                  title="Inspect relationship"
                >
                  {direction === "out" ? "→" : "←"} {edge.type}
                </button>
                <NodeRef node={other} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
