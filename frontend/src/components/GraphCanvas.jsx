/**
 * GraphCanvas – plain-SVG node-link view with a deterministic layered
 * layout (Reason | Decision → Claim → Evidence → Document).
 *
 * Controlled selection: `selected` is { kind: "node" | "edge", id } or null.
 * Pan by dragging the background, zoom with the buttons or Ctrl/⌘ + wheel.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CLAIM_CLS, decisionCls } from "../format.js";
import { EDGE_INFO, NODE_H, NODE_W, edgePath, layeredLayout } from "../graphUtils.js";
import { Icon } from "../ui/index.jsx";

const PAD = 24;
const TONES = ["structural", "support", "contradict", "conflict", "supersede", "retrieved"];

function nodeTone(n) {
  if (n.type === "Decision") return decisionCls(n.props.decision);
  if (n.type === "Claim") return CLAIM_CLS[n.props.status] ?? "abstain";
  if (n.type === "Document") return "accent";
  if (n.type === "Evidence") return "evidence";
  return "neutral";
}

function nodeKicker(n) {
  const p = n.props;
  switch (n.type) {
    case "Decision":
      return "Decision";
    case "Claim":
      return `Claim${p.claim_index !== undefined ? ` ${Number(p.claim_index) + 1}` : ""}${p.status ? ` · ${String(p.status).toLowerCase()}` : ""}`;
    case "Evidence":
      return `Evidence${p.evidence_index !== undefined ? ` E${Number(p.evidence_index) + 1}` : ""}`;
    case "Document":
      return "Document";
    case "Reason":
      return "Reason";
    default:
      return n.type;
  }
}

function clip(s, n) {
  const t = String(s ?? "");
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export function GraphLegend() {
  const nodes = [
    ["Decision", "answer"],
    ["Claim", "caveat"],
    ["Evidence", "evidence"],
    ["Document", "accent"],
    ["Reason", "neutral"],
  ];
  const edges = [
    ["supports", "support"],
    ["contradicts", "contradict"],
    ["conflicts with", "conflict"],
    ["supersedes", "supersede"],
    ["retrieved", "retrieved"],
    ["structural", "structural"],
  ];
  return (
    <div className="graph-legend" aria-label="Graph legend">
      <div className="graph-legend__group">
        {nodes.map(([label, tone]) => (
          <span className="graph-legend__item" key={label}>
            <span className={`graph-legend__node gtone--${tone}`} aria-hidden="true" />
            {label}
          </span>
        ))}
        <span className="graph-legend__note">Decision and claim colour follows outcome / status</span>
      </div>
      <div className="graph-legend__group">
        {edges.map(([label, tone]) => (
          <span className="graph-legend__item" key={label}>
            <svg width="26" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="26" y2="4" className={`gedge gedge--${tone}`} />
            </svg>
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function GraphCanvas({ graph, selected, onSelect, height = 420, ariaLabel = "Decision graph" }) {
  const wrapRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: height });
  const [view, setView] = useState(null); // {k,x,y} or null = auto-fit
  const drag = useRef(null);

  const layout = useMemo(() => layeredLayout(graph), [graph]);
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const measure = () => setSize({ w: el.clientWidth || 800, h: el.clientHeight || height });
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  const fit = useMemo(() => {
    const k = Math.min((size.w - PAD * 2) / layout.width, (size.h - PAD * 2) / layout.height, 1);
    // Never shrink below a readable scale; wider graphs pan instead.
    const kk = Math.max(k, 0.62);
    const w = layout.width * kk;
    const h = layout.height * kk;
    return {
      k: kk,
      x: w + PAD * 2 > size.w ? PAD : (size.w - w) / 2,
      y: h + PAD * 2 > size.h ? PAD : (size.h - h) / 2,
    };
  }, [size, layout]);

  // Re-fit when the graph's shape changes.
  useEffect(() => setView(null), [layout.width, layout.height]);

  const v = view ?? fit;

  const zoom = useCallback(
    (factor) => {
      const cur = view ?? fit;
      const k = Math.min(2.5, Math.max(0.2, cur.k * factor));
      const cx = size.w / 2;
      const cy = size.h / 2;
      setView({
        k,
        x: cx - ((cx - cur.x) / cur.k) * k,
        y: cy - ((cy - cur.y) / cur.k) * k,
      });
    },
    [view, fit, size]
  );

  const onWheel = (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12);
  };

  const onPointerDown = (e) => {
    if (e.target.closest("[data-hit]")) return;
    drag.current = { px: e.clientX, py: e.clientY, x: v.x, y: v.y, k: v.k, moved: false };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.px;
    const dy = e.clientY - d.py;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (d.moved) setView({ k: d.k, x: d.x + dx, y: d.y + dy });
  };
  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved) onSelect?.(null);
  };

  const selNode = selected?.kind === "node" ? selected.id : null;
  const selEdge = selected?.kind === "edge" ? selected.id : null;

  // Keep the selected node on screen (e.g. after the inspector narrows the canvas).
  useEffect(() => {
    const pos = selNode ? layout.positions[selNode] : null;
    if (!pos) return;
    const cur = view ?? fit;
    const sx = cur.x + pos.x * cur.k;
    const sy = cur.y + pos.y * cur.k;
    const inside = sx >= 0 && sy >= 0 && sx + NODE_W * cur.k <= size.w && sy + NODE_H * cur.k <= size.h;
    if (!inside) {
      setView({
        k: cur.k,
        x: size.w / 2 - (pos.x + NODE_W / 2) * cur.k,
        y: size.h / 2 - (pos.y + NODE_H / 2) * cur.k,
      });
    }
    // Only react to selection and canvas size, not to every pan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selNode, size.w, size.h, layout]);
  const touching = useMemo(() => {
    if (!selNode) return null;
    const s = new Set([selNode]);
    for (const e of graph.edges) {
      if (e.from === selNode) s.add(e.to);
      if (e.to === selNode) s.add(e.from);
    }
    return s;
  }, [selNode, graph]);

  if (!graph.nodes.length) {
    return (
      <div className="graph-canvas graph-canvas--empty" style={{ height }}>
        <p>No graph nodes to display.</p>
      </div>
    );
  }

  const key = (fn) => (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn();
    }
  };

  return (
    <div className="graph-canvas" style={{ height }} ref={wrapRef}>
      <div className="graph-canvas__tools">
        <button type="button" className="icon-btn" onClick={() => zoom(1.2)} aria-label="Zoom in" title="Zoom in">
          <Icon name="zoomin" size={15} />
        </button>
        <button type="button" className="icon-btn" onClick={() => zoom(1 / 1.2)} aria-label="Zoom out" title="Zoom out">
          <Icon name="zoomout" size={15} />
        </button>
        <button type="button" className="icon-btn" onClick={() => setView(null)} aria-label="Fit to view" title="Fit to view">
          <Icon name="fit" size={15} />
        </button>
      </div>
      <svg
        width="100%"
        height="100%"
        role="group"
        aria-label={ariaLabel}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (drag.current = null)}
      >
        <defs>
          {TONES.map((t) => (
            <marker key={t} id={`garrow-${t}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0.5 L8,4 L0,7.5 z" className={`garrow garrow--${t}`} />
            </marker>
          ))}
        </defs>
        <g transform={`translate(${v.x},${v.y}) scale(${v.k})`}>
          <g>
            {graph.edges.map((e) => {
              const a = layout.positions[e.from];
              const b = layout.positions[e.to];
              if (!a || !b) return null;
              const info = EDGE_INFO[e.type] ?? { label: e.type, tone: "structural" };
              const p = edgePath(a, b, layout.colOf[e.from], layout.colOf[e.to]);
              const isSel = selEdge === e.id;
              const dim = (selNode && e.from !== selNode && e.to !== selNode) || (selEdge && !isSel);
              return (
                <g key={e.id} className={`gedge-wrap${isSel ? " is-selected" : ""}${dim ? " is-dim" : ""}`}>
                  <path d={p.d} className={`gedge gedge--${info.tone}`} markerEnd={`url(#garrow-${info.tone})`} />
                  <path
                    d={p.d}
                    className="gedge-hit"
                    data-hit="edge"
                    tabIndex={0}
                    role="button"
                    aria-label={`${byId.get(e.from)?.label ?? e.from} ${info.label} ${byId.get(e.to)?.label ?? e.to}`}
                    onClick={() => onSelect?.({ kind: "edge", id: e.id })}
                    onKeyDown={key(() => onSelect?.({ kind: "edge", id: e.id }))}
                  />
                  {isSel && (
                    <text x={p.mx} y={p.my - 6} textAnchor="middle" className="gedge-label">
                      {info.label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
          <g>
            {graph.nodes.map((n) => {
              const pos = layout.positions[n.id];
              if (!pos) return null;
              const tone = nodeTone(n);
              const isSel = selNode === n.id;
              const dim = touching ? !touching.has(n.id) : false;
              return (
                <g
                  key={n.id}
                  transform={`translate(${pos.x},${pos.y})`}
                  className={`gnode gtone--${tone}${isSel ? " is-selected" : ""}${dim ? " is-dim" : ""}`}
                  data-hit="node"
                  data-node-type={n.type}
                  tabIndex={0}
                  role="button"
                  aria-pressed={isSel}
                  aria-label={`${n.type}: ${n.label}`}
                  onClick={() => onSelect?.({ kind: "node", id: n.id })}
                  onKeyDown={key(() => onSelect?.({ kind: "node", id: n.id }))}
                >
                  <title>{n.label}</title>
                  <rect className="gnode__box" width={NODE_W} height={NODE_H} rx="5" />
                  <rect className="gnode__rule" width="3" height={NODE_H - 12} x="0.5" y="6" rx="1.5" />
                  <text className="gnode__kicker" x="14" y="20">
                    {nodeKicker(n)}
                  </text>
                  <text className="gnode__label" x="14" y="38">
                    {clip(n.label, 30)}
                  </text>
                </g>
              );
            })}
          </g>
        </g>
      </svg>
    </div>
  );
}
