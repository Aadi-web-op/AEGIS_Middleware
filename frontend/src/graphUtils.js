/**
 * Graph helpers shared by the per-request graph and the Graph Explorer.
 *
 * Canonical shape (matches the /v1/graph API, contract §4):
 *   { nodes: [{ id, type, label, props }], edges: [{ id, type, from, to, props }] }
 *
 * `normaliseGraph` accepts either that shape or an evaluation trace
 * (`trace.nodes` with flat properties, `trace.edges` with from/to/kind).
 */

export const NODE_TYPES = ["Reason", "Decision", "Claim", "Evidence", "Document"];

/** Column per node type: Reason sits to the left of the decision. */
const COLUMN = { Reason: 0, Decision: 1, Claim: 2, Evidence: 3, Document: 4 };

export const EDGE_INFO = {
  HAS_CLAIM: {
    label: "has claim",
    meaning: "The answer evaluated by this decision makes this claim.",
    tone: "structural",
  },
  SUPPORTED_BY: {
    label: "supported by",
    meaning: "The evidence passage entails the claim (natural-language inference).",
    tone: "support",
  },
  CONTRADICTED_BY: {
    label: "contradicted by",
    meaning: "The evidence passage contradicts the claim.",
    tone: "contradict",
  },
  FROM: {
    label: "from",
    meaning: "The evidence passage was taken from this document version.",
    tone: "structural",
  },
  CONFLICTS_WITH: {
    label: "conflicts with",
    meaning: "Two evidence passages disagree with each other (numbers, dates, statements or versions).",
    tone: "conflict",
  },
  SUPERSEDES: {
    label: "supersedes",
    meaning: "The newer document version replaces the older one (same source, later version or date).",
    tone: "supersede",
  },
  BECAUSE: {
    label: "because",
    meaning: "The decision was reached for this reason.",
    tone: "structural",
  },
  ABOUT: {
    label: "about",
    meaning: "The reason refers to this specific claim or evidence passage.",
    tone: "structural",
  },
  RETRIEVED: {
    label: "retrieved",
    meaning: "The decision considered this evidence passage, whether or not a claim cited it.",
    tone: "retrieved",
  },
};

function trunc(s, n) {
  if (!s) return "";
  const t = String(s).replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export function defaultLabel(type, p = {}) {
  switch (type) {
    case "Decision":
      return p.decision ?? "Decision";
    case "Claim":
      return trunc(p.text, 70) || `Claim ${p.claim_index ?? ""}`;
    case "Evidence":
      return trunc(p.preview ?? p.text, 70) || p.source || "Evidence";
    case "Document":
      return `${p.source ?? "document"}${p.version ? ` @ ${p.version}` : ""}`;
    case "Reason":
      return p.code ? String(p.code).replaceAll("_", " ").toLowerCase() : "reason";
    default:
      return p.id ?? type ?? "node";
  }
}

const NODE_META_KEYS = new Set(["id", "type", "label", "props"]);

function normaliseNode(n) {
  const props = n.props && typeof n.props === "object" ? { ...n.props } : {};
  for (const [k, v] of Object.entries(n)) {
    if (!NODE_META_KEYS.has(k) && props[k] === undefined) props[k] = v;
  }
  const type = n.type ?? (Array.isArray(n.labels) ? n.labels[0] : "Unknown");
  return {
    id: String(n.id),
    type,
    label: n.label || defaultLabel(type, props),
    props,
  };
}

const EDGE_META_KEYS = new Set(["id", "type", "from", "to", "source", "target", "props"]);

function normaliseEdge(e, i) {
  const props = e.props && typeof e.props === "object" ? { ...e.props } : {};
  for (const [k, v] of Object.entries(e)) {
    if (!EDGE_META_KEYS.has(k) && props[k] === undefined) props[k] = v;
  }
  const from = String(e.from ?? e.source);
  const to = String(e.to ?? e.target);
  return {
    id: e.id ?? `${from}|${e.type}|${to}${props.kind ? `|${props.kind}` : ""}${e.id ? "" : `#${i}`}`,
    type: e.type,
    from,
    to,
    props,
  };
}

export function normaliseGraph(g) {
  if (!g || !Array.isArray(g.nodes)) return { nodes: [], edges: [] };
  const nodes = [];
  const seen = new Set();
  for (const raw of g.nodes) {
    if (!raw || raw.id === undefined || raw.id === null) continue;
    const n = normaliseNode(raw);
    if (seen.has(n.id)) continue;
    seen.add(n.id);
    nodes.push(n);
  }
  const edges = [];
  const seenE = new Set();
  (Array.isArray(g.edges) ? g.edges : []).forEach((raw, i) => {
    if (!raw) return;
    const e = normaliseEdge(raw, i);
    if (!seen.has(e.from) || !seen.has(e.to) || seenE.has(e.id)) return;
    seenE.add(e.id);
    edges.push(e);
  });
  return { nodes, edges };
}

/** Back-compat alias used by older callers/tests. */
export function buildGraphFromTrace(trace) {
  return normaliseGraph(trace);
}

export function mergeGraphs(a, b) {
  const base = normaliseGraph(a);
  const add = normaliseGraph(b);
  const byId = new Map(base.nodes.map((n) => [n.id, n]));
  for (const n of add.nodes) {
    const prev = byId.get(n.id);
    byId.set(n.id, prev ? { ...prev, props: { ...prev.props, ...n.props } } : n);
  }
  const edges = new Map(base.edges.map((e) => [e.id, e]));
  for (const e of add.edges) if (!edges.has(e.id)) edges.set(e.id, e);
  return { nodes: [...byId.values()], edges: [...edges.values()] };
}

export const NODE_W = 208;
export const NODE_H = 52;
const COL_GAP = 84;
const ROW_GAP = 14;

function idx(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 9999;
}

function trailingIndex(id) {
  const m = /:(\d+)$/.exec(id);
  return m ? Number(m[1]) : 9999;
}

/**
 * Deterministic layered layout: one column per node type, rows ordered by
 * owning decision then index; documents ordered by the mean row of the
 * evidence that cites them. Same input always yields the same picture.
 */
export function layeredLayout(graph) {
  const { nodes, edges } = graph;
  const cols = [[], [], [], [], [], []];
  for (const n of nodes) cols[COLUMN[n.type] ?? 5].push(n);

  const decisions = cols[1].slice().sort((a, b) => {
    const ta = String(a.props.created_at ?? "");
    const tb = String(b.props.created_at ?? "");
    return ta === tb ? a.id.localeCompare(b.id) : tb.localeCompare(ta);
  });
  const decOrder = new Map(decisions.map((d, i) => [d.id, i]));
  const owner = (n) => {
    const rid = n.props.request_id ?? n.id.split(":")[0];
    return decOrder.has(rid) ? decOrder.get(rid) : 9999;
  };
  const byOwnerIndex = (key) => (a, b) =>
    owner(a) - owner(b) ||
    idx(a.props[key] ?? trailingIndex(a.id)) - idx(b.props[key] ?? trailingIndex(b.id)) ||
    a.id.localeCompare(b.id);

  cols[1] = decisions;
  cols[0].sort(byOwnerIndex("reason_index"));
  cols[2].sort(byOwnerIndex("claim_index"));
  cols[3].sort(byOwnerIndex("evidence_index"));

  const evRow = new Map(cols[3].map((n, i) => [n.id, i]));
  const docScore = new Map();
  for (const d of cols[4]) {
    const rows = edges.filter((e) => e.type === "FROM" && e.to === d.id && evRow.has(e.from)).map((e) => evRow.get(e.from));
    docScore.set(d.id, rows.length ? rows.reduce((s, r) => s + r, 0) / rows.length : 9999);
  }
  cols[4].sort((a, b) => docScore.get(a.id) - docScore.get(b.id) || a.id.localeCompare(b.id));
  cols[5].sort((a, b) => a.id.localeCompare(b.id));

  const used = cols.map((c, i) => [c, i]).filter(([c]) => c.length);
  const heights = used.map(([c]) => c.length * NODE_H + (c.length - 1) * ROW_GAP);
  const maxH = Math.max(...heights, NODE_H);
  const positions = {};
  const colOf = {};
  used.forEach(([c, ci], k) => {
    const x = k * (NODE_W + COL_GAP);
    let y = (maxH - heights[k]) / 2;
    for (const n of c) {
      positions[n.id] = { x, y };
      colOf[n.id] = ci;
      y += NODE_H + ROW_GAP;
    }
  });
  const width = used.length * NODE_W + (used.length - 1) * COL_GAP;
  return { positions, colOf, width: Math.max(width, NODE_W), height: maxH };
}

/** Cubic path between two laid-out nodes. */
export function edgePath(a, b, colA, colB) {
  if (colA === colB) {
    const x = a.x + NODE_W;
    const y1 = a.y + NODE_H / 2;
    const y2 = b.y + NODE_H / 2;
    const bulge = 36 + Math.min(60, Math.abs(y2 - y1) / 4);
    return { d: `M${x},${y1} C${x + bulge},${y1} ${x + bulge},${y2} ${x},${y2}`, mx: x + bulge * 0.75, my: (y1 + y2) / 2 };
  }
  const forward = colA < colB;
  const x1 = forward ? a.x + NODE_W : a.x;
  const x2 = forward ? b.x : b.x + NODE_W;
  const y1 = a.y + NODE_H / 2;
  const y2 = b.y + NODE_H / 2;
  const dx = (x2 - x1) / 2;
  return { d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 };
}

/** Relationships touching a node, for the inspector. */
export function relationsOf(graph, id) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  return graph.edges
    .filter((e) => e.from === id || e.to === id)
    .map((e) => ({
      edge: e,
      direction: e.from === id ? "out" : "in",
      other: byId.get(e.from === id ? e.to : e.from),
    }));
}

/** Display-safe preview text (≤120 chars). */
export function safePreview(text, maxLen = 120) {
  if (!text) return null;
  const safe = String(text).replace(/[<>&"]/g, "");
  return safe.length > maxLen ? `${safe.slice(0, maxLen)}…` : safe;
}

export function fmtScore(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Not available";
  return `${(value * 100).toFixed(1)}%`;
}
