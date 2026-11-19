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
