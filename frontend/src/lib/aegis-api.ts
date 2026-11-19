export const decisions = ["ANSWER", "CAVEAT", "ESCALATE", "ABSTAIN"] as const;
export type Decision = (typeof decisions)[number];
export type RecordData = Record<string, unknown>;
export interface EvaluationResult {
  request_id: string;
  decision: Decision;
  answerability_score: number;
  signals: Record<string, number | null>;
  reasons: { code: string; message: string }[];
  claims: { claim: string; status: string; support: number; evidence_indices: number[] }[];
  policy_version: string;
  latency_ms?: number;
  caveat_text?: string;
  clarifying_question?: string;
  trace?: { nodes?: RecordData[]; edges?: RecordData[] };
}
export function apiUrl(value: string) {
  const url = new URL(value);
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password)
    throw new Error("Enter an HTTP or HTTPS API URL without credentials.");
  return url.href.replace(/\/$/, "");
}
export async function apiRequest<T>(
  base: string,
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  if (!base) throw new Error("No AEGIS API connected.");
  const response = await fetch(`${base}${path}`, {
    method: body ? method : "GET",
    ...(body
      ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {}),
    signal: AbortSignal.timeout(30000),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : `AEGIS returned ${response.status}.`,
    );
  return data as T;
}
export function score(value: unknown) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
}
export function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
export const statusValues = {
  Pending: "pending",
  "In Review": "in_review",
  Resolved: "resolved",
  Rejected: "dismissed",
} as const;
export function canTransition(current: unknown, target: string) {
  return (current === "pending" || current === "in_review") && current !== target;
}
export function evaluationPayload(
  query: string,
  answer: string,
  text: string,
  profile: string,
  timeSensitive: boolean,
) {
  return {
    query,
    answer,
    evidence: text
      .split(/\n\s*\n/)
      .filter((p) => p.trim())
      .map((text) => ({ text: text.trim() })),
    profile,
    time_sensitive: timeSensitive,
  };
}
