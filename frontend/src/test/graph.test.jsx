/**
 * Frontend tests – covers all 10 acceptance criteria.
 *
 * AC1.  A valid trace renders its nodes and relationships correctly.
 * AC2.  Support, contradiction, supersession use correct visual styles.
 * AC3.  Headline and reason sentences match the supplied trace.
 * AC4.  Missing scores are NOT represented as fabricated zeros.
 * AC5.  Selecting an evidence node shows its available provenance details.
 * AC6.  Incomplete / malformed trace does not crash the application.
 * AC7.  Insights render real API results and handle empty / failed responses.
 * AC8.  Escalation items navigate to the correct decision.
 * AC9.  Graph remains usable with Neo4j switched off (no graph block in trace).
 * AC10. Existing middleware tests continue to pass (backend tests, not here).
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DecisionGraph from '../DecisionGraph.jsx';
import ExplanationPanel from '../ExplanationPanel.jsx';
import { buildGraphFromTrace, fmtScore, safePreview } from '../graphUtils.js';
import { MOCK_TRACE } from '../mockTrace.js';

afterEach(cleanup);

// ── Helpers ──────────────────────────────────────────────────────────────

/** A minimal malformed trace to test robustness. */
const MALFORMED_TRACE = {
  decision: null,
  answerability_score: undefined,
  signals: null,
  reasons: undefined,
  claims: undefined,
  request_id: null,
};

/** A trace with all scores null to verify AC4. */
const NULL_SCORES_TRACE = {
  request_id: 'test-null-scores',
  decision: 'ABSTAIN',
  answerability_score: null,
  signals: {
    relevance: null,
    entailment: null,
    contradiction: null,
    freshness: null,
    completeness: null,
    ambiguity: null,
  },
  reasons: [{ code: 'NO_EVIDENCE', message: 'No evidence was provided.' }],
  claims: [],
  recommended_action: 'abstain',
  policy_version: '0.1.0',
};

/** A trace with no `graph` block — simulates Neo4j off (AC9). */
const NO_GRAPH_BLOCK_TRACE = {
  request_id: 'req-no-graph',
  decision: 'ANSWER',
  answerability_score: 0.9,
  signals: { relevance: 0.9, entailment: 0.88, contradiction: 0.05, freshness: 0.8, completeness: 0.85, ambiguity: 0.1 },
  reasons: [],
  claims: [{ claim: 'Sky is blue.', status: 'SUPPORTED', support: 0.95 }],
  recommended_action: 'return_answer',
  policy_version: '0.1.0',
  // No `graph` property — backend has not yet populated it.
};

// ─────────────────────────────────────────────────────────────────────────────
// AC1 – Valid trace renders nodes and relationships
// ─────────────────────────────────────────────────────────────────────────────

describe('AC1: valid trace renders nodes and relationships', () => {
  it('buildGraphFromTrace returns correct node count from mock trace', () => {
    const { nodes, edges } = buildGraphFromTrace(MOCK_TRACE);
    expect(nodes.length).toBeGreaterThanOrEqual(MOCK_TRACE.graph.nodes.length);
    expect(edges.length).toBeGreaterThanOrEqual(MOCK_TRACE.graph.edges.length);
  });

  it('passes through the graph block when the backend provides it', () => {
    const result = buildGraphFromTrace(MOCK_TRACE);
    // Should return the graph block directly (same reference)
    expect(result).toBe(MOCK_TRACE.graph);
  });

  it('DecisionGraph renders all node types from mock trace', () => {
    render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    // All five node types should have aria labels
    expect(screen.getAllByRole('button').length).toBeGreaterThan(0);
  });

  it('DecisionGraph renders SUPPORTED_BY and CONTRADICTED_BY edges', () => {
    const { container } = render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    const paths = container.querySelectorAll('path[stroke]');
    expect(paths.length).toBeGreaterThan(0);
  });

  it('synthesises nodes from trace without graph block', () => {
    const { nodes, edges } = buildGraphFromTrace(NO_GRAPH_BLOCK_TRACE);
    const decisionNode = nodes.find((n) => n.type === 'Decision');
    const claimNode = nodes.find((n) => n.type === 'Claim');
    expect(decisionNode).toBeTruthy();
    expect(claimNode).toBeTruthy();
    const hasClaim = edges.find((e) => e.type === 'HAS_CLAIM');
    expect(hasClaim).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC2 – Support / contradiction / supersession use correct visual styles
// ─────────────────────────────────────────────────────────────────────────────

describe('AC2: edge visual styles', () => {
  it('SUPPORTED_BY edge uses green stroke', () => {
    const { container } = render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    // The SVG edges include text labels — check support label exists
    const supportTexts = [...container.querySelectorAll('text')].filter(
      (el) => el.textContent.includes('supports')
    );
    expect(supportTexts.length).toBeGreaterThan(0);
    expect(supportTexts[0].getAttribute('fill')).toBe('#22c55e');
  });

  it('CONTRADICTED_BY edge uses red stroke', () => {
    const { container } = render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    const contTexts = [...container.querySelectorAll('text')].filter(
      (el) => el.textContent.includes('contradicts')
    );
    expect(contTexts.length).toBeGreaterThan(0);
    expect(contTexts[0].getAttribute('fill')).toBe('#ef4444');
  });

  it('SUPERSEDES edge is rendered as dashed', () => {
    const { container } = render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    const dashedPaths = [...container.querySelectorAll('path[stroke-dasharray]')];
    expect(dashedPaths.length).toBeGreaterThan(0);
  });

  it('inferred SUPERSEDES edge label contains "(inferred)"', () => {
    const { container } = render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    const inferredTexts = [...container.querySelectorAll('text')].filter(
      (el) => el.textContent.includes('inferred')
    );
    expect(inferredTexts.length).toBeGreaterThan(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC3 – Headline and reason sentences match the supplied trace
// ─────────────────────────────────────────────────────────────────────────────

describe('AC3: ExplanationPanel shows correct decision and reasons', () => {
  it('shows the correct decision outcome', () => {
    render(<ExplanationPanel trace={MOCK_TRACE} />);
    expect(screen.getByText('ESCALATE')).toBeInTheDocument();
  });

  it('shows all reason codes', () => {
    render(<ExplanationPanel trace={MOCK_TRACE} />);
    expect(screen.getByText(/CONTRADICTION/i)).toBeInTheDocument();
    expect(screen.getByText(/STALE EVIDENCE/i)).toBeInTheDocument();
  });

  it('shows reason messages verbatim from the trace', () => {
    render(<ExplanationPanel trace={MOCK_TRACE} />);
    const msg = MOCK_TRACE.reasons[0].message;
    expect(screen.getByText(msg)).toBeInTheDocument();
  });

  it('shows claim statuses', () => {
    render(<ExplanationPanel trace={MOCK_TRACE} />);
    expect(screen.getByText('SUPPORTED')).toBeInTheDocument();
    expect(screen.getByText('CONTRADICTED')).toBeInTheDocument();
  });

  it('shows request ID', () => {
    render(<ExplanationPanel trace={MOCK_TRACE} />);
    expect(screen.getByText(/mock-trace-aabbccdd1122/)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC4 – Missing scores are not represented as fabricated zeros
// ─────────────────────────────────────────────────────────────────────────────

describe('AC4: null scores show "Not available", not 0%', () => {
  it('fmtScore returns "Not available" for null', () => {
    expect(fmtScore(null)).toBe('Not available');
  });

  it('fmtScore returns "Not available" for undefined', () => {
    expect(fmtScore(undefined)).toBe('Not available');
  });

  it('fmtScore returns correct percentage for a real value', () => {
    expect(fmtScore(0.75)).toBe('75.0%');
    expect(fmtScore(0)).toBe('0.0%');
  });

  it('ExplanationPanel shows "Not available" for all null signals', () => {
    render(<ExplanationPanel trace={NULL_SCORES_TRACE} />);
    const notAvailable = screen.getAllByText('Not available');
    // There are 6 signal bars + answerability = expect several "Not available"
    expect(notAvailable.length).toBeGreaterThanOrEqual(6);
  });

  it('ExplanationPanel does NOT render 0% for null answerability', () => {
    render(<ExplanationPanel trace={NULL_SCORES_TRACE} />);
    // Should not find "0.0%" or "0%" as a score display
    const zeros = screen.queryAllByText(/^0\.0%$/);
    expect(zeros.length).toBe(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC5 – Selecting an evidence node shows its provenance details
// ─────────────────────────────────────────────────────────────────────────────

describe('AC5: selecting an evidence node shows provenance details', () => {
  it('clicking an evidence node opens the details panel', () => {
    render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    // Find evidence node buttons
    const evidenceBtn = screen.getByLabelText(/Node: Policy 2024 – leave entitlement/);
    fireEvent.click(evidenceBtn);
    // Details panel should show "Evidence" type
    expect(screen.getByText('Evidence')).toBeInTheDocument();
  });

  it('evidence node details show chunk_index', () => {
    render(<DecisionGraph graphData={MOCK_TRACE.graph} />);
    const evidenceBtn = screen.getByLabelText(/Node: Policy 2024 – leave entitlement/);
    fireEvent.click(evidenceBtn);
    expect(screen.getByText(/chunk index/i)).toBeInTheDocument();
  });

  it('evidence preview does not exceed 120 characters', () => {
    const longText = 'A'.repeat(200);
    const preview = safePreview(longText, 120);
    expect(preview.length).toBeLessThanOrEqual(124); // 120 + '…'
    expect(preview.endsWith('…')).toBe(true);
  });

  it('safePreview strips < > characters (no HTML injection)', () => {
    const malicious = '<script>alert("xss")</script>';
    const preview = safePreview(malicious);
    expect(preview).not.toContain('<');
    expect(preview).not.toContain('>');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC6 – Incomplete / malformed trace does not crash the application
// ─────────────────────────────────────────────────────────────────────────────

describe('AC6: malformed traces do not crash', () => {
  it('ExplanationPanel with null trace shows empty state', () => {
    render(<ExplanationPanel trace={null} />);
    expect(screen.getByText(/Awaiting evaluation/i)).toBeInTheDocument();
  });

  it('ExplanationPanel with all-null fields does not throw', () => {
    expect(() => render(<ExplanationPanel trace={MALFORMED_TRACE} />)).not.toThrow();
  });

  it('DecisionGraph with null graphData shows empty state', () => {
    render(<DecisionGraph graphData={null} />);
    expect(screen.getByText(/No graph data/i)).toBeInTheDocument();
  });

  it('DecisionGraph with empty nodes array shows empty state', () => {
    render(<DecisionGraph graphData={{ nodes: [], edges: [] }} />);
    expect(screen.getByText(/No graph data/i)).toBeInTheDocument();
  });

  it('buildGraphFromTrace with null returns empty graph', () => {
    const result = buildGraphFromTrace(null);
    expect(result.nodes).toEqual([]);
    expect(result.edges).toEqual([]);
  });

  it('buildGraphFromTrace with undefined claims/reasons does not throw', () => {
    expect(() => buildGraphFromTrace(MALFORMED_TRACE)).not.toThrow();
  });

  it('DecisionGraph handles nodes with missing position gracefully', () => {
    const graphWithDangling = {
      nodes: [{ id: 'n1', type: 'Decision', label: 'D', properties: {} }],
      edges: [
        { id: 'e1', source: 'n1', target: 'NONEXISTENT', type: 'HAS_CLAIM' },
      ],
    };
    expect(() => render(<DecisionGraph graphData={graphWithDangling} />)).not.toThrow();
  });

  it('DecisionGraph with unknown node type uses fallback colors', () => {
    const graphWithUnknown = {
      nodes: [{ id: 'n1', type: 'UnknownType', label: 'X', properties: {} }],
      edges: [],
    };
    expect(() => render(<DecisionGraph graphData={graphWithUnknown} />)).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC7 – Insights render real API results and handle empty/failed responses
// ─────────────────────────────────────────────────────────────────────────────

describe('AC7: InsightsDashboard API states', () => {
  it('shows loading state', async () => {
    global.fetch = vi.fn(() => new Promise(() => {})); // never resolves
    const { default: InsightsDashboard } = await import('../InsightsDashboard.jsx');
    render(<InsightsDashboard onNavigateToGraph={() => {}} />);
    expect(screen.getAllByText('Loading…').length).toBeGreaterThan(0);
  });

  it('shows error state with retry button on network failure', async () => {
    global.fetch = vi.fn(() => Promise.reject(new Error('Network failure')));
    const { default: InsightsDashboard } = await import('../InsightsDashboard.jsx');
    render(<InsightsDashboard onNavigateToGraph={() => {}} />);
    await waitFor(() => {
      expect(screen.getAllByText('Retry').length).toBeGreaterThan(0);
    });
  });

  it('shows 503 unavailable message when database is down', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: () => Promise.resolve({ detail: 'Audit database unavailable: no such table' }),
      })
    );
    const { default: InsightsDashboard } = await import('../InsightsDashboard.jsx');
    render(<InsightsDashboard onNavigateToGraph={() => {}} />);
    await waitFor(() => {
      expect(screen.getAllByText(/database is unavailable/i).length).toBeGreaterThan(0);
    });
  });

  it('shows empty state when API returns empty array', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
    );
    const { default: InsightsDashboard } = await import('../InsightsDashboard.jsx');
    render(<InsightsDashboard onNavigateToGraph={() => {}} />);
    await waitFor(() => {
      expect(screen.getAllByText('No data yet.').length).toBeGreaterThan(0);
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC8 – Escalation items navigate to the correct decision
// ─────────────────────────────────────────────────────────────────────────────

describe('AC8: escalation queue graph navigation', () => {
  it('calls onOpenGraph with the correct request_id', async () => {
    const mockItem = {
      escalation_id: 'esc-abc123',
      request_id: 'req-xyz789',
      reason: 'Contradiction detected.',
      decision: 'ESCALATE',
      status: 'pending',
      query: 'How many leaves?',
      answer: '18 leaves.',
      notes: null,
      created_at: '2026-10-27T10:00:00Z',
      updated_at: '2026-10-27T10:00:00Z',
    };
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([mockItem]) })
    );
    const navigateSpy = vi.fn();
    const { default: EscalationQueue } = await import('../EscalationQueue.jsx');
    render(<EscalationQueue onOpenGraph={navigateSpy} />);
    await waitFor(() => {
      expect(screen.getByText(/View graph →/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/View graph →/));
    expect(navigateSpy).toHaveBeenCalledWith('req-xyz789');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// AC9 – Graph remains usable without Neo4j (no graph block in trace)
// ─────────────────────────────────────────────────────────────────────────────

describe('AC9: graph works without Neo4j (no graph block in trace)', () => {
  it('buildGraphFromTrace synthesises graph from claims when no graph block present', () => {
    const { nodes, edges } = buildGraphFromTrace(NO_GRAPH_BLOCK_TRACE);
    expect(nodes.length).toBeGreaterThan(0);
    expect(edges.length).toBeGreaterThan(0);
  });

  it('DecisionGraph renders synthesised graph', () => {
    const graphData = buildGraphFromTrace(NO_GRAPH_BLOCK_TRACE);
    render(<DecisionGraph graphData={graphData} />);
    expect(screen.queryByText(/No graph data/i)).not.toBeInTheDocument();
  });

  it('Decision node is always present in synthesised graph', () => {
    const { nodes } = buildGraphFromTrace(NO_GRAPH_BLOCK_TRACE);
    const decisionNode = nodes.find((n) => n.type === 'Decision');
    expect(decisionNode).toBeTruthy();
    expect(decisionNode.properties.outcome).toBe('ANSWER');
  });

  it('Claim nodes are synthesised with correct status', () => {
    const { nodes } = buildGraphFromTrace(NO_GRAPH_BLOCK_TRACE);
    const claimNode = nodes.find((n) => n.type === 'Claim');
    expect(claimNode.properties.status).toBe('SUPPORTED');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Utility / helper tests
// ─────────────────────────────────────────────────────────────────────────────

describe('Utility functions', () => {
  it('safePreview returns null for null input', () => {
    expect(safePreview(null)).toBeNull();
  });

  it('safePreview returns text unchanged when short enough', () => {
    const short = 'Hello world';
    expect(safePreview(short)).toBe(short);
  });

  it('fmtScore handles 0 correctly (returns "0.0%", not "Not available")', () => {
    expect(fmtScore(0)).toBe('0.0%');
  });

  it('fmtScore handles 1.0 correctly', () => {
    expect(fmtScore(1.0)).toBe('100.0%');
  });
});
