/**
 * Frontend unit tests for the console's graph and result views.
 *
 * Note: on Node 22.11 vitest fails to start (jsdom ERR_REQUIRE_ESM); these
 * tests run on Node >= 22.12. `npm run build` type-checks the imports.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import DecisionResult, { segmentAnswer } from "../components/DecisionResult.jsx";
import GraphCanvas from "../components/GraphCanvas.jsx";
import GraphInspector from "../components/GraphInspector.jsx";
import { buildGraphFromTrace, layeredLayout, mergeGraphs, normaliseGraph, relationsOf } from "../graphUtils.js";
import { parseHash, href } from "../router.js";
import { score, pct, ratio } from "../format.js";
import { MOCK_TRACE } from "./mockTrace.js";

afterEach(cleanup);

const API_GRAPH = {
  nodes: [
    { id: "r1", type: "Decision", label: "ESCALATE", props: { request_id: "r1", decision: "ESCALATE", headline: "Sources disagree." } },
    { id: "r1:claim:0", type: "Claim", label: "18 days", props: { text: "18 days", status: "SUPPORTED", claim_index: 0 } },
    { id: "r1:claim:1", type: "Claim", label: "15 days", props: { text: "15 days", status: "CONTRADICTED", claim_index: 1 } },
    { id: "r1:ev:0", type: "Evidence", label: "18 days per year", props: { preview: "18 days per year", evidence_index: 0 } },
    { id: "r1:ev:1", type: "Evidence", label: "12 days per year", props: { preview: "12 days per year", evidence_index: 1 } },
    { id: "doc:a.pdf@v2", type: "Document", label: "a.pdf @ v2", props: { source: "a.pdf", version: "v2" } },
    { id: "doc:a.pdf@v1", type: "Document", label: "a.pdf @ v1", props: { source: "a.pdf", version: "v1" } },
    { id: "r1:reason:0", type: "Reason", label: "contradiction", props: { code: "CONTRADICTION" } },
  ],
  edges: [
    { id: "r1|HAS_CLAIM|r1:claim:0|", type: "HAS_CLAIM", from: "r1", to: "r1:claim:0", props: {} },
    { id: "r1|HAS_CLAIM|r1:claim:1|", type: "HAS_CLAIM", from: "r1", to: "r1:claim:1", props: {} },
    { id: "c0|SUPPORTED_BY", type: "SUPPORTED_BY", from: "r1:claim:0", to: "r1:ev:0", props: { support: 0.9 } },
    { id: "c1|CONTRADICTED_BY", type: "CONTRADICTED_BY", from: "r1:claim:1", to: "r1:ev:1", props: {} },
    { id: "e0|FROM", type: "FROM", from: "r1:ev:0", to: "doc:a.pdf@v2", props: {} },
    { id: "e1|FROM", type: "FROM", from: "r1:ev:1", to: "doc:a.pdf@v1", props: {} },
    { id: "sup", type: "SUPERSEDES", from: "doc:a.pdf@v2", to: "doc:a.pdf@v1", props: {} },
    { id: "because", type: "BECAUSE", from: "r1", to: "r1:reason:0", props: {} },
    { id: "dangling", type: "FROM", from: "r1:ev:0", to: "missing", props: {} },
  ],
};

describe("graphUtils", () => {
  it("normalises the API subgraph and drops dangling edges", () => {
    const g = normaliseGraph(API_GRAPH);
    expect(g.nodes).toHaveLength(8);
    expect(g.edges).toHaveLength(8);
    expect(g.edges.find((e) => e.id === "dangling")).toBeUndefined();
  });

  it("accepts trace edges with source/target", () => {
    const g = buildGraphFromTrace(MOCK_TRACE.graph);
    expect(g.nodes.length).toBe(MOCK_TRACE.graph.nodes.length);
    expect(g.edges.every((e) => typeof e.from === "string" && typeof e.to === "string")).toBe(true);
  });

  it("does not crash on malformed input", () => {
    expect(normaliseGraph(null)).toEqual({ nodes: [], edges: [] });
    expect(normaliseGraph({ nodes: "x" })).toEqual({ nodes: [], edges: [] });
    expect(normaliseGraph({ nodes: [null, { id: null }], edges: [null] })).toEqual({ nodes: [], edges: [] });
  });

  it("lays out deterministically by type column", () => {
    const g = normaliseGraph(API_GRAPH);
    const a = layeredLayout(g);
    const b = layeredLayout(normaliseGraph(API_GRAPH));
    expect(a).toEqual(b);
    expect(a.positions["r1:reason:0"].x).toBeLessThan(a.positions.r1.x);
    expect(a.positions.r1.x).toBeLessThan(a.positions["r1:claim:0"].x);
    expect(a.positions["r1:claim:0"].x).toBeLessThan(a.positions["r1:ev:0"].x);
    expect(a.positions["r1:ev:0"].x).toBeLessThan(a.positions["doc:a.pdf@v2"].x);
    expect(a.positions["r1:claim:0"].y).toBeLessThan(a.positions["r1:claim:1"].y);
  });

  it("merges neighbour subgraphs without duplicates", () => {
    const g = normaliseGraph(API_GRAPH);
    const more = { nodes: [API_GRAPH.nodes[0], { id: "r2", type: "Decision", props: { decision: "ANSWER" } }], edges: [] };
    const m = mergeGraphs(g, more);
    expect(m.nodes).toHaveLength(9);
    expect(mergeGraphs(m, more).nodes).toHaveLength(9);
  });

  it("lists relations of a node", () => {
    const g = normaliseGraph(API_GRAPH);
    const rels = relationsOf(g, "doc:a.pdf@v1");
    expect(rels.map((r) => r.edge.type).sort()).toEqual(["FROM", "SUPERSEDES"]);
  });
});

describe("format", () => {
  it("never renders missing numbers as zero", () => {
    expect(score(null)).toBe("—");
    expect(score(undefined)).toBe("—");
    expect(pct(null)).toBe("—");
    expect(ratio(1, 0)).toBe("—");
    expect(score(0)).toBe("0.00");
  });
});

describe("router", () => {
  it("parses hash routes with encoded args", () => {
    expect(parseHash("#graph/node/doc%3Aa.pdf%40v1")).toEqual({ page: "graph", args: ["node", "doc:a.pdf@v1"] });
    expect(parseHash("#nope")).toEqual({ page: "overview", args: [] });
    expect(href("documents", "doc:a@v1")).toBe("#documents/doc%3Aa%40v1");
  });
});

describe("segmentAnswer", () => {
  it("uses spans when given and falls back to text matching", () => {
    const answer = "Staff get 18 days. It was 15 days in 2025.";
    const { segments, matched } = segmentAnswer(answer, [
      { claim: "Staff get 18 days.", span: [0, 18] },
      { claim: "it was 15 days in 2025" },
      { claim: "Not in the answer" },
    ]);
    expect(matched).toBe(2);
    expect(segments.filter((s) => s.index !== undefined).map((s) => s.index)).toEqual([0, 1]);
    expect(segments.map((s) => s.text).join("")).toBe(answer);
  });
});

describe("GraphCanvas and inspector", () => {
  it("renders nodes and selects one", () => {
    const g = normaliseGraph(API_GRAPH);
    let sel = null;
    render(<GraphCanvas graph={g} selected={null} onSelect={(s) => (sel = s)} />);
    fireEvent.click(screen.getByLabelText("Claim: 15 days"));
    expect(sel).toEqual({ kind: "node", id: "r1:claim:1" });
  });

  it("explains a relationship", () => {
    const g = normaliseGraph(API_GRAPH);
    render(<GraphInspector graph={g} selected={{ kind: "edge", id: "sup" }} onSelect={() => {}} />);
    expect(screen.getByText(/newer document version replaces the older one/i)).toBeInTheDocument();
  });
});

describe("DecisionResult", () => {
  const response = {
    request_id: "abc",
    decision: "ESCALATE",
    answerability_score: 0.41,
    signals: { relevance: 0.8, entailment: 0.5, contradiction: 0.7, freshness: null, completeness: 0.6, ambiguity: 0.1 },
    unavailable_signals: ["freshness"],
    reasons: [{ code: "CONTRADICTION", message: "Sources disagree." }],
    claims: [{ claim: "Staff get 18 days.", status: "CONTRADICTED", support: 0.2, evidence_indices: [0], contradicting_evidence_indices: [0], reason: "E1 says 12." }],
    headline: "Escalated: the sources disagree.",
    explanation: { summary: "One claim is contradicted.", decisive_rule: "veto:contradiction", factors: [] },
    recommended_action: "escalate_to_human",
    trace: null,
  };

  it("renders headline, explanation and claim reason from the response", () => {
    render(<DecisionResult response={response} request={{ query: "How many?", answer: "Staff get 18 days.", evidence: [{ text: "Staff get 12 days." }] }} />);
    expect(screen.getByText("Escalated: the sources disagree.")).toBeInTheDocument();
    expect(screen.getByText("One claim is contradicted.")).toBeInTheDocument();
    expect(screen.getByText("veto:contradiction")).toBeInTheDocument();
    expect(screen.getByText("E1 says 12.")).toBeInTheDocument();
  });

  it("survives a malformed response", () => {
    expect(() => render(<DecisionResult response={{ decision: null, claims: undefined, signals: null }} />)).not.toThrow();
  });
});
