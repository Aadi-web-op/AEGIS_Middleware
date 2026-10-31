/**
 * DecisionGraph – SVG-based interactive graph renderer.
 *
 * Supports: zoom, pan, fit-to-view, node selection, details panel.
 * Renders all required node types and relationship types with correct
 * visual styles (green=support, red=contradiction, dashed=supersedes).
 * No heavy external library required.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { safePreview } from "./graphUtils.js";

// ── Visual configuration ───────────────────────────────────────────────────

const NODE_COLORS = {
  Decision: { bg: "#1e3a5f", border: "#4a9eff", text: "#e0eeff" },
  Claim: {
    SUPPORTED: { bg: "#0d3320", border: "#22c55e", text: "#bbf7d0" },
    UNSUPPORTED: { bg: "#2a2a1a", border: "#eab308", text: "#fef9c3" },
    CONTRADICTED: { bg: "#3a1a1a", border: "#ef4444", text: "#fecaca" },
    default: { bg: "#1e2a3a", border: "#64748b", text: "#cbd5e1" },
  },
  Evidence: { bg: "#1a2a3a", border: "#7dd3fc", text: "#e0f2fe" },
  Document: { bg: "#2a1a3a", border: "#c084fc", text: "#ede9fe" },
  Reason: { bg: "#2a1a2a", border: "#f472b6", text: "#fce7f3" },
  Unknown: { bg: "#1a1a2a", border: "#6b7280", text: "#d1d5db" },
};

const EDGE_STYLES = {
  SUPPORTED_BY: { stroke: "#22c55e", label: "supports", dashed: false },
  CONTRADICTED_BY: { stroke: "#ef4444", label: "contradicts", dashed: false },
  HAS_CLAIM: { stroke: "#4a9eff", label: "has claim", dashed: false },
  FROM: { stroke: "#c084fc", label: "from", dashed: false },
  CONFLICTS_WITH: { stroke: "#f97316", label: "conflicts", dashed: false },
  SUPERSEDES: { stroke: "#a3e635", label: "supersedes", dashed: true },
  BECAUSE: { stroke: "#f472b6", label: "because", dashed: false },
  ABOUT: { stroke: "#94a3b8", label: "about", dashed: false },
};

const NODE_W = 160;
const NODE_H = 54;
const LAYER_GAP = 220;
const NODE_GAP = 80;

// ── Layout: simple layered (BFS from Decision nodes) ─────────────────────

function computeLayout(nodes, edges) {
  if (!nodes.length) return {};

  // Adjacency
  const adj = {};
  for (const n of nodes) adj[n.id] = [];
  for (const e of edges) {
    if (adj[e.source] !== undefined) adj[e.source].push(e.target);
  }

  // BFS layers
  const layers = {};
  const visited = new Set();
  let queue = nodes
    .filter((n) => n.type === "Decision")
    .map((n) => n.id);
  if (!queue.length) queue = [nodes[0].id];

  let depth = 0;
  while (queue.length) {
    const next = [];
    for (const id of queue) {
      if (visited.has(id)) continue;
      visited.add(id);
      if (!layers[depth]) layers[depth] = [];
      layers[depth].push(id);
      for (const child of adj[id] ?? []) {
        if (!visited.has(child)) next.push(child);
      }
    }
    depth++;
    queue = next;
  }

  // Nodes not reached
  for (const n of nodes) {
    if (!visited.has(n.id)) {
      if (!layers[depth]) layers[depth] = [];
      layers[depth].push(n.id);
    }
  }

  // Assign positions
  const positions = {};
  for (const [d, ids] of Object.entries(layers)) {
    const x = Number(d) * LAYER_GAP + 40;
    const totalH = ids.length * (NODE_H + NODE_GAP) - NODE_GAP;
    let y = -totalH / 2;
    for (const id of ids) {
      positions[id] = { x, y };
      y += NODE_H + NODE_GAP;
    }
  }
  return positions;
}

// ── Arrow marker defs ────────────────────────────────────────────────────

function Markers() {
  const defs = Object.entries(EDGE_STYLES).map(([type, style]) => (
    <marker
      key={type}
      id={`arrow-${type}`}
      markerWidth="8"
      markerHeight="8"
      refX="7"
      refY="3"
      orient="auto"
    >
      <path d="M0,0 L0,6 L8,3 z" fill={style.stroke} />
    </marker>
  ));
  return <defs>{defs}</defs>;
}

// ── Single edge ──────────────────────────────────────────────────────────

function Edge({ edge, positions, onHover }) {
  const src = positions[edge.source];
  const tgt = positions[edge.target];
  if (!src || !tgt) return null;

  const style = EDGE_STYLES[edge.type] ?? {
    stroke: "#6b7280",
    label: edge.type,
    dashed: false,
  };

  const x1 = src.x + NODE_W;
  const y1 = src.y + NODE_H / 2;
  const x2 = tgt.x;
  const y2 = tgt.y + NODE_H / 2;
  const cx = (x1 + x2) / 2;
  const midX = cx;
  const midY = (y1 + y2) / 2;

  const pathD = `M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`;
  const dashArray = style.dashed ? "6,4" : undefined;
  const inferred = edge.properties?.inferred;
  const label = inferred ? `${style.label} (inferred)` : style.label;
  const conflictKind = edge.properties?.conflict_kind;

  return (
    <g
      onMouseEnter={() => onHover({ edge, style, label, conflictKind })}
      onMouseLeave={() => onHover(null)}
      style={{ cursor: "default" }}
    >
      <path
        d={pathD}
        fill="none"
        stroke={style.stroke}
        strokeWidth={inferred ? 1.5 : 2}
        strokeDasharray={dashArray}
        markerEnd={`url(#arrow-${edge.type})`}
        opacity={0.75}
      />
      <text
        x={midX}
        y={midY - 6}
        textAnchor="middle"
        fontSize="10"
        fill={style.stroke}
        style={{ pointerEvents: "none", userSelect: "none" }}
      >
        {label}
        {conflictKind ? ` (${conflictKind})` : ""}
      </text>
    </g>
  );
}

// ── Single node ──────────────────────────────────────────────────────────

function getNodeColors(node) {
  if (node.type === "Claim") {
    const status = node.properties?.status;
    return NODE_COLORS.Claim[status] ?? NODE_COLORS.Claim.default;
  }
  return NODE_COLORS[node.type] ?? NODE_COLORS.Unknown;
}

function GraphNode({ node, pos, selected, onClick }) {
  const colors = getNodeColors(node);
  return (
    <g
      transform={`translate(${pos.x},${pos.y})`}
      onClick={() => onClick(node)}
      style={{ cursor: "pointer" }}
      role="button"
      aria-label={`Node: ${node.label} (${node.type})`}
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick(node)}
    >
      <rect
        width={NODE_W}
        height={NODE_H}
        rx={10}
        fill={colors.bg}
        stroke={selected ? "#fff" : colors.border}
        strokeWidth={selected ? 2.5 : 1.5}
      />
      {/* Type badge */}
      <text
        x={8}
        y={15}
        fontSize="9"
        fill={colors.border}
        style={{ userSelect: "none" }}
      >
        {node.type.toUpperCase()}
      </text>
      {/* Label */}
      <foreignObject x={6} y={18} width={NODE_W - 12} height={32}>
        <div
          xmlns="http://www.w3.org/1999/xhtml"
          style={{
            fontSize: 11,
            color: colors.text,
            lineHeight: "1.3",
            overflow: "hidden",
            whiteSpace: "nowrap",
            textOverflow: "ellipsis",
            userSelect: "none",
          }}
          title={node.label}
        >
          {node.label}
        </div>
      </foreignObject>
    </g>
  );
}

// ── Legend ───────────────────────────────────────────────────────────────

function Legend() {
  return (
    <div className="dg-legend" aria-label="Graph legend">
      <strong>Node types</strong>
      <div className="dg-legend-items">
        {Object.entries(NODE_COLORS)
          .filter(([k]) => k !== "Unknown")
          .map(([type, color]) => {
            const c = type === "Claim" ? color.SUPPORTED : color;
            return (
              <span key={type} className="dg-legend-chip" style={{ borderColor: c.border, color: c.border }}>
                {type}
              </span>
            );
          })}
      </div>
      <strong style={{ marginTop: 8, display: "block" }}>Edges</strong>
      <div className="dg-legend-items">
        {Object.entries(EDGE_STYLES).map(([type, style]) => (
          <span
            key={type}
            className="dg-legend-edge"
            style={{
              borderBottom: `2px ${style.dashed ? "dashed" : "solid"} ${style.stroke}`,
              color: style.stroke,
            }}
          >
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Node details panel ────────────────────────────────────────────────────

function NodeDetails({ node, onClose }) {
  if (!node) return null;
  const props = node.properties ?? {};

  const rows = Object.entries(props)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => {
      let display;
      if (k === "text") {
        display = safePreview(String(v), 120);
      } else if (typeof v === "number") {
        display = Number.isInteger(v) ? String(v) : `${(v * 100).toFixed(1)}%`;
      } else {
        display = String(v);
      }
      return { k, display };
    });

  return (
    <div className="dg-details" role="region" aria-label="Node details">
      <div className="dg-details-header">
        <span className="dg-details-type">{node.type}</span>
        <button
          className="dg-close-btn"
          onClick={onClose}
          aria-label="Close details panel"
        >
          ✕
        </button>
      </div>
      <h4 className="dg-details-label">{node.label}</h4>
      {rows.length > 0 ? (
        <dl className="dg-details-dl">
          {rows.map(({ k, display }) => (
            <>
              <dt key={`dt-${k}`}>{k.replaceAll("_", " ")}</dt>
              <dd key={`dd-${k}`}>{display}</dd>
            </>
          ))}
        </dl>
      ) : (
        <p className="muted">No properties.</p>
      )}
    </div>
  );
}

// ── Main DecisionGraph component ──────────────────────────────────────────

export default function DecisionGraph({ graphData }) {
  const svgRef = useRef(null);
  const [transform, setTransform] = useState({ x: 40, y: 300, scale: 1 });
  const [selectedNode, setSelectedNode] = useState(null);
  const [hoveredEdge, setHoveredEdge] = useState(null);
  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });

  const { nodes, edges } = graphData ?? { nodes: [], edges: [] };
  const positions = computeLayout(nodes, edges);

  // Fit-to-view
  const fitToView = useCallback(() => {
    if (!nodes.length || !svgRef.current) return;
    const xs = nodes.map((n) => positions[n.id]?.x ?? 0);
    const ys = nodes.map((n) => positions[n.id]?.y ?? 0);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs) + NODE_W;
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys) + NODE_H;
    const graphW = maxX - minX;
    const graphH = maxY - minY;
    const svgW = svgRef.current.clientWidth || 800;
    const svgH = svgRef.current.clientHeight || 500;
    const scale = Math.min((svgW - 80) / graphW, (svgH - 80) / graphH, 1.5);
    setTransform({
      x: (svgW - graphW * scale) / 2 - minX * scale,
      y: (svgH - graphH * scale) / 2 - minY * scale,
      scale,
    });
  }, [nodes, positions]);

  useEffect(() => {
    fitToView();
  }, [fitToView]);

  // Pan
  const onMouseDown = (e) => {
    if (e.button !== 0) return;
    isDragging.current = true;
    dragStart.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
  };
  const onMouseMove = (e) => {
    if (!isDragging.current) return;
    setTransform((t) => ({
      ...t,
      x: dragStart.current.tx + e.clientX - dragStart.current.x,
      y: dragStart.current.ty + e.clientY - dragStart.current.y,
    }));
  };
  const onMouseUp = () => { isDragging.current = false; };

  // Wheel zoom
  const onWheel = (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    const svgRect = svgRef.current.getBoundingClientRect();
    const cx = e.clientX - svgRect.left;
    const cy = e.clientY - svgRect.top;
    setTransform((t) => ({
      scale: Math.max(0.2, Math.min(3, t.scale * factor)),
      x: cx - (cx - t.x) * factor,
      y: cy - (cy - t.y) * factor,
    }));
  };

  if (!nodes.length) {
    return (
      <div className="dg-empty">
        <span className="empty-icon">◎</span>
        <h4>No graph data</h4>
        <p>Ask a question to generate a decision graph.</p>
      </div>
    );
  }

  return (
    <div className="dg-container">
      {/* Controls */}
      <div className="dg-controls" role="toolbar" aria-label="Graph controls">
        <button
          onClick={() => setTransform((t) => ({ ...t, scale: Math.min(t.scale * 1.2, 3) }))}
          aria-label="Zoom in"
          className="dg-btn"
        >
          +
        </button>
        <button
          onClick={() => setTransform((t) => ({ ...t, scale: Math.max(t.scale * 0.8, 0.2) }))}
          aria-label="Zoom out"
          className="dg-btn"
        >
          −
        </button>
        <button onClick={fitToView} aria-label="Fit to view" className="dg-btn">
          ⊞
        </button>
        {selectedNode && (
          <button
            onClick={() => setSelectedNode(null)}
            aria-label="Deselect node"
            className="dg-btn"
          >
            ✕ Deselect
          </button>
        )}
      </div>

      {/* SVG canvas */}
      <svg
        ref={svgRef}
        className="dg-svg"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onWheel={onWheel}
        aria-label="AEGIS decision graph"
        role="img"
        style={{ cursor: isDragging.current ? "grabbing" : "grab" }}
      >
        <Markers />
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
          {/* Edges first */}
          {edges.map((edge) => (
            <Edge
              key={edge.id}
              edge={edge}
              positions={positions}
              onHover={setHoveredEdge}
            />
          ))}
          {/* Nodes */}
          {nodes.map((node) => {
            const pos = positions[node.id];
            if (!pos) return null;
            return (
              <GraphNode
                key={node.id}
                node={node}
                pos={pos}
                selected={selectedNode?.id === node.id}
                onClick={setSelectedNode}
              />
            );
          })}
        </g>
      </svg>

      {/* Edge hover tooltip */}
      {hoveredEdge && (
        <div className="dg-edge-tooltip" role="tooltip">
          <strong>{hoveredEdge.edge.type}</strong>
          {hoveredEdge.conflictKind && <span> · {hoveredEdge.conflictKind}</span>}
          {hoveredEdge.edge.properties?.inferred && (
            <span className="dg-inferred-badge"> inferred</span>
          )}
        </div>
      )}

      {/* Node details panel */}
      <NodeDetails node={selectedNode} onClose={() => setSelectedNode(null)} />

      {/* Legend */}
      <Legend />
    </div>
  );
}
