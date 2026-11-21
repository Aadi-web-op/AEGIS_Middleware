import { describe, expect, it } from "vitest";
import { apiUrl, canTransition, decisions, evaluationPayload, statusValues } from "./aegis-api";
describe("AEGIS contract integrity", () => {
  it("does not reopen resolved or rejected escalations", () => {
    expect(canTransition("resolved", "pending")).toBe(false);
    expect(canTransition("dismissed", "in_review")).toBe(false);
    expect(canTransition("pending", "in_review")).toBe(true);
  });
  it("keeps generation failures outside the four policy decisions", () => {
    expect([...decisions]).toEqual(["ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"]);
    expect(decisions).not.toContain("GENERATION_FAILURE");
  });
  it("preserves the evaluate request contract and literal evidence", () => {
    expect(
      evaluationPayload("Question", "Answer", "First passage\n\nSecond passage", "standard", true),
    ).toEqual({
      query: "Question",
      answer: "Answer",
      evidence: [{ text: "First passage" }, { text: "Second passage" }],
      profile: "standard",
      time_sensitive: true,
    });
  });
  it("maps rejected cases to the existing dismissed API status", () => {
    expect(statusValues.Rejected).toBe("dismissed");
  });
  it("allows HTTPS API origins without credentials", () => {
    expect(apiUrl("https://aegis.example.com/")).toBe("https://aegis.example.com");
    expect(() => apiUrl("javascript:alert(1)")).toThrow();
  });
});
import { graphLabel, highlightSegments, type GraphStatus } from "./aegis-api";
describe("evidence highlighting segments", () => {
  const text = "Employees get 12 days of leave. Managers approve requests.";
  it("splits a passage into plain, conflict and number-marked pieces", () => {
    const segments = highlightSegments({
      evidence_index: 0,
      source: null,
      version: null,
      text,
      spans: [{ start: 0, end: 31, kind: "conflict", claim_index: 0, overlap: 0.8 }],
      numbers: [{ start: 14, end: 21, value: "12 days", claim_value: "18 days", claim_index: 0 }],
    });
    expect(segments.map((s) => s.text).join("")).toBe(text);
    expect(segments.find((s) => s.number)?.text).toBe("12 days");
    expect(segments.find((s) => s.number)?.kind).toBe("conflict");
    expect(segments.at(-1)?.kind).toBe("plain");
  });
  it("prefers conflict when a sentence also supports another claim", () => {
    const [first] = highlightSegments({
      evidence_index: 0,
      source: null,
      version: null,
      text,
      spans: [
        { start: 0, end: 31, kind: "support", claim_index: 1, overlap: 1 },
        { start: 0, end: 31, kind: "conflict", claim_index: 0, overlap: 1 },
      ],
      numbers: [],
    });
    expect(first?.kind).toBe("conflict");
  });
});
describe("graphLabel", () => {
  const status = (configured: boolean, connected: boolean): GraphStatus => ({
    configured,
    connected,
    counts: {},
    relationships: {},
    writer: { written: 0, failed: 0, dropped: 0, pending: 0, last_error: null },
  });
  it("reports the Neo4j state from /v1/graph/status, never inferring it", () => {
    expect(graphLabel(undefined)).toBe("Not reported");
    expect(graphLabel(status(false, false))).toBe("Not configured");
    expect(graphLabel(status(true, false))).toBe("Unreachable");
    expect(graphLabel(status(true, true))).toBe("Connected");
  });
});
