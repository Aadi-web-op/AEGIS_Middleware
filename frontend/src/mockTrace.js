/**
 * AEGIS Decision Graph – Mock trace data.
 *
 * Represents a realistic evaluate-response trace with:
 *  - A conflicting claim (CONTRADICTED)
 *  - A supported claim
 *  - Supporting and contradicting evidence
 *  - Source documents with versions and dates
 *  - A reason for escalation
 *  - All defined relationship types
 *  - Realistic score fields (0–1, nullable)
 *  - An inferred supersession relationship
 *
 * This mock is ISOLATED: production code imports from the real API.
 * The graph component consumes the same shape whether this or a real response is used.
 */
export const MOCK_TRACE = {
  request_id: "mock-trace-aabbccdd1122",
  decision: "ESCALATE",
  recommended_action: "escalate_to_human",
  answerability_score: 0.41,
  signals: {
    relevance: 0.78,
    entailment: 0.52,
    contradiction: 0.71,
    freshness: 0.34,
    completeness: 0.60,
    ambiguity: 0.18,
  },
  reasons: [
    {
      code: "CONTRADICTION",
      message:
        "The evidence conflicts with the answer or with itself (contradiction 0.71).",
    },
    {
      code: "STALE_EVIDENCE",
      message:
        "The evidence may be outdated for a time-sensitive question (freshness 0.34).",
    },
  ],
  caveat_text: null,
  clarifying_question: null,
  claims: [
    {
      claim: "Employees are entitled to 18 casual leaves per year.",
      status: "SUPPORTED",
      support: 0.88,
      evidence_indices: [0],
    },
    {
      claim: "The leave entitlement was revised to 15 days in 2025.",
      status: "CONTRADICTED",
      support: 0.22,
      evidence_indices: [1, 2],
    },
  ],
  degraded: false,
  policy_version: "0.1.0",
  latency_ms: 142.3,

  // ── Graph trace ────────────────────────────────────────────────────────────
  // The graph is built from this `graph` block.  The evaluator does not yet
  // populate this field; when it does, the DecisionGraph component will use it
  // automatically because it reads from `trace.graph`.
  graph: {
    nodes: [
      {
        id: "decision-1",
        type: "Decision",
        label: "AEGIS Decision",
        properties: {
          outcome: "ESCALATE",
          answerability_score: 0.41,
          policy_version: "0.1.0",
          request_id: "mock-trace-aabbccdd1122",
        },
      },
      {
        id: "claim-1",
        type: "Claim",
        label: "18 casual leaves entitlement",
        properties: {
          text: "Employees are entitled to 18 casual leaves per year.",
          status: "SUPPORTED",
          support: 0.88,
        },
      },
      {
        id: "claim-2",
        type: "Claim",
        label: "Leave revised to 15 days",
        properties: {
          text: "The leave entitlement was revised to 15 days in 2025.",
          status: "CONTRADICTED",
          support: 0.22,
        },
      },
      {
        id: "evidence-1",
        type: "Evidence",
        label: "Policy 2024 – leave entitlement",
        properties: {
          text: "Employees are entitled to 18 casual leaves per annum as per HR policy 2024.",
          chunk_index: 3,
          relevance_score: 0.91,
        },
      },
      {
        id: "evidence-2",
        type: "Evidence",
        label: "HR Circular 2025 – leave update",
        properties: {
          text: "HR Circular 12/2025: casual leave entitlement reduced to 15 days effective 1 Jan 2025.",
          chunk_index: 1,
          relevance_score: 0.76,
        },
      },
      {
        id: "evidence-3",
        type: "Evidence",
        label: "Policy 2024 – leave cap note",
        properties: {
          text: "Subject to a maximum of 18 days in any calendar year, unchanged from 2023.",
          chunk_index: 7,
          relevance_score: 0.62,
        },
      },
      {
        id: "doc-1",
        type: "Document",
        label: "HR Policy 2024",
        properties: {
          source: "hr_policy_2024.pdf",
          version: "2.1",
          date: "2024-01-15",
        },
      },
      {
        id: "doc-2",
        type: "Document",
        label: "HR Circular 12/2025",
        properties: {
          source: "hr_circular_12_2025.pdf",
          version: "1.0",
          date: "2025-01-01",
        },
      },
      {
        id: "reason-1",
        type: "Reason",
        label: "Contradiction detected",
        properties: {
          code: "CONTRADICTION",
          message:
            "The evidence conflicts with the answer or with itself (contradiction 0.71).",
        },
      },
      {
        id: "reason-2",
        type: "Reason",
        label: "Stale evidence",
        properties: {
          code: "STALE_EVIDENCE",
          message:
            "The evidence may be outdated for a time-sensitive question (freshness 0.34).",
        },
      },
    ],
    edges: [
      // Decision HAS_CLAIM
      { id: "e1", source: "decision-1", target: "claim-1", type: "HAS_CLAIM" },
      { id: "e2", source: "decision-1", target: "claim-2", type: "HAS_CLAIM" },
      // Claim SUPPORTED_BY evidence
      {
        id: "e3",
        source: "claim-1",
        target: "evidence-1",
        type: "SUPPORTED_BY",
      },
      // Claim CONTRADICTED_BY evidence
      {
        id: "e4",
        source: "claim-2",
        target: "evidence-2",
        type: "CONTRADICTED_BY",
      },
      {
        id: "e5",
        source: "claim-2",
        target: "evidence-3",
        type: "CONTRADICTED_BY",
      },
      // Evidence FROM document
      { id: "e6", source: "evidence-1", target: "doc-1", type: "FROM" },
      { id: "e7", source: "evidence-2", target: "doc-2", type: "FROM" },
      { id: "e8", source: "evidence-3", target: "doc-1", type: "FROM" },
      // Claim CONFLICTS_WITH claim
      {
        id: "e9",
        source: "claim-1",
        target: "claim-2",
        type: "CONFLICTS_WITH",
        properties: { conflict_kind: "value_mismatch" },
      },
      // Document SUPERSEDES document (inferred from freshness signal)
      {
        id: "e10",
        source: "doc-2",
        target: "doc-1",
        type: "SUPERSEDES",
        properties: { inferred: true },
      },
      // Decision BECAUSE reason
      {
        id: "e11",
        source: "decision-1",
        target: "reason-1",
        type: "BECAUSE",
      },
      {
        id: "e12",
        source: "decision-1",
        target: "reason-2",
        type: "BECAUSE",
      },
      // Reason ABOUT claim
      {
        id: "e13",
        source: "reason-1",
        target: "claim-2",
        type: "ABOUT",
      },
    ],
  },
};
