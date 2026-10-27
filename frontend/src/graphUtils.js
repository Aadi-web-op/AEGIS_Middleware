/**
 * buildGraphFromTrace(trace)
 *
 * Converts an AEGIS EvaluateResponse (the `trace` object) into a
 * { nodes, edges } graph structure compatible with DecisionGraph.
 *
 * If `trace.graph` is already present (populated by the backend in the future),
 * it is returned directly. Otherwise the graph is synthesised from the
 * claims/reasons fields that the current backend already returns.
 *
 * This function is the single integration point: the graph component
 * never accesses the raw trace directly.
 */

let _nodeCounter = 0;
function uid(prefix) {
  return `${prefix}-${++_nodeCounter}`;
}

export function buildGraphFromTrace(trace) {
  if (!trace) return { nodes: [], edges: [] };

  // If the backend has already populated a graph block, use it directly.
  if (trace.graph && Array.isArray(trace.graph.nodes)) {
    return trace.graph;
  }

  // Synthesise from the current response schema.
  const nodes = [];
  const edges = [];

  // Decision node
  const decisionId = uid("decision");
  nodes.push({
    id: decisionId,
    type: "Decision",
    label: `Decision: ${trace.decision ?? "UNKNOWN"}`,
    properties: {
      outcome: trace.decision,
      answerability_score: trace.answerability_score ?? null,
      policy_version: trace.policy_version,
      request_id: trace.request_id,
    },
  });

  // Claim nodes
  const claimIds = [];
  (trace.claims ?? []).forEach((claim, i) => {
    const cid = uid("claim");
    claimIds.push(cid);
    nodes.push({
      id: cid,
      type: "Claim",
      label: claim.claim
        ? claim.claim.slice(0, 60) + (claim.claim.length > 60 ? "…" : "")
        : `Claim ${i + 1}`,
      properties: {
        text: claim.claim,
        status: claim.status,
        support: claim.support ?? null,
      },
    });
    edges.push({
      id: uid("e"),
      source: decisionId,
      target: cid,
      type: "HAS_CLAIM",
    });

    // CONFLICTS_WITH between CONTRADICTED claims and SUPPORTED claims
    if (claim.status === "CONTRADICTED" && claimIds.length > 1) {
      claimIds.slice(0, -1).forEach((prevId, pi) => {
        const prevClaim = (trace.claims ?? [])[pi];
        if (prevClaim && prevClaim.status === "SUPPORTED") {
          edges.push({
            id: uid("e"),
            source: prevId,
            target: cid,
            type: "CONFLICTS_WITH",
            properties: { conflict_kind: "status_mismatch" },
          });
        }
      });
    }
  });

  // Reason nodes
  (trace.reasons ?? []).forEach((reason) => {
    const rid = uid("reason");
    nodes.push({
      id: rid,
      type: "Reason",
      label: reason.code?.replaceAll("_", " ") ?? "Reason",
      properties: {
        code: reason.code,
        message: reason.message,
      },
    });
    edges.push({
      id: uid("e"),
      source: decisionId,
      target: rid,
      type: "BECAUSE",
    });
  });

  return { nodes, edges };
}

/**
 * Extract a display-safe evidence preview (≤120 chars, no HTML injection).
 */
export function safePreview(text, maxLen = 120) {
  if (!text) return null;
  const safe = String(text).replace(/[<>&"]/g, (c) =>
    ({ "<": "", ">": "", "&": "", '"': "" }[c])
  );
  return safe.length > maxLen ? safe.slice(0, maxLen) + "…" : safe;
}

/**
 * Format a 0–1 float as a percentage string, or return "Not available".
 */
export function fmtScore(value) {
  if (value === null || value === undefined) return "Not available";
  if (typeof value !== "number") return "Not available";
  return `${(value * 100).toFixed(1)}%`;
}
